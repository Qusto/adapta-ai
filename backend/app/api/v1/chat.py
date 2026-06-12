"""Chat endpoint — Phase 3.

POST /api/v1/chat/messages — streaming AI response (SSE).
Auth: JWT (role=migrant). Uses require_migrant dependency.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_jwt
from app.chat.message_handler import stream_chat_response
from app.chat.schemas import ChatRequest
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"error": {"code": "UNAUTHORIZED", "message": "Missing or invalid token."}},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={"error": {"code": "FORBIDDEN", "message": "Migrant role required."}},
)


@dataclass
class _JwtUser:
    """Minimal user-like object constructed from JWT claims (no DB round-trip)."""

    id: uuid.UUID
    role: str
    company_id: uuid.UUID
    preferred_language: str


async def require_migrant(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    """Dependency: verify JWT and assert role=migrant.

    Returns a User-like object with id, role, company_id, preferred_language.
    Raises 401 for missing/invalid token, 403 for non-migrant role.
    """
    if credentials is None:
        raise _UNAUTHORIZED

    try:
        payload = decode_jwt(credentials.credentials)
    except pyjwt.PyJWTError as exc:
        logger.warning("JWT decode failed in require_migrant: %s", exc)
        raise _UNAUTHORIZED from exc

    role = str(payload.get("role", ""))
    if role != "migrant":
        raise _FORBIDDEN

    user_id_raw = payload.get("sub")
    user_id_str: str = str(user_id_raw) if user_id_raw is not None else ""
    if not user_id_str:
        raise _UNAUTHORIZED

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise _UNAUTHORIZED from exc

    company_id_raw = payload.get("company_id")
    company_id_str: str = str(company_id_raw) if company_id_raw is not None else ""
    try:
        company_uuid = uuid.UUID(company_id_str)
    except (ValueError, TypeError) as exc:
        raise _UNAUTHORIZED from exc

    preferred_language_raw = payload.get("preferred_language")
    preferred_language: str = str(preferred_language_raw) if preferred_language_raw else "ru"

    # Build a minimal user-like object (avoid DB round-trip for streaming endpoint)
    # The real user_id and company_id are taken from the JWT claims.
    return _JwtUser(  # type: ignore[return-value]
        id=user_uuid,
        role="migrant",
        company_id=company_uuid,
        preferred_language=preferred_language,
    )


@router.post("/messages")
async def chat_messages(
    request: ChatRequest,
    current_user: Annotated[User, Depends(require_migrant)],
) -> StreamingResponse:
    """Stream AI answer to a migrant's question.

    Returns text/event-stream SSE with events:
      message_started, token (N×), citations, done, [error]
    """
    language = request.language
    skip_translate = request.skip_translate_response
    trace = request.trace
    pipeline_mode = request.pipeline_mode
    qwen_model_override = request.qwen_model_override

    async def _generate() -> AsyncIterator[str]:
        async for event in stream_chat_response(
            user_id=current_user.id,
            company_id=current_user.company_id,
            question=request.text,
            language=language,
            skip_translate_response=skip_translate,
            trace=trace,
            pipeline_mode=pipeline_mode,
            qwen_model_override=qwen_model_override,
        ):
            yield event

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
