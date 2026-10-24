"""Track failed worker executions separately from claims.

Revision ID: 20261025_0020
Revises: 20261023_0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261025_0020"
down_revision = "20261023_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "worker_jobs",
        sa.Column("failure_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("worker_jobs", "failure_attempts")
