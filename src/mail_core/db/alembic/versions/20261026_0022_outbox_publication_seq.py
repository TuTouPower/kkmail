"""Persist committed outbox publication order and publication state singleton.

Revision ID: 20261026_0022
Revises: 20261025_0021
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261026_0022"
down_revision: Union[str, None] = "20261025_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create outbox_publication_state singleton table
    op.create_table(
        "outbox_publication_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("epoch", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("next_seq", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_outbox_publication_state_singleton"),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_publication_state"),
    )

    # Initialize singleton state with fresh epoch
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO outbox_publication_state (id, epoch, next_seq)
            VALUES (1, gen_random_uuid(), 1)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # 2. Add publication_seq and published_at to outbox
    op.add_column("outbox", sa.Column("publication_seq", sa.BigInteger(), nullable=True))
    op.add_column("outbox", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_outbox_publication_seq",
        "outbox",
        ["publication_seq"],
        unique=True,
    )
    op.create_index(
        "ix_outbox_unassigned",
        "outbox",
        ["id"],
        unique=False,
        postgresql_where=sa.text("publication_seq IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_unassigned", table_name="outbox")
    op.drop_index("ix_outbox_publication_seq", table_name="outbox")
    op.drop_column("outbox", "published_at")
    op.drop_column("outbox", "publication_seq")
    op.drop_table("outbox_publication_state")
