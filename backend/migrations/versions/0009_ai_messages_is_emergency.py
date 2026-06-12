"""Phase 5+: add is_emergency to ai_messages.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-02

Adds boolean column `is_emergency` (NOT NULL, default false) to `ai_messages`
so the escalations endpoint can distinguish true keyword-emergencies
(is_emergency=True) from ordinary HR-tickets for out-of-corpus questions
(escalate=True, is_emergency=False).  This allows _severity() to gate
critical/emergency on is_emergency rather than on escalate, restoring the
"передано HR" semantic for out-of-corpus messages without triggering ЭКСТРЕННО.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_messages",
        sa.Column(
            "is_emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_messages", "is_emergency")
