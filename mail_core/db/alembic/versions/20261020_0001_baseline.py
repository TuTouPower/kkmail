"""mail-core alembic baseline (empty schema placeholder).

Revision ID: 20261020_0001
Revises:
Create Date: 2026-10-20
"""

from typing import Sequence, Union

revision: str = "20261020_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Full mail tables land in the next migration (unified model milestone).
    pass


def downgrade() -> None:
    pass
