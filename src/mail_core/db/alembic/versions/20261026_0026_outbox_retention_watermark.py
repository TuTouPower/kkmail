"""Outbox retention by publication sequence (repair design §9.2, R13).

Revision ID: 20261026_0026
Revises: 20261026_0025

- ``outbox_publication_state.pruned_through_seq``: highest publication_seq
  deleted by the retention service. It advances in the same transaction as
  the prefix deletion, so a replay cursor below it is known to be
  unrecoverable and must receive ``client.resync_hint`` (retention_gap).
- ``outbox.dispatched_at`` and its consumption index
  ``ix_outbox_undispatched`` are dropped: the v2 dispatcher never wrote
  ``dispatched_at`` (publication is tracked by ``publication_seq`` /
  ``published_at``), which left the old prune with nothing to delete.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261026_0026"
down_revision: Union[str, None] = "20261026_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_publication_state",
        sa.Column("pruned_through_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.drop_index("ix_outbox_undispatched", table_name="outbox")
    op.drop_column("outbox", "dispatched_at")


def downgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_undispatched", "outbox", ["dispatched_at", "id"], unique=False)
    op.drop_column("outbox_publication_state", "pruned_through_seq")
