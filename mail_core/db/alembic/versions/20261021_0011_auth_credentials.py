"""auth_credentials: persist login password hash in database (Plan A)

Revision ID: 20261021_0011
Revises: 20261021_0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261021_0011"
down_revision = "20261021_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_credentials",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("login_password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("auth_credentials")
