"""Unit tests for the unified-baseline migration logic (adoption A17 / A18).

The logic moved from ``scripts/migrate_to_unified_baseline.py`` (now a thin
argparse wrapper) to ``mail_core.db.baseline``; mocks and imports follow the
new home.

Retirement (A18 wrap-up): this file previously exercised the offline tool
entirely on in-memory / file-backed SQLite databases. ``mail_core.db.baseline``
is now PostgreSQL-only: every
read-only check, narrow-conversion step and patrol migration rejects a non-PG
backend. SQLite fixtures therefore no longer touch production logic and were
replaced wholesale rather than having their assertions flipped in place. Each
case now runs against the shared PostgreSQL test database, isolated to a
per-test schema so mutable legacy/empty/baseline states never collide with the
public schema (which ``clear_database()`` truncates between cases).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import (
    Column,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from mail_core.db.baseline import (
    CURRENT_HEAD_REVISION,
    KNOWN_LEGACY_REVISIONS,
    REQUIRED_TABLES,
    UNIFIED_BASELINE_REVISION,
    MigrationAction,
    SchemaValidationError,
    ensure_folder_patrol_status_table,
    is_legacy_revision,
    migrate_patrol_status_data,
    plan_migration,
    read_database_state,
    revision_context,
    run_migration,
    stamp_unified_baseline,
    verify_baseline_schema,
)
from migrate_to_unified_baseline import main

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
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

_ACCOUNT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_FOLDER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

_LEGACY_CURSOR = {
    "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
    "last_probe_at": 1700000000.0,
    "last_probe_failures": 3,
    "delta_token": "token-xyz",
}


@pytest.fixture
def pg_engine():
    """Yield an engine bound to a unique per-test PostgreSQL schema.

    ``MAIL_CORE_DATABASE_URL`` points at the shared, already-migrated test
    database. A dedicated ``CREATE SCHEMA``/``DROP SCHEMA ... CASCADE`` keeps
    every mutable fixture (empty, baseline, 0030 legacy) inside this schema and
    never drops or alters objects in ``public``. The URL query
    ``options=-csearch_path=<schema>`` (psycopg) pins the search_path to this
    schema alone. The production migration and ORM qualify their pg_trgm
    opclasses as ``public.gin_trgm_ops``, so no other schema is needed on the
    path and ``current_schema()``, ``get_table_names()``, ``inspect`` and
    ``compare_metadata`` all see only this schema -- the at-head baseline
    tables in public never leak into the fixture.
    """
    base = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    admin = create_engine(base.render_as_string(hide_password=False))
    schema = "test_baseline_" + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = base.update_query_dict(
        {"options": f"-csearch_path={schema}"}
    ).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _schema_url(engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _create_full_schema(engine) -> None:
    """Create the full baseline schema from the ORM metadata.

    A16: the metadata is the single source of truth for what a baseline
    schema is. The old fixture built 32 minimal fake tables (id +
    REQUIRED_COLUMNS as String(64)), which only satisfied the retired
    name-based verify; under compare_metadata verification such a schema
    is (correctly) not a baseline.
    """
    import mail_core.mail.storage  # noqa: F401  (populates Base.metadata)
    from mail_core.db.base import Base

    Base.metadata.create_all(engine)


def _create_0030_schema(engine) -> None:
    """Build a faithful convertible 0030 legacy shape from historical 0001 DDL.

    A real legacy database is the 0001 baseline (``accounts.sync_status``,
    none of the three health columns) minus ``folder_patrol_status``, stamped
    with the historical revision. Building it from the current ORM would forge
    the new schema and make every conversion test vacuous, so the fixture
    replays the historical Alembic revision instead.
    """

    from alembic import command
    from mail_core.db.baseline import UNIFIED_BASELINE_REVISION, alembic_config

    cfg = alembic_config()
    cfg.set_main_option("sqlalchemy.url", _schema_url(engine).replace("%", "%%"))
    command.upgrade(cfg, UNIFIED_BASELINE_REVISION)
    with engine.begin() as conn:
        # Guard: the fixture must faithfully represent the historical 0001
        # shape, never the current head (three health columns).
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
        conn.execute(text("UPDATE alembic_version SET version_num = '20261031_0030'"))
        conn.execute(
            text(
                "INSERT INTO accounts (id, email, provider) "
                "VALUES (:acc, 'legacy@example.com', 'outlook')"
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
                "VALUES (:acc, :folder, CAST(:cur AS jsonb))"
            ),
            {"acc": _ACCOUNT_ID, "folder": _FOLDER_ID, "cur": json.dumps(_LEGACY_CURSOR)},
        )


def _build_state(engine, state: str) -> None:
    if state == "no_version_full":
        _create_full_schema(engine)
        return
    with engine.begin() as conn:
        if state == "empty":
            return
        if state == "no_version_one":
            conn.execute(text("CREATE TABLE account_groups (id VARCHAR(64) PRIMARY KEY)"))
            return
        if state == "multiple":
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))
            conn.execute(text("INSERT INTO alembic_version VALUES ('20261107_0031')"))
            return
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        revision = {
            "at_head": CURRENT_HEAD_REVISION,
            "legacy": "20261031_0030",
            "unknown": "unknown_rev_9999",
        }[state]
        conn.execute(text("INSERT INTO alembic_version VALUES (:rev)"), {"rev": revision})


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


def test_required_tables_matches_expected_core_32_tables():
    """Verify REQUIRED_TABLES against the hardcoded specification of 32 core tables.

    Prevents self-referential / circular testing where tests pass trivially
    by simply importing whatever REQUIRED_TABLES happens to contain.
    """
    assert len(EXPECTED_CORE_TABLES) == 32
    assert REQUIRED_TABLES == EXPECTED_CORE_TABLES


def test_verify_baseline_schema_succeeds_on_full_schema(pg_engine):
    _create_full_schema(pg_engine)
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
        assert errors == []


def test_verify_baseline_schema_fails_on_empty_db(pg_engine):
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    assert len(errors) >= 32
    joined = "\n".join(errors)
    assert "accounts" in joined
    assert "messages" in joined


def test_verify_baseline_schema_detects_missing_columns(pg_engine):
    metadata = MetaData()
    for table_name in REQUIRED_TABLES:
        Table(table_name, metadata, Column("id", String(64), primary_key=True))
    metadata.create_all(pg_engine)

    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    assert len(errors) > 0
    joined = "\n".join(errors)
    assert "accounts" in joined
    assert "recipient_addresses" in joined
    assert "messages" in joined
    assert "remote_id" in joined


def test_verify_baseline_schema_rejects_type_drift(pg_engine):
    """A16: a column type drifted from the baseline is rejected (the retired
    name-only verify accepted this database)."""
    _create_full_schema(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("ALTER TABLE accounts ALTER COLUMN email TYPE VARCHAR(64)"))
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    assert any("accounts" in e and "email" in e for e in errors)


def test_verify_baseline_schema_rejects_dropped_constraint(pg_engine):
    """A16: dropping a unique constraint is detected and rejected."""
    _create_full_schema(pg_engine)
    with pg_engine.connect() as conn:
        email_uq = next(
            uq["name"]
            for uq in inspect(conn).get_unique_constraints("accounts")
            if uq["column_names"] == ["email"]
        )
    with pg_engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE accounts DROP CONSTRAINT "{email_uq}"'))
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    assert errors != []


def test_verify_baseline_schema_rejects_dropped_column(pg_engine):
    """A16: a baseline database missing a column is rejected."""
    _create_full_schema(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("ALTER TABLE accounts DROP COLUMN display_name"))
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    assert any("display_name" in e for e in errors)


def test_conversion_rejects_drifted_legacy_schema_after_upgrade(pg_engine):
    """A legacy database whose remaining schema drifts from the baseline is
    refused by the post-upgrade full comparison (t077).

    Rewritten from ``test_conversion_rejects_drifted_legacy_schema_and_rolls_back``:
    the full compare_metadata check now runs after ``upgrade head`` against the
    head the ORM describes, not inside the conversion transaction against an
    earlier-revision catalog. Conversion and upgrade are therefore committed
    before the check, so the old "zero writes / untouched" assertion no longer
    holds; the invariant is that the drift is caught and the database is not
    accepted as healthy.
    """

    db_url = _schema_url(pg_engine)
    _create_0030_schema(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("ALTER TABLE accounts ALTER COLUMN email TYPE VARCHAR(64)"))

    with pytest.raises(SchemaValidationError, match="does not match the unified baseline"):
        run_migration(db_url)

    with pg_engine.connect() as conn:
        # The drift survives and the full comparison still rejects it, so a
        # later run cannot silently accept the database as healthy.
        assert verify_baseline_schema(conn)


def test_run_migration_rejects_empty_database(pg_engine):
    """退役理由：原 test_run_migration_rejects_incomplete_schema 把空库断言为
    『Database schema verification failed』（旧实现的缺 critical 表分支）。统一分类后
    空库归类 EMPTY_DATABASE，离线明确提示走启动/Alembic、不建表、不盖印。"""
    db_url = _schema_url(pg_engine)
    with pytest.raises(SchemaValidationError, match="empty") as excinfo:
        run_migration(db_url)
    assert "alembic upgrade head" in str(excinfo.value)
    _assert_no_version_stamp(db_url)


def test_stamp_unified_baseline_creates_table_and_sets_revision(pg_engine):
    stamp_unified_baseline(pg_engine, dry_run=False)

    with pg_engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_stamp_unified_baseline_dry_run_leaves_table_empty(pg_engine):
    stamp_unified_baseline(pg_engine, dry_run=True)

    with pg_engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'alembic_version')"
        )).scalar()
        assert exists is False


def test_stamp_unified_baseline_overwrites_prior_revision(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))

    stamp_unified_baseline(pg_engine, dry_run=False)

    with pg_engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [UNIFIED_BASELINE_REVISION]


def test_no_version_full_schema_refused_by_both_entries(pg_engine, monkeypatch):
    """退役理由：原 test_run_migration_success_flow 断言『无版本 + 全 32 表 → 成功
    stamp』，固化了离线/启动双入口的行为分歧。统一分类后该状态为
    NO_VERSION_WITH_BUSINESS_TABLES，两个入口一律拒绝、不盖印。"""
    db_url = _schema_url(pg_engine)
    _create_full_schema(pg_engine)

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


def test_main_cli_returns_expected_exit_codes(pg_engine):
    db_url = _schema_url(pg_engine)

    # 1. Missing URL -> 2
    with patch.dict("os.environ", {}, clear=True):
        assert main([]) == 2

    # 2. Empty schema: the offline tool refuses and points to startup/Alembic -> 1
    assert main(["--database-url", db_url]) == 1

    # 3. No version + full 32 tables: refused -> 1 (retired: old case expected a success stamp)
    _create_full_schema(pg_engine)
    assert main(["--database-url", db_url]) == 1

    # 4. At the unified baseline (full schema + baseline version) -> 0
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:rev)"),
            {"rev": CURRENT_HEAD_REVISION},
        )
    assert main(["--database-url", db_url]) == 0


def test_real_0030_shape_upgrades_to_head_with_forward_data_mapping(pg_engine):
    """A faithful 0030 shape (``accounts.sync_status``) upgrades to head
    through the offline entry, with legacy status values mapped forward (t077).

    Rewritten from ``test_migrate_from_0030_legacy_database_success``: the
    legacy fixture is now the real 0001 baseline instead of the current ORM,
    and the offline entry replays the incremental 0002 revision rather than
    merely stamping 0001. The old "version == UNIFIED_BASELINE_REVISION"
    assertion is therefore replaced by the full head-upgrade contract.
    """

    db_url = _schema_url(pg_engine)
    _create_0030_schema(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, email, provider, sync_status) "
                "VALUES (:acc, 'dead-credential@example.test', 'imap', 'auth_failed')"
            ),
            {"acc": uuid.uuid4()},
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, email, provider, sync_status) "
                "VALUES (:acc, 'broken-link@example.test', 'imap', 'failed')"
            ),
            {"acc": uuid.uuid4()},
        )

    ret = main(["--database-url", db_url])
    assert ret == 0

    with pg_engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "folder_patrol_status" in tables

        row = conn.execute(
            text("SELECT folder_id, last_status, last_probe_failures, last_probe_at FROM folder_patrol_status")
        ).fetchone()
        assert row is not None
        assert row[0] == _FOLDER_ID
        status_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        assert status_data == {"folder_path": "/Inbox", "uidvalidity": 12345}
        assert row[2] == 3
        assert row[3] is not None

        cp_row = conn.execute(
            text("SELECT cursor FROM sync_checkpoints WHERE folder_id = :fid"),
            {"fid": _FOLDER_ID},
        ).fetchone()
        assert cp_row is not None
        cur_data = json.loads(cp_row[0]) if isinstance(cp_row[0], str) else cp_row[0]
        assert "last_status" not in cur_data
        assert "last_probe_at" not in cur_data
        assert "last_probe_failures" not in cur_data
        assert cur_data.get("delta_token") == "token-xyz"

        # The offline entry replays 0002: full head schema + forward mapping.
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        assert versions == [CURRENT_HEAD_REVISION]
        account_columns = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='accounts' AND table_schema=current_schema()"
                )
            )
        }
        assert "sync_status" not in account_columns
        assert {"credential_state", "connectivity_state", "sync_activity"} <= account_columns

        dead = conn.execute(
            text(
                "SELECT credential_state, sync_enabled FROM accounts "
                "WHERE email='dead-credential@example.test'"
            )
        ).one()
        assert dead == ("invalid", False)
        broken = conn.execute(
            text(
                "SELECT credential_state, connectivity_state FROM accounts "
                "WHERE email='broken-link@example.test'"
            )
        ).one()
        assert broken == ("valid", "degraded")


def test_run_migration_refuses_unknown_revision_with_zero_writes(pg_engine):
    """退役理由：原用例断言『Refusing to stamp unified baseline』（旧实现把
    unknown revision + 缺表 归入缺 critical 表分支的措辞）。统一分类后 unknown
    revision 一律按 UNKNOWN_REVISION 拒绝、不盖印、零写入。"""
    db_url = _schema_url(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))

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


def test_stamp_refuses_to_overwrite_unknown_revision(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('some_future_head')"))

    with pytest.raises(SchemaValidationError, match="Refusing to overwrite"):
        stamp_unified_baseline(pg_engine, dry_run=False)

    with pg_engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == ["some_future_head"]


def test_stamp_is_noop_when_already_at_baseline(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:rev)"),
            {"rev": UNIFIED_BASELINE_REVISION},
        )

    stamp_unified_baseline(pg_engine, dry_run=False)

    with pg_engine.connect() as conn:
        versions = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == [UNIFIED_BASELINE_REVISION]


# Retired (A16): test_verify_schema_exempt_tables_only_skips_named_table and
# test_verify_schema_exempt_table_still_checks_columns_when_present exercised
# verify_database_schema(exempt_tables=...), which A16 deleted together with
# REQUIRED_COLUMNS. The surviving intent of the second test — an existing but
# incomplete folder_patrol_status is reported with its missing columns — is
# covered by the narrow-conversion precondition check (see
# test_dry_run_reports_missing_columns_on_existing_patrol_table).


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
def test_run_migration_refuses_unsupported_legacy_database(pg_engine, dry_run):
    """A15 semantics: 20261027_0029 is a known legacy revision outside the
    narrow-conversion set, so it is refused at classification time as
    LEGACY_UNSUPPORTED (previously it reached the narrow schema check and
    failed there on missing tables). Zero writes either way."""
    db_url = _schema_url(pg_engine)
    legacy_cursor = json.dumps({"last_status": "ok", "delta_token": "keep-me"})
    folder_id = uuid.uuid4()
    with pg_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261027_0029')"))
        conn.execute(text("CREATE TABLE folders (id UUID PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE sync_checkpoints ("
                "folder_id UUID PRIMARY KEY, cursor JSONB NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO folders (id) VALUES (:fid)"), {"fid": folder_id})
        conn.execute(
            text(
                "INSERT INTO sync_checkpoints (folder_id, cursor) "
                "VALUES (:fid, CAST(:cur AS jsonb))"
            ),
            {"fid": folder_id, "cur": legacy_cursor},
        )

    with pytest.raises(SchemaValidationError, match="not supported") as excinfo:
        run_migration(db_url, dry_run=dry_run)
    assert "20261027_0029" in str(excinfo.value)
    assert "historical kkmail release" in str(excinfo.value)
    assert "Restore the pre-upgrade sealed backup" in str(excinfo.value)

    with pg_engine.connect() as conn:
        assert "folder_patrol_status" not in set(inspect(conn).get_table_names())
        assert conn.execute(
            text("SELECT cursor FROM sync_checkpoints")
        ).scalar_one() == json.loads(legacy_cursor)
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all() == ["20261027_0029"]


def test_dry_run_reports_missing_columns_on_existing_patrol_table(pg_engine):
    db_url = _schema_url(pg_engine)
    _create_0030_schema(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("CREATE TABLE folder_patrol_status (folder_id UUID PRIMARY KEY)"))

    with pytest.raises(SchemaValidationError, match="not supported") as excinfo:
        run_migration(db_url, dry_run=True)
    msg = str(excinfo.value)
    assert "folder_patrol_status" in msg
    assert "missing required columns" in msg
    assert "last_probe_failures" in msg


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
def test_plan_migration_two_entries_agree_on_classification(pg_engine, state, expected_action):
    """Both entries classify with the single production revision_context().

    A1 removed the hand-built startup context: mail_core.__main__.run_migrations
    and baseline.run_migration now both obtain their context from
    baseline.revision_context(), which reads the real Alembic ScriptDirectory.
    Contexts built from that single source must classify the same database
    state identically, so the two entries cannot diverge.
    """
    _build_state(pg_engine, state)
    startup_ctx = revision_context()
    offline_ctx = revision_context()
    with pg_engine.connect() as conn:
        db_state = read_database_state(conn)
    startup_plan = plan_migration(db_state, context=startup_ctx)
    offline_plan = plan_migration(db_state, context=offline_ctx)
    assert startup_plan.action == expected_action
    assert offline_plan.action == expected_action
    assert startup_plan.action == offline_plan.action


def test_verify_baseline_schema_never_exempts_health_columns(pg_engine):
    """A 0001-shaped catalog must report all four column differences.

    Regression guard for t077 AC-001: if a column-level exemption were ever
    reintroduced, every conversion test could go green on a forged shape and
    this one must go red. ``verify_baseline_schema`` has no exemption switch;
    it compares against the head ORM unconditionally.
    """

    from alembic import command
    from mail_core.db.baseline import UNIFIED_BASELINE_REVISION, alembic_config

    cfg = alembic_config()
    cfg.set_main_option("sqlalchemy.url", _schema_url(pg_engine).replace("%", "%%"))
    command.upgrade(cfg, UNIFIED_BASELINE_REVISION)
    with pg_engine.connect() as conn:
        errors = verify_baseline_schema(conn)
    joined = "\n".join(errors)
    assert "sync_status" in joined
    assert "credential_state" in joined
    assert "connectivity_state" in joined
    assert "sync_activity" in joined


def test_offline_upgrade_to_head_from_0001_baseline(pg_engine):
    """UPGRADE_TO_HEAD via the offline entry replays 0002 and verifies.

    The offline tool no longer refuses an earlier known revision; it replays
    the incremental Alembic chain, then runs the full ORM comparison.
    """

    from alembic import command
    from mail_core.db.baseline import UNIFIED_BASELINE_REVISION, alembic_config

    db_url = _schema_url(pg_engine)
    cfg = alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    command.upgrade(cfg, UNIFIED_BASELINE_REVISION)
    with pg_engine.connect() as conn:
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == UNIFIED_BASELINE_REVISION

    assert main(["--database-url", db_url]) == 0
    with pg_engine.connect() as conn:
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == CURRENT_HEAD_REVISION
        assert verify_baseline_schema(conn) == []
        columns = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='accounts' AND table_schema=current_schema()"
                )
            )
        }
        assert "sync_status" not in columns
        assert {"credential_state", "connectivity_state", "sync_activity"} <= columns
