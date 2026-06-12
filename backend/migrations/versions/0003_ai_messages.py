"""Phase 3: add ai_messages table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-24

Implements the Phase 3 schema described in PRD/07_DATA_MODEL_AND_API.md §2.5.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column(
            "language",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'agent')",
            name="ck_ai_messages_role",
        ),
    )
    op.create_index(
        "ix_ai_messages_user_created",
        "ai_messages",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_messages_user_created", table_name="ai_messages")
    op.drop_table("ai_messages")
