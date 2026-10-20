"""credential_secrets: durable encrypted provider credentials

Revision ID: 20261021_0007
Revises: 20261021_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0007"
down_revision = "20261021_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credential_secrets",
        sa.Column("ref", sa.String(length=512), primary_key=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("credential_secrets")
