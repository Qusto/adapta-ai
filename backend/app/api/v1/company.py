"""GET /api/v1/company/me — company info for the current user (HR or migrant).

Single source of truth for the employer name/site shown across the migrant PWA
and HR console, so renaming the company in the DB propagates everywhere without
editing hardcoded strings.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.workers import _site_for_company
from app.auth.deps import get_current_user
from app.database import async_session_factory
from app.db.models import Company, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/company", tags=["company"])


class CompanyMeResponse(BaseModel):
    id: str
    name: str
    inn: str | None
    site: str


@router.get("/me", response_model=CompanyMeResponse)
async def company_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    """Return the current user's company (name/inn + derived demo site name)."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).where(Company.id == current_user.company_id)
        )
        company = result.scalar_one_or_none()

    name = company.name if company else "—"
    return CompanyMeResponse(
        id=str(current_user.company_id),
        name=name,
        inn=(company.inn if company else None),
        site=_site_for_company(name),
    )
