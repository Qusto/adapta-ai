"""Integration tests for POST /api/v1/auth/login — Phase 1 (red).

Tests-first items covered:
  #4  test_jwt_issued_on_login_for_hr  (HTTP-layer aspect — full roundtrip)
  #7  test_login_with_wrong_password_returns_401
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# test #4 — HTTP login returns JWT with correct claims for HR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_issued_on_login_for_hr(
    app_client, seed_hr, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/auth/login with daria@pik.demo/demo returns 200 + valid HR JWT.

    JWT must decode with role=hr, company_id matching seed, exp-iat ≈ 28800s.
    """
    import base64
    import json

    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "daria@pik.demo", "password": "demo"},
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "access_token" in body, "Response must include access_token"
    assert body.get("token_type") == "Bearer", "token_type must be Bearer"

    user_obj = body.get("user", {})
    assert user_obj.get("role") == "hr", "user.role must be hr"
    assert user_obj.get("email") == "daria@pik.demo", "user.email must match seed"
    assert "company_id" in user_obj, "user must include company_id"

    # Decode JWT payload (without verification — just inspect claims)
    token = body["access_token"]
    parts = token.split(".")
    assert len(parts) == 3, "JWT must have 3 parts"  # noqa: PLR2004

    padding = "=" * (-len(parts[1]) % 4)
    jwt_payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))

    assert jwt_payload.get("role") == "hr", "JWT payload role must be hr"
    assert str(jwt_payload.get("company_id")) == str(
        user_obj["company_id"]
    ), "JWT company_id must match user object"

    ttl = jwt_payload["exp"] - jwt_payload["iat"]
    assert abs(ttl - 28800) <= 5, f"HR JWT TTL must be ~28800s, got {ttl}s"  # noqa: PLR2004


# ---------------------------------------------------------------------------
# test #7 — Wrong password returns 401 INVALID_CREDENTIALS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(
    app_client, seed_hr, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/auth/login with wrong password → 401 error envelope.

    Body must conform to error envelope (§5 of DATA_MODEL_AND_API):
    { "error": { "code": "INVALID_CREDENTIALS", "message": "..." } }
    """
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "daria@pik.demo", "password": "wrong"},
    )

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    body = resp.json()
    error = body.get("error", {})
    assert error.get("code") == "INVALID_CREDENTIALS", (
        f"Error code must be INVALID_CREDENTIALS, got: {error.get('code')}"
    )
    assert "message" in error, "Error envelope must include message"


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(
    app_client, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/auth/login with non-existent email → 401 INVALID_CREDENTIALS.

    Must not leak existence of account (same error code as wrong password).
    """
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anypassword"},
    )

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    body = resp.json()
    error = body.get("error", {})
    assert error.get("code") == "INVALID_CREDENTIALS"
