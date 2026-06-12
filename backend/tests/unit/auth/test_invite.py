"""Unit tests for invite HMAC sign/verify — Phase 1 (red).

Tests-first items covered:
  #1  test_invite_link_sign_and_verify_roundtrip
  #2  test_invite_link_rejects_expired_token
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

# These imports will raise ImportError until Phase 1 implementer creates the module.
from app.auth.invite import (  # type: ignore[import]
    InviteExpiredError,
    sign_invite,
    verify_invite,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def invite_payload() -> dict:
    """Canonical invite payload as per §4 of DATA_MODEL_AND_API."""
    return {
        "invite_id": str(uuid.uuid4()),
        "email": "raju@example.com",
        "company_id": str(uuid.uuid4()),
    }


# ---------------------------------------------------------------------------
# test #1 — Sign → verify roundtrip restores payload
# ---------------------------------------------------------------------------


def test_invite_link_sign_and_verify_roundtrip(
    env_vars: dict, invite_payload: dict
) -> None:
    """sign_invite produces a raw token; verify_invite decodes it back to original payload.

    Token format: <base64url(payload)>.<base64url(hmac_sha256(payload, INVITE_SECRET))>
    """
    raw_token = sign_invite(invite_payload)

    # Token must be a string with exactly 2 "." separators (3 parts)
    assert isinstance(raw_token, str), "sign_invite must return a string"
    parts = raw_token.split(".")
    assert len(parts) == 2, (  # noqa: PLR2004 — two-part token: payload.sig
        "Invite token must be <payload_b64>.<sig_b64>"
    )

    recovered = verify_invite(raw_token)

    assert recovered["invite_id"] == invite_payload["invite_id"], "invite_id must round-trip"
    assert recovered["email"] == invite_payload["email"], "email must round-trip"
    assert recovered["company_id"] == invite_payload["company_id"], "company_id must round-trip"


def test_invite_link_roundtrip_includes_exp(
    env_vars: dict, invite_payload: dict
) -> None:
    """verify_invite result must include exp claim (unix ts, ~7 days from now)."""
    raw_token = sign_invite(invite_payload)
    recovered = verify_invite(raw_token)

    assert "exp" in recovered, "invite payload must include exp claim"
    # exp should be ~7 days from now (within ±60s tolerance)
    expected_exp = (
        datetime.now(timezone.utc) + timedelta(days=7)
    ).timestamp()
    assert abs(recovered["exp"] - expected_exp) < 60, (
        f"exp should be ~7 days from now, got diff {recovered['exp'] - expected_exp}s"
    )


# ---------------------------------------------------------------------------
# test #2 — Expired token raises InviteExpiredError
# ---------------------------------------------------------------------------


def test_invite_link_rejects_expired_token(env_vars: dict, invite_payload: dict) -> None:
    """verify_invite raises InviteExpiredError when exp is in the past.

    We sign with a manually crafted past exp to simulate expiry.
    sign_invite must accept an optional exp override for testing.
    """
    past_exp = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).timestamp()

    raw_token = sign_invite(invite_payload, exp=past_exp)

    with pytest.raises(InviteExpiredError):
        verify_invite(raw_token)


def test_invite_link_rejects_tampered_token(env_vars: dict, invite_payload: dict) -> None:
    """verify_invite raises an exception when HMAC signature is wrong."""
    raw_token = sign_invite(invite_payload)
    # Corrupt 3 chars in the MIDDLE of the token. Flipping the last base64 char
    # is flaky: trailing base64 chars carry redundant low bits that often decode
    # to the same signature byte, so a tampered last char can still verify.
    mid = len(raw_token) // 2
    repl = "AAA" if raw_token[mid : mid + 3] != "AAA" else "BBB"
    tampered = raw_token[:mid] + repl + raw_token[mid + 3 :]

    with pytest.raises(Exception):
        verify_invite(tampered)
