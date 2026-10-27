"""Add to_text to message_search and recipient_addresses to accounts.

Revision ID: 20261027_0027
Revises: 20261026_0026
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261027_0027"
down_revision: Union[str, None] = "20261026_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Accounts: add recipient_addresses JSONB
    op.add_column(
        "accounts",
        sa.Column(
            "recipient_addresses",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    # Backfill accounts.recipient_addresses from messages.to_addresses.
    # Elements may be plain strings or {"name": ..., "address": ...} dicts;
    # dict elements must contribute only their address (A118) — expanding
    # them as raw text would store whole JSON text instead.
    op.execute(
        """
        UPDATE accounts a
        SET recipient_addresses = COALESCE(
            (
                SELECT jsonb_agg(DISTINCT sub.addr)
                FROM (
                    SELECT CASE
                        WHEN jsonb_typeof(e.elem) = 'object' THEN e.elem->>'address'
                        WHEN jsonb_typeof(e.elem) = 'string' THEN e.elem #>> '{}'
                    END AS addr
                    FROM messages m
                    CROSS JOIN LATERAL jsonb_array_elements(m.to_addresses) AS e(elem)
                    WHERE m.account_id = a.id
                ) sub
                WHERE sub.addr IS NOT NULL AND sub.addr != ''
            ),
            '[]'::jsonb
        )
        """
    )

    # 2. message_search: add to_text, rebuild document tsvector, add trigram index
    op.add_column(
        "message_search",
        sa.Column("to_text", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    # Backfill message_search.to_text from messages.to_addresses, matching
    # the runtime form in mail_core.search.index._format_recipient_text:
    # dict elements contribute "name address", strings contribute themselves.
    op.execute(
        """
        UPDATE message_search ms
        SET to_text = COALESCE(
            (
                SELECT string_agg(sub.txt, ' ')
                FROM (
                    SELECT CASE
                        WHEN jsonb_typeof(e.elem) = 'object'
                            THEN trim(concat_ws(' ', e.elem->>'name', e.elem->>'address'))
                        WHEN jsonb_typeof(e.elem) = 'string' THEN e.elem #>> '{}'
                        ELSE ''
                    END AS txt
                    FROM messages m
                    CROSS JOIN LATERAL jsonb_array_elements(m.to_addresses) AS e(elem)
                    WHERE m.id = ms.message_id
                ) sub
                WHERE sub.txt != ''
            ),
            ''
        )
        """
    )
    # Drop and recreate document column to include to_text
    op.drop_index("ix_message_search_document", table_name="message_search")
    op.drop_column("message_search", "document")
    op.execute(
        """
        ALTER TABLE message_search
        ADD COLUMN document tsvector GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(from_text,'') || ' ' || coalesce(to_text,'') || ' ' || coalesce(body_text,''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_message_search_document ON message_search USING GIN (document)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_search_to_text_trgm ON message_search USING GIN (to_text gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_message_search_to_text_trgm")
    op.drop_index("ix_message_search_document", table_name="message_search")
    op.drop_column("message_search", "document")
    op.execute(
        """
        ALTER TABLE message_search
        ADD COLUMN document tsvector GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(from_text,'') || ' ' || coalesce(body_text,''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_message_search_document ON message_search USING GIN (document)")
    op.drop_column("message_search", "to_text")
    op.drop_column("accounts", "recipient_addresses")
