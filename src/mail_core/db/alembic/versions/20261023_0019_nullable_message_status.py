"""Preserve unknown provider mail status instead of defaulting to false.

Revision ID: 20261023_0019
Revises: 20261023_0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261023_0019"
down_revision = "20261023_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("is_read", "is_flagged", "has_attachments"):
        op.alter_column("messages", name, existing_type=sa.Boolean(), nullable=True, server_default=None)
    op.alter_column("folder_stats", "unread_count", existing_type=sa.Integer(), nullable=True, server_default=None)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM messages WHERE is_read IS NULL OR is_flagged IS NULL OR has_attachments IS NULL) "
        "OR EXISTS (SELECT 1 FROM folder_stats WHERE unread_count IS NULL)"
    )).scalar_one():
        raise RuntimeError("cannot downgrade while mail status or unread counts contain NULL values")
    for name in ("is_read", "is_flagged", "has_attachments"):
        op.alter_column("messages", name, existing_type=sa.Boolean(), nullable=False, server_default=sa.text("false"))
    op.alter_column("folder_stats", "unread_count", existing_type=sa.Integer(), nullable=False, server_default=sa.text("0"))
