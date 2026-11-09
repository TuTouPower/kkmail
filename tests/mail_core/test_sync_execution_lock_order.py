"""DEFECT 2: refresh_requests must lock Targets before Requests.

The settlement lock order documented in ``mail_core.sync.execution`` is
WorkerJob row -> generation lock -> binding rows / Targets (UUID ascending)
-> Requests (UUID ascending). The old ``refresh_requests`` violated it: it
locked each SyncRequest row first and only then that request's Target rows.
Callers that already hold Target locks (``settle_job_bindings`` via
complete_job/fail_job) therefore wanted Requests while holding Targets,
whereas independent callers (``converge_orphaned_bindings``,
``mark_bindings_running``) reached ``refresh_requests`` holding no Target
locks and took Request locks first, then Target locks -- the two orders
deadlock in PostgreSQL (40P01).

These tests pin the *statement acquisition order* on the real PostgreSQL
schema created by ``alembic upgrade head``. The locking selects carry a real
``FOR UPDATE`` clause and the generation coordination uses the real
``pg_advisory_xact_lock``; the invariant under test is that the Targets
select precedes the Requests select (and settle takes no Request lock).

No existing test is modified by this file.
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
    OutboxEvent,
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


def _seed_request(Session, *, binding_status: str):
    """One request + one target + one binding; returns (request_id, generation)."""
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    generation = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"lock-order-{uuid.uuid4().hex}",
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
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=target_id,
                execution_generation=generation,
                job_id=None,
                phase="sync",
                status=binding_status,
                created_at=_NOW,
                finished_at=_NOW if binding_status in ("complete", "failed") else None,
            )
        )
        session.commit()
    return request_id, generation


class _Capture:
    """before_cursor_execute listener recording executed statements."""

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
        self.statements.append(statement)


def _first_select_index(statements: list[str], table: str) -> int | None:
    """Index of the first SELECT ... FROM <table> in ``statements``.

    Word-boundary match so ``sync_request_targets`` does not match
    ``sync_request_target_jobs`` and vice versa.
    """
    pattern = re.compile(rf"\bfrom\s+{re.escape(table)}\b")
    for index, statement in enumerate(statements):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and pattern.search(normalized):
            return index
    return None


def _assert_targets_locked_before_requests(statements: list[str]) -> None:
    targets_index = _first_select_index(statements, "sync_request_targets")
    requests_index = _first_select_index(statements, "sync_requests")
    assert targets_index is not None, (
        f"no select against sync_request_targets captured: {statements!r}"
    )
    assert requests_index is not None, (
        f"no select against sync_requests captured: {statements!r}"
    )
    assert targets_index < requests_index, (
        "lock acquisition order violated: the first (FOR UPDATE) "
        "select against sync_requests precedes the first (FOR UPDATE) "
        f"select against sync_request_targets: {statements!r}"
    )


def test_refresh_requests_locks_targets_before_requests_direct():
    """(a) Direct / independent entry point: refresh_requests alone."""
    Session = get_session_factory()
    engine = Session.kw["bind"]
    first_id, _ = _seed_request(Session, binding_status="complete")
    second_id, _ = _seed_request(Session, binding_status="complete")

    with _Capture(engine) as capture:
        with Session() as session:
            refresh_requests(session, [second_id, first_id])
            session.commit()
        captured = list(capture.statements)

    _assert_targets_locked_before_requests(captured)

    with Session() as session:
        for request_id in (first_id, second_id):
            req = session.get(SyncRequest, request_id)
            assert req is not None and req.state == "complete"
            assert req.finished_at is not None
        events = list(session.scalars(select(OutboxEvent)).all())
        assert {e.payload.get("request_id") for e in events} == {
            str(first_id),
            str(second_id),
        }
        assert all(e.payload.get("state") == "complete" for e in events)


def test_refresh_requests_locks_targets_before_requests_via_settle_path():
    """(b) Settlement entry point: settle_job_bindings + refresh_requests.

    This is the complete_job/fail_job path in jobs.py: settle locks
    bindings/Targets and returns request ids, then the caller persists
    aggregation via refresh_requests in the same transaction. The
    refresh phase must follow the same Targets -> Requests order, and
    the combined sequence must never take a Request lock before a
    Target lock.
    """
    Session = get_session_factory()
    engine = Session.kw["bind"]
    request_id, generation = _seed_request(Session, binding_status="queued")
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
        binding = session.scalar(select(SyncRequestTargetJob))
        assert binding is not None
        binding.job_id = job_id
        session.commit()

    with _Capture(engine) as capture:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            capture.statements.clear()
            request_ids = settle_job_bindings(session, job, outcome="complete")
            during_settle = list(capture.statements)
            capture.statements.clear()
            refresh_requests(session, request_ids)
            during_refresh = list(capture.statements)
            session.commit()

    assert request_ids == {request_id}
    assert _first_select_index(during_settle, "sync_request_targets") is not None
    assert _first_select_index(during_settle, "sync_requests") is None
    _assert_targets_locked_before_requests(during_refresh)
    _assert_targets_locked_before_requests(during_settle + during_refresh)

    with Session() as session:
        req = session.get(SyncRequest, request_id)
        assert req is not None and req.state == "complete"
        assert req.finished_at is not None
