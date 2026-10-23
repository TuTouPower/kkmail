"""Persist independent master-list and group account ordering.

Revision ID: 20261023_0016
Revises: 20261022_0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_0016"
down_revision = "20261022_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("master_order", sa.Integer(), nullable=True))
    op.add_column("accounts", sa.Column("group_order", sa.Integer(), nullable=True))
    op.create_index("ix_accounts_group_id", "accounts", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_group_id", table_name="accounts")
    op.drop_column("accounts", "group_order")
    op.drop_column("accounts", "master_order")
