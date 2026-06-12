"""Unit tests for JWT encode/decode — Phase 1 (red).

Tests-first items covered:
  #4  test_jwt_issued_on_login_for_hr
  #6  test_jwt_rejects_tampered_signature
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone

import pytest

# These imports will raise ImportError until Phase 1 implementer creates the module.
from app.auth.jwt import (  # type: ignore[import]
    JWT_TTL_HR_SECONDS,
    JWT_TTL_MIGRANT_SECONDS,
    decode_jwt,
    encode_jwt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hr_payload() -> dict:
    """Minimal HR payload for JWT tests."""
    return {
        "sub": str(uuid.uuid4()),
        "role": "hr",
        "company_id": str(uuid.uuid4()),
    }


@pytest.fixture()
def migrant_payload() -> dict:
    """Minimal migrant payload for JWT tests."""
    return {
        "sub": str(uuid.uuid4()),
        "role": "migrant",
        "company_id": str(uuid.uuid4()),
        "preferred_language": "hi",
    }


# ---------------------------------------------------------------------------
# test #4 — JWT issued on login contains correct claims for HR
# ---------------------------------------------------------------------------


def test_jwt_issued_on_login_for_hr(env_vars: dict, hr_payload: dict) -> None:
    """encode_jwt for an HR produces HS256 token with role=hr, correct TTL ≈8h."""
    token = encode_jwt(hr_payload)

    decoded = decode_jwt(token)

    assert decoded["role"] == "hr", "JWT must carry role=hr"
    assert decoded["sub"] == hr_payload["sub"], "sub must match"
    assert decoded["company_id"] == hr_payload["company_id"], "company_id must match"

    # TTL check: exp - iat ≈ JWT_TTL_HR_SECONDS (allow ±2s for test execution)
    ttl = decoded["exp"] - decoded["iat"]
    assert abs(ttl - JWT_TTL_HR_SECONDS) <= 2, (
        f"HR JWT TTL should be ~{JWT_TTL_HR_SECONDS}s, got {ttl}s"
    )
    # 8 hours = 28800 seconds
    assert JWT_TTL_HR_SECONDS == 28800, f"Expected HR TTL 28800, got {JWT_TTL_HR_SECONDS}"


def test_jwt_issued_on_invite_accept_for_migrant_ttl(
    env_vars: dict, migrant_payload: dict
) -> None:
    """encode_jwt for a migrant produces token with role=migrant and 30-day TTL ≈2592000s."""
    token = encode_jwt(migrant_payload)

    decoded = decode_jwt(token)

    assert decoded["role"] == "migrant", "JWT must carry role=migrant"
    assert decoded["preferred_language"] == "hi", "preferred_language must be preserved"

    ttl = decoded["exp"] - decoded["iat"]
    assert abs(ttl - JWT_TTL_MIGRANT_SECONDS) <= 2, (
        f"Migrant JWT TTL should be ~{JWT_TTL_MIGRANT_SECONDS}s, got {ttl}s"
    )
    # 30 days = 2592000 seconds
    assert JWT_TTL_MIGRANT_SECONDS == 2592000, (
        f"Expected migrant TTL 2592000, got {JWT_TTL_MIGRANT_SECONDS}"
    )


# ---------------------------------------------------------------------------
# test #6 — Tampered JWT signature is rejected
# ---------------------------------------------------------------------------


def test_jwt_rejects_tampered_signature(env_vars: dict, hr_payload: dict) -> None:
    """A JWT whose payload segment has been modified must not verify.

    The tampered token should raise an exception (JWTError or similar).
    decode_jwt must never return a decoded payload for tampered input.
    """
    token = encode_jwt(hr_payload)

    # JWT has 3 parts: header.payload.signature
    parts = token.split(".")
    assert len(parts) == 3, "JWT must be 3-part base64url"

    # Tamper: flip the role claim in the decoded payload
    padding = "=" * (-len(parts[1]) % 4)
    original_payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
    original_payload["role"] = "migrant"  # flip hr → migrant
    tampered_payload_bytes = base64.urlsafe_b64encode(
        json.dumps(original_payload).encode()
    ).rstrip(b"=")
    tampered_token = f"{parts[0]}.{tampered_payload_bytes.decode()}.{parts[2]}"

    with pytest.raises(Exception):
        # Must raise — any of JWTError, jose.ExpiredSignatureError, ValueError, etc.
        decode_jwt(tampered_token)
