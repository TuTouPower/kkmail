"""indexes for archive claim, thread resolution, and from_text trigram search

Revision ID: 20261022_0014
Revises: 20261021_0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261022_0014"
down_revision = "20261021_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A3: composite partial index on message_archive_state
    op.create_index(
        "ix_archive_claim",
        "message_archive_state",
        ["state", "priority"],
        unique=False,
        postgresql_where=sa.text("claimed_by IS NULL"),
    )

    # A18: composite index on messages (account_id, internet_message_id) for threading
    op.create_index(
        "ix_messages_account_internet_id",
        "messages",
        ["account_id", "internet_message_id"],
        unique=False,
    )

    # A22: GIN trigram index on message_search(from_text)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_message_search_from_text_trgm ON message_search USING GIN (from_text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_search_from_text_trgm")
    op.drop_index("ix_messages_account_internet_id", table_name="messages")
    op.drop_index("ix_archive_claim", table_name="message_archive_state")
