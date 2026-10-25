"""Package C unit-mode coverage (R06/R08): schema shape, migration chain, and
settlement helpers that must be safe against minimal job test doubles.

PostgreSQL-backed lifecycle/competition behavior lives in
test_sync_execution_tracking.py and test_sync_execution_migration.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from mail_core.mail.storage.models import (
    SyncCheckpoint,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.execution import _successor_is_periodic, settle_job_bindings

ROOT = Path(__file__).resolve().parents[2]


def test_worker_job_execution_generation_is_unique_and_non_null():
    column = WorkerJob.__table__.c.execution_generation
    assert column.nullable is False
    assert column.unique is True


def test_sync_checkpoint_scan_generation_is_nullable_uuid():
    column = SyncCheckpoint.__table__.c.scan_generation
    assert column.nullable is True


def test_target_no_longer_has_current_job_id_and_binding_table_shape():
    assert "current_job_id" not in SyncRequestTarget.__table__.c
    assert "requested_generation" in SyncRequestTarget.__table__.c
    unique_sets = {
        tuple(c.name for c in constraint.columns)
        for constraint in SyncRequestTargetJob.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("target_id", "execution_generation") in unique_sets
    job_fk = SyncRequestTargetJob.__table__.c.job_id.foreign_keys
    assert job_fk and next(iter(job_fk)).ondelete == "SET NULL"


def test_alembic_chain_single_head_is_0026_and_linear():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["20261026_0026"]
    current = script.get_revision("20261026_0026")
    assert current.down_revision == "20261026_0025"
    visited = []
    while current is not None:
        visited.append(current.revision)
        down = current.down_revision
        if down is None:
            break
        assert isinstance(down, str), f"fork at {current.revision}"
        current = script.get_revision(down)
    assert visited[-1] == "20261020_0001"
    assert len(visited) == 26


def test_settle_is_noop_for_job_double_without_generation():
    job = SimpleNamespace(id=uuid.uuid4(), payload={})
    session = SimpleNamespace()  # no scalars: settlement must not explode
    assert settle_job_bindings(session, job, outcome="complete") == set()  # type: ignore[arg-type]


def test_periodic_successor_detection():
    job = SimpleNamespace(payload={"poll_round": 0})
    poll = SimpleNamespace(payload={"folder_id": "f", "poll_round": 1})
    continuation = SimpleNamespace(payload={"folder_id": "f"})
    assert _successor_is_periodic(job, poll, {"exhausted": True}) is True  # type: ignore[arg-type]
    assert _successor_is_periodic(job, poll, {}) is True  # type: ignore[arg-type]
    assert _successor_is_periodic(job, continuation, {"exhausted": True}) is False  # type: ignore[arg-type]
    assert _successor_is_periodic(job, None, {"exhausted": True}) is False  # type: ignore[arg-type]
