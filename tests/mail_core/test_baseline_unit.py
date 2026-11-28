"""Non-PG unit tests for the unified-baseline planner helpers.

These exercise the pure classification / context logic in
``mail_core.db.baseline`` without a database, so they run everywhere. The
PostgreSQL-gated suites live in
``tests/scripts/test_migrate_to_unified_baseline.py`` and
``tests/mail_core/test_migration_validation.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mail_core.db import baseline
from mail_core.db.baseline import UNIFIED_BASELINE_REVISION


def _write_revision(versions: Path, filename: str, revision: str, down: str | None) -> None:
    (versions / filename).write_text(
        f'revision = "{revision}"\ndown_revision = {down!r}\n',
        encoding="utf-8",
    )


def _config_for(tree: Path):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(tree))
    return cfg


def test_revision_context_matches_shipped_tree():
    ctx = baseline.revision_context()
    assert {UNIFIED_BASELINE_REVISION, baseline.CURRENT_HEAD_REVISION} <= ctx.known_revisions
    assert ctx.heads == (baseline.CURRENT_HEAD_REVISION,)
    assert ctx.legacy_revisions == baseline.NARROW_CONVERSION_LEGACY_REVISIONS
    assert ctx.known_legacy_revisions == (
        baseline.KNOWN_LEGACY_REVISIONS - baseline.NARROW_CONVERSION_LEGACY_REVISIONS
    )


def test_revision_context_sees_extra_revision_in_temp_tree(tmp_path):
    """A tree with one more revision: the single context constructor sees it.

    Regression shape for adoption A1: the retired ``offline_revision_context``
    hardcoded ``{UNIFIED_BASELINE_REVISION}``, so once a second revision is
    added the offline entry would classify the new head as unknown while the
    startup entry saw it. Both entries now build their context through
    ``revision_context()``, so both see the same sets.
    """
    versions = tmp_path / "versions"
    versions.mkdir()
    _write_revision(
        versions, "20261107_0001_unified_baseline.py", UNIFIED_BASELINE_REVISION, None
    )
    _write_revision(
        versions, "20261201_0002_next.py", "20261201_0002", UNIFIED_BASELINE_REVISION
    )

    ctx = baseline.revision_context(_config_for(tmp_path))
    assert ctx.known_revisions == frozenset(
        {UNIFIED_BASELINE_REVISION, "20261201_0002"}
    )
    assert ctx.heads == ("20261201_0002",)


def test_offline_revision_context_is_gone():
    assert not hasattr(baseline, "offline_revision_context")


def test_startup_entry_delegates_to_shared_executor():
    """t099: the startup entry must not hand-copy migration orchestration.

    ``run_migrations`` is a thin adapter over ``baseline.execute_migration``
    (the single executor the offline entry also uses, which owns state
    reading via ``baseline.read_database_state``), so check, connection
    release and write dispatch cannot diverge between entries.

    Retires ``test_startup_entry_reads_state_via_baseline_helper`` (A2): its
    source assertion pinned ``run_migrations``' own call to
    ``baseline.read_database_state(conn)``; the unified executor moved that
    call into ``baseline.execute_migration``, so the old shape no longer
    exists to assert. The A2 invariant (no hand-copied state reading in the
    startup entry) is preserved in the stronger form asserted here.
    """
    import inspect as py_inspect

    from mail_core import __main__ as main_module

    src = py_inspect.getsource(main_module.run_migrations)
    assert "baseline.execute_migration" in src
    assert "create_engine" not in src
    assert "SELECT version_num FROM alembic_version" not in src


def _plan_for(revision: str, *, context: baseline.RevisionContext | None = None):
    ctx = context or baseline.revision_context()
    state = baseline.DatabaseState(
        version_rows=(revision,), table_names=frozenset()
    )
    return baseline.plan_migration(state, context=ctx)


def test_plan_newer_than_code_for_future_dated_revision():
    """A3: a dated revision beyond every head is its own classification.

    It must not fall into UNKNOWN_REVISION, whose message advised restoring
    a known-good backup — following that advice against a newer database
    would discard newer data.
    """
    plan = _plan_for("20261201_0001")
    assert plan.action is baseline.MigrationAction.NEWER_THAN_CODE
    assert "newer version of kkmail" in plan.message
    assert "Do NOT overwrite" in plan.message


def test_plan_newer_than_code_requires_greater_than_all_heads():
    ctx = baseline.RevisionContext(
        known_revisions=frozenset({"20261107_0001", "20270101_0001"}),
        legacy_revisions=frozenset(),
        heads=("20261107_0001", "20270101_0001"),
    )
    plan = _plan_for("20261201_0001", context=ctx)
    assert plan.action is baseline.MigrationAction.UNKNOWN_REVISION


def test_plan_unknown_for_dated_revision_that_never_existed():
    """A15: the deleted legacy tree is enumerated explicitly; a dated string
    that was never a real revision is UNKNOWN, not LEGACY."""
    plan = _plan_for("20200101_0001")
    assert plan.action is baseline.MigrationAction.UNKNOWN_REVISION


@pytest.mark.parametrize("revision", ["20261031_0030", "20261107_0031"])
def test_plan_legacy_for_narrow_supported_revisions(revision):
    plan = _plan_for(revision)
    assert plan.action is baseline.MigrationAction.LEGACY


@pytest.mark.parametrize(
    "revision",
    ["20261020_0001", "f5f312751c77", "20261021_0005", "20261027_0029"],
)
def test_plan_legacy_unsupported_for_other_known_revisions(revision):
    plan = _plan_for(revision)
    assert plan.action is baseline.MigrationAction.LEGACY_UNSUPPORTED
    assert "historical kkmail release" in plan.message


def test_every_enumerated_legacy_revision_classifies():
    """The full Git-history enumeration: each of the 31 old revisions is
    either narrow-supported (LEGACY) or known-but-unsupported."""
    assert len(baseline.KNOWN_LEGACY_REVISIONS) == 31
    assert (
        baseline.NARROW_CONVERSION_LEGACY_REVISIONS
        <= baseline.KNOWN_LEGACY_REVISIONS
    )
    for revision in baseline.KNOWN_LEGACY_REVISIONS:
        plan = _plan_for(revision)
        expected = (
            baseline.MigrationAction.LEGACY
            if revision in baseline.NARROW_CONVERSION_LEGACY_REVISIONS
            else baseline.MigrationAction.LEGACY_UNSUPPORTED
        )
        assert plan.action is expected, revision


def test_is_legacy_revision_is_set_membership_only():
    assert baseline.is_legacy_revision("f5f312751c77") is True
    assert baseline.is_legacy_revision("20261031_0030") is True
    assert baseline.is_legacy_revision("20200101_0001") is False
    assert baseline.is_legacy_revision("20261201_0001") is False
    assert baseline.is_legacy_revision("20261107_0001") is False
    assert baseline.is_legacy_revision(None) is False
    assert baseline.is_legacy_revision("") is False


def test_required_tables_match_orm_metadata():
    """A16: REQUIRED_TABLES (planner business-table detection) and the ORM
    metadata (schema truth) must name the same 32 tables."""
    assert baseline.REQUIRED_TABLES == frozenset(baseline._baseline_metadata().tables)


def test_baseline_diff_filter_ignores_only_registered_raw_sql_objects():
    """A16: the compare_metadata exclusion list covers exactly the raw-SQL
    objects of the baseline migration — nothing else is ignored."""
    from sqlalchemy import Column, Index, Integer, MetaData, Table

    metadata = MetaData()
    table = Table(
        "message_search", metadata, Column("message_id", Integer, primary_key=True)
    )
    document = Column("document", Integer)
    assert (
        baseline._is_ignored_baseline_diff(
            ("remove_column", None, "message_search", document)
        )
        is True
    )
    assert (
        baseline._is_ignored_baseline_diff(
            ("remove_column", None, "message_search", Column("subject", Integer))
        )
        is False
    )
    assert (
        baseline._is_ignored_baseline_diff(
            ("remove_index", Index("ix_message_search_document", table.c.message_id))
        )
        is True
    )
    assert (
        baseline._is_ignored_baseline_diff(
            ("remove_index", Index("ix_unregistered", table.c.message_id))
        )
        is False
    )
    assert baseline._is_ignored_baseline_diff(("add_table", table)) is False
    assert not hasattr(baseline, "REQUIRED_COLUMNS")
    assert not hasattr(baseline, "_column_affinity")
    assert not hasattr(baseline, "verify_database_schema")


def test_describe_diff_names_table_and_column():
    from sqlalchemy import Column, String

    message = baseline._describe_diff(
        ("add_column", None, "accounts", Column("recipient_addresses", String))
    )
    assert "accounts" in message and "recipient_addresses" in message
    modify = baseline._describe_diff(
        ("modify_type", None, "accounts", "email", {}, "VARCHAR(64)", "VARCHAR(320)")
    )
    assert "accounts" in modify and "email" in modify


def test_verify_for_plan_dispatches_by_action(monkeypatch):
    """A14: one dispatch maps each actionable plan to its verification;
    both entries call it, so their verdicts cannot diverge."""
    calls: list[str] = []
    monkeypatch.setattr(
        baseline, "verify_baseline_schema", lambda conn: calls.append("full") or ["e1"]
    )
    monkeypatch.setattr(
        baseline,
        "verify_narrow_legacy_schema",
        lambda conn: calls.append("narrow") or ["e2"],
    )

    def plan(action: baseline.MigrationAction) -> baseline.MigrationPlan:
        return baseline.MigrationPlan(action=action)

    assert baseline.verify_for_plan(None, plan(baseline.MigrationAction.AT_BASELINE)) == ["e1"]
    assert baseline.verify_for_plan(None, plan(baseline.MigrationAction.LEGACY)) == ["e2"]
    assert baseline.verify_for_plan(None, plan(baseline.MigrationAction.EMPTY_DATABASE)) == []
    assert baseline.verify_for_plan(None, plan(baseline.MigrationAction.UNKNOWN_REVISION)) == []
    assert calls == ["full", "narrow"]


class _ExecutorRig:
    """Wire ``execute_migration`` to in-memory collaborators (no database).

    The check connection is a sentinel: the rig records the order in which
    the read-only context exits and the write collaborators are entered, so
    tests can assert the release-before-write invariant structurally.
    """

    def __init__(self, monkeypatch, state: baseline.DatabaseState):
        from contextlib import contextmanager

        self.events: list[str] = []
        self.upgrades: list[str] = []
        self.upgrade_and_verify: list[str] = []
        self.conversions: list[str] = []
        events = self.events

        @contextmanager
        def fake_read_only(url):
            events.append("check_open")
            try:
                yield object()
            finally:
                events.append("check_closed")

        monkeypatch.setattr(baseline, "read_only_connection", fake_read_only)
        monkeypatch.setattr(
            baseline, "read_database_state", lambda conn: state
        )
        monkeypatch.setattr(baseline, "verify_for_plan", lambda conn, plan: [])
        monkeypatch.setattr(
            "alembic.command.upgrade",
            lambda cfg, rev: (events.append("upgrade"), self.upgrades.append(rev)),
        )
        monkeypatch.setattr(
            baseline,
            "upgrade_head_and_verify",
            lambda url: (
                events.append("upgrade_head_and_verify"),
                self.upgrade_and_verify.append(url),
            ),
        )
        monkeypatch.setattr(
            baseline,
            "apply_narrow_legacy_conversion",
            lambda url: (events.append("conversion"), self.conversions.append(url), "converted")[2],
        )


def _state(*version_rows: str, tables: frozenset[str] = frozenset()) -> baseline.DatabaseState:
    return baseline.DatabaseState(version_rows=tuple(version_rows), table_names=tables)


def test_executor_empty_database_write_dispatch_depends_on_policy(monkeypatch):
    """t099: startup initializes an empty database; the offline entry refuses it."""
    rig = _ExecutorRig(monkeypatch, _state())
    plan = baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.STARTUP_POLICY
    )
    assert plan.action is baseline.MigrationAction.EMPTY_DATABASE
    assert rig.upgrades == ["head"]
    assert rig.events == ["check_open", "check_closed", "upgrade"]

    rig = _ExecutorRig(monkeypatch, _state())
    with pytest.raises(baseline.SchemaValidationError, match="empty"):
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
        )
    assert rig.upgrades == []


def test_executor_check_modes_never_dispatch_writes(monkeypatch):
    """t099: CHECK_ONLY / DRY_RUN stop after the check phase for every plan."""
    rig = _ExecutorRig(monkeypatch, _state("20261031_0030"))
    plan = baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.CHECK_ONLY, policy=baseline.STARTUP_POLICY
    )
    assert plan.action is baseline.MigrationAction.LEGACY
    assert rig.events == ["check_open", "check_closed"]
    assert rig.conversions == [] and rig.upgrades == [] and rig.upgrade_and_verify == []


def test_executor_refusal_actions_raise_plan_message(monkeypatch):
    rig = _ExecutorRig(monkeypatch, _state("unknown_rev_9999"))
    with pytest.raises(baseline.SchemaValidationError, match="unrecognized"):
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.STARTUP_POLICY
        )
    assert rig.events == ["check_open", "check_closed"]


def test_executor_legacy_verification_error_wording_is_per_entry(monkeypatch):
    """t099: a failed narrow-conversion precondition check keeps each
    entry's operator wording, produced by the entry's policy."""
    rig = _ExecutorRig(monkeypatch, _state("20261031_0030"))
    monkeypatch.setattr(baseline, "verify_for_plan", lambda conn, plan: ["some drift"])
    with pytest.raises(
        baseline.SchemaValidationError, match="narrow conversion"
    ) as startup_exc:
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.STARTUP_POLICY
        )
    assert "matching historical release" in str(startup_exc.value)

    with pytest.raises(
        baseline.SchemaValidationError, match="offline tool cannot reconstruct"
    ):
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
        )
    assert rig.conversions == []


def test_executor_legacy_conversion_error_wrapping_is_per_entry(monkeypatch):
    """t099: startup wraps a conversion SchemaValidationError as a rolled-back
    RuntimeError; the offline entry propagates it unchanged."""
    rig = _ExecutorRig(monkeypatch, _state("20261031_0030"))

    def _fail(url):
        raise baseline.SchemaValidationError("conversion precondition lost")

    monkeypatch.setattr(baseline, "apply_narrow_legacy_conversion", _fail)
    with pytest.raises(RuntimeError, match="rolled back") as startup_exc:
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.STARTUP_POLICY
        )
    assert isinstance(startup_exc.value.__cause__, baseline.SchemaValidationError)

    with pytest.raises(baseline.SchemaValidationError, match="precondition lost"):
        baseline.execute_migration(
            "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
        )
    assert rig.upgrade_and_verify == []


def test_executor_write_dispatch_by_action(monkeypatch):
    """t099: AT_BASELINE replays the chain for startup and re-stamps for the
    offline entry; UPGRADE_TO_HEAD and LEGACY go through
    upgrade_head_and_verify (LEGACY after the narrow conversion), always
    after the check connection closed."""
    rig = _ExecutorRig(monkeypatch, _state(baseline.CURRENT_HEAD_REVISION))
    baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.STARTUP_POLICY
    )
    assert rig.upgrades == ["head"]
    assert rig.upgrade_and_verify == []

    stamps: list[str] = []
    rig = _ExecutorRig(monkeypatch, _state(baseline.CURRENT_HEAD_REVISION))
    monkeypatch.setattr(baseline, "_stamp_at_baseline", lambda url: stamps.append(url))
    baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
    )
    assert rig.upgrades == []
    assert stamps == ["postgresql://x"]

    rig = _ExecutorRig(monkeypatch, _state(UNIFIED_BASELINE_REVISION))
    baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
    )
    assert rig.upgrades == []
    assert rig.upgrade_and_verify == ["postgresql://x"]

    rig = _ExecutorRig(monkeypatch, _state("20261031_0030"))
    baseline.execute_migration(
        "postgresql://x", mode=baseline.MigrationMode.WRITE, policy=baseline.OFFLINE_POLICY
    )
    assert rig.conversions == ["postgresql://x"]
    assert rig.upgrade_and_verify == ["postgresql://x"]
    assert rig.events == [
        "check_open",
        "check_closed",
        "conversion",
        "upgrade_head_and_verify",
    ]


def test_testing_doc_baseline_gate_describes_a16_full_comparison():
    doc = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "blueprint"
        / "testing.md"
    ).read_text(encoding="utf-8")
    start = doc.index("## 数据库迁移与结构一致性门禁")
    end = doc.index("\n## ", start + 1)
    section = doc[start:end]

    assert "verify_database_schema" not in section
    assert "仅表名与关键列名" not in section
    assert "两者都不做与统一基线完整 catalog 的等价校验" not in section
    assert "verify_baseline_schema" in section
    assert "compare_metadata" in section
    assert hasattr(baseline, "verify_baseline_schema")
    assert not hasattr(baseline, "verify_database_schema")
