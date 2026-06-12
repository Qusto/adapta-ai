"""Invite endpoints — Phase 1.

POST /api/v1/invites              — HR creates invite, sends email
GET  /api/v1/invites/{token}      — public preview
POST /api/v1/invites/{token}/accept — migrant registers
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.auth import _set_session_cookie
from app.auth.deps import require_hr
from app.auth.invite import InviteExpiredError, InviteInvalidError, sign_invite, verify_invite
from app.auth.jwt import encode_jwt
from app.config import get_settings
from app.database import async_session_factory
from app.db.models import Company, Invite, User
from app.email.mailhog_client import send_invite_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invites", tags=["invites"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateInviteRequest(BaseModel):
    email: str
    first_name: str
    last_name: str
    preferred_language: str = "ru"


class InviteCreatedResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    preferred_language: str
    token: str
    expires_at: str
    created_at: str


class InvitePreviewResponse(BaseModel):
    invite_id: str
    company_name: str
    first_name: str
    last_name: str
    hr_name: str
    preferred_language: str
    expires_at: str


class AcceptInviteRequest(BaseModel):
    preferred_language: str = "ru"


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    first_name: str
    last_name: str
    preferred_language: str
    company_id: str


class AcceptInviteResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _error_response(
    http_status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return HTTPException(status_code=http_status, detail={"error": body})


# ---------------------------------------------------------------------------
# POST /api/v1/invites
# ---------------------------------------------------------------------------


@router.post("", response_model=InviteCreatedResponse)
async def create_invite(
    body: CreateInviteRequest,
    current_user: Annotated[User, Depends(require_hr)],
    response: Response,
) -> Any:
    """HR creates an invite for a migrant. Side effect: send email via MailHog.

    Idempotent: if an active (non-used, non-expired) invite already exists for
    the same (company, email) pair, the existing invite is refreshed in-place
    (new token, extended expiry, updated name/language) and 200 OK is returned.
    First-time creation returns 201 CREATED.
    """
    settings = get_settings()

    async with async_session_factory() as session:
        async with session.begin():
            # Fetch company name for email (needed in both paths)
            company = await session.get(Company, current_user.company_id)
            company_name = company.name if company else "Unknown"

            # Check for existing active (non-used, non-expired) invite
            existing_result = await session.execute(
                select(Invite).where(
                    Invite.email == body.email,
                    Invite.company_id == current_user.company_id,
                    Invite.used_at.is_(None),
                    Invite.expires_at > datetime.now(UTC),
                )
            )
            existing_invite = existing_result.scalar_one_or_none()
            is_refresh = existing_invite is not None

            expires_at = datetime.now(UTC) + timedelta(hours=settings.invite_ttl_days * 24)

            if is_refresh:
                # Refresh existing invite in-place: rotate token, extend expiry,
                # update mutable fields. Keep the original id and created_at.
                invite_payload = {
                    "invite_id": str(existing_invite.id),
                    "email": existing_invite.email,
                    "company_id": str(existing_invite.company_id),
                }
                raw_token = sign_invite(invite_payload)

                existing_invite.first_name = body.first_name
                existing_invite.last_name = body.last_name
                existing_invite.preferred_language = body.preferred_language
                existing_invite.token_hash = _token_hash(raw_token)
                existing_invite.expires_at = expires_at

                invite = existing_invite
                invite_id = existing_invite.id
                created_at = existing_invite.created_at or datetime.now(UTC)
                # No session.add() — already tracked by the session
            else:
                # New invite
                invite_id = uuid.uuid4()

                invite_payload = {
                    "invite_id": str(invite_id),
                    "email": body.email,
                    "company_id": str(current_user.company_id),
                }
                raw_token = sign_invite(invite_payload)

                invite = Invite(
                    id=invite_id,
                    company_id=current_user.company_id,
                    email=body.email,
                    first_name=body.first_name,
                    last_name=body.last_name,
                    preferred_language=body.preferred_language,
                    token_hash=_token_hash(raw_token),
                    expires_at=expires_at,
                )
                session.add(invite)

                # Flush to persist before sending email
                await session.flush()

                created_at = invite.created_at or datetime.now(UTC)

    logger.info(
        "invite %s for %s by company=%s",
        "refreshed" if is_refresh else "created",
        body.email,
        current_user.company_id,
    )

    response.status_code = status.HTTP_200_OK if is_refresh else status.HTTP_201_CREATED

    # Best-effort email (outside transaction — failure won't rollback invite)
    invite_url = f"{settings.invite_base_url}/{raw_token}"
    try:
        await send_invite_email(
            to_email=body.email,
            first_name=body.first_name,
            last_name=body.last_name,
            invite_url=invite_url,
            company_name=company_name,
        )
    except Exception as exc:
        logger.warning("Email send failed for invite %s: %s", invite_id, exc)

    return InviteCreatedResponse(
        id=str(invite_id),
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        preferred_language=body.preferred_language,
        token=raw_token,
        expires_at=expires_at.isoformat(),
        created_at=created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/invites/{token}
# ---------------------------------------------------------------------------


@router.get("/{token}", response_model=InvitePreviewResponse)
async def get_invite_preview(token: str) -> Any:
    """Public: preview invite details by raw HMAC token."""
    # First verify HMAC and expiry
    try:
        verify_invite(token)
    except InviteExpiredError as exc:
        raise _error_response(
            status.HTTP_410_GONE,
            "INVITE_EXPIRED",
            "This invite link has expired.",
        ) from exc
    except InviteInvalidError as exc:
        raise _error_response(
            status.HTTP_404_NOT_FOUND,
            "INVITE_NOT_FOUND",
            "Invite not found or invalid.",
        ) from exc

    th = _token_hash(token)

    async with async_session_factory() as session:
        result = await session.execute(select(Invite).where(Invite.token_hash == th))
        invite: Invite | None = result.scalar_one_or_none()

    if invite is None:
        raise _error_response(
            status.HTTP_404_NOT_FOUND,
            "INVITE_NOT_FOUND",
            "Invite not found or invalid.",
        )
    if invite.used_at is not None:
        raise _error_response(
            status.HTTP_409_CONFLICT,
            "INVITE_ALREADY_USED",
            "This invite has already been accepted.",
            {"invite_id": str(invite.id)},
        )
    if invite.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise _error_response(
            status.HTTP_410_GONE,
            "INVITE_EXPIRED",
            "This invite link has expired.",
        )

    async with async_session_factory() as session:
        company = await session.get(Company, invite.company_id)

    company_name = company.name if company else "Unknown"

    # Find any HR for the company. A company may have multiple HR users —
    # the preview only needs *a* name, so pick the first match.
    async with async_session_factory() as session:
        hr_result = await session.execute(
            select(User).where(
                User.company_id == invite.company_id,
                User.role == "hr",
            ).limit(1)
        )
        hr: User | None = hr_result.scalars().first()

    hr_name = f"{hr.first_name} {hr.last_name}" if hr else "HR"

    return InvitePreviewResponse(
        invite_id=str(invite.id),
        company_name=company_name,
        first_name=invite.first_name,
        last_name=invite.last_name,
        hr_name=hr_name,
        preferred_language=invite.preferred_language,
        expires_at=invite.expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/invites/{token}/accept
# ---------------------------------------------------------------------------


@router.post(
    "/{token}/accept",
    response_model=AcceptInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invite(token: str, body: AcceptInviteRequest, response: Response) -> Any:
    """Register a migrant user by accepting the invite token."""
    settings = get_settings()

    # Verify HMAC + expiry first
    try:
        verify_invite(token)
    except InviteExpiredError as exc:
        raise _error_response(
            status.HTTP_410_GONE,
            "INVITE_EXPIRED",
            "This invite link has expired.",
        ) from exc
    except InviteInvalidError as exc:
        raise _error_response(
            status.HTTP_404_NOT_FOUND,
            "INVITE_NOT_FOUND",
            "Invite not found or invalid.",
        ) from exc

    th = _token_hash(token)

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Invite).where(Invite.token_hash == th))
            invite: Invite | None = result.scalar_one_or_none()

            if invite is None:
                raise _error_response(
                    status.HTTP_404_NOT_FOUND,
                    "INVITE_NOT_FOUND",
                    "Invite not found or invalid.",
                )
            if invite.used_at is not None:
                raise _error_response(
                    status.HTTP_409_CONFLICT,
                    "INVITE_ALREADY_USED",
                    "This invite has already been accepted.",
                    {"invite_id": str(invite.id)},
                )

            now = datetime.now(UTC)
            expires_naive = invite.expires_at
            if expires_naive.tzinfo is None:
                expires_aware = expires_naive.replace(tzinfo=UTC)
            else:
                expires_aware = expires_naive
            if expires_aware < now:
                raise _error_response(
                    status.HTTP_410_GONE,
                    "INVITE_EXPIRED",
                    "This invite link has expired.",
                )

            # Create migrant user
            new_user = User(
                id=uuid.uuid4(),
                company_id=invite.company_id,
                email=invite.email,
                password_hash=None,
                role="migrant",
                first_name=invite.first_name,
                last_name=invite.last_name,
                preferred_language=body.preferred_language or invite.preferred_language,
                created_at=now,
            )
            session.add(new_user)
            await session.flush()

            # Mark invite as used
            invite.used_at = now
            invite.accepted_user_id = new_user.id

            user_id = str(new_user.id)
            company_id = str(new_user.company_id)
            preferred_lang = new_user.preferred_language

    jwt_payload = {
        "sub": user_id,
        "role": "migrant",
        "company_id": company_id,
        "preferred_language": preferred_lang,
    }
    access_token = encode_jwt(jwt_payload)

    _set_session_cookie(
        response,
        access_token,
        max_age=settings.jwt_ttl_migrant_seconds,
    )

    return AcceptInviteResponse(
        access_token=access_token,
        token_type="Bearer",
        user=UserOut(
            id=user_id,
            email=invite.email,
            role="migrant",
            first_name=invite.first_name,
            last_name=invite.last_name,
            preferred_language=preferred_lang,
            company_id=company_id,
        ),
    )
