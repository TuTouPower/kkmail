"""message_blob_links(blob_id) index

Revision ID: 20261021_0010
Revises: 20261021_0009
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0010"
down_revision = "20261021_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_message_blob_links_blob_id",
        "message_blob_links",
        ["blob_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_blob_links_blob_id", table_name="message_blob_links")
