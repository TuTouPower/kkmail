"""Multi-target settlement must pre-lock the full target set (deadlock fix).

``refresh_requests`` locks ALL targets of the affected requests in UUID
ascending order, then the requests. That alone does not prevent a
deadlock between two workers settling different jobs of the SAME
request: each settler first locked only its own job's target subset in
``settle_job_bindings`` and then entered ``refresh_requests`` already
holding a member of the set — the holder of the higher target waits on
the lower one while the holder of the lower one waits on the higher
(PostgreSQL 40P01).

The pinned invariant: ``settle_job_bindings`` must lock every target of
every affected request (one UUID-ascending FOR UPDATE select keyed by
``request_id``) BEFORE locking only the job's own subset — a settler
never waits on a target while already holding another target of the
same request set. Planning reads that merely map target -> request are
non-locking and are ignored here.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``:
locking selects carry a real ``FOR UPDATE`` clause and generation
coordination uses the real advisory lock. Entity selects are identified
as the selects rendering the full mapped column list (``target_key``).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.execution import refresh_requests, settle_job_bindings

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)

_LOW = uuid.UUID("00000000-0000-0000-0000-000000000001")
_HIGH = uuid.UUID("00000000-0000-0000-0000-000000000002")


class _Capture:
    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._record)
        return False

    def _record(self, _conn, _cursor, statement, _params, _context, _many):
        self.statements.append(" ".join(str(statement).lower().split()))


def _target_entity_selects(statements: list[str]) -> list[str]:
    """Entity selects against sync_request_targets (they render target_key)."""
    return [
        s
        for s in statements
        if s.startswith("select")
        and re.search(r"\bfrom\s+sync_request_targets\b", s)
        and "target_key" in s
    ]


def test_settle_prelocks_all_targets_of_affected_requests():
    """A job bound only to the HIGH target must still lock LOW first-hand:
    settle must issue one full-set lock keyed by request_id, and must not
    issue a subset-only (id IN) entity lock before it."""
    Session = get_session_factory()
    engine = Session.kw["bind"]
    request_id = uuid.uuid4()
    generation = uuid.uuid4()
    other_generation = uuid.uuid4()
    job_id = uuid.uuid4()
    with Session() as session:
        session.add(
            WorkerJob(
                id=job_id,
                execution_generation=generation,
                job_type="sync_folder_delta",
                payload={},
                status="claimed",
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"prelock-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="running",
                scope={},
                created_at=_NOW,
            )
        )
        for target_id in (_LOW, _HIGH):
            session.add(
                SyncRequestTarget(
                    id=target_id,
                    request_id=request_id,
                    target_key=f"folder:{target_id}",
                    requested_generation=generation,
                    state="running",
                    created_at=_NOW,
                )
            )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=_HIGH,
                execution_generation=generation,
                job_id=job_id,
                phase="sync",
                status="running",
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=_LOW,
                execution_generation=other_generation,
                job_id=None,
                phase="sync",
                status="complete",
                created_at=_NOW,
                finished_at=_NOW,
            )
        )
        session.commit()

    with _Capture(engine) as capture:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            capture.statements.clear()
            request_ids = settle_job_bindings(session, job, outcome="complete")
            during_settle = list(capture.statements)
            refresh_requests(session, request_ids)
            session.commit()

    assert request_ids == {request_id}
    entity_selects = _target_entity_selects(during_settle)
    assert entity_selects, f"no target entity select captured: {during_settle!r}"
    full_set = [
        s for s in entity_selects if re.search(r"sync_request_targets\.request_id\s+in", s)
    ]
    subset_only = [
        s
        for s in entity_selects
        if re.search(r"sync_request_targets\.id\s+in", s)
        and not re.search(r"sync_request_targets\.request_id\s+in", s)
    ]
    assert full_set, (
        "settle never locked the full target set of the affected request; "
        f"entity selects were: {entity_selects!r}"
    )
    first_full = entity_selects.index(full_set[0])
    for stmt in subset_only:
        assert entity_selects.index(stmt) > first_full, (
            "settle locked a subset of targets before the full request set: "
            f"{entity_selects!r}"
        )

    with Session() as session:
        req = session.get(SyncRequest, request_id)
        assert req is not None and req.state == "complete"
        assert req.finished_at is not None
        binding = session.scalar(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.execution_generation == generation
            )
        )
        assert binding is not None and binding.status == "complete"
