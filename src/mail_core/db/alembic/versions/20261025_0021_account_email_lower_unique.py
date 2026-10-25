"""Enforce case-insensitive account email uniqueness.

Before applying this migration, create and verify a recoverable database backup.
The preflight is read-only and aborts on conflicts without rewriting account rows.

Revision ID: 20261025_0021
Revises: 20261025_0020
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261025_0021"
down_revision: Union[str, None] = "20261025_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    conflict_rows = connection.execute(
        sa.text(
            """
            SELECT account_ids
            FROM (
                SELECT lower(email) AS normalized_email,
                       array_agg(id::text ORDER BY id) AS account_ids
                FROM accounts
                GROUP BY lower(email)
                HAVING count(*) > 1
            ) AS conflicts
            ORDER BY normalized_email
            LIMIT 10
            """
        )
    ).fetchall()
    if conflict_rows:
        account_ids = "; ".join(", ".join(row[0]) for row in conflict_rows)
        raise RuntimeError(
            "case-insensitive duplicate account emails exist; migration aborted without changing rows. "
            f"Conflicting account IDs (up to 10 groups): {account_ids}. "
            "Create a recoverable backup, choose a per-account resolution, then retry."
        )
    op.create_index(
        "uq_accounts_email_lower",
        "accounts",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_accounts_email_lower", table_name="accounts")
