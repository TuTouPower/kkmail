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
