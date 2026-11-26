"""Promote WorkerJob execution lineage to a first-class NOT NULL column.

Revises: 20261124_0005
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261125_0006"
down_revision = "20261124_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "worker_jobs",
        sa.Column("execution_origin", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE worker_jobs AS wj
               SET execution_origin = CASE
                   WHEN lower(coalesce(wj.payload->>'background', '')) IN ('true', 't', '1', 'yes')
                     THEN 'background'
                   WHEN COALESCE(wj.payload->>'request_id', wj.payload->>'parent_request_id', '')
                        ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    AND EXISTS (
                        SELECT 1
                          FROM sync_requests AS sr
                         WHERE sr.id = CAST(COALESCE(wj.payload->>'request_id', wj.payload->>'parent_request_id') AS uuid)
                           AND lower(coalesce(sr.scope->>'background', '')) IN ('true', 't', '1', 'yes')
                    )
                     THEN 'background'
                   WHEN wj.job_type IN ('gc_blobs', 'backup_run', 'outbox_dispatch_wake')
                     THEN 'background'
                   WHEN wj.job_type = 'archive_mime_batch' AND NOT (wj.payload ? 'message_id')
                     THEN 'background'
                   ELSE 'foreground'
               END
            """
        )
    )
    op.alter_column(
        "worker_jobs",
        "execution_origin",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_worker_jobs_execution_origin",
        "worker_jobs",
        "execution_origin IN ('foreground', 'background')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_worker_jobs_execution_origin", "worker_jobs", type_="check")
    op.drop_column("worker_jobs", "execution_origin")
