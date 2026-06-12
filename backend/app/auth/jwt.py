"""JWT encode/decode helpers — Phase 1.

Algorithm: HS256, secret from env JWT_SECRET.
TTL:
  HR      — JWT_TTL_HR_SECONDS      (8 hours  = 28800s)
  Migrant — JWT_TTL_MIGRANT_SECONDS (30 days  = 2592000s)

Payload shape per PRD §3:
  { "sub", "role", "company_id", "iat", "exp", [preferred_language] }
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

JWT_TTL_HR_SECONDS: int = 28800  # 8 hours
JWT_TTL_MIGRANT_SECONDS: int = 2592000  # 30 days


def _ttl_for_role(role: str) -> int:
    """Return TTL seconds based on role claim."""
    if role == "hr":
        return JWT_TTL_HR_SECONDS
    return JWT_TTL_MIGRANT_SECONDS


def encode_jwt(payload: dict[str, Any]) -> str:
    """Encode a JWT HS256 token.

    `payload` must include at least: sub, role, company_id.
    iat and exp are injected automatically based on role.
    """
    settings = get_settings()
    now = int(datetime.now(UTC).timestamp())
    ttl = _ttl_for_role(payload.get("role", "migrant"))

    claims: dict[str, Any] = {**payload, "iat": now, "exp": now + ttl}
    token: str = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    return token


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises jwt.PyJWTError (e.g. jwt.DecodeError, jwt.InvalidSignatureError,
    jwt.ExpiredSignatureError) on any failure.
    """
    settings = get_settings()
    decoded: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
    )
    return decoded
