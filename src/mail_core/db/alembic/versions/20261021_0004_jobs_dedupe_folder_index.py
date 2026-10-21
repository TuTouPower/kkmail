"""worker_jobs.dedupe_key + message_locations(folder_id) index

Revision ID: 20261021_0004
Revises: 20261021_0003
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0004"
down_revision = "20261021_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("worker_jobs", sa.Column("dedupe_key", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_worker_jobs_dedupe_active",
        "worker_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('pending', 'claimed')"),
    )
    op.create_index("ix_message_locations_folder_id", "message_locations", ["folder_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_message_locations_folder_id", table_name="message_locations")
    op.drop_index("ix_worker_jobs_dedupe_active", table_name="worker_jobs")
    op.drop_column("worker_jobs", "dedupe_key")
