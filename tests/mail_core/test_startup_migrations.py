"""Startup migration orchestration tests (single guarded entry).

Covers ``mail_core.__main__.run_migrations`` and the ``--migrate-only`` /
``--check-migrations`` flags against isolated PostgreSQL schemas. Each case
creates a unique schema whose search_path is pinned through the connection URL
(``options=-csearch_path=<schema>``), so every connection the production
planner opens lands in that schema and the shared at-head public schema is
never touched. The production migration and ORM qualify their pg_trgm
opclasses as ``public.gin_trgm_ops``, so no other schema is needed on the
path and ``current_schema()``, ``inspect`` and ``compare_metadata`` see only
the isolated schema.

The 0030 legacy shape is derived from the historical 0001 baseline --
``alembic upgrade 20261107_0001`` -- minus ``folder_patrol_status``, so the
fixture faithfully represents the real legacy input (``accounts.sync_status``,
none of the three health columns). Full compare_metadata verification runs
only after the incremental upgrade to head, never against the earlier-revision
catalog. The object under test is the conversion logic (table creation, patrol
data migration, stamping, idempotency, concurrent serialization, failed-
conversion rollback); forging the shape from ``upgrade head`` would make those
assertions vacuous, so each fixture asserts its historical shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

from alembic.command import upgrade as _alembic_upgrade
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from mail_core import __main__ as main_module
from mail_core.db import baseline
from mail_core.db.baseline import SchemaValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(REPO_ROOT / "src")

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
def pg_schema():
    """Yield a factory returning (schema, schema-scoped URL); drop every schema at teardown.

    The search_path is pinned to ``<schema>`` alone. The production migration
    and ORM qualify their pg_trgm opclasses as ``public.gin_trgm_ops``, so
    unqualified DDL, ``current_schema()``, ``inspect`` and ``compare_metadata``
    act only on the isolated schema; public is never visible to a fixture.
    """
    base_url = os.environ["MAIL_CORE_DATABASE_URL"]
    admin = create_engine(base_url)
    created: list[str] = []

    def _new() -> tuple[str, str]:
        schema = "startup_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(base_url).update_query_dict(
            {"options": f"-csearch_path={schema}"}
        ).render_as_string(hide_password=False)
        created.append(schema)
        return schema, url

    try:
        yield _new
    finally:
        with admin.begin() as conn:
            for schema in created:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def _make_0030_db(db_url: str, *, revision: str = "20261031_0030") -> str:
    """Build a faithful 0030 legacy shape from the historical 0001 baseline.

    The fixture must describe the real legacy input: the 0001 baseline DDL
    (``accounts.sync_status``, none of the three health columns) minus
    ``folder_patrol_status``, stamped with the historical revision. Deriving it
    from ``upgrade head`` would forge the new schema and make every conversion
    test vacuous. The real upgrade is invoked directly so fixture construction
    never depends on the mock installed over the startup path's own upgrade
    call.
    """
    cfg = baseline.alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
        _alembic_upgrade(cfg, baseline.UNIFIED_BASELINE_REVISION)
        with engine.begin() as conn:
            # Guard: the fixture must faithfully represent the historical
            # 0001 shape, never the current head (three health columns).
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
    """Read the schema through a PG inspector and normalize native types back to text.

    PostgreSQL returns UUID columns as uuid.UUID and JSONB columns as dict/list,
    whereas the frozen fixture assertions compare plain strings. Normalizing here
    keeps every assertion byte-for-byte identical to the retired SQLite fixture.
    """
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            insp = inspect(conn)
            tables = sorted(insp.get_table_names())
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
            return {"tables": tables, "revs": revs, "patrol": patrol, "cursors": cursors}
    finally:
        engine.dispose()


def _mock_upgrade(monkeypatch) -> list:
    """Record upgrade calls without replaying the Alembic chain.

    These cases assert the orchestration (conversion + upgrade call). The
    post-upgrade schema check is a separate collaborator covered by the
    real-PG cases, so it is stubbed here to keep the assertion focused.
    """

    calls: list = []
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, rev: calls.append(rev))
    monkeypatch.setattr(
        "mail_core.db.baseline.verify_upgraded_schema", lambda *a, **k: []
    )
    return calls


def test_t1_narrow_legacy_converts_inline(pg_schema, monkeypatch):
    """T1: narrow legacy (0030) converts inline through the startup path."""
    _, db_url = pg_schema()
    _make_0030_db(db_url)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    main_module.run_migrations()

    assert upgrades == ["head"]
    state = _snapshot(db_url)
    assert state["revs"] == [baseline.UNIFIED_BASELINE_REVISION]
    assert "folder_patrol_status" in state["tables"]
    assert len(state["patrol"]) == 1
    folder_id, last_status, failures = state["patrol"][0]
    assert folder_id == _FOLDER_ID
    assert json.loads(last_status) == {"folder_path": "/Inbox", "uidvalidity": 12345}
    assert failures == 3
    assert state["cursors"] == [(_FOLDER_ID, json.dumps({"delta_token": "token-xyz"}))]


def test_t2_unsupported_legacy_rejected_with_zero_changes(pg_schema, monkeypatch):
    """T2: legacy revision with missing tables is refused; tables/data/revision untouched.

    The sync_checkpoints cursor is JSONB (not TEXT as in the retired SQLite
    fixture): on PostgreSQL jsonb_typeof(text) aborts the read-only verification
    transaction before the refusal message can be produced.
    """
    _, db_url = pg_schema()
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261027_0029')"))
        conn.execute(text("CREATE TABLE folders (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE sync_checkpoints (folder_id VARCHAR(64) PRIMARY KEY, cursor JSONB)"))
        conn.execute(
            text("INSERT INTO sync_checkpoints (folder_id, cursor) VALUES ('f-1', '{\"a\": 1}')")
        )
    engine.dispose()
    before = _snapshot(db_url)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    with pytest.raises(RuntimeError) as excinfo:
        main_module.run_migrations()

    message = str(excinfo.value)
    assert "20261027_0029" in message
    assert "not supported" in message
    assert "Restore the pre-upgrade sealed backup" in message
    assert "do not re-run" in message
    assert _snapshot(db_url) == before
    assert upgrades == []


def test_t3_dry_run_and_check_reject_without_writes(pg_schema, monkeypatch):
    """T3: dry-run and --check paths refuse unknown revisions and incomplete structure; zero writes."""
    _, unknown_url = pg_schema()
    engine = create_engine(unknown_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))
    engine.dispose()
    before_unknown = _snapshot(unknown_url)
    with pytest.raises(SchemaValidationError):
        baseline.run_migration(unknown_url, dry_run=True)
    assert _snapshot(unknown_url) == before_unknown

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", unknown_url)
    with pytest.raises(RuntimeError) as excinfo:
        main_module.run_migrations(check_only=True)
    assert "not modified" in str(excinfo.value)
    assert _snapshot(unknown_url) == before_unknown

    _, incomplete_url = pg_schema()
    _make_0030_db(incomplete_url)
    engine = create_engine(incomplete_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE folder_patrol_status (folder_id VARCHAR(64) PRIMARY KEY)"))
    engine.dispose()
    before_incomplete = _snapshot(incomplete_url)
    with pytest.raises(SchemaValidationError, match="missing required columns"):
        baseline.run_migration(incomplete_url, dry_run=True)
    assert _snapshot(incomplete_url) == before_incomplete


def test_t4_failed_conversion_rolls_back_and_rerun_is_idempotent(pg_schema, monkeypatch):
    """T4: a mid-conversion failure rolls back DDL/data/revision; success then re-run is a no-op.

    PostgreSQL rolls back the whole conversion transaction (including the
    CREATE TABLE for folder_patrol_status), so the SQLite-only workaround that
    manually dropped the surviving DDL shell is retired: nothing to clean up
    before the successful re-run.
    """
    _, db_url = pg_schema()
    _make_0030_db(db_url)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    before = _snapshot(db_url)

    real_migrate = baseline.migrate_patrol_status_data

    def _boom(bind, *, dry_run: bool = False):
        real_migrate(bind, dry_run=dry_run)
        raise RuntimeError("injected mid-conversion failure")

    monkeypatch.setattr("mail_core.db.baseline.migrate_patrol_status_data", _boom)
    with pytest.raises(RuntimeError, match="injected mid-conversion failure"):
        main_module.run_migrations()
    after_failure = _snapshot(db_url)
    assert after_failure["revs"] == before["revs"]
    assert after_failure["cursors"] == before["cursors"]
    assert after_failure["patrol"] == []
    assert upgrades == []

    monkeypatch.setattr("mail_core.db.baseline.migrate_patrol_status_data", real_migrate)
    main_module.run_migrations()
    assert upgrades == ["head"]
    after_success = _snapshot(db_url)
    assert after_success["revs"] == [baseline.UNIFIED_BASELINE_REVISION]

    main_module.run_migrations()
    assert upgrades == ["head", "head"]
    assert _snapshot(db_url) == after_success


def test_t5_empty_head_and_incremental_never_stamp(pg_schema, monkeypatch):
    """T5: empty DB initializes via upgrade; at-head/normal revisions never stamp; versioned-with-tables refused."""
    _, empty_url = pg_schema()
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", empty_url)
    main_module.run_migrations()
    assert upgrades == ["head"]
    assert _snapshot(empty_url)["tables"] == []

    _, head_url = pg_schema()
    cfg = baseline.alembic_config()
    cfg.set_main_option("sqlalchemy.url", head_url.replace("%", "%%"))
    _alembic_upgrade(cfg, "head")
    before_head = _snapshot(head_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", head_url)
    main_module.run_migrations()
    assert upgrades == ["head", "head"]
    assert _snapshot(head_url) == before_head

    class _FakeScript:
        def get_heads(self):
            return ["20270101_0003"]

        def walk_revisions(self):
            return iter([
                SimpleNamespace(revision="20270101_0003"),
                SimpleNamespace(revision=baseline.CURRENT_HEAD_REVISION),
                SimpleNamespace(revision=baseline.UNIFIED_BASELINE_REVISION),
            ])

    monkeypatch.setattr(
        "alembic.script.ScriptDirectory",
        SimpleNamespace(from_config=staticmethod(lambda cfg: _FakeScript())),
    )
    main_module.run_migrations()
    assert upgrades == ["head", "head", "head"]
    assert _snapshot(head_url) == before_head

    _, orphans_url = pg_schema()
    engine = create_engine(orphans_url)
    # Orphan state: one business table and no alembic_version mark. By this
    # point T5 has stubbed ScriptDirectory, so this is a single inline table
    # rather than a baseline-derived shape.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE account_groups (id UUID PRIMARY KEY)"))
    engine.dispose()
    before_orphans = _snapshot(orphans_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", orphans_url)
    with pytest.raises(RuntimeError, match="no alembic_version mark"):
        main_module.run_migrations()
    assert _snapshot(orphans_url) == before_orphans
    assert upgrades == ["head", "head", "head"]


def test_t6_migrate_only_runs_without_server_or_worker(monkeypatch):
    """T6: --migrate-only executes even with SKIP_MIGRATIONS=1 and never starts server/worker."""
    db_url = os.environ["MAIL_CORE_DATABASE_URL"]
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    monkeypatch.delenv("MAIL_CORE_PORT", raising=False)
    monkeypatch.delenv("MAIL_CORE_HOST", raising=False)
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    monkeypatch.setenv("MAIL_CORE_SKIP_MIGRATIONS", "1")

    calls: list = []
    monkeypatch.setattr(
        "mail_core.__main__.run_migrations",
        lambda *, check_only=False: calls.append(check_only),
    )

    import threading as threading_module

    def _no_thread(*args, **kwargs):
        raise AssertionError("worker thread must not start for --migrate-only")

    monkeypatch.setattr(threading_module, "Thread", _no_thread)

    import sys as _sys
    from types import ModuleType

    bomb = ModuleType("uvicorn")
    def _bomb_getattr(name):
        raise AssertionError("uvicorn must not be touched for --migrate-only")
    bomb.__getattr__ = _bomb_getattr  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "uvicorn", bomb)

    assert main_module.main(["--migrate-only"]) == 0
    assert calls == [False]


def test_t6_migrate_only_and_check_are_mutually_exclusive():
    """T6: argparse rejects combining both gate flags without touching any database."""
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": SRC_DIR,
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mail_core", "--migrate-only", "--check-migrations"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 2


def test_t7_check_migrations_exit_codes_and_zero_writes(pg_schema, monkeypatch):
    """T7: --check-migrations reports pass/fail for the same fixtures with zero writes."""
    _, good_url = pg_schema()
    _make_0030_db(good_url)
    before_good = _snapshot(good_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", good_url)
    assert main_module.main(["--check-migrations"]) == 0
    assert _snapshot(good_url) == before_good

    _, bad_url = pg_schema()
    engine = create_engine(bad_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))
    engine.dispose()
    before_bad = _snapshot(bad_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", bad_url)
    with pytest.raises(RuntimeError):
        main_module.main(["--check-migrations"])
    assert _snapshot(bad_url) == before_bad


def test_t7_check_migrations_clean_subprocess_zero_writes(pg_schema):
    """T7: --check-migrations in a clean subprocess env (only DATABASE_URL + SKIP=1) exits 0 with zero writes."""
    _, db_url = pg_schema()
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": SRC_DIR,
        "HOME": os.environ.get("HOME", "/tmp"),
        "MAIL_CORE_DATABASE_URL": db_url,
        "MAIL_CORE_SKIP_MIGRATIONS": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mail_core", "--check-migrations"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            assert inspect(conn).get_table_names() == []
    finally:
        engine.dispose()


def test_both_entries_delegate_to_single_planner(pg_schema, monkeypatch):
    """Both entries classify through baseline.plan_migration, not their own judgement."""
    _, empty_url = pg_schema()
    calls: list[object] = []
    real_plan = baseline.plan_migration

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("context"))
        return real_plan(*args, **kwargs)

    monkeypatch.setattr("mail_core.db.baseline.plan_migration", _spy)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", empty_url)

    main_module.run_migrations()
    with pytest.raises(baseline.SchemaValidationError):
        baseline.run_migration(empty_url, dry_run=True)

    assert len(calls) == 2
    assert upgrades == ["head"]


def test_t8_drifted_baseline_refused_by_all_three_entries(pg_schema, monkeypatch):
    """A14: a baseline-stamped database whose schema drifted (one dropped
    column) is refused identically by the startup check, normal startup and
    the offline tool; undrifted, all three accept it."""
    _, db_url = pg_schema()
    import mail_core.mail.storage  # noqa: F401  (populates Base.metadata)
    from mail_core.db.base import Base

    engine = create_engine(db_url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE alembic_version ("
                    "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(
                text("INSERT INTO alembic_version VALUES (:rev)"),
                {"rev": baseline.CURRENT_HEAD_REVISION},
            )
    finally:
        engine.dispose()

    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    # Undrifted baseline: the startup check and the offline tool accept it.
    main_module.run_migrations(check_only=True)
    baseline.run_migration(db_url)

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE accounts DROP COLUMN display_name"))
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="display_name"):
        main_module.run_migrations(check_only=True)
    with pytest.raises(RuntimeError, match="display_name"):
        main_module.run_migrations()
    assert upgrades == []
    with pytest.raises(SchemaValidationError, match="display_name"):
        baseline.run_migration(db_url)


def test_t7_older_baseline_upgrades_in_place_with_data_mapping(pg_schema, monkeypatch):
    """A database stamped at the unified baseline is upgraded to head by
    startup, preserving accounts and mapping legacy sync_status values (t076).
    """

    _, db_url = pg_schema()
    cfg = baseline.alembic_config()
    cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    # Build only the historical baseline (accounts.sync_status present).
    _alembic_upgrade(cfg, baseline.UNIFIED_BASELINE_REVISION)

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_status, sync_enabled) "
                    "VALUES (:id, :email, 'imap', 'auth_failed', true)"
                ),
                {"id": uuid.uuid4(), "email": "old-auth@example.test"},
            )
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_status, sync_enabled) "
                    "VALUES (:id, :email, 'imap', 'failed', true)"
                ),
                {"id": uuid.uuid4(), "email": "old-failed@example.test"},
            )
    finally:
        engine.dispose()

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    # Real upgrade (no mock): startup must classify UPGRADE_TO_HEAD and apply
    # the incremental revision instead of refusing to start.
    main_module.run_migrations()

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            rev = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert rev == baseline.CURRENT_HEAD_REVISION
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'accounts' AND table_schema = current_schema()"
                    )
                )
            }
            assert "sync_status" not in columns
            assert {"credential_state", "connectivity_state", "sync_activity"} <= columns
            auth = conn.execute(
                text(
                    "SELECT credential_state, connectivity_state, sync_enabled "
                    "FROM accounts WHERE email = 'old-auth@example.test'"
                )
            ).one()
            assert auth == ("invalid", "connected", False)
            failed = conn.execute(
                text(
                    "SELECT credential_state, connectivity_state "
                    "FROM accounts WHERE email = 'old-failed@example.test'"
                )
            ).one()
            assert failed == ("valid", "degraded")
    finally:
        engine.dispose()


def test_t8_real_0030_legacy_shape_upgrades_via_startup(pg_schema, monkeypatch):
    """A faithful 0030 legacy shape (``accounts.sync_status``) upgrades to
    head through the startup entry with forward status mapping (t077 AC-004).

    Unlike the orchestration cases, no collaborator is mocked: the real
    conversion, the real incremental upgrade and the real post-upgrade schema
    check all run.
    """

    _, db_url = pg_schema()
    _make_0030_db(db_url)
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_status) "
                    "VALUES (:id, 'legacy-dead@example.test', 'imap', 'auth_failed')"
                ),
                {"id": uuid.uuid4()},
            )
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_status) "
                    "VALUES (:id, 'legacy-broken@example.test', 'imap', 'failed')"
                ),
                {"id": uuid.uuid4()},
            )
    finally:
        engine.dispose()

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    main_module.run_migrations()

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert rev == baseline.CURRENT_HEAD_REVISION
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='accounts' AND table_schema=current_schema()"
                    )
                )
            }
            assert "sync_status" not in columns
            assert {"credential_state", "connectivity_state", "sync_activity"} <= columns
            assert conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name='folder_patrol_status' AND table_schema=current_schema()"
                )
            ).scalar_one() == 1
            dead = conn.execute(
                text(
                    "SELECT credential_state, sync_enabled FROM accounts "
                    "WHERE email='legacy-dead@example.test'"
                )
            ).one()
            assert dead == ("invalid", False)
            broken = conn.execute(
                text(
                    "SELECT credential_state, connectivity_state FROM accounts "
                    "WHERE email='legacy-broken@example.test'"
                )
            ).one()
            assert broken == ("valid", "degraded")
    finally:
        engine.dispose()
