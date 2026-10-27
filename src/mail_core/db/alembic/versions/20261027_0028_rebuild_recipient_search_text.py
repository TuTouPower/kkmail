"""Rebuild recipient search text polluted by the original 0027 backfill.

Revision ID: 20261027_0028
Revises: 20261027_0027

A118: the original 0027 backfill expanded array elements as raw text, so dict
recipients ({"name": ..., "address": ...}) were stored as whole JSON text
in message_search.to_text and accounts.recipient_addresses. Databases that
already ran 0027 keep that polluted data, so rebuild both columns here
with the corrected extraction (dict -> name/address, string -> itself).
message_search.to_text also picks up cc_addresses, matching the runtime
index form (A58); the generated `document` tsvector follows automatically.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261027_0028"
down_revision: Union[str, None] = "20261027_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.execute(
        """
        UPDATE message_search ms
        SET to_text = COALESCE(
            (
                SELECT string_agg(sub.txt, ' ' ORDER BY sub.grp, sub.ord)
                FROM (
                    SELECT 0 AS grp, e.ord, CASE
                        WHEN jsonb_typeof(e.elem) = 'object'
                            THEN trim(concat_ws(' ', e.elem->>'name', e.elem->>'address'))
                        WHEN jsonb_typeof(e.elem) = 'string' THEN e.elem #>> '{}'
                        ELSE ''
                    END AS txt
                    FROM messages m
                    CROSS JOIN LATERAL jsonb_array_elements(m.to_addresses)
                        WITH ORDINALITY AS e(elem, ord)
                    WHERE m.id = ms.message_id
                    UNION ALL
                    SELECT 1 AS grp, e.ord, CASE
                        WHEN jsonb_typeof(e.elem) = 'object'
                            THEN trim(concat_ws(' ', e.elem->>'name', e.elem->>'address'))
                        WHEN jsonb_typeof(e.elem) = 'string' THEN e.elem #>> '{}'
                        ELSE ''
                    END AS txt
                    FROM messages m
                    CROSS JOIN LATERAL jsonb_array_elements(m.cc_addresses)
                        WITH ORDINALITY AS e(elem, ord)
                    WHERE m.id = ms.message_id
                ) sub
                WHERE sub.txt != ''
            ),
            ''
        )
        """
    )


def downgrade() -> None:
    # Data-only rebuild: the pre-rebuild values were the polluted form this
    # migration exists to remove, so there is nothing meaningful to restore.
    pass
