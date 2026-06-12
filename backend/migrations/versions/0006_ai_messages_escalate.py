"""Phase 5: add escalate to ai_messages.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-28

Adds boolean column `escalate` (NOT NULL, default false) to `ai_messages` so
the emergency short-circuit in chat/message_handler.py can flag rows for the
HR-escalations endpoint independent of confidence.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_messages",
        sa.Column(
            "escalate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_messages", "escalate")
