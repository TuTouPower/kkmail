"""Mark accounts whose historical Gmail labels have been backfilled.

Revision ID: 20261124_0005
Revises: 20261123_0004
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261124_0005"
down_revision = "20261123_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("label_backfill_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "label_backfill_completed_at")
