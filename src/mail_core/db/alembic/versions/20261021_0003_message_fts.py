"""Add message_search FTS table with tsvector + trigram helpers.

Revision ID: 20261021_0003
Revises: f5f312751c77
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261021_0003"
down_revision: Union[str, None] = "f5f312751c77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE message_search (
            message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            subject TEXT NOT NULL DEFAULT '',
            from_text TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            document tsvector GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(from_text,'') || ' ' || coalesce(body_text,''))
            ) STORED,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_message_search_account ON message_search (account_id)")
    op.execute("CREATE INDEX ix_message_search_document ON message_search USING GIN (document)")
    op.execute("CREATE INDEX ix_message_search_from_trgm ON message_search USING GIN (from_text gin_trgm_ops)")


def downgrade() -> None:
    # Indexes on message_search drop with the table. Do not DROP EXTENSION pg_trgm —
    # other schemas may depend on it.
    op.execute("DROP TABLE IF EXISTS message_search")
