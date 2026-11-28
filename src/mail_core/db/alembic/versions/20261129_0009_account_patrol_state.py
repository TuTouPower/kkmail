"""t097: move patrol cooldown + half-open lease out of Account.config.

Creates the dedicated ``account_patrol_state`` table, migrates every
parseable legacy ``patrol_cooldown_until`` value from ``accounts.config``
into it (unparseable values were already treated as inactive by the old
reader and are dropped), and removes the legacy key from every account
config while preserving all other keys and values.

Downgrade restores each stored ``cooldown_until`` back into the legacy
config key (ISO-8601, the exact shape the pre-t097 reader parses) and
drops the table, keeping the remaining account config intact.

Revises: 20261128_0008
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20261129_0009"
down_revision = "20261128_0008"
branch_labels = None
depends_on = None

_LEGACY_KEY = "patrol_cooldown_until"


def _parse_legacy_until(raw: object) -> datetime | None:
    """Parse a legacy config cooldown value exactly like the old reader."""
    if not raw:
        return None
    try:
        until = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until


def upgrade() -> None:
    op.create_table(
        "account_patrol_state",
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, config ->> :key AS raw_until FROM accounts "
            "WHERE config ? :key"
        ),
        {"key": _LEGACY_KEY},
    ).all()
    for account_id, raw_until in rows:
        until = _parse_legacy_until(raw_until)
        if until is None:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO account_patrol_state (account_id, cooldown_until) "
                "VALUES (:account_id, :until) "
                "ON CONFLICT (account_id) DO NOTHING"
            ),
            {"account_id": account_id, "until": until},
        )
    # Remove the legacy key from every account that carries it; all other
    # config keys and values are preserved by the jsonb key-delete operator.
    op.execute(
        "UPDATE accounts SET config = config - 'patrol_cooldown_until' "
        "WHERE config ? 'patrol_cooldown_until'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT account_id, cooldown_until FROM account_patrol_state "
            "WHERE cooldown_until IS NOT NULL"
        )
    ).all()
    for account_id, until in rows:
        bind.execute(
            sa.text(
                "UPDATE accounts SET config = jsonb_set("
                "COALESCE(config, '{}'::jsonb), '{patrol_cooldown_until}', "
                "to_jsonb(CAST(:until_iso AS text)), true) WHERE id = :account_id"
            ),
            {"account_id": account_id, "until_iso": until.isoformat()},
        )
    op.drop_table("account_patrol_state")
