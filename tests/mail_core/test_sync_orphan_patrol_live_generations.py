"""DEFECT 8: orphan patrol must derive ``live_generations`` from live jobs only.

``converge_orphaned_bindings`` decides, for a binding whose ``job_id`` is
NULL, whether its ``execution_generation`` is still executable by checking
membership in a ``live_generations`` set. The old code built that set from
``select(WorkerJob.execution_generation)`` with no WHERE clause, so every
patrol cycle loaded the generation of *every* WorkerJob row ever retained
(done/failed history included -- tens of thousands of rows) into memory,
and, worse, a generation belonging only to a terminal job counted as
"live", so an open ``job_id``-NULL binding at that generation leaked open
forever instead of converging to ``execution_lost``.

The fix restricts the query to ``PENDING``/``CLAIMED`` jobs -- the only
non-terminal ``JobStatus`` values. Bindings that *do* carry a ``job_id``
never consult this set: they converge via the bound job's own status branch.
A terminal job's bindings are settled by ``complete_job``/``fail_job`` in
the settlement transaction, so an open ``job_id``-NULL binding left at a
terminal generation is by definition orphaned and must fail with
``execution_lost``.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``.
On the old (unfiltered) code case (i) below stays open and the test fails;
with the fix it fails with ``execution_lost`` while case (ii) stays open.

No existing test is modified by this file.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.execution import EXECUTION_LOST_MESSAGE, converge_orphaned_bindings

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _seed(Session, *, job_status: str) -> tuple[uuid.UUID, uuid.UUID]:
    """One job at a fresh generation + one open job_id-NULL binding on it.

    Returns ``(binding_id, generation)``.
    """
    generation = uuid.uuid4()
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    binding_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"orphan-patrol-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTarget(
                id=target_id,
                request_id=request_id,
                target_key=f"folder:{uuid.uuid4().hex}",
                requested_generation=generation,
                state="queued",
                created_at=_NOW,
            )
        )
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                execution_generation=generation,
                job_type="sync_folder_delta",
                payload={},
                status=job_status,
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=binding_id,
                target_id=target_id,
                execution_generation=generation,
                job_id=None,
                phase="sync",
                status="queued",
                created_at=_NOW,
            )
        )
        session.commit()
    return binding_id, generation


def test_orphan_patrol_ignores_terminal_generations_but_keeps_pending_live():
    Session = get_session_factory()

    done_binding_id, _g1 = _seed(Session, job_status=JobStatus.DONE.value)
    pending_binding_id, _g2 = _seed(Session, job_status=JobStatus.PENDING.value)

    with Session() as session:
        changed = converge_orphaned_bindings(session)
        session.commit()
    assert changed == 1

    with Session() as session:
        bindings = {
            b.id: b for b in session.scalars(select(SyncRequestTargetJob)).all()
        }
        done_binding = bindings[done_binding_id]
        assert done_binding.status == "failed"
        assert done_binding.error_code == "execution_lost"
        assert done_binding.safe_error == EXECUTION_LOST_MESSAGE
        assert done_binding.finished_at is not None

        pending_binding = bindings[pending_binding_id]
        assert pending_binding.status == "queued"
        assert pending_binding.error_code is None
        assert pending_binding.finished_at is None
