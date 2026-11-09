"""R07: unified lock order — Targets before Bindings at every entry point.

The settlement path used to lock Binding rows before Targets while
``fail_open_targets`` (account/folder deletion) locked Targets before
Bindings; the inverted orders deadlocked on real PostgreSQL (40P01).
Both paths — and the claim/reclaim/patrol helpers — now take planning
reads first, then lock the FULL Target set of every affected request
(UUID ascending), and only then lock Binding rows.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``:
locking selects carry a real ``FOR UPDATE`` clause. The pinned invariant:
in each entry point's statement stream, the first Target entity select
precedes the first Binding entity select. Entity selects render every
mapped column and are captured via before_cursor_execute; planning reads
(selecting single columns) never match.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    Account,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.execution import fail_open_targets, settle_job_bindings

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


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


def _first_entity_select(statements: list[str], table: str) -> int | None:
    prefix = f"select {table}.id, {table}."
    for i, s in enumerate(statements):
        if s.startswith(prefix):
            return i
    return None


def _seed(Session):
    account_id = uuid.uuid4()
    request_id = uuid.uuid4()
    generation = uuid.uuid4()
    job_id = uuid.uuid4()
    target_id = uuid.uuid4()
    with Session() as session:
        session.add(
            WorkerJob(
                id=job_id, execution_generation=generation,
                job_type="sync_folder_delta", payload={}, status="claimed",
                run_after=_NOW, created_at=_NOW, updated_at=_NOW,
            )
        )
        session.commit()
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"r07-{account_id.hex}@example.test",
                provider="imap",
                sync_enabled=True,
            )
        )
        session.add(
            SyncRequest(
                id=request_id, client_request_id=f"r07-{uuid.uuid4().hex}",
                mode="delta", trigger="manual", state="running", scope={},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTarget(
                id=target_id, request_id=request_id, account_id=account_id,
                target_key=f"folder:{target_id}", requested_generation=generation,
                state="running", created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(), target_id=target_id,
                execution_generation=generation, job_id=job_id, phase="sync",
                status="running", created_at=_NOW,
            )
        )
        session.commit()
    return account_id, job_id


def _assert_targets_before_bindings(statements: list[str]) -> None:
    target_idx = _first_entity_select(statements, "sync_request_targets")
    binding_idx = _first_entity_select(statements, "sync_request_target_jobs")
    assert target_idx is not None, f"no Target entity select in {statements}"
    assert binding_idx is not None, f"no Binding entity select in {statements}"
    assert target_idx < binding_idx, (
        f"Target lock must precede Binding lock:\n" + "\n".join(statements)
    )


def test_settle_locks_targets_before_bindings():
    Session = get_session_factory()
    engine = Session.kw["bind"]
    _account_id, job_id = _seed(Session)
    with _Capture(engine) as cap, Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        cap.statements.clear()
        settle_job_bindings(session, job, outcome="complete")
        session.commit()
    _assert_targets_before_bindings(cap.statements)


def test_fail_open_targets_locks_targets_before_bindings():
    Session = get_session_factory()
    engine = Session.kw["bind"]
    account_id, _job_id = _seed(Session)
    with _Capture(engine) as cap, Session() as session:
        fail_open_targets(
            session,
            account_id=account_id,
            error_code="account_deleted",
            safe_error="Account was deleted before the sync completed",
        )
        session.commit()
    _assert_targets_before_bindings(cap.statements)
