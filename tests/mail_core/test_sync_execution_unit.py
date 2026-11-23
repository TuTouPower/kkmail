"""T082 unit coverage: schema shape, migration chain, no-op settlement.

PostgreSQL-backed lifecycle/competition behavior lives in
test_sync_request_completion_by_data.py and test_sync_execution_tracking.py.
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
from mail_core.sync.execution import settle_job_links

ROOT = Path(__file__).resolve().parents[2]


def test_worker_job_has_no_execution_generation():
    assert "execution_generation" not in WorkerJob.__table__.c


def test_sync_checkpoint_scan_generation_is_nullable_uuid():
    column = SyncCheckpoint.__table__.c.scan_generation
    assert column.nullable is True


def test_target_link_always_points_at_a_real_job():
    assert "current_job_id" not in SyncRequestTarget.__table__.c
    assert "requested_generation" in SyncRequestTarget.__table__.c
    unique_sets = {
        tuple(c.name for c in constraint.columns)
        for constraint in SyncRequestTargetJob.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("target_id", "job_id") in unique_sets
    job_column = SyncRequestTargetJob.__table__.c.job_id
    assert job_column.nullable is False
    fk = next(iter(job_column.foreign_keys))
    assert fk.ondelete == "CASCADE"
    assert "needs_successor" in SyncRequestTargetJob.__table__.c
    assert "execution_generation" not in SyncRequestTargetJob.__table__.c


def test_alembic_chain_single_head_and_linear():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    script = ScriptDirectory.from_config(cfg)
    from mail_core.db.baseline import CURRENT_HEAD_REVISION

    assert script.get_heads() == [CURRENT_HEAD_REVISION]
    current = script.get_revision("20261107_0001")
    assert current is not None
    assert current.down_revision is None


def test_settle_is_noop_for_job_double_without_session():
    job = SimpleNamespace(id=uuid.uuid4(), payload={})
    session = SimpleNamespace()  # no scalars: settlement must not explode
    assert settle_job_links(session, job, outcome="complete") == set()  # type: ignore[arg-type]
