"""Unit tests for scripts/migrate_to_unified_baseline.py (adoption A17)."""

from __future__ import annotations

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
