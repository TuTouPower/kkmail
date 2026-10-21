"""account_groups, app_settings, accounts.group_id

Revision ID: 20261021_0005
Revises: 20261021_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261021_0005"
down_revision = "20261021_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "accounts",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("account_groups.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "group_id")
    op.drop_table("app_settings")
    op.drop_table("account_groups")
