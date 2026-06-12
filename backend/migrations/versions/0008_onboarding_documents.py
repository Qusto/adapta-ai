"""Phase 10: add onboarding_state + personal_documents JSONB to users.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-01

Single source of truth for the migrant onboarding journey (8 steps) and the
migrant's personal documents (base set, metadata only). Both nullable — the
API computes a default when null and persists on first mutation.

NOTE (v1.1): document storage here is METADATA ONLY. Real document files
require at-rest encryption — deferred to v1.1.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_state", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("personal_documents", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "personal_documents")
    op.drop_column("users", "onboarding_state")
