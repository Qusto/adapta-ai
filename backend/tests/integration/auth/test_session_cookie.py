"""Integration tests for POST /api/v1/auth/cookie.

Heals the cookie/localStorage desync: a returning user carries a JWT in
localStorage (used for fetch Authorization headers) but may have no session
cookie. Public entry pages POST that Bearer JWT here to (re)establish the
cookie so subsequent top-level navigations to gated pages are not bounced.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cookie_set_from_valid_bearer(
    app_client, hr_token, env_vars  # noqa: ANN001
) -> None:
    """A valid Bearer JWT → 200 and sets the HttpOnly adapta_token cookie."""
    resp = await app_client.post(
        "/api/v1/auth/cookie",
        headers={"Authorization": f"Bearer {hr_token}"},
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text[:200]}"
    assert resp.cookies.get("adapta_token") == hr_token
    assert "httponly" in resp.headers.get("set-cookie", "").lower()


@pytest.mark.asyncio
async def test_cookie_missing_bearer_rejected(app_client, env_vars) -> None:  # noqa: ANN001
    """No Authorization header → 401, no cookie set."""
    resp = await app_client.post("/api/v1/auth/cookie")
    assert resp.status_code == 401, resp.text[:200]
    assert resp.cookies.get("adapta_token") is None


@pytest.mark.asyncio
async def test_cookie_garbage_token_rejected(app_client, env_vars) -> None:  # noqa: ANN001
    """A malformed JWT → 401, no cookie set (cannot set an arbitrary cookie)."""
    resp = await app_client.post(
        "/api/v1/auth/cookie",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401, resp.text[:200]
    assert resp.cookies.get("adapta_token") is None
