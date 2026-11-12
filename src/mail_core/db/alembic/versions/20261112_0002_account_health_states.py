"""Split account sync_status into orthogonal health states.

The single ``accounts.sync_status`` column mixed credential validity,
transport reachability and execution activity.  This migration replaces it
with three independent columns and maps the two meaningful legacy failure
values forward, preserving account data.

Revision ID: 20261112_0002
Revises: 20261107_0001
Create Date: 2026-11-12
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261112_0002"
down_revision: Union[str, None] = "20261107_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("credential_state", sa.String(length=32), server_default=sa.text("'valid'"), nullable=False),
    )
    op.add_column(
        "accounts",
        sa.Column("connectivity_state", sa.String(length=32), server_default=sa.text("'connected'"), nullable=False),
    )
    op.add_column(
        "accounts",
        sa.Column("sync_activity", sa.String(length=32), server_default=sa.text("'idle'"), nullable=False),
    )
    # Preserve the meaning of the old mixed status: a dead credential stops
    # syncing, a transport failure is a degraded (retrying) link.
    op.execute(
        "UPDATE accounts SET credential_state = 'invalid', sync_enabled = false "
        "WHERE sync_status = 'auth_failed'"
    )
    op.execute(
        "UPDATE accounts SET connectivity_state = 'degraded' "
        "WHERE sync_status = 'failed'"
    )
    op.drop_column("accounts", "sync_status")


def downgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("sync_status", sa.String(length=32), server_default=sa.text("'idle'"), nullable=False),
    )
    op.execute(
        "UPDATE accounts SET sync_status = 'auth_failed' "
        "WHERE credential_state = 'invalid'"
    )
    op.execute(
        "UPDATE accounts SET sync_status = 'failed' "
        "WHERE connectivity_state IN ('degraded', 'unreachable')"
    )
    op.drop_column("accounts", "sync_activity")
    op.drop_column("accounts", "connectivity_state")
    op.drop_column("accounts", "credential_state")
