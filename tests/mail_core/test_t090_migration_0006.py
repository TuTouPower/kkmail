"""Real PostgreSQL migration validation for revision 20261125_0006 (t090 AC-001)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from mail_core.db.baseline import CURRENT_HEAD_REVISION

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _alembic_config_for(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _seed_pre0006_rows(target) -> dict[uuid.UUID, str]:
    bg_req_id, fg_req_id = uuid.uuid4(), uuid.uuid4()
    ids = {
        "marker_bg": uuid.uuid4(),
        "req_bg": uuid.uuid4(),
        "parent_req_bg": uuid.uuid4(),
        "req_fg": uuid.uuid4(),
        "gc_bg": uuid.uuid4(),
        "outbox_bg": uuid.uuid4(),
        "backup_bg": uuid.uuid4(),
        "arch_bg": uuid.uuid4(),
        "arch_fg": uuid.uuid4(),
        "plain_fg": uuid.uuid4(),
    }
    with target.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_requests (id, client_request_id, mode, trigger, state, scope) "
                "VALUES (:id, :cid, 'delta', 'manual', 'queued', CAST(:scope AS jsonb))"
            ),
            [
                {"id": bg_req_id, "cid": f"bg-{bg_req_id.hex}", "scope": '{"background": true}'},
                {"id": fg_req_id, "cid": f"fg-{fg_req_id.hex}", "scope": '{"account_id": "a"}'},
            ],
        )
        conn.execute(
            text(
                "INSERT INTO worker_jobs (id, job_type, payload) "
                "VALUES (:id, :jtype, CAST(:payload AS jsonb))"
            ),
            [
                {"id": ids["marker_bg"], "jtype": "sync_folder_delta", "payload": '{"background": true}'},
                {"id": ids["req_bg"], "jtype": "sync_account_folders", "payload": f'{{"request_id": "{bg_req_id}"}}'},
                {
                    "id": ids["parent_req_bg"],
                    "jtype": "sync_folder_delta",
                    "payload": f'{{"parent_request_id": "{bg_req_id}"}}',
                },
                {"id": ids["req_fg"], "jtype": "sync_folder_delta", "payload": f'{{"request_id": "{fg_req_id}"}}'},
                {"id": ids["gc_bg"], "jtype": "gc_blobs", "payload": "{}"},
                {"id": ids["outbox_bg"], "jtype": "outbox_dispatch_wake", "payload": "{}"},
                {"id": ids["backup_bg"], "jtype": "backup_run", "payload": "{}"},
                {"id": ids["arch_bg"], "jtype": "archive_mime_batch", "payload": "{}"},
                {
                    "id": ids["arch_fg"],
                    "jtype": "archive_mime_batch",
                    "payload": f'{{"message_id": "{uuid.uuid4()}"}}',
                },
                {"id": ids["plain_fg"], "jtype": "sync_folder_delta", "payload": '{"request_id": "non-uuid"}'},
            ],
        )
    return {
        ids["marker_bg"]: "background",
        ids["req_bg"]: "background",
        ids["parent_req_bg"]: "background",
        ids["req_fg"]: "foreground",
        ids["gc_bg"]: "background",
        ids["outbox_bg"]: "background",
        ids["backup_bg"]: "background",
        ids["arch_bg"]: "background",
        ids["arch_fg"]: "foreground",
        ids["plain_fg"]: "foreground",
    }


def _verify_0006_upgrade_and_constraints(target, expected_rows: dict[uuid.UUID, str]) -> None:
    with target.connect() as conn:
        rows = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT id, execution_origin FROM worker_jobs")).all()
        }
        assert rows == expected_rows
        cols = {c["name"]: c for c in inspect(conn).get_columns("worker_jobs")}
        assert cols["execution_origin"]["nullable"] is False
        checks = {c["name"] for c in inspect(conn).get_check_constraints("worker_jobs")}
        assert "ck_worker_jobs_execution_origin" in checks

    with target.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text("INSERT INTO worker_jobs (id, job_type, payload) VALUES (:id, 'sync_folder_delta', '{}')"),
                {"id": uuid.uuid4()},
            )
    with target.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO worker_jobs (id, job_type, execution_origin, payload) "
                    "VALUES (:id, 'sync_folder_delta', 'other', '{}')"
                ),
                {"id": uuid.uuid4()},
            )


def test_migration_0006_backfills_execution_origin_and_roundtrips():
    """Upgrade 0005->0006 backfills pre-existing worker_jobs rows cleanly and reverts symmetrically."""
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_mig0006_{uuid.uuid4().hex[:16]}"
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    temp_url = parsed.set(database=db_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target = create_engine(temp_url, poolclass=NullPool)
    cfg = _alembic_config_for(temp_url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        command.upgrade(cfg, "20261124_0005")
        expected_rows = _seed_pre0006_rows(target)

        assert CURRENT_HEAD_REVISION == "20261125_0006"
        assert ScriptDirectory.from_config(cfg).get_heads() == ["20261125_0006"]

        command.upgrade(cfg, "head")
        _verify_0006_upgrade_and_constraints(target, expected_rows)

        command.downgrade(cfg, "20261124_0005")
        with target.connect() as conn:
            col_names = {c["name"] for c in inspect(conn).get_columns("worker_jobs")}
            assert "execution_origin" not in col_names
            checks = {c["name"] for c in inspect(conn).get_check_constraints("worker_jobs")}
            assert "ck_worker_jobs_execution_origin" not in checks

        command.upgrade(cfg, "head")
        with target.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261125_0006"
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()
