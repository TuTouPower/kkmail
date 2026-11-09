"""Unit tests for the unified-baseline migration logic (adoption A17).

The logic moved from ``scripts/migrate_to_unified_baseline.py`` (now a thin
argparse wrapper) to ``mail_core.db.baseline``; mocks and imports follow the
new home.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Integer,
    JSON,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from mail_core.db.baseline import (
    KNOWN_LEGACY_REVISIONS,
    REQUIRED_COLUMNS,
    REQUIRED_TABLES,
    UNIFIED_BASELINE_REVISION,
    MigrationAction,
    RevisionContext,
    SchemaValidationError,
    ensure_folder_patrol_status_table,
    is_legacy_revision,
    migrate_patrol_status_data,
    offline_revision_context,
    plan_migration,
    read_database_state,
    run_migration,
    stamp_unified_baseline,
    verify_database_schema,
)
from migrate_to_unified_baseline import main

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


def _create_full_schema_engine(db_url: str = "sqlite:///:memory:"):
    """Create a SQLite engine populated with all required tables and columns."""
    engine = create_engine(db_url)
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


def _startup_revision_context():
    """Build the startup entry's context from the real Alembic ScriptDirectory."""
    import mail_core.db as db_pkg
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    here = Path(db_pkg.__file__).resolve().parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    return RevisionContext(
        known_revisions=frozenset(r.revision for r in script.walk_revisions()),
        legacy_revisions=KNOWN_LEGACY_REVISIONS,
        heads=tuple(script.get_heads()),
    )


def _assert_no_version_stamp(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            rows: list[str] = []
            if "alembic_version" in tables:
                rows = list(
                    conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                )
            assert UNIFIED_BASELINE_REVISION not in rows
    finally:
        engine.dispose()


def _read_versions(db_url: str) -> list[str]:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            if "alembic_version" not in tables:
                return []
            return sorted(
                conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            )
    finally:
        engine.dispose()


def _build_state_db(tmp_path: Path, state: str) -> str:
    db_url = f"sqlite:///{tmp_path / ('state_' + state + '.db')}"
    if state == "no_version_full":
        _create_full_schema_engine(db_url).dispose()
        return db_url
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            if state == "empty":
                return db_url
            if state == "no_version_one":
                conn.execute(text("CREATE TABLE account_groups (id VARCHAR(64) PRIMARY KEY)"))
                return db_url
            if state == "multiple":
                conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))
                conn.execute(text("INSERT INTO alembic_version VALUES ('20261107_0031')"))
                return db_url
            conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            revision = {
                "at_head": UNIFIED_BASELINE_REVISION,
                "legacy": "20261031_0030",
                "unknown": "unknown_rev_9999",
            }[state]
            conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": revision})
        return db_url
    finally:
        engine.dispose()


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


def test_run_migration_rejects_empty_database(tmp_path: Path):
    """退役理由：原 test_run_migration_rejects_incomplete_schema 把空库断言为
    『Database schema verification failed』（旧实现的缺 critical 表分支）。统一分类后
    空库归类 EMPTY_DATABASE，离线明确提示走启动/Alembic、不建表、不盖印。"""
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"
    with pytest.raises(SchemaValidationError, match="empty") as excinfo:
        run_migration(db_url)
    assert "alembic upgrade head" in str(excinfo.value)
    _assert_no_version_stamp(db_url)


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


def test_no_version_full_schema_refused_by_both_entries(tmp_path: Path, monkeypatch):
    """退役理由：原 test_run_migration_success_flow 断言『无版本 + 全 32 表 → 成功
    stamp』，固化了离线/启动双入口的行为分歧。统一分类后该状态为
    NO_VERSION_WITH_BUSINESS_TABLES，两个入口一律拒绝、不盖印。"""
    db_url = f"sqlite:///{tmp_path / 'full.db'}"
    _create_full_schema_engine(db_url).dispose()

    with pytest.raises(SchemaValidationError, match="no alembic_version mark"):
        run_migration(db_url, dry_run=False)
    _assert_no_version_stamp(db_url)

    from mail_core import __main__ as main_module

    upgrades: list[str] = []
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, rev: upgrades.append(rev))
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    with pytest.raises(RuntimeError, match="no alembic_version mark"):
        main_module.run_migrations()
    assert upgrades == []
    _assert_no_version_stamp(db_url)


def test_main_cli_returns_expected_exit_codes(tmp_path: Path):
    # 1. Missing URL
    with patch.dict("os.environ", {}, clear=True):
        ret = main([])
        assert ret == 2

    # 2. Empty DB: the offline tool refuses and points to startup/Alembic.
    ret = main(["--database-url", f"sqlite:///{tmp_path / 'empty.db'}"])
    assert ret == 1

    # 3. No version + full 32 tables: refused (retired: old case expected a success stamp).
    full_url = f"sqlite:///{tmp_path / 'full.db'}"
    _create_full_schema_engine(full_url)
    ret = main(["--database-url", full_url])
    assert ret == 1


def _create_0030_schema_engine(db_path: Path | str):
    """Create an engine populated with schema at revision 20261031_0030.

    Hand-written transcription of the real historical shape (composite
    primary key and CASCADE foreign keys on sync_checkpoints, composite
    unique on folders): all 31 tables (missing folder_patrol_status),
    alembic_version='20261031_0030', and sample sync_checkpoints data
    containing legacy patrol keys in cursor. Deliberately NOT generated
    from REQUIRED_COLUMNS.
    """
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    metadata = MetaData()

    Table("account_groups", metadata, Column("id", String(64), primary_key=True))
    Table("credential_secrets", metadata, Column("ref", String(512), primary_key=True))
    Table("app_settings", metadata, Column("key", String(128), primary_key=True))
    Table("auth_credentials", metadata, Column("id", String(64), primary_key=True))
    Table(
        "accounts",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("email", String(320), nullable=False),
        Column("provider", String(32), nullable=False),
        Column("group_id", String(64)),
        Column("master_order", Integer),
        Column("group_order", Integer),
        Column("recipient_addresses", JSON, nullable=False),
    )
    Table("account_sync_leases", metadata, Column("account_id", String(64), primary_key=True))
    Table("account_sync_activity", metadata, Column("account_id", String(64), primary_key=True))
    Table(
        "folders",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("account_id", String(64), nullable=False),
        Column("remote_id", String(512), nullable=False),
        UniqueConstraint("account_id", "remote_id"),
    )
    Table(
        "threads",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("account_id", String(64), nullable=False),
    )
    Table(
        "messages",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("account_id", String(64), nullable=False),
        Column("sort_time", String(64)),
        Column("remote_id", String(512)),
        Column("is_read", Integer),
        Column("is_flagged", Integer),
        Column("has_attachments", Integer),
    )
    Table("message_locations", metadata, Column("id", String(64), primary_key=True))
    Table("message_bodies", metadata, Column("message_id", String(64), primary_key=True))
    Table(
        "message_blobs",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("content_sha256", String(64), nullable=False),
        Column("key_version", Integer, nullable=False),
        Column("gc_eligible_at", String(64)),
        Column("ref_count", Integer, nullable=False),
    )
    Table("message_blob_links", metadata, Column("message_id", String(64), primary_key=True))
    Table(
        "attachments",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("message_id", String(64), nullable=False),
        Column("part_id", String(64)),
    )
    Table("thread_messages", metadata, Column("id", String(64), primary_key=True))
    Table(
        "sync_checkpoints",
        metadata,
        Column("account_id", String(64), nullable=False),
        Column("folder_id", String(64), nullable=False),
        Column("scan_generation", String(64)),
        Column("cursor", JSON, nullable=False),
        ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
        PrimaryKeyConstraint("account_id", "folder_id"),
    )
    Table("sync_runs", metadata, Column("id", String(64), primary_key=True))
    Table(
        "remote_operations",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("next_attempt_at", String(64)),
    )
    Table("folder_stats", metadata, Column("folder_id", String(64), primary_key=True))
    Table(
        "outbox_publication_state",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("epoch", String(64), nullable=False),
        Column("next_seq", Integer, nullable=False),
        Column("pruned_through_seq", Integer, nullable=False),
    )
    Table(
        "outbox",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("publication_seq", Integer),
        Column("published_at", String(64)),
    )
    Table(
        "message_archive_state",
        metadata,
        Column("message_id", String(64), primary_key=True),
        Column("claim_revision", Integer, nullable=False),
        Column("state", String(32), nullable=False),
    )
    Table(
        "worker_jobs",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("execution_generation", String(64), nullable=False),
        Column("dedupe_key", String(128)),
        Column("failure_attempts", Integer, nullable=False),
    )
    Table(
        "message_search",
        metadata,
        Column("message_id", String(64), primary_key=True),
        Column("to_text", String(64)),
        Column("document", String(64)),
    )
    Table("blob_quota_reservations", metadata, Column("id", String(64), primary_key=True))
    Table(
        "sync_requests",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("client_request_id", String(64), nullable=False),
    )
    Table(
        "sync_request_targets",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("request_id", String(64), nullable=False),
        Column("target_key", String(255), nullable=False),
    )
    Table(
        "sync_request_target_jobs",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("target_id", String(64), nullable=False),
        Column("execution_generation", String(64), nullable=False),
    )
    Table("message_remote_image_allows", metadata, Column("message_id", String(64), primary_key=True))
    Table("sender_remote_image_allows", metadata, Column("id", String(64), primary_key=True))

    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))
        conn.execute(
            text(
                """
                INSERT INTO sync_checkpoints (account_id, folder_id, cursor)
                VALUES ('acc-1', 'folder-1', :cur)
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
            text("SELECT cursor FROM sync_checkpoints WHERE folder_id = 'folder-1'")
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


def test_run_migration_refuses_unknown_revision_with_zero_writes(tmp_path: Path):
    """退役理由：原用例断言『Refusing to stamp unified baseline』（旧实现把
    unknown revision + 缺表 归入缺 critical 表分支的措辞）。统一分类后 unknown
    revision 一律按 UNKNOWN_REVISION 拒绝、不盖印、零写入。"""
    db_file = tmp_path / "unknown_rev.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))
    engine.dispose()

    before = _read_versions(db_url)
    with pytest.raises(SchemaValidationError, match="unrecognized"):
        run_migration(db_url)
    assert _read_versions(db_url) == before


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
    with patch("mail_core.db.baseline.inspect", return_value=inspector):
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
    with patch("mail_core.db.baseline.inspect", return_value=inspector):
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


@pytest.mark.parametrize(
    "state, expected_action",
    [
        ("empty", MigrationAction.EMPTY_DATABASE),
        ("no_version_full", MigrationAction.NO_VERSION_WITH_BUSINESS_TABLES),
        ("no_version_one", MigrationAction.NO_VERSION_WITH_BUSINESS_TABLES),
        ("at_head", MigrationAction.AT_BASELINE),
        ("legacy", MigrationAction.LEGACY),
        ("unknown", MigrationAction.UNKNOWN_REVISION),
        ("multiple", MigrationAction.MULTIPLE_VERSIONS),
    ],
)
def test_plan_migration_two_entries_agree_on_classification(tmp_path, state, expected_action):
    """Both entries supply a RevisionContext to the single planner.

    The startup context comes from ScriptDirectory.walk_revisions/get_heads and
    the offline context from baseline constants; for the same database state
    the returned action must be identical, so the two entries cannot diverge.
    """
    db_url = _build_state_db(tmp_path, state)
    startup_ctx = _startup_revision_context()
    offline_ctx = offline_revision_context()
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            db_state = read_database_state(conn)
    finally:
        engine.dispose()
    startup_plan = plan_migration(db_state, context=startup_ctx)
    offline_plan = plan_migration(db_state, context=offline_ctx)
    assert startup_plan.action == expected_action
    assert offline_plan.action == expected_action
    assert startup_plan.action == offline_plan.action
