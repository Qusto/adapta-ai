"""HR thread & reply endpoints — Phase 5+.

GET  /api/v1/chat/threads/{worker_id}?limit=50
     Returns message thread for a migrant, accessible only to their company HR.

POST /api/v1/chat/escalations/{escalation_id}/reply
     HR sends a reply to a migrant; stored as role='hr' in ai_messages.

Auth: require_hr dependency (same as chat_escalations.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import require_hr
from app.database import async_session_factory
from app.db.models import AiMessage, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ThreadMessage(BaseModel):
    id: str
    role: str  # "user" | "agent" | "hr"
    text: str
    language: str
    created_at: str  # ISO-8601
    confidence: float | None


class ThreadResponse(BaseModel):
    worker_id: str
    messages: list[ThreadMessage]
    total: int


class HrReplyRequest(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_thread_message(msg: AiMessage) -> ThreadMessage:
    return ThreadMessage(
        id=str(msg.id),
        role=msg.role,
        text=msg.text,
        language=msg.language or "ru",
        created_at=msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        confidence=msg.confidence,
    )


async def _get_worker_for_hr(
    worker_id: uuid.UUID,
    company_id: uuid.UUID,
    session_factory=async_session_factory,
) -> User:
    """Fetch worker by id and verify they belong to the HR's company.

    Raises 404 if worker not found, 403 if company mismatch.
    """
    async with async_session_factory() as session:
        worker = await session.get(User, worker_id)

    if worker is None or worker.role != "migrant":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Worker not found."}},
        )
    if worker.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Worker does not belong to your company.",
                }
            },
        )
    return worker


# ---------------------------------------------------------------------------
# Endpoint 1: GET /chat/threads/{worker_id}
# ---------------------------------------------------------------------------


@router.get("/threads/{worker_id}", response_model=ThreadResponse)
async def get_thread(
    worker_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_hr)],
    limit: int = Query(default=50, ge=1, le=500),
) -> ThreadResponse:
    """Return the full message thread for a migrant worker.

    Ordered by created_at ASC (chronological). HR may only access workers
    from their own company; returns 403 otherwise.
    """
    company_id: uuid.UUID = current_user.company_id

    await _get_worker_for_hr(worker_id, company_id)

    async with async_session_factory() as session:
        stmt = (
            select(AiMessage)
            .where(AiMessage.user_id == worker_id)
            .order_by(AiMessage.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        # Fetched in DESC order (newest first); reverse to ASC for chronological display
        messages = list(reversed(result.scalars().all()))

    return ThreadResponse(
        worker_id=str(worker_id),
        messages=[_to_thread_message(m) for m in messages],
        total=len(messages),
    )


# ---------------------------------------------------------------------------
# Endpoint 2: POST /chat/escalations/{escalation_id}/reply
# ---------------------------------------------------------------------------


@router.post(
    "/escalations/{escalation_id}/reply",
    response_model=ThreadMessage,
    status_code=status.HTTP_200_OK,
)
async def reply_to_escalation(
    escalation_id: uuid.UUID,
    body: HrReplyRequest,
    current_user: Annotated[User, Depends(require_hr)],
) -> ThreadMessage:
    """HR replies to a migrant via an escalation message.

    Resolves the migrant's user_id from the escalation message, verifies
    company membership, then inserts a new ai_messages row with role='hr'.
    """
    company_id: uuid.UUID = current_user.company_id

    # Look up the escalation message to find worker_id
    async with async_session_factory() as session:
        escalation_msg = await session.get(AiMessage, escalation_id)

    if escalation_msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {"code": "NOT_FOUND", "message": "Escalation not found."}
            },
        )

    worker_id: uuid.UUID = escalation_msg.user_id

    # Verify the worker belongs to the HR's company
    await _get_worker_for_hr(worker_id, company_id)

    # Persist the HR reply
    now = datetime.now(tz=UTC)
    reply = AiMessage(
        id=uuid.uuid4(),
        user_id=worker_id,
        role="hr",
        text=body.text.strip(),
        language="ru",
        confidence=None,
        is_answerable=None,
        escalate=False,
        latency_ms=None,
        created_at=now,
    )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(reply)

    logger.info(
        "HR reply saved: escalation=%s worker=%s hr=%s",
        escalation_id,
        worker_id,
        current_user.id,
    )

    return _to_thread_message(reply)
