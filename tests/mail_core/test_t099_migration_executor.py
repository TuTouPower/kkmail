"""t099 PostgreSQL integration tests: unified migration executor.

Covers the executor contract against real PostgreSQL:

- AC-001: an empty database is initialized to head through ``--migrate-only``
  (the offline tool's refusal of empty databases is covered in
  tests/scripts/test_migrate_to_unified_baseline.py); a supported legacy
  database is upgraded to head through the offline tool's actual write path
  and passes the full schema comparison.
- AC-002: the backend PIDs that served the read-only check are gone from
  ``pg_stat_activity`` when the first write entry is reached — for the
  empty-database upgrade and for the LEGACY narrow conversion — observed
  from an independent connection against a dedicated database.
- AC-003: ``--check-migrations`` and the offline dry-run perform zero writes
  on an upgradeable database; a drifted supported legacy database is refused
  by startup, the startup check and the offline tool with schema, version
  and business data untouched.
- AC-004: a ``SchemaValidationError`` raised after the narrow conversion has
  already written rolls the whole conversion transaction back; removing the
  fault lets the retry succeed, and re-running a converted database keeps
  its data identical.

The 0030 legacy shape is derived from the historical 0001 baseline minus
``folder_patrol_status`` (the same faithful fixture as
tests/mail_core/test_startup_migrations.py).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from mail_core import __main__ as main_module
from mail_core.db import baseline
from mail_core.db.baseline import SchemaValidationError

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_ACCOUNT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_FOLDER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_LEGACY_CURSOR = {
    "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
    "last_probe_at": 1700000000.0,
    "last_probe_failures": 3,
    "delta_token": "token-xyz",
}


@pytest.fixture
def pg_db():
    """Yield a factory creating dedicated databases; drop them at teardown.

    A dedicated database per case keeps ``pg_stat_activity`` observations
    attributable to this test alone: every backend on the database belongs
    to the fixture or the code under test.
    """
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    created: list[str] = []

    def _new() -> str:
        db_name = f"kkmail_t099_{uuid.uuid4().hex[:16]}"
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        created.append(db_name)
        return parsed.set(database=db_name).render_as_string(hide_password=False)

    try:
        yield _new
    finally:
        with admin.connect() as conn:
            for db_name in created:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


def _make_0030_db(db_url: str, *, revision: str = "20261031_0030") -> str:
    """Build a faithful 0030 legacy shape from the historical 0001 baseline."""
    cfg = baseline.alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
        command.upgrade(cfg, baseline.UNIFIED_BASELINE_REVISION)
        with engine.begin() as conn:
            account_columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'accounts' AND table_schema = current_schema()"
                    )
                )
            }
            assert "sync_status" in account_columns
            assert not {"credential_state", "connectivity_state", "sync_activity"} & account_columns
            conn.execute(text("DROP TABLE folder_patrol_status"))
            conn.execute(
                text("UPDATE alembic_version SET version_num = :rev"),
                {"rev": revision},
            )
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, recipient_addresses) "
                    "VALUES (:acc, 'legacy@example.com', 'imap', '[]')"
                ),
                {"acc": _ACCOUNT_ID},
            )
            conn.execute(
                text(
                    "INSERT INTO folders (id, account_id, remote_id, name) "
                    "VALUES (:folder, :acc, 'INBOX', 'Inbox')"
                ),
                {"folder": _FOLDER_ID, "acc": _ACCOUNT_ID},
            )
            conn.execute(
                text(
                    "INSERT INTO sync_checkpoints (account_id, folder_id, cursor) "
                    "VALUES (:acc, :folder, :cur)"
                ),
                {"acc": _ACCOUNT_ID, "folder": _FOLDER_ID, "cur": json.dumps(_LEGACY_CURSOR)},
            )
    finally:
        engine.dispose()
    return db_url


def _as_json_text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _snapshot(db_url: str) -> dict:
    """Schema + version + representative business data, normalized to text."""
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            insp = inspect(conn)
            tables = sorted(insp.get_table_names())
            columns = {
                table: sorted(
                    (col["name"], str(col["type"])) for col in insp.get_columns(table)
                )
                for table in tables
            }
            revs: list[str] = []
            if "alembic_version" in tables:
                revs = sorted(
                    row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
                )
            cursors: list[tuple] = []
            if "sync_checkpoints" in tables:
                cursors = sorted(
                    (str(row[0]), _as_json_text(row[1]))
                    for row in conn.execute(text("SELECT folder_id, cursor FROM sync_checkpoints")).fetchall()
                )
            patrol: list[tuple] = []
            if "folder_patrol_status" in tables:
                try:
                    cols = {c["name"] for c in insp.get_columns("folder_patrol_status")}
                    if {"folder_id", "last_status", "last_probe_failures"} <= cols:
                        patrol = [
                            (str(row[0]), _as_json_text(row[1]), row[2])
                            for row in conn.execute(
                                text(
                                    "SELECT folder_id, last_status, last_probe_failures "
                                    "FROM folder_patrol_status ORDER BY folder_id"
                                )
                            ).fetchall()
                        ]
                    else:
                        patrol = [("<unreadable>",)]
                except Exception:
                    patrol = [("<unreadable>",)]
            accounts: list[str] = []
            if "accounts" in tables:
                accounts = sorted(
                    row[0] for row in conn.execute(text("SELECT email FROM accounts")).fetchall()
                )
            return {
                "tables": tables,
                "columns": columns,
                "revs": revs,
                "patrol": patrol,
                "cursors": cursors,
                "accounts": accounts,
            }
    finally:
        engine.dispose()


def _record_check_pids(monkeypatch) -> list[int]:
    """Spy on the executor's state read to capture the check connection PID."""
    pids: list[int] = []
    real_read_state = baseline.read_database_state

    def _spy(conn):
        pids.append(int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one()))
        return real_read_state(conn)

    monkeypatch.setattr(baseline, "read_database_state", _spy)
    return pids


def _assert_pids_gone(admin_url: str, db_name: str, pids: list[int]) -> None:
    """From an independent connection, assert the check backends have exited.

    Polls briefly: backend teardown is prompt once the pool is disposed,
    but ``pg_stat_activity`` is a snapshot, not a subscription.
    """
    observer = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        deadline = time.monotonic() + 10.0
        remaining: list[int] = []
        while True:
            with observer.connect() as conn:
                remaining = [
                    int(row[0])
                    for row in conn.execute(
                        text(
                            "SELECT pid FROM pg_stat_activity "
                            "WHERE datname = :db AND pid = ANY(:pids)"
                        ),
                        {"db": db_name, "pids": pids},
                    ).fetchall()
                ]
            if not remaining or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        assert remaining == [], f"check backends still present at write entry: {remaining}"
    finally:
        observer.dispose()


def test_ac002_check_connection_released_before_empty_upgrade(pg_db, monkeypatch):
    """AC-002: entering the empty-database write upgrade, every transaction
    that took part in the read-only check has ended and its physical
    connection is closed (its backend PID no longer exists)."""
    db_url = pg_db()
    db_name = make_url(db_url).database
    admin_url = make_url(os.environ["MAIL_CORE_DATABASE_URL"]).set(
        database="postgres"
    ).render_as_string(hide_password=False)
    check_pids = _record_check_pids(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    orig_upgrade = command.upgrade
    observed: list[bool] = []

    def _spy_upgrade(cfg, rev):
        _assert_pids_gone(admin_url, db_name, check_pids)
        observed.append(True)
        return orig_upgrade(cfg, rev)

    monkeypatch.setattr("alembic.command.upgrade", _spy_upgrade)
    main_module.run_migrations()

    assert observed == [True]
    assert check_pids, "the check phase must have used a real backend"
    assert _snapshot(db_url)["revs"] == [baseline.CURRENT_HEAD_REVISION]


def test_ac002_check_connection_released_before_legacy_conversion(pg_db, monkeypatch):
    """AC-002: entering the LEGACY narrow conversion, the check connection
    is fully released; the conversion and the real Alembic upgrade to head
    then complete."""
    db_url = pg_db()
    _make_0030_db(db_url)
    db_name = make_url(db_url).database
    admin_url = make_url(os.environ["MAIL_CORE_DATABASE_URL"]).set(
        database="postgres"
    ).render_as_string(hide_password=False)
    check_pids = _record_check_pids(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    real_conversion = baseline.apply_narrow_legacy_conversion
    observed: list[bool] = []

    def _spy_conversion(url):
        _assert_pids_gone(admin_url, db_name, check_pids)
        observed.append(True)
        return real_conversion(url)

    monkeypatch.setattr(baseline, "apply_narrow_legacy_conversion", _spy_conversion)
    main_module.run_migrations()

    assert observed == [True]
    state = _snapshot(db_url)
    assert state["revs"] == [baseline.CURRENT_HEAD_REVISION]
    assert len(state["patrol"]) == 1
    folder_id, last_status, failures = state["patrol"][0]
    assert folder_id == _FOLDER_ID
    assert json.loads(last_status) == {"folder_path": "/Inbox", "uidvalidity": 12345}
    assert failures == 3
    assert state["cursors"] == [(_FOLDER_ID, json.dumps({"delta_token": "token-xyz"}))]


def test_ac001_migrate_only_initializes_empty_database(pg_db, monkeypatch):
    """AC-001: --migrate-only initializes an empty database to current head."""
    db_url = pg_db()
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    assert main_module.main(["--migrate-only"]) == 0

    state = _snapshot(db_url)
    assert state["revs"] == [baseline.CURRENT_HEAD_REVISION]
    assert set(baseline.REQUIRED_TABLES) <= set(state["tables"])


def test_ac001_offline_tool_upgrades_supported_legacy_to_head(pg_db):
    """AC-001: a supported legacy database upgraded through the offline
    tool's actual write path reaches head and passes schema verification."""
    db_url = pg_db()
    _make_0030_db(db_url)

    baseline.run_migration(db_url)

    state = _snapshot(db_url)
    assert state["revs"] == [baseline.CURRENT_HEAD_REVISION]
    assert len(state["patrol"]) == 1
    assert baseline.verify_upgraded_schema(db_url) == []


def test_ac003_check_only_on_upgradeable_database_writes_nothing(pg_db, monkeypatch):
    """AC-003: on a database at a known older revision, --check-migrations
    and the offline dry-run execute the check only — schema, version and
    business data are byte-identical afterwards."""
    db_url = pg_db()
    cfg = baseline.alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    command.upgrade(cfg, baseline.UNIFIED_BASELINE_REVISION)
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_status, sync_enabled) "
                    "VALUES (:id, 'older@example.test', 'imap', 'failed', true)"
                ),
                {"id": uuid.uuid4()},
            )
    finally:
        engine.dispose()

    before = _snapshot(db_url)
    assert before["revs"] == [baseline.UNIFIED_BASELINE_REVISION]
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    assert main_module.main(["--check-migrations"]) == 0
    assert _snapshot(db_url) == before

    baseline.run_migration(db_url, dry_run=True)
    assert _snapshot(db_url) == before


def test_ac003_drifted_supported_legacy_refused_by_all_entries(pg_db, monkeypatch):
    """AC-003: a supported legacy database whose schema drifted (a malformed
    folder_patrol_status the conversion cannot trust) is explicitly refused
    by startup, the startup check and the offline tool; nothing changes."""
    db_url = pg_db()
    _make_0030_db(db_url)
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE folder_patrol_status (folder_id VARCHAR(64) PRIMARY KEY)"))
    finally:
        engine.dispose()
    before = _snapshot(db_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    with pytest.raises(RuntimeError, match="not supported"):
        main_module.run_migrations()
    assert _snapshot(db_url) == before

    with pytest.raises(RuntimeError, match="not supported"):
        main_module.run_migrations(check_only=True)
    assert _snapshot(db_url) == before

    with pytest.raises(SchemaValidationError, match="missing required columns"):
        baseline.run_migration(db_url)
    assert _snapshot(db_url) == before

    with pytest.raises(SchemaValidationError, match="missing required columns"):
        baseline.run_migration(db_url, dry_run=True)
    assert _snapshot(db_url) == before


def test_ac004_conversion_validation_error_rolls_back_fully(pg_db, monkeypatch):
    """AC-004: a SchemaValidationError raised after the narrow conversion
    has already written (patrol table created, patrol data migrated) rolls
    the whole conversion transaction back — schema, version and business
    data identical to before, and the Alembic upgrade never started.
    Removing the fault lets the retry succeed; a re-run of the converted
    database keeps its data identical."""
    db_url = pg_db()
    _make_0030_db(db_url)
    before = _snapshot(db_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    upgrade_calls: list[str] = []
    monkeypatch.setattr(
        "alembic.command.upgrade", lambda cfg, rev: upgrade_calls.append(rev)
    )

    real_migrate = baseline.migrate_patrol_status_data

    def _boom(bind, *, dry_run: bool = False):
        real_migrate(bind, dry_run=dry_run)
        raise SchemaValidationError("injected validation failure after partial writes")

    monkeypatch.setattr(baseline, "migrate_patrol_status_data", _boom)
    with pytest.raises(RuntimeError, match="rolled back") as excinfo:
        main_module.run_migrations()
    assert isinstance(excinfo.value.__cause__, SchemaValidationError)

    after_failure = _snapshot(db_url)
    assert after_failure == before
    assert "folder_patrol_status" not in after_failure["tables"]
    assert upgrade_calls == []

    monkeypatch.setattr(baseline, "migrate_patrol_status_data", real_migrate)
    monkeypatch.undo()
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    main_module.run_migrations()
    after_success = _snapshot(db_url)
    assert after_success["revs"] == [baseline.CURRENT_HEAD_REVISION]
    assert len(after_success["patrol"]) == 1

    main_module.run_migrations()
    assert _snapshot(db_url) == after_success
