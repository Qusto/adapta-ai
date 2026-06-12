"""Integration tests for POST /api/v1/demo/login-{hr,migrant} cookie behaviour.

Regression guard for the demo flow: the one-button demo login must set the
same HttpOnly `adapta_token` cookie as /api/v1/auth/login. Without it, a
top-level browser navigation to a gated page (e.g. /b2b/18-ticket-inbox.html)
carries no Authorization header and StaticAuthMiddleware redirects to the
landing — the "tickets/RAG kick me out" bug seen during the demo recording.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration

_DEMO_PW = "demo-pw-for-tests"


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTA_DEMO_ENABLED", "true")
    monkeypatch.setenv("ADAPTA_DEMO_PASSWORD", _DEMO_PW)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["hr", "migrant"])
async def test_demo_login_sets_session_cookie(
    app_client, env_vars, demo_env, role  # noqa: ANN001
) -> None:
    """POST /api/v1/demo/login-<role> returns 200 and sets adapta_token cookie."""
    resp = await app_client.post(
        f"/api/v1/demo/login-{role}",
        headers={"X-Demo-Password": _DEMO_PW},
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    assert "access_token" in resp.json(), "Response must include access_token"

    # Cookie must be present so gated page navigations (no Authorization header) pass.
    token_cookie = resp.cookies.get("adapta_token")
    assert token_cookie, f"adapta_token cookie not set. Cookies: {dict(resp.cookies)}"
    assert token_cookie == resp.json()["access_token"], "Cookie value must equal the JWT"

    # HttpOnly must be present in the raw Set-Cookie header.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower(), f"Cookie must be HttpOnly: {set_cookie!r}"
