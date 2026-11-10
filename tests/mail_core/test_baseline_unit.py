"""Non-PG unit tests for the unified-baseline planner helpers.

These exercise the pure classification / context logic in
``mail_core.db.baseline`` without a database, so they run everywhere. The
PostgreSQL-gated suites live in
``tests/scripts/test_migrate_to_unified_baseline.py`` and
``tests/mail_core/test_migration_validation.py``.
"""

from __future__ import annotations

from pathlib import Path

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
    assert ctx.known_revisions == frozenset({UNIFIED_BASELINE_REVISION})
    assert ctx.heads == (UNIFIED_BASELINE_REVISION,)
    assert ctx.legacy_revisions == baseline.KNOWN_LEGACY_REVISIONS


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


def test_startup_entry_reads_state_via_baseline_helper():
    """A2: the startup entry must not hand-copy database-state reading.

    ``run_migrations`` delegates to ``baseline.read_database_state`` (the same
    reader the offline entry uses), so any future extension of the reader
    reaches both entries.
    """
    import inspect as py_inspect

    from mail_core import __main__ as main_module

    src = py_inspect.getsource(main_module.run_migrations)
    assert "baseline.read_database_state(conn)" in src
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
