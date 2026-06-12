"""HR escalations endpoint — Phase 3+.

GET /api/v1/chat/escalations?limit=10

Returns user messages where the AI answered with low confidence or could not
answer (is_answerable=False), filtered to the HR user's company.
Auth: Bearer JWT with role=hr (require_hr dependency).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.auth.deps import require_hr
from app.database import async_session_factory
from app.db.models import AiMessage, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# ---------------------------------------------------------------------------
# Country-flag mapping for commonly represented migrant languages/countries
# ---------------------------------------------------------------------------

_LANG_FLAG: dict[str, str] = {
    "hi": "\U0001f1ee\U0001f1f3",  # India
    "uz": "\U0001f1fa\U0001f1ff",  # Uzbekistan
    "tg": "\U0001f1f9\U0001f1ef",  # Tajikistan
    "ky": "\U0001f1f0\U0001f1ec",  # Kyrgyzstan
    "kk": "\U0001f1f0\U0001f1ff",  # Kazakhstan
    "az": "\U0001f1e6\U0001f1ff",  # Azerbaijan
    "ru": "\U0001f1f7\U0001f1fa",  # Russia (default)
}

# Languages considered "migrant primary" for severity escalation
_HIGH_RISK_LANGS = {"hi", "uz", "tg"}

# Confidence-float threshold treated as "low"
_LOW_CONFIDENCE_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EscalationItem(BaseModel):
    id: str
    worker_id: str
    worker_name: str
    worker_country: str
    question: str
    language: str
    original_text: str
    ai_confidence: str
    is_answerable: bool
    severity: str
    reason: str
    created_at: str
    relative_time: str


class EscalationsResponse(BaseModel):
    items: list[EscalationItem]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _confidence_label(confidence: float | None) -> str:
    """Convert stored float confidence to human label."""
    if confidence is None:
        return "low"
    if confidence <= _LOW_CONFIDENCE_THRESHOLD:
        return "low"
    if confidence <= 0.65:
        return "medium"
    return "high"


def _severity(
    _language: str,
    is_answerable: bool,
    confidence: float | None,
    escalate: bool = False,
    is_emergency: bool = False,
) -> tuple[str, str]:
    """Derive (severity, reason) from answerability, confidence, and emergency flag.

    Returns a tuple (severity, reason) where reason is one of:
        'emergency'      — is_emergency=True only (keyword emergency-detector fired).
                           This is the ONLY path to critical/emergency.
                           escalate=True alone (out-of-corpus HR-ticket) does NOT
                           produce critical — it is handled by the unanswerable branch.
        'unanswerable'   — AI could not answer (out-of-corpus, no gate pass).
                           Always 'high', never 'critical', regardless of language.
        'low_confidence' — confidence at or below _LOW_CONFIDENCE_THRESHOLD

    The ``_language`` and ``escalate`` parameters are kept in the signature for
    backwards compatibility with call-sites, but they no longer gate critical.
    The ``_language`` parameter does not influence severity (language-based
    critical branch was removed).
    """
    # is_emergency=True is the sole path to critical/emergency.
    # escalate=True alone (out-of-corpus) must NOT produce critical.
    if is_emergency:
        return "critical", "emergency"
    if not is_answerable:
        return "high", "unanswerable"
    if confidence is not None and confidence <= _LOW_CONFIDENCE_THRESHOLD:
        return "high", "low_confidence"
    return "medium", "low_confidence"


def _relative_time(created_at: datetime) -> str:
    """Human-friendly relative time in Russian."""
    now = datetime.now(tz=UTC)
    # Ensure created_at is tz-aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    delta_seconds = int((now - created_at).total_seconds())

    if delta_seconds < 0:
        return "только что"
    if delta_seconds < 60:
        return f"{delta_seconds} сек назад"
    if delta_seconds < 3600:
        minutes = delta_seconds // 60
        return f"{minutes} мин назад"
    if delta_seconds < 86400:
        hours = delta_seconds // 3600
        return f"{hours} ч назад"
    days = delta_seconds // 86400
    if days == 1:
        return "вчера"
    return f"{days} д назад"


def _build_item(msg: AiMessage, user: User) -> EscalationItem:
    worker_name = f"{user.first_name} {user.last_name}".strip()
    language = msg.language or "ru"
    country_flag = _LANG_FLAG.get(language, _LANG_FLAG["ru"])
    is_ans = bool(msg.is_answerable) if msg.is_answerable is not None else False
    escalate_flag = bool(msg.escalate) if hasattr(msg, "escalate") else False
    is_emergency_flag = bool(msg.is_emergency) if hasattr(msg, "is_emergency") else False
    severity, reason = _severity(
        language, is_ans, msg.confidence,
        escalate=escalate_flag, is_emergency=is_emergency_flag,
    )

    return EscalationItem(
        id=str(msg.id),
        worker_id=str(user.id),
        worker_name=worker_name or "Неизвестный",
        worker_country=country_flag,
        question=msg.text,
        language=language,
        original_text=msg.text,
        ai_confidence=_confidence_label(msg.confidence),
        is_answerable=is_ans,
        severity=severity,
        reason=reason,
        created_at=msg.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        relative_time=_relative_time(msg.created_at),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/escalations", response_model=EscalationsResponse)
async def get_escalations(
    current_user: Annotated[User, Depends(require_hr)],
    limit: int = Query(default=10, ge=1, le=50),
) -> EscalationsResponse:
    """Return escalated user messages for the HR user's company.

    Escalations = user messages where AI had low confidence OR could not answer.
    Ordered by most recent first.
    """
    company_id: uuid.UUID = current_user.company_id

    async with async_session_factory() as session:
        stmt = (
            select(AiMessage, User)
            .join(User, AiMessage.user_id == User.id)
            .where(User.company_id == company_id)
            .where(AiMessage.role == "user")
            .where(
                or_(
                    AiMessage.confidence <= _LOW_CONFIDENCE_THRESHOLD,
                    AiMessage.is_answerable.is_(False),
                    AiMessage.escalate.is_(True),
                )
            )
            .order_by(AiMessage.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.all()

    items = [_build_item(msg, user) for msg, user in rows]
    return EscalationsResponse(items=items, total=len(items))
