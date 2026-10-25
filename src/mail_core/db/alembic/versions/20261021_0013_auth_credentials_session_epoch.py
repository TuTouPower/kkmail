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
    connection = op.get_bind()
    has_null_hashes = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM auth_credentials WHERE login_password_hash IS NULL)")
    ).scalar_one()
    if has_null_hashes:
        raise RuntimeError("cannot downgrade while auth_credentials.login_password_hash contains NULL values")
    op.alter_column(
        "auth_credentials",
        "login_password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_column("auth_credentials", "session_epoch")
