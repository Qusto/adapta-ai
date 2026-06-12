"""Phase 5+: extend ai_messages.role to include 'hr'.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29

Drops the existing CHECK constraint that only allows 'user'|'agent' and
replaces it with one that also permits 'hr' — used by the HR-reply endpoint
(POST /api/v1/chat/escalations/{escalation_id}/reply).
"""

from __future__ import annotations

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ai_messages_role", "ai_messages", type_="check")
    op.create_check_constraint(
        "ck_ai_messages_role",
        "ai_messages",
        "role IN ('user', 'agent', 'hr')",
    )


def downgrade() -> None:
    # Remove any hr-role rows first to avoid violating the narrower constraint
    op.execute("DELETE FROM ai_messages WHERE role = 'hr'")
    op.drop_constraint("ck_ai_messages_role", "ai_messages", type_="check")
    op.create_check_constraint(
        "ck_ai_messages_role",
        "ai_messages",
        "role IN ('user', 'agent')",
    )
