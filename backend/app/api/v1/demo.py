"""Demo login endpoints — one-button auth for Sergey's 30.06.2026 presentation.

POST /api/v1/demo/login-hr       → JWT + user for Дарья (HR, Застройщик№1)
POST /api/v1/demo/login-migrant  → JWT + user for Раджу Шарма (migrant)

Активируются только когда ADAPTA_DEMO_ENABLED=true И задан ADAPTA_DEMO_PASSWORD.
Клиент обязан передать заголовок `X-Demo-Password`, совпадающий с ENV.
Без этого endpoints отдают 403 — публичный доступ к JWT seed-юзеров закрыт.
Seed users are created on first call (idempotent).
"""

from __future__ import annotations

import hmac
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import _set_session_cookie
from app.auth.jwt import encode_jwt
from app.config import get_settings
from app.database import async_session_factory
from app.db.models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed constants — MUST match scripts/seed_demo.py for idempotency
# ---------------------------------------------------------------------------

_PIK_COMPANY_ID: uuid.UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_DARIA_USER_ID: uuid.UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_RAJU_USER_ID: uuid.UUID = uuid.UUID("44444444-4444-4444-4444-444444444444")

_DARIA_EMAIL: str = "daria@pik.demo"
_RAJU_EMAIL: str = "raju.sharma@example.com"


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    company_id: uuid.UUID
    preferred_language: str


class DemoLoginResponse(BaseModel):
    access_token: str
    user: UserInfo


# ---------------------------------------------------------------------------
# Router — only registered when ADAPTA_DEMO_ENABLED=true
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/demo", tags=["demo"])


def _demo_enabled() -> bool:
    return os.getenv("ADAPTA_DEMO_ENABLED", "true").lower() == "true"


def _demo_password() -> str:
    """Shared demo-пароль из ENV. Пустая строка = demo полностью закрыто."""
    return os.getenv("ADAPTA_DEMO_PASSWORD", "").strip()


def _require_demo_enabled() -> None:
    if not _demo_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Demo endpoints disabled."}},
        )


def _verify_demo_password(provided: str | None) -> None:
    """403 если ENV-пароль не задан или header не совпадает.

    Сравнение через hmac.compare_digest, чтобы исключить timing-атаки.
    """
    expected = _demo_password()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "DEMO_DISABLED",
                    "message": "Demo password not configured on server.",
                }
            },
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "DEMO_BAD_PASSWORD",
                    "message": "Invalid demo password.",
                }
            },
        )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _ensure_pik_company(session: AsyncSession) -> None:
    """Create Застройщик№1 if it does not exist yet."""
    existing = (
        await session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": _PIK_COMPANY_ID},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await session.execute(
        text("INSERT INTO companies (id, name, inn) VALUES (:id, :name, :inn)"),
        {"id": _PIK_COMPANY_ID, "name": "Застройщик№1", "inn": "7700000001"},
    )
    logger.info("demo: created company Застройщик№1 id=%s", _PIK_COMPANY_ID)


async def _ensure_daria(session: AsyncSession) -> None:
    """Create Дарья (HR) if she does not exist."""
    existing = (
        await session.execute(
            text("SELECT id FROM users WHERE id = :id"),
            {"id": _DARIA_USER_ID},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await session.execute(
        text(
            "INSERT INTO users "
            "(id, company_id, email, password_hash, role, "
            " first_name, last_name, preferred_language) "
            "VALUES (:id, :company_id, :email, NULL, :role, :first_name, :last_name, :lang)"
        ),
        {
            "id": _DARIA_USER_ID,
            "company_id": _PIK_COMPANY_ID,
            "email": _DARIA_EMAIL,
            "role": "hr",
            "first_name": "Дарья",
            "last_name": "Соколова",
            "lang": "ru",
        },
    )
    logger.info("demo: created HR user Дарья id=%s", _DARIA_USER_ID)


async def _ensure_raju(session: AsyncSession) -> None:
    """Create Раджу Шарма (migrant) if he does not exist."""
    existing = (
        await session.execute(
            text("SELECT id FROM users WHERE id = :id"),
            {"id": _RAJU_USER_ID},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    await session.execute(
        text(
            "INSERT INTO users "
            "(id, company_id, email, password_hash, role, "
            " first_name, last_name, preferred_language) "
            "VALUES (:id, :company_id, :email, NULL, :role, :first_name, :last_name, :lang)"
        ),
        {
            "id": _RAJU_USER_ID,
            "company_id": _PIK_COMPANY_ID,
            "email": _RAJU_EMAIL,
            "role": "migrant",
            "first_name": "Раджу",
            "last_name": "Шарма",
            "lang": "hi",
        },
    )
    logger.info("demo: created migrant user Раджу id=%s", _RAJU_USER_ID)


def _make_token(user: User) -> str:
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role,
        "company_id": str(user.company_id),
        "preferred_language": user.preferred_language,
    }
    return encode_jwt(payload)


def _user_to_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        company_id=user.company_id,
        preferred_language=user.preferred_language,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login-hr", status_code=status.HTTP_200_OK)
async def demo_login_hr(
    response: Response,
    x_demo_password: str | None = Header(default=None, alias="X-Demo-Password"),
) -> DemoLoginResponse:
    """One-button HR login — returns JWT for Дарья (Застройщик№1).

    Требует header `X-Demo-Password`, совпадающий с ADAPTA_DEMO_PASSWORD.
    """
    _require_demo_enabled()
    _verify_demo_password(x_demo_password)

    async with async_session_factory() as session:
        async with session.begin():
            await _ensure_pik_company(session)
            await _ensure_daria(session)

    async with async_session_factory() as session:
        user = await session.get(User, _DARIA_USER_ID)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "INTERNAL_ERROR", "message": "Seed HR user not found."}},
        )

    logger.info("demo login: %s", user.email)
    token = _make_token(user)
    # Set the same HttpOnly cookie as /auth/login so that gated page
    # navigations (e.g. /b2b/18-ticket-inbox.html) pass StaticAuthMiddleware —
    # top-level navigations carry the cookie but no Authorization header.
    _set_session_cookie(response, token, max_age=get_settings().jwt_ttl_hr_seconds)
    return DemoLoginResponse(access_token=token, user=_user_to_info(user))


@router.post("/login-migrant", status_code=status.HTTP_200_OK)
async def demo_login_migrant(
    response: Response,
    x_demo_password: str | None = Header(default=None, alias="X-Demo-Password"),
) -> DemoLoginResponse:
    """One-button migrant login — returns JWT for Раджу Шарма.

    Требует header `X-Demo-Password`, совпадающий с ADAPTA_DEMO_PASSWORD.
    """
    _require_demo_enabled()
    _verify_demo_password(x_demo_password)

    async with async_session_factory() as session:
        async with session.begin():
            await _ensure_pik_company(session)
            await _ensure_raju(session)

    async with async_session_factory() as session:
        user = await session.get(User, _RAJU_USER_ID)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "INTERNAL_ERROR", "message": "Seed migrant user not found."}},
        )

    logger.info("demo login: %s", user.email)
    token = _make_token(user)
    _set_session_cookie(response, token, max_age=get_settings().jwt_ttl_migrant_seconds)
    return DemoLoginResponse(access_token=token, user=_user_to_info(user))
