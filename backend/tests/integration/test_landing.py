"""Phase 08 — role-selection landing on `/`.

Asserts that:
- `GET /` returns the landing HTML (200 + text/html + brand string).
- Both role cards link to the correct mocks (b2c welcome, b2b hr-dashboard).
- The landing's CSS is served via the /landing static mount.
- The pre-existing /b2c static mount is not broken by the new root route.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_landing_root_returns_200_html(app_client: Any) -> None:
    """GET / returns 200 + text/html and contains the AdaptaAI brand."""
    response = await app_client.get("/")

    assert response.status_code == 200, (
        f"expected 200 from /, got {response.status_code}: {response.text[:200]}"
    )

    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("text/html"), (
        f"expected text/html content-type, got {content_type!r}"
    )

    body = response.text
    assert "AdaptaAI" in body, "landing body must contain the brand word 'AdaptaAI'"


@pytest.mark.asyncio
async def test_landing_links_to_b2c_and_b2b(app_client: Any) -> None:
    """Landing must offer both role entrypoints — migrant (b2c) + employer (b2b)."""
    response = await app_client.get("/")
    assert response.status_code == 200
    body = response.text

    assert "/b2c/01-welcome.html" in body, (
        "landing must link the migrant card to /b2c/01-welcome.html"
    )
    assert "/b2b/15-hr-dashboard.html" in body, (
        "landing must link the employer card to /b2b/15-hr-dashboard.html"
    )


@pytest.mark.asyncio
async def test_landing_css_served(app_client: Any) -> None:
    """Stylesheet at /landing/landing.css must be reachable through StaticFiles."""
    response = await app_client.get("/landing/landing.css")

    assert response.status_code == 200, (
        f"expected 200 from /landing/landing.css, got {response.status_code}"
    )

    content_type = response.headers.get("content-type", "")
    assert "css" in content_type, f"expected CSS content-type, got {content_type!r}"

    assert ".role-card" in response.text, (
        "landing.css must define .role-card layout — otherwise the page is unstyled"
    )


@pytest.mark.asyncio
async def test_b2c_welcome_still_reachable(app_client: Any) -> None:
    """Regression: the new GET / route must not shadow the /b2c static mount.

    The welcome page is one of the few /b2c pages that must remain anonymous —
    migrants land on it from invite emails before they have any session.
    """
    response = await app_client.get("/b2c/01-welcome.html")

    assert response.status_code == 200, (
        f"expected 200 from /b2c/01-welcome.html after adding GET /, "
        f"got {response.status_code}: {response.text[:200]}"
    )

    assert "AdaptaAI" in response.text, "b2c welcome page must still render"


@pytest.mark.asyncio
async def test_b2c_hub_now_requires_auth(app_client: Any) -> None:
    """After auth-gate rollout, /b2c/04-hub.html must NOT be public.

    Browsers (Accept: text/html) get a 302 → /, fetch/XHR clients get 401.
    """
    response = await app_client.get(
        "/b2c/04-hub.html",
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 401), (
        f"expected 302 or 401 from /b2c/04-hub.html without auth, "
        f"got {response.status_code}"
    )
