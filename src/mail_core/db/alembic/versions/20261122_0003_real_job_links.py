"""Remove pre-allocated execution generations from sync-request tracking.

Links now always point at a real WorkerJob row. Orphan links left by the old
successor-generation mechanism are settled as explicit failures with a
readable message rather than surviving as ``execution_lost``.

Revision ID: 20261122_0003
Revises: 20261112_0002
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261122_0003"
down_revision = "20261112_0002"
branch_labels = None
depends_on = None

STALLED_MESSAGE = "同步未能完成，请重试"


def upgrade() -> None:
    # Links whose job_id is NULL referenced a successor that never existed.
    # Their targets can no longer be observed; fail them explicitly so no
    # request is left in a misleading running state.
    op.execute(
        sa.text(
            """
            UPDATE sync_request_targets
               SET state = 'failed',
                   error_code = 'sync_incomplete',
                   safe_error = :msg,
                   finished_at = now()
             WHERE id IN (
                 SELECT target_id FROM sync_request_target_jobs WHERE job_id IS NULL
             )
               AND state IN ('queued', 'running')
            """
        ).bindparams(msg=STALLED_MESSAGE)
    )
    op.execute(sa.text("DELETE FROM sync_request_target_jobs WHERE job_id IS NULL"))

    op.drop_constraint("uq_sync_target_jobs_target_generation", "sync_request_target_jobs", type_="unique")
    op.drop_index("ix_sync_target_jobs_generation", table_name="sync_request_target_jobs")
    op.drop_column("sync_request_target_jobs", "execution_generation")
    op.drop_constraint("sync_request_target_jobs_job_id_fkey", "sync_request_target_jobs", type_="foreignkey")
    op.alter_column("sync_request_target_jobs", "job_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_foreign_key(
        "fk_sync_target_jobs_job", "sync_request_target_jobs", "worker_jobs",
        ["job_id"], ["id"], ondelete="CASCADE",
    )
    op.add_column(
        "sync_request_target_jobs",
        sa.Column("needs_successor", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_unique_constraint(
        "uq_sync_target_jobs_target_job", "sync_request_target_jobs", ["target_id", "job_id"]
    )

    op.drop_constraint("uq_worker_jobs_execution_generation", "worker_jobs", type_="unique")
    op.drop_column("worker_jobs", "execution_generation")

    op.execute(
        sa.text(
            """
            UPDATE sync_requests
               SET state = 'failed', finished_at = now()
             WHERE state IN ('queued', 'running')
               AND id IN (
                 SELECT request_id FROM sync_request_targets WHERE state = 'failed'
               )
               AND id NOT IN (
                 SELECT request_id FROM sync_request_targets WHERE state IN ('queued', 'running')
               )
            """
        )
    )


def downgrade() -> None:
    op.add_column("worker_jobs", sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(sa.text("UPDATE worker_jobs SET execution_generation = gen_random_uuid() WHERE execution_generation IS NULL"))
    op.alter_column("worker_jobs", "execution_generation", nullable=False)
    op.create_unique_constraint("uq_worker_jobs_execution_generation", "worker_jobs", ["execution_generation"])

    op.drop_constraint("uq_sync_target_jobs_target_job", "sync_request_target_jobs", type_="unique")
    op.drop_column("sync_request_target_jobs", "needs_successor")
    op.drop_constraint("fk_sync_target_jobs_job", "sync_request_target_jobs", type_="foreignkey")
    op.alter_column("sync_request_target_jobs", "job_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_foreign_key(None, "sync_request_target_jobs", "worker_jobs", ["job_id"], ["id"], ondelete="SET NULL")
    op.add_column("sync_request_target_jobs", sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(sa.text("UPDATE sync_request_target_jobs SET execution_generation = gen_random_uuid() WHERE execution_generation IS NULL"))
    op.alter_column("sync_request_target_jobs", "execution_generation", nullable=False)
    op.create_index("ix_sync_target_jobs_generation", "sync_request_target_jobs", ["execution_generation"])
    op.create_unique_constraint(
        "uq_sync_target_jobs_target_generation", "sync_request_target_jobs", ["target_id", "execution_generation"]
    )
