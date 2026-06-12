"""HR chat stats endpoint.

GET /api/v1/chat/stats?since=<ISO>

Returns aggregate chat statistics for the HR's company — total messages,
auto-answered count, escalated count, auto-answer rate, avg confidence,
and avg response latency.

Auth: Bearer JWT with role=hr (require_hr dependency).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.auth.deps import require_hr
from app.database import async_session_factory
from app.db.models import AiMessage, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Confidence threshold — must stay in sync with chat_escalations.py
_LOW_CONFIDENCE_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class ChatStatsResponse(BaseModel):
    company_id: str
    total_messages: int
    auto_answered: int
    escalated: int
    auto_answer_rate: float
    avg_confidence: float | None
    avg_response_ms: float | None
    since: datetime


# ---------------------------------------------------------------------------
# Helper — escalation filter expression (must stay in sync with chat_escalations.py)
# ---------------------------------------------------------------------------


def _escalations_filter() -> ColumnElement[bool]:
    """Return the SQLAlchemy OR clause that identifies escalated user messages.

    Must stay in sync with chat_escalations.py WHERE clause.
    Criteria:
      - escalate = True  (explicit escalation flag)
      - confidence <= threshold AND is_answerable = True  (low confidence but answerable)
      - is_answerable = False  (AI could not answer at all)
    """
    return or_(
        AiMessage.escalate.is_(True),
        AiMessage.confidence <= _LOW_CONFIDENCE_THRESHOLD,
        AiMessage.is_answerable.is_(False),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=ChatStatsResponse)
async def get_chat_stats(
    current_user: Annotated[User, Depends(require_hr)],
    since: Annotated[datetime | None, Query()] = None,
) -> ChatStatsResponse:
    """Return aggregate chat stats for the HR user's company.

    If `since` is not provided, defaults to last 7 days.
    """
    company_id: uuid.UUID = current_user.company_id

    if since is None:
        since = datetime.now(tz=UTC) - timedelta(days=7)
    elif since.tzinfo is None:
        since = since.replace(tzinfo=UTC)

    async with async_session_factory() as session:
        # Total user-side messages in the window
        total_stmt = (
            select(func.count())
            .select_from(AiMessage)
            .join(User, AiMessage.user_id == User.id)
            .where(User.company_id == company_id)
            .where(AiMessage.role == "user")
            .where(AiMessage.created_at >= since)
        )
        total_result = await session.execute(total_stmt)
        total_messages: int = total_result.scalar_one() or 0

        # Escalated user messages (same criteria as chat_escalations.py)
        escalated_stmt = (
            select(func.count())
            .select_from(AiMessage)
            .join(User, AiMessage.user_id == User.id)
            .where(User.company_id == company_id)
            .where(AiMessage.role == "user")
            .where(AiMessage.created_at >= since)
            .where(_escalations_filter())
        )
        escalated_result = await session.execute(escalated_stmt)
        escalated: int = escalated_result.scalar_one() or 0

        # Avg confidence and avg response_ms over assistant messages
        agent_stats_stmt = (
            select(
                func.avg(AiMessage.confidence),
                func.avg(AiMessage.latency_ms),
            )
            .select_from(AiMessage)
            .join(User, AiMessage.user_id == User.id)
            .where(User.company_id == company_id)
            .where(AiMessage.role == "agent")
            .where(AiMessage.created_at >= since)
        )
        agent_stats_result = await session.execute(agent_stats_stmt)
        agent_row = agent_stats_result.one()
        avg_confidence: float | None = float(agent_row[0]) if agent_row[0] is not None else None
        avg_response_ms: float | None = float(agent_row[1]) if agent_row[1] is not None else None

    auto_answered = total_messages - escalated
    auto_answer_rate = (auto_answered / total_messages) if total_messages > 0 else 0.0

    return ChatStatsResponse(
        company_id=str(company_id),
        total_messages=total_messages,
        auto_answered=auto_answered,
        escalated=escalated,
        auto_answer_rate=round(auto_answer_rate, 4),
        avg_confidence=avg_confidence,
        avg_response_ms=avg_response_ms,
        since=since,
    )
