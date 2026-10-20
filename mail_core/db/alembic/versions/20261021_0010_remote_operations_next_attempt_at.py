"""remote operations retry: add next_attempt_at column

Revision ID: 20261021_0010
Revises: 20261021_0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0010"
down_revision = "20261021_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remote_operations", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_remote_operations_retry",
        "remote_operations",
        ["account_id", "status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_remote_operations_retry", table_name="remote_operations")
    op.drop_column("remote_operations", "next_attempt_at")
