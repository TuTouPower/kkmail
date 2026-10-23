"""Allow unknown provider received times to remain NULL.

Revision ID: 20261023_0017
Revises: 20261023_0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_0017"
down_revision = "20261023_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "messages",
        "sort_time",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        nullable=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_unknown_times = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM messages WHERE sort_time IS NULL)")
    ).scalar_one()
    if has_unknown_times:
        raise RuntimeError("cannot downgrade while messages.sort_time contains NULL values")
    op.alter_column(
        "messages",
        "sort_time",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
        nullable=False,
    )
