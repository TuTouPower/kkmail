"""Unit tests for scripts/migrate_to_unified_baseline.py (adoption A17)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from migrate_to_unified_baseline import (
    KNOWN_LEGACY_REVISIONS,
    REQUIRED_COLUMNS,
    REQUIRED_TABLES,
    UNIFIED_BASELINE_REVISION,
    SchemaValidationError,
    ensure_folder_patrol_status_table,
    is_legacy_revision,
    main,
    migrate_patrol_status_data,
    run_migration,
    stamp_unified_baseline,
    verify_database_schema,
)

EXPECTED_CORE_TABLES: frozenset[str] = frozenset({
    "account_groups",
    "credential_secrets",
    "app_settings",
    "auth_credentials",
    "accounts",
    "account_sync_leases",
    "account_sync_activity",
    "folders",
    "threads",
    "messages",
    "message_locations",
    "message_bodies",
    "message_blobs",
    "message_blob_links",
    "attachments",
    "thread_messages",
    "sync_checkpoints",
    "sync_runs",
    "remote_operations",
    "folder_stats",
    "folder_patrol_status",
    "outbox_publication_state",
    "outbox",
    "message_archive_state",
    "worker_jobs",
    "message_search",
    "blob_quota_reservations",
    "sync_requests",
    "sync_request_targets",
    "sync_request_target_jobs",
    "message_remote_image_allows",
    "sender_remote_image_allows",
})


def _create_full_schema_engine():
    """Create an in-memory SQLite engine populated with all required tables and columns."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    for table_name in EXPECTED_CORE_TABLES:
        cols = [Column("id", String(64), primary_key=True)]
        req_cols = REQUIRED_COLUMNS.get(table_name, frozenset())
        for col_name in req_cols:
            if col_name == "id":
                continue
            cols.append(Column(col_name, String(64)))
        Table(table_name, metadata, *cols)

    metadata.create_all(engine)
    return engine


def test_required_tables_matches_expected_core_32_tables():
    """Verify REQUIRED_TABLES against the hardcoded specification of 32 core tables.

    Prevents self-referential / circular testing where tests pass trivially
    by simply importing whatever REQUIRED_TABLES happens to contain.
    """
    assert len(EXPECTED_CORE_TABLES) == 32
    assert REQUIRED_TABLES == EXPECTED_CORE_TABLES


def test_verify_schema_succeeds_on_full_schema():
    engine = _create_full_schema_engine()
    with engine.connect() as conn:
        errors = verify_database_schema(conn)
        assert errors == []


def test_verify_schema_fails_on_empty_db():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        errors = verify_database_schema(conn)
        assert len(errors) == 1
        assert "Missing required tables" in errors[0]
        assert "accounts" in errors[0]
        assert "messages" in errors[0]


def test_verify_schema_detects_missing_columns():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    # Create all tables but with only "id", omitting required columns
    for table_name in REQUIRED_TABLES:
        Table(table_name, metadata, Column("id", String(64), primary_key=True))
    metadata.create_all(engine)

    with engine.connect() as conn:
        errors = verify_database_schema(conn)
        assert len(errors) > 0
        joined = "\n".join(errors)
        assert "accounts" in joined
        assert "recipient_addresses" in joined
        assert "messages" in joined
        assert "remote_id" in joined


def test_run_migration_rejects_incomplete_schema():
    engine = create_engine("sqlite:///:memory:")
    with patch("migrate_to_unified_baseline.create_engine", return_value=engine):
        with pytest.raises(SchemaValidationError, match="Database schema verification failed"):
            run_migration("sqlite:///:memory:")


def test_stamp_unified_baseline_creates_table_and_sets_revision():
    engine = create_engine("sqlite:///:memory:")
    stamp_unified_baseline(engine, dry_run=False)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_stamp_unified_baseline_dry_run_leaves_table_empty():
    engine = create_engine("sqlite:///:memory:")
    stamp_unified_baseline(engine, dry_run=True)

    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        ).scalars().all()
        assert tables == []


def test_stamp_unified_baseline_overwrites_prior_revision():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))

    stamp_unified_baseline(engine, dry_run=False)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_run_migration_success_flow():
    engine = _create_full_schema_engine()
    with patch("migrate_to_unified_baseline.create_engine", return_value=engine):
        run_migration("sqlite:///:memory:", dry_run=False)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_main_cli_returns_expected_exit_codes():
    # 1. Missing URL
    with patch.dict("os.environ", {}, clear=True):
        ret = main([])
        assert ret == 2

    # 2. Schema validation failure
    empty_engine = create_engine("sqlite:///:memory:")
    with patch("migrate_to_unified_baseline.create_engine", return_value=empty_engine):
        ret = main(["--database-url", "sqlite:///:memory:"])
        assert ret == 1

    # 3. Success
    full_engine = _create_full_schema_engine()
    with patch("migrate_to_unified_baseline.create_engine", return_value=full_engine):
        ret = main(["--database-url", "sqlite:///:memory:"])
        assert ret == 0


def _create_0030_schema_engine(db_path: Path | str):
    """Create an engine populated with schema at revision 20261031_0030.

    This includes all 31 tables (missing folder_patrol_status), alembic_version='20261031_0030',
    and sample sync_checkpoints data containing legacy patrol keys in cursor.
    """
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    metadata = MetaData()

    tables_0030 = REQUIRED_TABLES - {"folder_patrol_status"}
    for table_name in tables_0030:
        cols = [Column("id", String(64), primary_key=True)]
        req_cols = REQUIRED_COLUMNS.get(table_name, frozenset())
        for col_name in req_cols:
            if col_name == "id":
                continue
            cols.append(Column(col_name, String(64)))
        if table_name == "sync_checkpoints":
            cols.append(Column("cursor", String(512)))
        Table(table_name, metadata, *cols)

    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))
        conn.execute(
            text(
                """
                INSERT INTO sync_checkpoints (id, account_id, folder_id, scan_generation, cursor)
                VALUES ('cp-1', 'acc-1', 'folder-1', '1', :cur)
                """
            ),
            {
                "cur": json.dumps(
                    {
                        "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
                        "last_probe_at": 1700000000.0,
                        "last_probe_failures": 3,
                        "delta_token": "token-xyz",
                    }
                )
            },
        )
    return engine


def test_migrate_from_0030_legacy_database_success(tmp_path: Path):
    db_file = tmp_path / "legacy_0030.db"
    _create_0030_schema_engine(db_file)
    db_url = f"sqlite:///{db_file}"

    # 1. Run migration CLI on 0030 database
    ret = main(["--database-url", db_url])

    # 2. Assert exit code 0
    assert ret == 0

    # 3. Assert folder_patrol_status was created and contains migrated patrol data
    verify_engine = create_engine(db_url)
    with verify_engine.connect() as conn:
        from sqlalchemy import inspect
        tables = set(inspect(conn).get_table_names())
        assert "folder_patrol_status" in tables

        row = conn.execute(
            text("SELECT folder_id, last_status, last_probe_failures, last_probe_at FROM folder_patrol_status")
        ).fetchone()
        assert row is not None
        assert row[0] == "folder-1"
        status_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        assert status_data == {"folder_path": "/Inbox", "uidvalidity": 12345}
        assert row[2] == 3
        assert row[3] is not None

        # 4. Assert sync_checkpoints.cursor has old keys stripped
        cp_row = conn.execute(
            text("SELECT cursor FROM sync_checkpoints WHERE id = 'cp-1'")
        ).fetchone()
        assert cp_row is not None
        cur_data = json.loads(cp_row[0]) if isinstance(cp_row[0], str) else cp_row[0]
        assert "last_status" not in cur_data
        assert "last_probe_at" not in cur_data
        assert "last_probe_failures" not in cur_data
        assert cur_data.get("delta_token") == "token-xyz"

        # 5. Assert alembic_version stamped to unified baseline
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_run_migration_refuses_stamp_on_unknown_revision_with_missing_tables(tmp_path: Path):
    db_file = tmp_path / "unknown_rev.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))

    with pytest.raises(SchemaValidationError, match="Refusing to stamp unified baseline"):
        run_migration(db_url)


def test_legacy_revision_set_uses_real_hashed_id():
    assert "f5f312751c77" in KNOWN_LEGACY_REVISIONS
    assert "20261020_0002" not in KNOWN_LEGACY_REVISIONS


def test_is_legacy_revision_recognizes_hashed_revision():
    assert is_legacy_revision("f5f312751c77") is True


def test_is_legacy_revision_rejects_unknown_and_future_revisions():
    assert is_legacy_revision(None) is False
    assert is_legacy_revision("unknown_rev_9999") is False
    assert is_legacy_revision("g9f312751c77") is False
    assert is_legacy_revision("20261107_0001") is False
    assert is_legacy_revision("20261201_0002") is False


def test_stamp_refuses_to_overwrite_unknown_revision():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('some_future_head')"))

    with pytest.raises(SchemaValidationError, match="Refusing to overwrite"):
        stamp_unified_baseline(engine, dry_run=False)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == ["some_future_head"]


def test_stamp_is_noop_when_already_at_baseline():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:rev)"),
            {"rev": UNIFIED_BASELINE_REVISION},
        )

    stamp_unified_baseline(engine, dry_run=False)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == [UNIFIED_BASELINE_REVISION]


def test_verify_schema_exempt_tables_only_skips_named_table():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    for table_name in REQUIRED_TABLES - {"folder_patrol_status", "accounts"}:
        Table(table_name, metadata, Column("id", String(64), primary_key=True))
    metadata.create_all(engine)

    with engine.connect() as conn:
        errors = verify_database_schema(
            conn, exempt_tables=frozenset({"folder_patrol_status"})
        )
    joined = "\n".join(errors)
    assert "accounts" in joined
    assert "folder_patrol_status" not in joined


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
def test_run_migration_refuses_unsupported_legacy_database(tmp_path: Path, dry_run: bool):
    db_file = tmp_path / f"old_legacy_{'dry' if dry_run else 'apply'}.db"
    db_url = f"sqlite:///{db_file}"
    legacy_cursor = json.dumps({"last_status": "ok", "delta_token": "keep-me"})
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261027_0029')"))
        conn.execute(text("CREATE TABLE folders (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE sync_checkpoints (id VARCHAR(64) PRIMARY KEY, "
                "folder_id VARCHAR(64), cursor TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sync_checkpoints (id, folder_id, cursor) "
                "VALUES ('cp-1', 'folder-1', :cur)"
            ),
            {"cur": legacy_cursor},
        )
    engine.dispose()

    with pytest.raises(SchemaValidationError, match="not supported") as excinfo:
        run_migration(db_url, dry_run=dry_run)
    assert "message_remote_image_allows" in str(excinfo.value)
    assert "Restore the pre-upgrade sealed backup" in str(excinfo.value)

    verify_engine = create_engine(db_url)
    with verify_engine.connect() as conn:
        from sqlalchemy import inspect
        assert "folder_patrol_status" not in set(inspect(conn).get_table_names())
        assert conn.execute(
            text("SELECT cursor FROM sync_checkpoints WHERE id = 'cp-1'")
        ).scalar_one() == legacy_cursor
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all() == ["20261027_0029"]
    verify_engine.dispose()


def test_dry_run_reports_missing_columns_on_existing_patrol_table(tmp_path: Path):
    db_file = tmp_path / "legacy_0030_incomplete_patrol.db"
    _create_0030_schema_engine(db_file)
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE folder_patrol_status (folder_id VARCHAR(64) PRIMARY KEY)")
        )
    engine.dispose()

    with pytest.raises(SchemaValidationError, match="not supported") as excinfo:
        run_migration(db_url, dry_run=True)
    msg = str(excinfo.value)
    assert "folder_patrol_status" in msg
    assert "missing required columns" in msg
    assert "last_probe_failures" in msg


def test_verify_schema_exempt_table_still_checks_columns_when_present():
    engine = _create_full_schema_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE folder_patrol_status"))
        conn.execute(
            text("CREATE TABLE folder_patrol_status (folder_id VARCHAR(64) PRIMARY KEY)")
        )
    with engine.connect() as conn:
        errors = verify_database_schema(
            conn, exempt_tables=frozenset({"folder_patrol_status"})
        )
    joined = "\n".join(errors)
    assert "folder_patrol_status" in joined
    assert "missing required columns" in joined
    assert "Missing required tables" not in joined


def _captured_sql(call):
    return call.args[0].text


def test_ensure_folder_patrol_status_emits_postgres_ddl():
    """Mock-level check of the PostgreSQL DDL text only.

    The connection is a MagicMock: no statement reaches a real PostgreSQL
    server, so dialect or runtime failures cannot surface here. Real execution
    is covered by tests/mail_core/test_migration_validation.py.
    """
    conn = MagicMock()
    conn.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["folders", "sync_checkpoints"]
    with patch("migrate_to_unified_baseline.inspect", return_value=inspector):
        ensure_folder_patrol_status_table(conn, dry_run=False)

    assert conn.execute.call_count == 1
    sql = _captured_sql(conn.execute.call_args)
    assert "CREATE TABLE folder_patrol_status" in sql
    assert "UUID" in sql
    assert "JSONB" in sql
    assert "ON DELETE CASCADE" in sql
    assert "now()" in sql


def test_migrate_patrol_status_data_emits_postgres_ddl():
    """Mock-level check of the PostgreSQL data-migration SQL text only.

    The INSERT ... ON CONFLICT and cursor-minus-ARRAY statements are asserted
    as strings against a MagicMock, never executed. Real JSONB execution is
    covered by tests/mail_core/test_migration_validation.py.
    """
    conn = MagicMock()
    conn.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["sync_checkpoints", "folder_patrol_status"]
    with patch("migrate_to_unified_baseline.inspect", return_value=inspector):
        migrate_patrol_status_data(conn, dry_run=False)

    assert conn.execute.call_count == 2
    insert_sql = _captured_sql(conn.execute.call_args_list[0])
    update_sql = _captured_sql(conn.execute.call_args_list[1])
    assert "INSERT INTO folder_patrol_status" in insert_sql
    assert "ON CONFLICT" in insert_sql
    assert "cursor ? 'last_status'" in insert_sql
    assert "to_timestamp" in insert_sql
    assert "::double precision" in insert_sql
    assert "cursor - ARRAY" in update_sql


def test_run_migrations_guard_reports_historical_revision_upgrade_path(tmp_path: Path, monkeypatch):
    """Historical revisions must still be refused at startup, with the offline-tool path.

    Replaces ``test_run_migrations_guard_raises_on_legacy_revision``: that test
    locked the former single-message wording, which was retired when the startup
    guard began distinguishing newer / historical / unverifiable revisions
    (see tests/mail_core/test_sidecar_detection.py::test_legacy_guard_distinguishes_revision_cases).
    """
    from mail_core.__main__ import run_migrations

    db_file = tmp_path / "historical_guard.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    with pytest.raises(RuntimeError) as excinfo:
        run_migrations()

    msg = str(excinfo.value)
    assert "20261031_0030" in msg
    assert "migrate_to_unified_baseline.py" in msg
    assert "offline" in msg
