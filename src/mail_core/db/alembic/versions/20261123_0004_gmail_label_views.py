"""Model Gmail aggregate labels as read-only derived views.

Physical mailboxes keep syncing; ``\\All`` and ``\\Important`` become query
projections over the canonical message store instead of duplicate-fetched
folders. Their membership is materialised as message locations by normal
label-aware sync, so no separate folder scan is ever enqueued.

Revision ID: 20261123_0004
Revises: 20261122_0003
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261123_0004"
down_revision = "20261122_0003"
branch_labels = None
depends_on = None

VIEW_REMOTE_IDS = (
    "[Gmail]/&YkBnCZCuTvY-",
    "[Gmail]/&kc2JgQ-",
    "[Gmail]/All Mail",
    "[Gmail]/Important",
    "[Gmail]/所有邮件",
    "[Gmail]/重要",
)

VIEW_UPDATE = """
    UPDATE folders
       SET kind = :kind, sync_status = :sync_status
     WHERE (role IN ('all', 'important') OR remote_id IN :remote_ids)
       AND EXISTS (
           SELECT 1 FROM accounts a
            WHERE a.id = folders.account_id
              AND (
                  lower(a.email) LIKE '%@gmail.com'
                  OR lower(a.email) LIKE '%@googlemail.com'
                  OR lower(COALESCE(a.config ->> 'imap_host', '')) LIKE '%gmail%'
              )
       )
"""


def view_update_statement(kind: str, sync_status: str):
    return sa.text(VIEW_UPDATE).bindparams(
        sa.bindparam("kind", value=kind),
        sa.bindparam("sync_status", value=sync_status),
        sa.bindparam("remote_ids", value=VIEW_REMOTE_IDS, expanding=True),
    )


def upgrade() -> None:
    op.add_column(
        "folders",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=sa.text("'container'")),
    )
    op.execute(view_update_statement("view", "idle"))


def downgrade() -> None:
    op.execute(view_update_statement("container", "paused"))
    op.drop_column("folders", "kind")
