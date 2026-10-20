"""Inbox keyset indexes: messages(sort_time,id) + locations(folder_id,message_id)

Revision ID: 20261021_0009
Revises: 20261021_0008
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0009"
down_revision = "20261021_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_messages_sort_id", "messages", ["sort_time", "id"], unique=False)
    op.create_index(
        "ix_message_locations_folder_message",
        "message_locations",
        ["folder_id", "message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_locations_folder_message", table_name="message_locations")
    op.drop_index("ix_messages_sort_id", table_name="messages")
