"""FastAPI application entrypoint.

Phase 0: only `/healthz`.
Phase 1: auth/invite/workers routers registered under /api/v1/.
Static: b2c/b2b HTML mocks served via StaticFiles; shared assets at root.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.chat_escalations import router as chat_escalations_router
from app.api.v1.chat_stats import router as chat_stats_router
from app.api.v1.chat_threads import router as chat_threads_router
from app.api.v1.demo import router as demo_router
from app.api.v1.documents import router as documents_router
from app.api.v1.company import router as company_router
from app.api.v1.docs_login import router as docs_login_router
from app.api.v1.invites import router as invites_router
from app.api.v1.journey import router as journey_router
from app.api.v1.workers import router as workers_router
from app.middleware.static_auth import StaticAuthMiddleware

app = FastAPI(title="AdaptaAI API", version="0.1.0")

# Auth gate for static pages — registered FIRST so it runs LAST in the
# request chain (Starlette wraps middlewares in reverse), but registered
# BEFORE CORS so CORS headers are added even on 302/401 responses.
app.add_middleware(StaticAuthMiddleware)

# CORS — allow all origins in dev so file:// and localhost frontends work.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Transform HTTPException detail into canonical error envelope.

    If detail is already a dict with an 'error' key, pass it through directly.
    Otherwise wrap in {"error": {"code": ..., "message": ...}}.
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        body = detail  # already {"error": {...}}
    else:
        body = {"error": {"code": "ERROR", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body)


# Docs password gate (no prefix — route is /docs/login)
app.include_router(docs_login_router)

# Phase 1 routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(invites_router, prefix="/api/v1")
app.include_router(workers_router, prefix="/api/v1")
app.include_router(company_router, prefix="/api/v1")
app.include_router(journey_router, prefix="/api/v1")

# Phase 2 routers
app.include_router(documents_router, prefix="/api/v1")

# Phase 3 routers
app.include_router(chat_router, prefix="/api/v1")
app.include_router(chat_escalations_router, prefix="/api/v1")
app.include_router(chat_stats_router, prefix="/api/v1")
app.include_router(chat_threads_router, prefix="/api/v1")

# Demo endpoints (only when ADAPTA_DEMO_ENABLED=true, default: true)
if os.getenv("ADAPTA_DEMO_ENABLED", "true").lower() == "true":
    app.include_router(demo_router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — used by docker-compose healthcheck and `make smoke`."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static file mounts — AFTER all API routers so /api/v1/* is never shadowed.
#
# In Docker:  b2c/b2b/landing are bind-mounted to /app/static/{b2c,b2b,landing}.
#             Shared assets (design-tokens.css, i18n.js, mock-data.js) are
#             bind-mounted directly into /app/static/.
# Locally:    STATIC_B2C_DIR / STATIC_B2B_DIR / STATIC_LANDING_DIR /
#             STATIC_ROOT_DIR env vars can override (or the is_dir() guard
#             silently skips absent dirs).
#
# HTML mocks use relative paths like `../design-tokens.css`.  When a page is
# served at /b2c/01-welcome.html the browser resolves `..` to `/`, so
# design-tokens.css must be available at /design-tokens.css.  We achieve this
# by mounting the static root dir (which contains the shared files) at "/".
#
# GET "/" is bound to a dedicated route that serves landing/index.html — the
# StaticFiles mount at "/" intentionally has html=False so it would 404 on
# the bare prefix.
# ---------------------------------------------------------------------------

# Repo root holds b2c/, b2b/, landing/ next to backend/ — used as a fallback
# when env vars are absent (i.e. local dev and pytest, but not Docker).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_static_dir(env_var: str, docker_default: str, repo_subdir: str) -> Path:
    """Pick the first existing dir among: $env_var → docker default → repo root."""
    candidates = [os.getenv(env_var), docker_default, str(_REPO_ROOT / repo_subdir)]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return Path(docker_default)  # may not exist; downstream is_dir() guards mounts


_static_b2c = _resolve_static_dir("STATIC_B2C_DIR", "static/b2c", "b2c")
_static_b2b = _resolve_static_dir("STATIC_B2B_DIR", "static/b2b", "b2b")
_static_landing = _resolve_static_dir("STATIC_LANDING_DIR", "static/landing", "landing")
# Internal module-map site for developers — protected by StaticAuthMiddleware.
_static_docs_site = _resolve_static_dir(
    "STATIC_DOCS_DIR", "static/docs/modules/site", "docs/modules/site"
)
# Root static dir that contains design-tokens.css, i18n.js, mock-data.js
# alongside the b2c/ and b2b/ sub-directories.
_static_root = _resolve_static_dir("STATIC_ROOT_DIR", "static", ".")


@app.get("/i/{token}", include_in_schema=False)
async def invite_redirect(token: str) -> RedirectResponse:
    """Migrant clicks invite link from email — redirect to welcome page with token."""
    return RedirectResponse(url=f"/b2c/01-welcome.html?invite={token}", status_code=302)


@app.get("/", include_in_schema=False)
async def landing() -> FileResponse:
    """Serve the role-selection landing page at the application root.

    Resolves landing/index.html via the same directory used for the
    /landing static mount, so local dev (`landing/` in repo root) and the
    Docker bind-mount (`/app/static/landing`) both work.
    """
    return FileResponse(_static_landing / "index.html", media_type="text/html")


# Mount specific sub-directories first (more specific prefix wins in Starlette).
if _static_b2c.is_dir():
    app.mount("/b2c", StaticFiles(directory=_static_b2c, html=True), name="b2c")

if _static_b2b.is_dir():
    app.mount("/b2b", StaticFiles(directory=_static_b2b, html=True), name="b2b")

if _static_landing.is_dir():
    app.mount(
        "/landing",
        StaticFiles(directory=_static_landing, html=True),
        name="landing",
    )

# Docs site (carte des modules) — auth-protected via StaticAuthMiddleware.
# Mount BEFORE the catch-all "/" so /docs/modules/site/* resolves here.
if _static_docs_site.is_dir():
    app.mount(
        "/docs/modules/site",
        StaticFiles(directory=_static_docs_site, html=True),
        name="docs-modules-site",
    )

# Mount the root static dir at "/" so that ../design-tokens.css resolves to
# /design-tokens.css.  html=False prevents a stray index.html from hijacking
# the root path; the guard ensures missing dirs don't crash non-Docker runs.
if _static_root.is_dir():
    app.mount("/", StaticFiles(directory=_static_root), name="static-root")
