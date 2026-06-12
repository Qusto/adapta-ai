"""Phase 0 — `GET /healthz` smoke contract.

Expected to FAIL in red phase: `app.main` module does not exist yet.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_healthz_returns_200(app_client: Any) -> None:
    """GET /healthz returns 200 with body {"status": "ok"}."""
    response = await app_client.get("/healthz")

    assert response.status_code == 200, (
        f"expected 200 from /healthz, got {response.status_code}: {response.text}"
    )

    payload = response.json()
    assert payload == {"status": "ok"}, (
        f"expected body {{'status': 'ok'}}, got {payload!r}"
    )


@pytest.mark.asyncio
async def test_healthz_responds_with_json_content_type(app_client: Any) -> None:
    """Edge: response Content-Type must be application/json (FastAPI default)."""
    response = await app_client.get("/healthz")

    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/json"), (
        f"expected JSON content-type, got {content_type!r}"
    )
