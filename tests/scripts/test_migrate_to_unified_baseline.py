"""Unit tests for scripts/migrate_to_unified_baseline.py (adoption A17)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from migrate_to_unified_baseline import (
    REQUIRED_COLUMNS,
    REQUIRED_TABLES,
    UNIFIED_BASELINE_REVISION,
    SchemaValidationError,
    main,
    run_migration,
    stamp_unified_baseline,
    verify_database_schema,
)


def _create_full_schema_engine():
    """Create an in-memory SQLite engine populated with all required tables and columns."""
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    for table_name in REQUIRED_TABLES:
        cols = [Column("id", String(64), primary_key=True)]
        req_cols = REQUIRED_COLUMNS.get(table_name, frozenset())
        for col_name in req_cols:
            if col_name == "id":
                continue
            cols.append(Column(col_name, String(64)))
        Table(table_name, metadata, *cols)

    metadata.create_all(engine)
    return engine


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


def test_run_migrations_guard_raises_on_legacy_revision(tmp_path: Path, monkeypatch):
    from mail_core.__main__ import run_migrations

    db_file = tmp_path / "legacy_guard.db"
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
    assert "Database is at legacy revision '20261031_0030'" in msg
    assert "Run 'python scripts/migrate_to_unified_baseline.py' to upgrade to the unified baseline." in msg
