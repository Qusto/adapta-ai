"""Invite HMAC-SHA256 sign/verify — Phase 1.

Token format (PRD §4):
  <base64url(json_payload)>.<base64url(hmac_sha256(json_payload, INVITE_SECRET))>

Payload: { "invite_id", "email", "company_id", "exp": <unix_ts> }
Default expiry: INVITE_TTL_HOURS = 168 h (7 days).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

INVITE_TTL_HOURS: int = 168  # 7 days


class InviteExpiredError(Exception):
    """Raised when the invite token's exp claim is in the past."""


class InviteInvalidError(Exception):
    """Raised when the HMAC signature does not match."""


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def sign_invite(
    payload: dict[str, Any],
    exp: float | None = None,
) -> str:
    """Sign an invite payload and return a raw HMAC token.

    Args:
        payload: Must include invite_id, email, company_id.
        exp:     Optional unix timestamp override (for testing expired tokens).
                 Defaults to now + 168 h.

    Returns:
        Raw token string: <payload_b64>.<sig_b64>
    """
    settings = get_settings()

    if exp is None:
        exp = (datetime.now(UTC) + timedelta(hours=INVITE_TTL_HOURS)).timestamp()

    full_payload: dict[str, Any] = {**payload, "exp": exp}
    payload_bytes = json.dumps(full_payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64 = _b64_encode(payload_bytes)

    sig = hmac.new(
        settings.invite_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    sig_b64 = _b64_encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_invite(raw_token: str) -> dict[str, Any]:
    """Verify an invite token's HMAC signature and expiry.

    Returns:
        Decoded payload dict including exp.

    Raises:
        InviteInvalidError:  HMAC mismatch or malformed token.
        InviteExpiredError:  exp claim is in the past.
    """
    settings = get_settings()

    parts = raw_token.split(".")
    if len(parts) != 2:
        raise InviteInvalidError("Token must be <payload_b64>.<sig_b64>")

    payload_b64, sig_b64 = parts

    # Verify HMAC
    expected_sig = hmac.new(
        settings.invite_secret.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    try:
        provided_sig = _b64_decode(sig_b64)
    except Exception as exc:
        raise InviteInvalidError("Cannot decode signature") from exc

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise InviteInvalidError("HMAC signature mismatch")

    # Decode payload
    try:
        payload_bytes = _b64_decode(payload_b64)
        decoded: dict[str, Any] = json.loads(payload_bytes.decode())
    except Exception as exc:
        raise InviteInvalidError("Cannot decode payload") from exc

    # Check expiry
    exp = decoded.get("exp")
    if exp is None:
        raise InviteInvalidError("Token has no exp claim")

    now = datetime.now(UTC).timestamp()
    if float(exp) < now:
        raise InviteExpiredError("Invite token has expired")

    return decoded
