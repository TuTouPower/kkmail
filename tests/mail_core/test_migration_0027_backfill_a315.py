"""A315: migration-level coverage for the 0027 recipient backfill.

Seeds data at the 0026 schema (empty recipient list, multiple
recipients in string and dict form, and a non-array ``to_addresses``
row), upgrades to 0027, and asserts both backfills:
``accounts.recipient_addresses`` and ``message_search.to_text``.

PostgreSQL-only (the backfill SQL uses jsonb functions): the module is
skipped when ``MAIL_CORE_DATABASE_URL`` is not set, following the
existing migration-test pattern in test_sync_execution_migration.py.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from mail_core.db.session import get_engine

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set (PG required)",
)


def _get_alembic_config() -> Config:
    cfg = Config(str(ROOT / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    safe_url = os.environ["MAIL_CORE_DATABASE_URL"].replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", safe_url)
    return cfg


def test_upgrade_0027_backfills_recipient_addresses_and_to_text():
    cfg = _get_alembic_config()
    engine = get_engine()
    account_id = uuid.uuid4()
    empty_account_id = uuid.uuid4()
    msg_multi = uuid.uuid4()
    msg_empty = uuid.uuid4()
    msg_scalar = uuid.uuid4()
    try:
        command.downgrade(cfg, "20261026_0026")
        with engine.begin() as conn:
            for aid, label in ((account_id, "mig27"), (empty_account_id, "mig27-empty")):
                conn.execute(
                    text("INSERT INTO accounts (id, email, provider) VALUES (:id, :email, 'imap')"),
                    {"id": aid, "email": f"{label}-{aid.hex[:8]}@example.com"},
                )
            messages = [
                (
                    msg_multi,
                    account_id,
                    json.dumps(
                        [
                            "ann@example.com",
                            {"name": "Bob", "address": "bob@example.com"},
                            "ann@example.com",
                        ]
                    ),
                ),
                (msg_empty, account_id, "[]"),
                # Historical non-array shape: must be skipped, not fatal (A25).
                (msg_scalar, account_id, json.dumps("scalar@example.com")),
            ]
            for mid, aid, to_addresses in messages:
                conn.execute(
                    text(
                        "INSERT INTO messages (id, account_id, remote_id, to_addresses) "
                        "VALUES (:id, :aid, :rid, CAST(:ta AS jsonb))"
                    ),
                    {"id": mid, "aid": aid, "rid": f"mig27-{mid.hex[:8]}", "ta": to_addresses},
                )
                conn.execute(
                    text(
                        "INSERT INTO message_search (message_id, account_id, subject, from_text, body_text) "
                        "VALUES (:mid, :aid, 'hello', 'sender@example.com', 'body')"
                    ),
                    {"mid": mid, "aid": aid},
                )

        command.upgrade(cfg, "20261027_0027")

        with engine.connect() as conn:
            addresses = conn.scalar(
                text("SELECT recipient_addresses FROM accounts WHERE id = :id"), {"id": account_id}
            )
            assert set(addresses) == {"ann@example.com", "bob@example.com"}
            empty_addresses = conn.scalar(
                text("SELECT recipient_addresses FROM accounts WHERE id = :id"),
                {"id": empty_account_id},
            )
            assert empty_addresses == []

            to_text_multi = conn.scalar(
                text("SELECT to_text FROM message_search WHERE message_id = :id"), {"id": msg_multi}
            )
            assert "ann@example.com" in to_text_multi
            assert "Bob bob@example.com" in to_text_multi
            assert "{" not in to_text_multi, "dict recipients must not leak raw JSON text"
            to_text_empty = conn.scalar(
                text("SELECT to_text FROM message_search WHERE message_id = :id"), {"id": msg_empty}
            )
            assert to_text_empty == ""
            to_text_scalar = conn.scalar(
                text("SELECT to_text FROM message_search WHERE message_id = :id"), {"id": msg_scalar}
            )
            assert to_text_scalar == ""
    finally:
        # Remove the seeded rows before returning to head so the 0028
        # rebuild runs on a clean slate, then restore the chain head.
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM accounts WHERE id IN (:a, :b)"), {"a": account_id, "b": empty_account_id})
        command.upgrade(cfg, "head")
