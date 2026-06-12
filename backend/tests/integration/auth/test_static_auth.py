"""Integration tests for StaticAuthMiddleware + cookie session lifecycle.

Coverage:
  - Public allow-list: landing, healthz, welcome, HR dashboard, shared assets.
  - Protected redirect: HTML request → 302 /?next=...
  - Protected 401: JSON request → 401 {"detail": "Unauthorized"}
  - Cookie issuance: login, accept_invite both set adapta_token.
  - Logout: deletes the cookie.
  - Cookie grants access on a subsequent page navigation.
  - Authorization header still works (fetch / XHR with localStorage token).
"""

from __future__ import annotations

from typing import Any

import pytest


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Public paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_landing_is_public(app_client: Any) -> None:
    """GET / returns 200 without any auth — landing must stay anonymous."""
    response = await app_client.get("/")
    assert response.status_code == 200, response.text[:200]


@pytest.mark.asyncio
async def test_welcome_is_public(app_client: Any) -> None:
    """GET /b2c/01-welcome.html returns 200 — migrants land here from invite email."""
    response = await app_client.get("/b2c/01-welcome.html")
    assert response.status_code == 200, response.text[:200]


@pytest.mark.asyncio
async def test_hr_login_page_is_public(app_client: Any) -> None:
    """GET /b2b/15-hr-dashboard.html returns 200 — HR cannot log in otherwise."""
    response = await app_client.get("/b2b/15-hr-dashboard.html")
    assert response.status_code == 200, response.text[:200]


@pytest.mark.asyncio
async def test_design_tokens_public(app_client: Any) -> None:
    """GET /design-tokens.css returns 200 — landing page depends on it."""
    response = await app_client.get("/design-tokens.css")
    assert response.status_code == 200, response.text[:200]


@pytest.mark.asyncio
async def test_healthz_is_public(app_client: Any) -> None:
    """GET /healthz returns 200 — Docker healthcheck must succeed without auth."""
    response = await app_client.get("/healthz")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Protected paths — unauthenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protected_b2c_redirects_html(app_client: Any) -> None:
    """Browser navigation to a protected b2c page → 302 /?next=<path>."""
    response = await app_client.get(
        "/b2c/04-hub.html",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"},
        follow_redirects=False,
    )
    assert response.status_code == 302, (
        f"expected 302 redirect, got {response.status_code}: {response.text[:200]}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/?next=/b2c/04-hub.html"), (
        f"expected Location=/?next=/b2c/04-hub.html, got {location!r}"
    )


@pytest.mark.asyncio
async def test_protected_b2c_returns_401_json(app_client: Any) -> None:
    """Fetch/XHR to a protected b2c page → 401 JSON envelope."""
    response = await app_client.get(
        "/b2c/04-hub.html",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401, response.text[:200]
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_protected_b2b_redirects(app_client: Any) -> None:
    """Browser navigation to a protected b2b page → 302 /?next=<path>."""
    response = await app_client.get(
        "/b2b/16-worker-detail.html",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers.get("location", "").startswith(
        "/?next=/b2b/16-worker-detail.html"
    )


# ---------------------------------------------------------------------------
# Cookie issuance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sets_cookie(app_client: Any, seed_hr, env_vars) -> None:  # noqa: ANN001
    """POST /api/v1/auth/login → response carries adapta_token cookie."""
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "daria@pik.demo", "password": "demo"},
    )
    assert response.status_code == 200
    assert "adapta_token" in response.cookies, (
        f"expected adapta_token in cookies, got {list(response.cookies.keys())}"
    )
    assert response.cookies["adapta_token"] == response.json()["access_token"]


@pytest.mark.asyncio
async def test_accept_invite_sets_cookie(
    app_client: Any, valid_invite, env_vars  # noqa: ANN001
) -> None:
    """POST /api/v1/invites/{token}/accept → response carries adapta_token cookie."""
    token = valid_invite["raw_token"]
    response = await app_client.post(
        f"/api/v1/invites/{token}/accept",
        json={"preferred_language": "hi"},
    )
    assert response.status_code == 201, response.text[:200]
    assert "adapta_token" in response.cookies
    assert response.cookies["adapta_token"] == response.json()["access_token"]


@pytest.mark.asyncio
async def test_logout_clears_cookie(app_client: Any, env_vars) -> None:  # noqa: ANN001
    """POST /api/v1/auth/logout → cookie is deleted (max-age=0)."""
    response = await app_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    # delete_cookie sets the cookie header with an expired/empty value.
    set_cookie = response.headers.get("set-cookie", "")
    assert "adapta_token=" in set_cookie, (
        f"expected adapta_token Set-Cookie header, got {set_cookie!r}"
    )
    # Either Max-Age=0 or an expired Expires date — both mean "delete".
    assert "Max-Age=0" in set_cookie or "1970" in set_cookie, (
        f"expected cookie expiry directive in {set_cookie!r}"
    )


# ---------------------------------------------------------------------------
# Cookie / Bearer access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookie_grants_access(
    app_client: Any, seed_hr, env_vars  # noqa: ANN001
) -> None:
    """After login, the cookie alone lets the browser navigate to a protected page.

    httpx's cookie jar drops Secure cookies on http:// URLs (correctly mirroring
    real browsers). So we replay the issued token as a cookie on the follow-up
    request — which is exactly what a browser does on the production host.
    """
    login = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "daria@pik.demo", "password": "demo"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = await app_client.get(
        "/b2b/16-worker-detail.html",
        headers={"Accept": "text/html"},
        cookies={"adapta_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 200, (
        f"expected 200 with cookie, got {response.status_code}: {response.text[:200]}"
    )


@pytest.mark.asyncio
async def test_bearer_header_grants_access(
    app_client: Any, hr_token, env_vars  # noqa: ANN001
) -> None:
    """Authorization: Bearer <jwt> alone (no cookie) also unlocks a protected page."""
    response = await app_client.get(
        "/b2c/04-hub.html",
        headers={
            "Accept": "text/html",
            "Authorization": f"Bearer {hr_token}",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text[:200]


@pytest.mark.asyncio
async def test_invalid_cookie_rejected(app_client: Any, env_vars) -> None:  # noqa: ANN001
    """A malformed JWT cookie still triggers the auth gate (redirect / 401)."""
    app_client.cookies.set("adapta_token", "not-a-real-jwt")
    response = await app_client.get(
        "/b2c/04-hub.html",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers.get("location", "").startswith("/?next=/b2c/04-hub.html")
    # Cleanup so we don't pollute other tests sharing the client (function-scoped though).
    app_client.cookies.delete("adapta_token")


# ---------------------------------------------------------------------------
# Developer module-map site (/docs/modules/site/*) — auth-gated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docs_modules_site_requires_auth(app_client: Any) -> None:
    """GET /docs/modules/site/ without a token → 302 to /?next=... (HTML nav)."""
    response = await app_client.get(
        "/docs/modules/site/",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"},
        follow_redirects=False,
    )
    assert response.status_code == 302, (
        f"expected 302 redirect, got {response.status_code}: {response.text[:200]}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/?next=/docs/modules/site"), (
        f"expected Location=/?next=/docs/modules/site..., got {location!r}"
    )


@pytest.mark.asyncio
async def test_docs_modules_site_accessible_with_jwt(
    app_client: Any, hr_token, env_vars  # noqa: ANN001
) -> None:
    """With a valid JWT cookie the developer site is served (200 + HTML)."""
    response = await app_client.get(
        "/docs/modules/site/",
        headers={"Accept": "text/html"},
        cookies={"adapta_token": hr_token},
        follow_redirects=False,
    )
    assert response.status_code == 200, (
        f"expected 200 with cookie, got {response.status_code}: {response.text[:200]}"
    )
    # html=True on StaticFiles serves index.html for the directory root.
    assert "html" in response.headers.get("content-type", "").lower()
