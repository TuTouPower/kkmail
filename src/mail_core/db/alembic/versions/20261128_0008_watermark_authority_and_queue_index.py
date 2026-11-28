"""t094: authoritative delta watermark, terminal cleanup index, duplicate GIN removal.

Revises: 20261126_0007
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261128_0008"
down_revision = "20261126_0007"
branch_labels = None
depends_on = None

_STATS_TARGETS = ("message_search", "messages", "message_bodies", "worker_jobs", "outbox")


def upgrade() -> None:
    # Authoritative delta execution-chain settlement watermark. Backfill from
    # the checkpoint's own updated_at so existing folders are never suddenly
    # overdue after the upgrade (conservative: may re-poll once, never skip).
    op.add_column(
        "sync_checkpoints",
        sa.Column("last_delta_settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE sync_checkpoints SET last_delta_settled_at = updated_at")

    # Terminal cleanup scans over the large done/failed heap.
    op.create_index(
        "ix_worker_jobs_terminal_cleanup",
        "worker_jobs",
        ["updated_at"],
        postgresql_where=sa.text("status IN ('done', 'failed')"),
    )

    # Historical baseline created two equivalent GIN indexes on from_text;
    # keep only the canonical one declared by the ORM.
    op.execute("DROP INDEX IF EXISTS ix_message_search_from_trgm")

    # Converge stale statistics accumulated by bulk import / migration.
    for table in _STATS_TARGETS:
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_message_search_from_trgm "
        "ON message_search USING GIN (from_text public.gin_trgm_ops)"
    )
    op.drop_index("ix_worker_jobs_terminal_cleanup", table_name="worker_jobs")
    op.drop_column("sync_checkpoints", "last_delta_settled_at")
