"""Sync execution tracking: job generations, target-job bindings, scan generations.

Revision ID: 20261026_0025
Revises: 20261026_0024

Implements repair design §5.1/§12 for R06/R08:

- ``worker_jobs.execution_generation``: unique, non-null UUID per job row.
  Existing rows each receive their own freshly generated UUID; retries and
  reclaims of a row keep it, successors created later get a new one.
- ``sync_request_target_jobs``: relational binding between a request target
  and one execution generation (phase/folder/status/sanitized result).
- ``sync_checkpoints.scan_generation``: nullable root generation of the full
  scan that owns the checkpoint cursor state.
- ``sync_request_targets.current_job_id`` is dropped; execution linkage now
  lives in the binding table. The public request DTO is unchanged.

Data migration (§12): requests still ``queued``/``running`` at upgrade time
have no reliable execution binding, so they — and their still-open targets —
are marked ``failed`` with error code ``execution_tracking_unavailable``.
Their IDs and history are preserved (terminal requests are pruned by the
existing 7-day cleanup, never deleted here), and the underlying background
sync jobs are left untouched: shared periodic polling keeps running, only
the dead request association is ended. This marking is not reversible; the
downgrade restores the schema shape but not the pre-upgrade request states.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261026_0025"
down_revision: Union[str, None] = "20261026_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. WorkerJob.execution_generation — backfill one UUID per existing row.
    op.add_column(
        "worker_jobs",
        sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE worker_jobs SET execution_generation = gen_random_uuid() WHERE execution_generation IS NULL")
    op.alter_column("worker_jobs", "execution_generation", nullable=False)
    op.create_unique_constraint("uq_worker_jobs_execution_generation", "worker_jobs", ["execution_generation"])

    # 2. SyncCheckpoint.scan_generation (nullable; set by the first tracked full scan).
    op.add_column(
        "sync_checkpoints",
        sa.Column("scan_generation", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 3. SyncRequestTargetJob binding table.
    op.create_table(
        "sync_request_target_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sync_request_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worker_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("phase", sa.String(64), nullable=False, server_default=sa.text("'sync'")),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("target_id", "execution_generation", name="uq_sync_target_jobs_target_generation"),
    )
    op.create_index("ix_sync_target_jobs_job", "sync_request_target_jobs", ["job_id"])
    op.create_index("ix_sync_target_jobs_generation", "sync_request_target_jobs", ["execution_generation"])

    # 4. Data migration: pre-tracking queued/running requests cannot be
    #    reliably bound to an execution — fail them explicitly (§12). The
    #    background jobs themselves are NOT cancelled or detached from
    #    periodic polling; only the request/target rows are terminated.
    op.execute(
        """
        UPDATE sync_request_targets
        SET state = 'failed',
            error_code = 'execution_tracking_unavailable',
            safe_error = 'Request predates execution tracking and cannot be bound to a sync execution',
            finished_at = now()
        WHERE state IN ('queued', 'running')
        """
    )
    op.execute(
        """
        UPDATE sync_requests
        SET state = 'failed', finished_at = now()
        WHERE state IN ('queued', 'running')
        """
    )

    # 5. Drop the single-pointer job column superseded by the binding table.
    op.drop_index("ix_sync_targets_job_id", table_name="sync_request_targets")
    op.drop_column("sync_request_targets", "current_job_id")


def downgrade() -> None:
    op.add_column(
        "sync_request_targets",
        sa.Column(
            "current_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worker_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_sync_targets_job_id", "sync_request_targets", ["current_job_id"])
    op.drop_table("sync_request_target_jobs")
    op.drop_column("sync_checkpoints", "scan_generation")
    op.drop_constraint("uq_worker_jobs_execution_generation", "worker_jobs", type_="unique")
    op.drop_column("worker_jobs", "execution_generation")
