"""message_search.subject trigram index; attachments(message_id) index

Revision ID: 20261021_0006
Revises: 20261021_0005
"""

from __future__ import annotations

from alembic import op

revision = "20261021_0006"
down_revision = "20261021_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_search_subject_trgm ON message_search USING GIN (subject gin_trgm_ops)")
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_attachments_message_id", table_name="attachments")
    op.execute("DROP INDEX IF EXISTS ix_message_search_subject_trgm")
