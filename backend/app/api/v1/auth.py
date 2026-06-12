"""POST /api/v1/auth/login — HR email/password login — Phase 1.

Also exposes POST /api/v1/auth/logout, which clears the HttpOnly cookie used
by the StaticAuthMiddleware to gate /b2c/* and /b2b/* page navigations.
"""

from __future__ import annotations

import logging
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.jwt import decode_jwt, encode_jwt
from app.auth.password import verify_password
from app.config import get_settings
from app.database import async_session_factory
from app.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: Name of the HttpOnly cookie that mirrors the JWT for page navigations.
COOKIE_NAME = "adapta_token"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    first_name: str
    last_name: str
    company_id: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    """Attach the HttpOnly adapta_token cookie to `response`.

    `secure=True` is required for the SameSite=Lax + cross-page-nav flow we use
    behind the production host (behind a reverse proxy). In local HTTP dev browsers will skip
    the cookie, which is fine: the frontend falls back to Authorization headers
    from localStorage for fetch calls.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(body: LoginRequest, response: Response) -> Any:
    """Authenticate HR user by email + bcrypt password; return HS256 JWT."""
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == body.email))
        user: User | None = result.scalar_one_or_none()

    # Constant-time: always check password even if user not found
    dummy_hash = "$2b$12$KIXexxx"  # will fail bcrypt compare below
    stored_hash = user.password_hash if user is not None else dummy_hash

    if stored_hash is None or not verify_password(body.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid email or password.",
                }
            },
        )
    if user is None:
        # Unreachable but satisfies type checker
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)  # pragma: no cover

    payload = {
        "sub": str(user.id),
        "role": user.role,
        "company_id": str(user.company_id),
        "preferred_language": user.preferred_language,
    }
    token = encode_jwt(payload)

    settings = get_settings()
    _set_session_cookie(response, token, max_age=settings.jwt_ttl_hr_seconds)

    return LoginResponse(
        access_token=token,
        token_type="Bearer",
        user=UserOut(
            id=str(user.id),
            email=user.email,
            role=user.role,
            first_name=user.first_name,
            last_name=user.last_name,
            company_id=str(user.company_id),
        ),
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(response: Response) -> dict[str, bool]:
    """Clear the session cookie. Idempotent — works with or without an active token."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        domain=None,
        secure=True,
        samesite="lax",
        httponly=True,
    )
    return {"ok": True}


@router.post("/cookie", status_code=status.HTTP_200_OK)
async def set_cookie_from_bearer(request: Request, response: Response) -> dict[str, bool]:
    """(Re)establish the HttpOnly session cookie from a valid Bearer JWT.

    Heals the cookie/localStorage desync: a returning user may carry a JWT in
    localStorage (used for fetch Authorization headers) but have no cookie —
    e.g. they authenticated before the cookie was introduced, or in another
    tab. Without the cookie, a top-level browser navigation to a gated page
    (no Authorization header on navigations) is bounced to the landing.

    Public entry pages call this with the localStorage JWT so that subsequent
    page navigations carry the cookie. The JWT is fully validated first, so
    this cannot be used to set an arbitrary cookie.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "MISSING_BEARER", "message": "Bearer token required."}},
        )
    token = token.strip()
    try:
        payload = decode_jwt(token)
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN", "message": "Invalid or expired token."}},
        ) from exc

    settings = get_settings()
    ttl = (
        settings.jwt_ttl_hr_seconds
        if payload.get("role") == "hr"
        else settings.jwt_ttl_migrant_seconds
    )
    _set_session_cookie(response, token, max_age=ttl)
    return {"ok": True}
