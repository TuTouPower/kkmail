"""Create sync_requests, sync_request_targets, and account_sync_activity tables.

Revision ID: 20261026_0023
Revises: 20261026_0022
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261026_0023"
down_revision: Union[str, None] = "20261026_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. sync_requests table
    op.create_table(
        "sync_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sync_requests_state_created", "sync_requests", ["state", "created_at"])

    # 2. sync_request_targets table
    op.create_table(
        "sync_request_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sync_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("current_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("worker_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_key", sa.String(255), nullable=False),
        sa.Column("requested_generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("safe_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("request_id", "target_key", name="uq_sync_targets_request_key"),
    )
    op.create_index("ix_sync_targets_account_state", "sync_request_targets", ["account_id", "state"])
    op.create_index("ix_sync_targets_job_id", "sync_request_targets", ["current_job_id"])

    # 3. account_sync_activity table
    op.create_table(
        "account_sync_activity",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("last_foreground_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_sync_activity_expires", "account_sync_activity", ["expires_at"])


def downgrade() -> None:
    op.drop_table("account_sync_activity")
    op.drop_table("sync_request_targets")
    op.drop_table("sync_requests")
