"""message_blobs.gc_eligible_at for cool-off from unreferenced time

Revision ID: 20261021_0008
Revises: 20261021_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0008"
down_revision = "20261021_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_blobs",
        sa.Column("gc_eligible_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing zero-ref rows: cool-off from created_at so behavior stays conservative.
    op.execute(
        sa.text(
            "UPDATE message_blobs SET gc_eligible_at = created_at "
            "WHERE ref_count <= 0 AND gc_eligible_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("message_blobs", "gc_eligible_at")
