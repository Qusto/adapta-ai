"""Integration tests for GET /api/v1/workers — workers list endpoint.

test_workers_list_returns_company_migrants: HR JWT → 200 with migrant list
test_workers_list_non_hr_forbidden: non-HR JWT → 403
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# test: HR JWT → 200 with migrant list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workers_list_returns_company_migrants(
    client_authed_as_hr, db_session_with_users, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/workers with HR JWT returns list of company's migrants.

    Preconditions (db_session_with_users fixture):
      - new_user: migrant in ГК ПИК company → must appear
      - old_user: migrant in ГК ПИК company → must appear

    Response shape:
    { "items": [{"id", "first_name", "last_name", "language", "created_at", "status",
                 "country", "object", "updated"}], "total": N }
    """
    resp = await client_authed_as_hr.get("/api/v1/workers")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "items" in body, "Response must have 'items' key"
    assert "total" in body, "Response must have 'total' key"

    items = body["items"]
    assert isinstance(items, list), "'items' must be a list"
    assert body["total"] == len(items), "'total' must match items count"

    # Both migrant users from the fixture must be present
    ids = [item["id"] for item in items]
    new_user_id = str(db_session_with_users["new_user"].id)
    old_user_id = str(db_session_with_users["old_user"].id)

    assert new_user_id in ids, f"new_user {new_user_id} must be in workers list"
    assert old_user_id in ids, f"old_user {old_user_id} must be in workers list"

    # Each item must have required fields
    for item in items:
        assert "id" in item, "Each item must have 'id'"
        assert "first_name" in item, "Each item must have 'first_name'"
        assert "last_name" in item, "Each item must have 'last_name'"
        assert "language" in item, "Each item must have 'language'"
        assert "created_at" in item, "Each item must have 'created_at'"
        assert "status" in item, "Each item must have 'status'"
        assert item["status"] == "active", f"status must be 'active', got {item['status']!r}"
        assert "country" in item, "Each item must have 'country'"
        assert "object" in item, "Each item must have 'object'"
        assert "updated" in item, "Each item must have 'updated'"

    # Validate derived fields for hindi-speaking migrant (new_user fixture uses 'hi')
    new_user_item = next(
        (i for i in items if i["id"] == str(db_session_with_users["new_user"].id)),
        None,
    )
    if new_user_item is not None:
        assert new_user_item["country"] == "🇮🇳", (
            f"Hindi-speaking user must have country=🇮🇳, got {new_user_item['country']!r}"
        )
        # ГК ПИК company must map to Метрополия-14
        assert new_user_item["object"] == "Метрополия-14", (
            f"ГК ПИК company must map to 'Метрополия-14', got {new_user_item['object']!r}"
        )


# ---------------------------------------------------------------------------
# test: migrant JWT → 403 FORBIDDEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workers_list_non_hr_forbidden(
    app_client, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/workers with migrant JWT → 403 FORBIDDEN."""
    # Accept invite to get a migrant JWT
    token = valid_invite["raw_token"]
    accept_resp = await app_client.post(
        f"/api/v1/invites/{token}/accept",
        json={"preferred_language": "hi"},
    )
    assert accept_resp.status_code == 201, (
        f"Invite accept must succeed: {accept_resp.text}"
    )
    migrant_jwt = accept_resp.json()["access_token"]

    # Hit /workers with migrant JWT → must be 403
    resp = await app_client.get(
        "/api/v1/workers",
        headers={"Authorization": f"Bearer {migrant_jwt}"},
    )

    assert resp.status_code == 403, (
        f"Migrant JWT must be rejected with 403, got {resp.status_code}: {resp.text}"
    )

    body = resp.json()
    error = body.get("error", {})
    assert error.get("code") == "FORBIDDEN", (
        f"Error code must be FORBIDDEN, got: {error.get('code')}"
    )


# ---------------------------------------------------------------------------
# test: no auth → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workers_list_unauthenticated(
    app_client, env_vars  # noqa: ANN001
) -> None:
    """GET /api/v1/workers without JWT → 401 UNAUTHORIZED."""
    resp = await app_client.get("/api/v1/workers")

    assert resp.status_code == 401, (
        f"Missing JWT must return 401, got {resp.status_code}: {resp.text}"
    )
