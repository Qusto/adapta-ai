"""Phase 3+: add is_answerable to ai_messages.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28

Adds nullable boolean column `is_answerable` to `ai_messages` so the
HR-escalations endpoint can filter user messages where the AI could not
answer the question.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_messages",
        sa.Column("is_answerable", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_messages", "is_answerable")
