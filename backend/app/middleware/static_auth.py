"""StaticAuthMiddleware — gate all internal static pages behind a JWT.

Public surface (anonymous traffic allowed):
  - Landing root and shared front-end assets needed by it.
  - The invite landing page (/b2c/01-welcome.html) and the HR login page
    (/b2b/15-hr-dashboard.html GET-only) — both must be reachable to obtain
    a token in the first place.
  - All public API endpoints (login, invite preview/accept, healthz, docs).

Everything else under /b2c/* and /b2b/* requires a valid JWT, which the
middleware reads from either:
  - Cookie `adapta_token` (set by login/accept endpoints, HttpOnly), or
  - `Authorization: Bearer <token>` header (kept for fetch-API calls that
    still rely on localStorage).

For /docs/modules/site/* there is an additional gate — demo cookie:
  - Cookie `adapta_demo_auth` with the correct HMAC token is accepted
    (set by the POST /docs/login endpoint).
  - If neither JWT nor demo cookie is present, an HTML login form is returned
    (Content-Type: text/html, HTTP 200) instead of a redirect.

Unauthenticated requests to /b2c/* /b2b/* are redirected (HTML navigations)
to /?next=<path> or rejected with 401 JSON (fetch / XHR).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from urllib.parse import quote

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.auth.jwt import decode_jwt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public-path patterns
# ---------------------------------------------------------------------------

#: Exact paths that anyone can hit without a token.
#:
#: Includes the FastAPI auto-generated API browser routes (/docs, /redoc,
#: /openapi.json).  These MUST stay exact-match — using a "/docs" prefix
#: would accidentally expose other paths under /docs/* (e.g. the auth-gated
#: developer module map at /docs/modules/site/).
PUBLIC_EXACT: frozenset[str] = frozenset(
    {
        "/",
        "/healthz",
        "/favicon.ico",
        "/b2c/01-welcome.html",
        # PWA assets — must be fetchable anonymously (the public welcome page
        # links the manifest, and the service worker + icons are loaded before
        # the user obtains a token).
        "/b2c/manifest.json",
        "/b2c/sw.js",
        "/b2c/icon-192.png",
        "/b2c/icon-512.png",
        "/b2b/15-hr-dashboard.html",
        # Partner / Sber-admin entry — has its own client-side login screen,
        # so the HTML shell must be reachable anonymously (same as the HR
        # dashboard above). Data APIs it calls still require a valid JWT.
        "/b2b/20-sber-products.html",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        "/docs/login",  # demo password POST endpoint — must be public
    }
)

#: Path prefixes that are fully public (assets, public API).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/landing/",
    "/i/",
    "/api/v1/auth/",
    "/api/v1/invites/",
    "/api/v1/demo/",  # one-button demo login — no token required
)

#: Shared front-end assets at root that the landing page needs unauthenticated.
PUBLIC_EXACT_ASSETS: frozenset[str] = frozenset(
    {
        "/design-tokens.css",
        "/i18n.js",
        "/mock-data.js",
        "/rag-metrics.json",
    }
)

#: Paths under /docs/ that are protected by the demo-password gate
#: (rather than the standard JWT gate).
_DOCS_PROTECTED_PREFIX = "/docs/modules/site"


def _is_public(path: str) -> bool:
    """Return True if `path` should bypass the auth gate."""
    if path in PUBLIC_EXACT or path in PUBLIC_EXACT_ASSETS:
        return True
    return path.startswith(PUBLIC_PREFIXES)


def _extract_token(request: Request) -> str | None:
    """Pull a JWT from cookie first, then Authorization header."""
    cookie_token = request.cookies.get("adapta_token")
    if cookie_token:
        return cookie_token

    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        return None
    # Accept "Bearer <token>" — anything else is treated as missing.
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def _wants_html(request: Request) -> bool:
    """Heuristic: True if the client likely wants an HTML response.

    Browser page navigations always send Accept that contains text/html,
    while fetch/XHR calls typically advertise application/json or */*.
    """
    accept = request.headers.get("accept", "")
    return "text/html" in accept.lower()


# ---------------------------------------------------------------------------
# Demo password helpers
# ---------------------------------------------------------------------------

_DEMO_COOKIE_NAME = "adapta_demo_auth"


def _get_demo_password() -> str | None:
    """Read ADAPTA_DEMO_PASSWORD from environment."""
    return os.environ.get("ADAPTA_DEMO_PASSWORD") or None


def _make_demo_token(password: str) -> str:
    """Derive a stable HMAC token from the demo password.

    Using HMAC-SHA256 with the password as both key and message means
    the token is deterministic (same password → same token) and cannot
    be reversed to recover the password.
    """
    return hmac.new(  # type: ignore[attr-defined]
        password.encode(),
        password.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify_demo_cookie(request: Request, demo_password: str) -> bool:
    """Return True if the demo auth cookie matches the current password."""
    cookie_val = request.cookies.get(_DEMO_COOKIE_NAME)
    if not cookie_val:
        return False
    expected = _make_demo_token(demo_password)
    return hmac.compare_digest(cookie_val, expected)


def _docs_login_form(error: str = "") -> str:
    """Return minimal HTML login form for the docs gate."""
    error_html = (
        f'<p style="color:#e53e3e;margin:0 0 12px">{error}</p>' if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AdaptaAI — Документация</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#f1f5f9;
        display:flex;align-items:center;justify-content:center;min-height:100vh}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:12px;
         padding:40px;max-width:380px;width:100%}}
  h1{{font-size:18px;font-weight:600;margin-bottom:6px;color:#f8fafc}}
  .sub{{font-size:13px;color:#94a3b8;margin-bottom:28px}}
  label{{font-size:13px;color:#94a3b8;display:block;margin-bottom:6px}}
  input[type=password]{{width:100%;padding:10px 14px;border:1px solid #334155;
    border-radius:8px;background:#0f172a;color:#f1f5f9;font-size:14px;
    outline:none;transition:border .15s}}
  input[type=password]:focus{{border-color:#06b6d4}}
  button{{margin-top:16px;width:100%;padding:10px 14px;
    background:linear-gradient(135deg,#06b6d4,#10b981);
    border:none;border-radius:8px;color:#fff;font-size:14px;
    font-weight:600;cursor:pointer}}
  button:hover{{opacity:.9}}
  .hint{{margin-top:20px;font-size:12px;color:#64748b;text-align:center}}
  .hint a{{color:#06b6d4;text-decoration:none}}
</style>
</head>
<body>
<div class="card">
  <h1>AdaptaAI · Документация</h1>
  <p class="sub">Закрытая зона — только для команды.</p>
  {error_html}
  <form method="POST" action="/docs/login">
    <input type="hidden" name="next" value="">
    <label for="pw">Демо-пароль</label>
    <input type="password" id="pw" name="password"
           placeholder="Введите пароль" autofocus required>
    <button type="submit">Войти →</button>
  </form>
  <p class="hint">Получить пароль — у команды Digital Teams Сбер Университета.</p>
</div>
</body>
</html>"""


class StaticAuthMiddleware(BaseHTTPMiddleware):
    """Block anonymous access to /b2c/*, /b2b/*, and /docs/modules/site/*.

    /b2c/* and /b2b/* (except public pages):
      - Page navigations (Accept contains text/html) get a 302 to /?next=...
      - API/JSON calls get 401 JSON.

    /docs/modules/site/*:
      - Valid JWT → pass through.
      - Valid demo cookie `adapta_demo_auth` → pass through.
      - Neither → return HTML login form (200 text/html), not a redirect.
        Actual login handled by POST /docs/login (separate router).
      - If ADAPTA_DEMO_PASSWORD env is not set → 503.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # CORS preflight must pass through untouched — the CORS middleware
        # downstream attaches the right headers.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        if _is_public(path):
            return await call_next(request)

        # ----------------------------------------------------------------
        # /docs/modules/site/* — separate gate (JWT or demo cookie)
        # ----------------------------------------------------------------
        if path.startswith(_DOCS_PROTECTED_PREFIX):
            return await self._handle_docs(request, call_next, path)

        # ----------------------------------------------------------------
        # Standard JWT gate for /b2c/* /b2b/*
        # ----------------------------------------------------------------
        token = _extract_token(request)
        if token is not None:
            try:
                decode_jwt(token)
            except jwt.PyJWTError as exc:
                logger.info("StaticAuthMiddleware: JWT rejected for %s: %s", path, exc)
                token = None  # fall through to the unauthorized branch

        if token is None:
            if _wants_html(request):
                next_qs = quote(path, safe="/")
                return RedirectResponse(
                    url=f"/?next={next_qs}",
                    status_code=302,
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        return await call_next(request)

    async def _handle_docs(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        path: str,
    ) -> Response:
        """Gate for /docs/modules/site/*: JWT or demo cookie."""
        demo_password = _get_demo_password()
        if not demo_password:
            return HTMLResponse(
                status_code=503,
                content="<h1>503 — Demo mode disabled</h1>"
                "<p>ADAPTA_DEMO_PASSWORD is not configured on this server.</p>",
            )

        # 1. Valid JWT — always accepted
        token = _extract_token(request)
        if token is not None:
            try:
                decode_jwt(token)
                return await call_next(request)
            except jwt.PyJWTError:
                token = None  # fall through

        # 2. Valid demo cookie — accepted
        if _verify_demo_cookie(request, demo_password):
            return await call_next(request)

        # 3. Neither — return HTML form (not a redirect)
        return HTMLResponse(
            status_code=200,
            content=_docs_login_form(),
        )
