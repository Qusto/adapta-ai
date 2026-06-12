"""Phase 4-demo: add is_partner_global to documents table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27

Adds a boolean flag `is_partner_global` to the `documents` table so that
partner-product documents (collection=partner_products) can be distinguished from
employer-scoped documents in Postgres queries.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "is_partner_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "is_partner_global")
