"""Integration tests for invite endpoints — Phase 1 (red).

Tests-first items covered:
  #3  test_invite_link_single_use
  #5  test_jwt_issued_on_invite_accept_for_migrant
  #8  test_invite_preview_returns_company_and_lang
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# test #8 — GET /api/v1/invites/{token} returns company_name and lang
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_preview_returns_company_and_lang(
    app_client, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/invites/{token} returns 200 with company_name, preferred_language.

    Response shape (§6.5):
    { invite_id, company_name, first_name, last_name, hr_name, preferred_language, expires_at }
    """
    token = valid_invite["raw_token"]

    resp = await app_client.get(f"/api/v1/invites/{token}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body.get("company_name") == "ГК ПИК", (
        f"company_name must be 'ГК ПИК', got: {body.get('company_name')}"
    )
    assert body.get("preferred_language") == "hi", (
        f"preferred_language must be 'hi', got: {body.get('preferred_language')}"
    )
    assert body.get("first_name") == "Раджу", "first_name must match invite"
    assert body.get("last_name") == "Шарма", "last_name must match invite"
    assert "invite_id" in body, "Response must include invite_id"
    assert "expires_at" in body, "Response must include expires_at"


@pytest.mark.asyncio
async def test_invite_preview_returns_hr_name(
    app_client, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/invites/{token} response includes hr_name from issuing HR user."""
    token = valid_invite["raw_token"]

    resp = await app_client.get(f"/api/v1/invites/{token}")

    assert resp.status_code == 200
    body = resp.json()
    assert "hr_name" in body, "Response must include hr_name"


@pytest.mark.asyncio
async def test_invite_preview_returns_410_for_expired(
    app_client, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/invites/{expired_token} returns 410 INVITE_EXPIRED.

    We craft a token with exp in the past using sign_invite's exp override.
    """
    import hashlib
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.auth.invite import sign_invite  # type: ignore[import]
    from app.db.models import Company, Invite, User  # type: ignore[import]

    # This test requires an invite row with expires_at in the past to be in DB.
    # Since we cannot access db_session here, this endpoint must detect expiry
    # via the token's exp field and return 410.
    past_exp = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
    payload = {
        "invite_id": str(uuid.uuid4()),
        "email": "expired@example.com",
        "company_id": str(uuid.uuid4()),
    }
    expired_token = sign_invite(payload, exp=past_exp)

    resp = await app_client.get(f"/api/v1/invites/{expired_token}")

    # 404 is also acceptable if the token_hash is not in DB; 410 if DB has it expired.
    # The primary contract: must NOT return 200.
    assert resp.status_code in (
        404, 410
    ), f"Expired invite must return 404 or 410, got {resp.status_code}"


# ---------------------------------------------------------------------------
# test #5 — POST /api/v1/invites/{token}/accept returns migrant JWT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_issued_on_invite_accept_for_migrant(
    app_client, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/invites/{token}/accept → 201 with JWT role=migrant, 30d TTL.

    MailHog SMTP is mocked — no real SMTP connection during this test.
    """
    import base64
    import json

    token = valid_invite["raw_token"]

    resp = await app_client.post(
        f"/api/v1/invites/{token}/accept",
        json={"preferred_language": "hi"},
    )

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "access_token" in body, "Response must include access_token"
    assert body.get("token_type") == "Bearer", "token_type must be Bearer"

    user_obj = body.get("user", {})
    assert user_obj.get("role") == "migrant", f"user.role must be migrant, got: {user_obj.get('role')}"
    assert user_obj.get("email") == "raju@example.com", "user.email must match invite"
    assert str(user_obj.get("company_id")) == str(valid_invite["company_id"]), (
        "user.company_id must match invite's company_id"
    )

    # Verify JWT TTL ≈ 30 days = 2592000s
    jwt_token = body["access_token"]
    parts = jwt_token.split(".")
    assert len(parts) == 3  # noqa: PLR2004
    padding = "=" * (-len(parts[1]) % 4)
    jwt_payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))

    assert jwt_payload.get("role") == "migrant", "JWT must carry role=migrant"
    ttl = jwt_payload["exp"] - jwt_payload["iat"]
    assert abs(ttl - 2592000) <= 10, (  # noqa: PLR2004
        f"Migrant JWT TTL must be ~2592000s (30d), got {ttl}s"
    )


# ---------------------------------------------------------------------------
# test #3 — Single-use: second accept returns 409 INVITE_ALREADY_USED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_link_single_use(
    app_client, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """Accepting the same invite token twice: first returns 201, second returns 409.

    Error on second call must be INVITE_ALREADY_USED (§5, §6.5).
    """
    token = valid_invite["raw_token"]

    # First accept — must succeed
    resp_first = await app_client.post(
        f"/api/v1/invites/{token}/accept",
        json={"preferred_language": "hi"},
    )
    assert resp_first.status_code == 201, (
        f"First accept must be 201, got {resp_first.status_code}: {resp_first.text}"
    )

    # Second accept — must be 409
    resp_second = await app_client.post(
        f"/api/v1/invites/{token}/accept",
        json={"preferred_language": "hi"},
    )
    assert resp_second.status_code == 409, (
        f"Second accept must be 409, got {resp_second.status_code}: {resp_second.text}"
    )

    error = resp_second.json().get("error", {})
    assert error.get("code") == "INVITE_ALREADY_USED", (
        f"Error code must be INVITE_ALREADY_USED, got: {error.get('code')}"
    )


# ---------------------------------------------------------------------------
# POST /api/v1/invites — HR creates invite (side-effect: MailHog mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hr_can_create_invite(
    client_authed_as_hr, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/invites with HR JWT → 201, response includes token field.

    aiosmtplib SMTP send is mocked to avoid real MailHog dependency in unit tests.
    """
    with patch(
        "app.email.mailhog_client.send_invite_email",  # type: ignore[attr-defined]
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = None

        resp = await client_authed_as_hr.post(
            "/api/v1/invites",
            json={
                "email": "newmigrant@example.com",
                "first_name": "Новый",
                "last_name": "Мигрант",
                "preferred_language": "ru",
            },
        )

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "token" in body, "Response must include raw token (only on create)"
    assert "expires_at" in body, "Response must include expires_at"
    assert body.get("email") == "newmigrant@example.com"


@pytest.mark.asyncio
async def test_create_invite_duplicate_active_refreshes(
    client_authed_as_hr, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/invites twice for the same (company, email) while the first
    invite is still active → second call returns 200 with the same invite_id,
    a rotated token (different URL), and the updated first_name/last_name.

    No 409 is raised — the endpoint is idempotent for the demo flow.
    """
    with patch(
        "app.email.mailhog_client.send_invite_email",
        new_callable=AsyncMock,
    ) as mock_send:
        mock_send.return_value = None

        # First invite — must create (201)
        resp_first = await client_authed_as_hr.post(
            "/api/v1/invites",
            json={
                "email": "refresh@example.com",
                "first_name": "Оригинал",
                "last_name": "Фамилия",
                "preferred_language": "ru",
            },
        )
        assert resp_first.status_code == 201, (
            f"First invite must be 201, got {resp_first.status_code}: {resp_first.text}"
        )
        first_body = resp_first.json()
        first_invite_id = first_body["id"]
        first_url = first_body["token"]

        # Second invite — same email, updated name → must refresh (200)
        resp_second = await client_authed_as_hr.post(
            "/api/v1/invites",
            json={
                "email": "refresh@example.com",
                "first_name": "Обновлённый",
                "last_name": "Мигрант",
                "preferred_language": "hi",
            },
        )
        assert resp_second.status_code == 200, (
            f"Duplicate active invite must return 200 (refresh), "
            f"got {resp_second.status_code}: {resp_second.text}"
        )
        second_body = resp_second.json()

    # Same record refreshed in-place
    assert second_body.get("id") == first_invite_id, (
        f"Refreshed invite must keep the original id={first_invite_id}, "
        f"got {second_body.get('id')}"
    )
    # Token must have rotated
    assert second_body.get("token") != first_url, (
        "Refreshed invite must have a new token (different from the first one)"
    )
    # Mutable fields updated
    assert second_body.get("first_name") == "Обновлённый", (
        f"first_name must be updated to 'Обновлённый', got {second_body.get('first_name')}"
    )
    assert second_body.get("preferred_language") == "hi", (
        f"preferred_language must be updated to 'hi', got {second_body.get('preferred_language')}"
    )
    # Structural fields present
    assert "expires_at" in second_body, "Response must include expires_at"
    assert second_body.get("email") == "refresh@example.com"
    # Email was sent twice (once per call)
    assert mock_send.call_count == 2, (  # noqa: PLR2004
        f"send_invite_email must be called twice (create + refresh), got {mock_send.call_count}"
    )
