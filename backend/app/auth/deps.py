"""FastAPI dependencies for authentication — Phase 1.

Exports:
  get_current_user  — parse Bearer JWT → User ORM object (or raise 401)
  require_hr        — like get_current_user but asserts role=hr (or raise 403)
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_jwt
from app.database import async_session_factory
from app.db.models import User

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"error": {"code": "UNAUTHORIZED", "message": "Missing or invalid token."}},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={"error": {"code": "FORBIDDEN", "message": "Insufficient role."}},
)


def _decode_jwt_payload(
    credentials: HTTPAuthorizationCredentials | None,
) -> dict[str, object]:
    """Decode JWT and return payload, or raise 401."""
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        return decode_jwt(credentials.credentials)
    except jwt.PyJWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise _UNAUTHORIZED from exc


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    """Parse Bearer JWT and return the corresponding User from DB.

    Raises 401 if missing/invalid token, or if user not found.
    """
    payload = _decode_jwt_payload(credentials)

    user_id_str: str | None = payload.get("sub")  # type: ignore[assignment]
    if not user_id_str:
        raise _UNAUTHORIZED

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise _UNAUTHORIZED from exc

    async with async_session_factory() as session:
        user = await session.get(User, user_uuid)

    if user is None:
        raise _UNAUTHORIZED

    return user


async def require_hr(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    """Dependency that asserts the token is valid and role=hr.

    Fast-path: checks JWT role claim BEFORE hitting the DB (returns 403 for
    non-HR tokens without a DB round-trip).
    Raises 401 for missing/invalid/no-user tokens, 403 for non-HR role.
    """
    payload = _decode_jwt_payload(credentials)

    # Fast rejection: check role claim before DB lookup
    role: str | None = payload.get("role")  # type: ignore[assignment]
    if role != "hr":
        raise _FORBIDDEN

    user_id_str: str | None = payload.get("sub")  # type: ignore[assignment]
    if not user_id_str:
        raise _UNAUTHORIZED

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError as exc:
        raise _UNAUTHORIZED from exc

    async with async_session_factory() as session:
        user = await session.get(User, user_uuid)

    if user is None:
        raise _UNAUTHORIZED

    return user
