"""auth_credentials: persist session epoch in database

Revision ID: 20261021_0013
Revises: 20261021_0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0013"
down_revision = "20261021_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_credentials",
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.alter_column(
        "auth_credentials",
        "login_password_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "auth_credentials",
        "login_password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_column("auth_credentials", "session_epoch")
