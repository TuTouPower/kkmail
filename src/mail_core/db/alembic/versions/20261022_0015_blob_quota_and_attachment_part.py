"""blob quota reservations and attachment part identifier

Revision ID: 20261022_0015
Revises: 20261022_0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261022_0015"
down_revision = "20261022_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Attachment stable part_id
    op.add_column("attachments", sa.Column("part_id", sa.String(length=64), nullable=True))
    op.execute(
        """
        UPDATE attachments
        SET part_id = sub.new_pid
        FROM (
            SELECT id, 'legacy_' || ROW_NUMBER() OVER (PARTITION BY message_id ORDER BY id) AS new_pid
            FROM attachments
        ) sub
        WHERE attachments.id = sub.id
        """
    )
    op.create_unique_constraint("uq_attachments_message_part", "attachments", ["message_id", "part_id"])

    # 2. Blob quota reservations for atomic cross-worker reservation
    op.create_table(
        "blob_quota_reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_blob_quota_reservations_expires_at",
        "blob_quota_reservations",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_blob_quota_reservations_expires_at", table_name="blob_quota_reservations")
    op.drop_table("blob_quota_reservations")
    op.drop_constraint("uq_attachments_message_part", "attachments", type_="unique")
    op.drop_column("attachments", "part_id")
