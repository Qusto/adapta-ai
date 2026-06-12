"""Phase 10 — migrant onboarding journey, personal documents, chat history.

Single source of truth shared by the migrant PWA and the HR console:
  GET   /api/v1/me/onboarding                      (migrant)
  GET   /api/v1/me/documents                        (migrant)
  POST  /api/v1/me/documents                        (migrant — upload metadata)
  GET   /api/v1/me/chat/history                      (migrant — full thread incl. HR)
  GET   /api/v1/workers/{id}/onboarding              (HR, same company)
  PATCH /api/v1/workers/{id}/onboarding/{step_key}   (HR — move a step)
  GET   /api/v1/workers/{id}/documents               (HR, same company)

Documents are METADATA ONLY (number/expiry/status). Real file storage needs
at-rest encryption — deferred to v1.1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.auth.deps import get_current_user, require_hr
from app.database import async_session_factory
from app.db.models import AiMessage, User
from app.onboarding import (
    DOC_TO_STEP,
    DOC_TYPES,
    STEP_DONE,
    _STEP_STATUSES,
    default_documents,
    default_onboarding,
    documents_progress,
    onboarding_progress,
)

router = APIRouter(tags=["journey"])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _require_migrant(user: User) -> None:
    if user.role != "migrant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Migrant only."}},
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class JourneyResponse(BaseModel):
    steps: list[dict[str, Any]]
    done: int
    total: int


class DocumentsResponse(BaseModel):
    docs: list[dict[str, Any]]
    uploaded: int
    required: int


class DocumentUpload(BaseModel):
    type: str
    number: str | None = None
    expires_at: str | None = None
    status: str | None = None  # defaults to "uploaded"


class StepPatch(BaseModel):
    status: str  # todo | in_progress | done


class ChatHistoryItem(BaseModel):
    role: str
    text: str
    created_at: str
    confidence: float | None = None


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryItem]


# ---------------------------------------------------------------------------
# Helpers — load/seed JSONB state
# ---------------------------------------------------------------------------


async def _get_onboarding(user: User, session: Any) -> dict[str, Any]:
    if user.onboarding_state is None:
        user.onboarding_state = default_onboarding(user.created_at.isoformat())
        flag_modified(user, "onboarding_state")
        await session.commit()
    return user.onboarding_state


async def _get_documents(user: User, session: Any) -> dict[str, Any]:
    if user.personal_documents is None:
        user.personal_documents = default_documents()
        flag_modified(user, "personal_documents")
        await session.commit()
    return user.personal_documents


async def _load_worker_for_hr(worker_id: uuid.UUID, hr: User) -> User:
    async with async_session_factory() as session:
        worker = await session.get(User, worker_id)
    if worker is None or worker.company_id != hr.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Worker not found."}},
        )
    return worker


# ---------------------------------------------------------------------------
# Migrant — self
# ---------------------------------------------------------------------------


@router.get("/me/onboarding", response_model=JourneyResponse)
async def my_onboarding(
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    _require_migrant(current_user)
    async with async_session_factory() as session:
        user = await session.get(User, current_user.id)
        state = await _get_onboarding(user, session)
    done, total = onboarding_progress(state)
    return JourneyResponse(steps=state["steps"], done=done, total=total)


@router.get("/me/documents", response_model=DocumentsResponse)
async def my_documents(
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    _require_migrant(current_user)
    async with async_session_factory() as session:
        user = await session.get(User, current_user.id)
        docs_state = await _get_documents(user, session)
    uploaded, required = documents_progress(docs_state)
    return DocumentsResponse(docs=docs_state["docs"], uploaded=uploaded, required=required)


@router.post("/me/documents", response_model=DocumentsResponse)
async def upload_document(
    body: DocumentUpload,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    _require_migrant(current_user)
    if body.type not in DOC_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "BAD_DOC_TYPE", "message": f"Unknown doc type: {body.type}"}},
        )
    now = _now_iso()
    async with async_session_factory() as session:
        user = await session.get(User, current_user.id)
        docs_state = await _get_documents(user, session)
        for d in docs_state["docs"]:
            if d["type"] == body.type:
                d["status"] = body.status or "uploaded"
                d["number"] = body.number
                d["expires_at"] = body.expires_at
                d["uploaded_at"] = now
                break
        user.personal_documents = docs_state
        flag_modified(user, "personal_documents")

        # Auto-advance the linked onboarding step, if any.
        step_key = DOC_TO_STEP.get(body.type)
        if step_key:
            ob = user.onboarding_state or default_onboarding(user.created_at.isoformat())
            for st in ob["steps"]:
                if st["key"] == step_key and st["status"] != STEP_DONE:
                    st["status"] = STEP_DONE
                    st["updated_at"] = now
            user.onboarding_state = ob
            flag_modified(user, "onboarding_state")

        await session.commit()
        docs_state = user.personal_documents
    uploaded, required = documents_progress(docs_state)
    return DocumentsResponse(docs=docs_state["docs"], uploaded=uploaded, required=required)


@router.get("/me/chat/history", response_model=ChatHistoryResponse)
async def my_chat_history(
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    """Full thread for the current migrant — includes user, agent AND hr replies.

    Closes the two-way loop: HR replies (role='hr') reach the migrant's app.
    """
    _require_migrant(current_user)
    async with async_session_factory() as session:
        result = await session.execute(
            select(AiMessage)
            .where(AiMessage.user_id == current_user.id)
            .order_by(AiMessage.created_at.asc())
        )
        rows = list(result.scalars().all())
    items = [
        ChatHistoryItem(
            role=m.role,
            text=m.text,
            created_at=m.created_at.isoformat(),
            confidence=m.confidence,
        )
        for m in rows
    ]
    return ChatHistoryResponse(items=items)


# ---------------------------------------------------------------------------
# HR — by worker
# ---------------------------------------------------------------------------


@router.get("/workers/{worker_id}/onboarding", response_model=JourneyResponse)
async def worker_onboarding(
    worker_id: uuid.UUID,
    hr: Annotated[User, Depends(require_hr)],
) -> Any:
    await _load_worker_for_hr(worker_id, hr)
    async with async_session_factory() as session:
        worker = await session.get(User, worker_id)
        state = await _get_onboarding(worker, session)
    done, total = onboarding_progress(state)
    return JourneyResponse(steps=state["steps"], done=done, total=total)


@router.patch("/workers/{worker_id}/onboarding/{step_key}", response_model=JourneyResponse)
async def patch_worker_step(
    worker_id: uuid.UUID,
    step_key: str,
    body: StepPatch,
    hr: Annotated[User, Depends(require_hr)],
) -> Any:
    if body.status not in _STEP_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "BAD_STATUS", "message": f"Bad status: {body.status}"}},
        )
    await _load_worker_for_hr(worker_id, hr)
    async with async_session_factory() as session:
        worker = await session.get(User, worker_id)
        state = await _get_onboarding(worker, session)
        found = False
        for st in state["steps"]:
            if st["key"] == step_key:
                st["status"] = body.status
                st["updated_at"] = _now_iso()
                found = True
                break
        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "NO_STEP", "message": f"Unknown step: {step_key}"}},
            )
        worker.onboarding_state = state
        flag_modified(worker, "onboarding_state")
        await session.commit()
        state = worker.onboarding_state
    done, total = onboarding_progress(state)
    return JourneyResponse(steps=state["steps"], done=done, total=total)


@router.get("/workers/{worker_id}/documents", response_model=DocumentsResponse)
async def worker_documents(
    worker_id: uuid.UUID,
    hr: Annotated[User, Depends(require_hr)],
) -> Any:
    await _load_worker_for_hr(worker_id, hr)
    async with async_session_factory() as session:
        worker = await session.get(User, worker_id)
        docs_state = await _get_documents(worker, session)
    uploaded, required = documents_progress(docs_state)
    return DocumentsResponse(docs=docs_state["docs"], uploaded=uploaded, required=required)
