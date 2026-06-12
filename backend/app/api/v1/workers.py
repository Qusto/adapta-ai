"""GET /api/v1/workers — HR workers list endpoint.
GET /api/v1/workers/notifications/new — HR polling endpoint — Phase 1.

/workers          : list all migrant users for the HR's company (HR-only, JWT).
/workers/notifications/new : returns newly registered migrants filtered by ?since=<iso_timestamp>.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import require_hr
from app.database import async_session_factory
from app.db.models import Company, User

logger = logging.getLogger(__name__)

# Language → country flag emoji (proxy for nationality in demo)
_LANGUAGE_TO_COUNTRY: dict[str, str] = {
    "ru": "🇷🇺",
    "hi": "🇮🇳",
    "uz": "🇺🇿",
    "tg": "🇹🇯",
    "ky": "🇰🇬",
    "en": "🌐",
}

# Company name (lowercased) → demo site name
_COMPANY_TO_SITE: dict[str, str] = {
    "застройщик№1": "Метрополия-14",
    "гк пик": "Метрополия-14",
    "пик": "Метрополия-14",
}


def _country_for_language(lang: str) -> str:
    return _LANGUAGE_TO_COUNTRY.get((lang or "").lower(), "—")


def _site_for_company(company_name: str | None) -> str:
    if not company_name:
        return "—"
    return _COMPANY_TO_SITE.get(company_name.strip().lower(), "—")


def _relative_time_ru(dt: datetime) -> str:
    """Returns Russian relative time string: '5 мин', '2 ч', '3 д'."""
    now = datetime.now(UTC)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    if seconds < 86400:
        return f"{seconds // 3600} ч"
    return f"{seconds // 86400} д"


router = APIRouter(prefix="/workers", tags=["workers"])


class WorkerItem(BaseModel):
    worker_id: str
    first_name: str
    last_name: str
    accepted_at: str


class NotificationsResponse(BaseModel):
    items: list[WorkerItem]
    server_time: str


class WorkerListItem(BaseModel):
    id: str
    first_name: str
    last_name: str
    language: str
    created_at: str
    status: str
    country: str       # derived from preferred_language (flag emoji)
    object: str        # derived from company (site name)
    updated: str       # derived from created_at (relative time)


class WorkersListResponse(BaseModel):
    items: list[WorkerListItem]
    total: int


@router.get("", response_model=WorkersListResponse)
async def list_workers(
    current_user: Annotated[User, Depends(require_hr)],
) -> Any:
    """Return all migrant users from the HR's company.

    HR-only. Returns id, first_name, last_name, language (preferred_language),
    created_at, status='active' for all migrants in the same company.
    """
    async with async_session_factory() as session:
        # Fetch company name for site derivation
        company_result = await session.execute(
            select(Company).where(Company.id == current_user.company_id)
        )
        company = company_result.scalar_one_or_none()
        company_name = company.name if company else None
        site_name = _site_for_company(company_name)

        result = await session.execute(
            select(User)
            .where(
                User.company_id == current_user.company_id,
                User.role == "migrant",
            )
            .order_by(User.created_at.desc())
        )
        users: list[User] = list(result.scalars().all())

    worker_items = [
        WorkerListItem(
            id=str(u.id),
            first_name=u.first_name,
            last_name=u.last_name,
            language=u.preferred_language,
            created_at=u.created_at.isoformat(),
            status="active",
            country=_country_for_language(u.preferred_language),
            object=site_name,
            updated=_relative_time_ru(u.created_at),
        )
        for u in users
    ]

    return WorkersListResponse(items=worker_items, total=len(worker_items))


@router.get("/notifications/new", response_model=NotificationsResponse)
async def get_new_notifications(
    current_user: Annotated[User, Depends(require_hr)],
    since: str | None = Query(default=None),
) -> Any:
    """Return migrants from the HR's company created after `since` timestamp.

    `since`: ISO8601 string. Defaults to now() - 30s.
    """
    if since is None:
        since_dt = datetime.now(UTC) - timedelta(seconds=30)
    else:
        try:
            # URL-decode: '+' in query string becomes ' ' (space); restore it.
            since_clean = since.replace(" ", "+")
            since_dt = datetime.fromisoformat(since_clean)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=UTC)
        except ValueError:
            since_dt = datetime.now(UTC) - timedelta(seconds=30)

    async with async_session_factory() as session:
        result = await session.execute(
            select(User)
            .where(
                User.company_id == current_user.company_id,
                User.role == "migrant",
                User.created_at > since_dt,
            )
            .order_by(User.created_at.desc())
        )
        users: list[User] = list(result.scalars().all())

    items = [
        WorkerItem(
            worker_id=str(u.id),
            first_name=u.first_name,
            last_name=u.last_name,
            accepted_at=u.created_at.isoformat(),
        )
        for u in users
    ]

    return NotificationsResponse(
        items=items,
        server_time=datetime.now(UTC).isoformat(),
    )
