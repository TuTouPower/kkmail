"""Add claim_revision to message_archive_state.

Revision ID: 20261026_0024
Revises: 20261026_0023
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261026_0024"
down_revision: Union[str, None] = "20261026_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_archive_state",
        sa.Column("claim_revision", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("message_archive_state", "claim_revision")
