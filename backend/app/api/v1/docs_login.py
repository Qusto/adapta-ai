"""POST /docs/login — demo password gate for /docs/modules/site/*.

Accepts form-data `password=...` and `next=...` (redirect target).
On success: sets HttpOnly cookie `adapta_demo_auth` (24h) + redirects.
On failure: returns HTML login form with error message.
On missing env var: 503.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.middleware.static_auth import (
    _DEMO_COOKIE_NAME,
    _docs_login_form,
    _get_demo_password,
    _make_demo_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["docs-auth"])

_COOKIE_MAX_AGE = 86400  # 24 hours


@router.post("/docs/login", include_in_schema=False)
async def docs_login(
    password: str = Form(...),
    next: str = Form(default="/docs/modules/site/"),
) -> Response:
    """Verify demo password and set auth cookie.

    - Correct password → 302 redirect to `next` with HttpOnly cookie.
    - Wrong password → 200 HTML form with error message.
    - ADAPTA_DEMO_PASSWORD not set → 503.
    """
    demo_password = _get_demo_password()
    if not demo_password:
        return HTMLResponse(
            status_code=503,
            content="<h1>503 — Demo mode disabled</h1>"
            "<p>ADAPTA_DEMO_PASSWORD is not configured on this server.</p>",
        )

    if password != demo_password:
        logger.warning("docs/login: wrong password attempt")
        return HTMLResponse(
            status_code=200,
            content=_docs_login_form(error="Неверный пароль. Попробуйте ещё раз."),
        )

    # Correct password — issue cookie and redirect
    token = _make_demo_token(demo_password)

    # Sanitize redirect target: must start with /docs/
    redirect_to = next if next.startswith("/docs/") else "/docs/modules/site/"

    logger.info("docs/login: successful auth, redirecting to %s", redirect_to)

    response = RedirectResponse(url=redirect_to, status_code=302)
    response.set_cookie(
        key=_DEMO_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # secure=True is set by Caddy/nginx in production via HTTPS
        # Don't set here to allow local dev over HTTP
    )
    return response
