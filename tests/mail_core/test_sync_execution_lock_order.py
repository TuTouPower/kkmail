"""T082: refresh_requests and settlement lock Targets before Requests.

The lock order is WorkerJob row -> Targets (UUID ascending) -> Links ->
Requests (UUID ascending). These tests pin statement acquisition order on the
real PostgreSQL schema, with links pointing at real WorkerJob rows.
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
from mail_core.sync.execution import refresh_requests, settle_job_links

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _seed_request(Session, *, link_status: str):
    """One request + one target + one link to a real job; returns ids."""
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    job_id = uuid.uuid4()
    with Session() as session:
        session.add(
            WorkerJob(
                id=job_id,
                job_type="sync_folder_delta",
                payload={},
                status="claimed",
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
                execution_origin="foreground",
            )
        )
        session.flush()
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
                requested_generation=uuid.uuid4(),
                state="queued",
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=target_id,
                job_id=job_id,
                phase="sync",
                status=link_status,
                created_at=_NOW,
                finished_at=_NOW if link_status in ("complete", "failed") else None,
            )
        )
        session.commit()
    return request_id, job_id


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
        self.statements.append(statement)


def _first_select_index(statements: list[str], table: str) -> int | None:
    pattern = re.compile(rf"\bfrom\s+{re.escape(table)}\b")
    for index, statement in enumerate(statements):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and pattern.search(normalized):
            return index
    return None


def _assert_targets_locked_before_requests(statements: list[str]) -> None:
    targets_index = _first_select_index(statements, "sync_request_targets")
    requests_index = _first_select_index(statements, "sync_requests")
    assert targets_index is not None, f"no select against sync_request_targets: {statements!r}"
    assert requests_index is not None, f"no select against sync_requests: {statements!r}"
    assert targets_index < requests_index, (
        "lock acquisition order violated: Request select precedes Target select"
    )


def test_refresh_requests_locks_targets_before_requests_direct():
    Session = get_session_factory()
    engine = Session.kw["bind"]
    first_id, _ = _seed_request(Session, link_status="complete")
    second_id, _ = _seed_request(Session, link_status="complete")

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


def test_refresh_requests_locks_targets_before_requests_via_settle_path():
    Session = get_session_factory()
    engine = Session.kw["bind"]
    request_id, job_id = _seed_request(Session, link_status="queued")

    with _Capture(engine) as capture:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            capture.statements.clear()
            request_ids = settle_job_links(session, job, outcome="complete")
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
