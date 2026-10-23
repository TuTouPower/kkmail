"""Allow imported messages without a verified provider remote identity.

Revision ID: 20261023_0018
Revises: 20261023_0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_0018"
down_revision = "20261023_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "messages",
        "remote_id",
        existing_type=sa.String(length=512),
        existing_nullable=False,
        nullable=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_unknown_remote_ids = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM messages WHERE remote_id IS NULL)")
    ).scalar_one()
    if has_unknown_remote_ids:
        raise RuntimeError("cannot downgrade while messages.remote_id contains NULL values")
    op.alter_column(
        "messages",
        "remote_id",
        existing_type=sa.String(length=512),
        existing_nullable=True,
        nullable=False,
    )
