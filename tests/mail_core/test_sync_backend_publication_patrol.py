"""Adoption fixes for outbox publication and folder patrol (S6/S7).

Both fixes replace a select-then-insert with a conflict-safe upsert; the
races are reproduced deterministically on the real PostgreSQL schema with
a stale first read (same technique as test_a352_publication_state_race.py).
The conflict-safe ON CONFLICT DO NOTHING paths are PostgreSQL-only and are
now exercised for real rather than against hand-written DDL.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderPatrolStatus,
    OutboxEvent,
    OutboxPublicationState,
    SyncCheckpoint,
)
from mail_core.providers.base import FolderStatus
from mail_core.realtime.publication import publish_committed_batch
from mail_core.sync.patrol import PatrolConfig, schedule_folder_status_patrol

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _capture_sql():
    engine = get_engine()
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return statements, lambda: event.remove(engine, "before_cursor_execute", _record)


class _StaleFirstScalarSession:
    def __init__(self, real):
        self._real = real
        self._scalar_calls = 0

    def scalar(self, *args, **kwargs):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return None
        return self._real.scalar(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_s6_publish_creates_state_on_first_start():
    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"n": 1}))
        session.commit()
    with Session() as session:
        batch = publish_committed_batch(session, limit=10)
        session.commit()
    assert batch.count == 1
    assert batch.first_seq == 1
    with Session() as session:
        state = session.scalar(
            select(OutboxPublicationState).where(OutboxPublicationState.id == 1)
        )
        assert state is not None
        assert state.next_seq == 2


def test_s6_publish_survives_stale_first_read_race():
    Session = get_session_factory()
    existing_epoch = uuid.uuid4()
    with Session() as session:
        session.add(
            OutboxPublicationState(id=1, epoch=existing_epoch, next_seq=42, pruned_through_seq=0)
        )
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"n": 2}))
        session.commit()

    with Session() as real:
        wrapped = _StaleFirstScalarSession(real)
        batch = publish_committed_batch(wrapped, limit=10)  # type: ignore[arg-type]
        real.commit()
    assert batch.count == 1
    assert batch.first_seq == 42
    assert batch.epoch == existing_epoch
    with Session() as session:
        rows = list(session.scalars(select(OutboxPublicationState)).all())
        assert len(rows) == 1
        assert rows[0].epoch == existing_epoch


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _StaleFirstExecuteSession:
    def __init__(self, real, rows):
        self._real = real
        self._rows = rows
        self._execute_calls = 0

    def execute(self, *args, **kwargs):
        self._execute_calls += 1
        if self._execute_calls == 1:
            return _FakeRows(self._rows)
        return self._real.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _StubProvider:
    def probe_folder_status(self, remote_id):
        return FolderStatus(messages=1, uidnext=1, unseen=0, highestmodseq=1)


class _FailingProvider:
    def probe_folder_status(self, remote_id):
        raise RuntimeError("probe failed")


def _seed_patrol_failure(*, failures: int):
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(id=account_id, email=f"s9-{uuid.uuid4().hex[:6]}@example.test",
                    provider="stub", sync_enabled=True)
        )
        session.add(
            Folder(id=folder_id, account_id=account_id, remote_id="Sent", name="Sent",
                   role="sent", sync_status="idle")
        )
        session.flush()
        session.add(
            SyncCheckpoint(account_id=account_id, folder_id=folder_id, cursor={"modseq": 0},
                           full_scan_complete=True)
        )
        session.add(
            FolderPatrolStatus(folder_id=folder_id, last_status=None,
                               last_probe_failures=failures)
        )
        session.commit()
    return Session, folder_id


def _patrol_config():
    return PatrolConfig(
        enabled=True, interval_s=0.0, max_probes=10, max_unprobed_s=999999.0
    )


def test_s7_patrol_failure_count_is_atomic_sql_increment():
    Session, folder_id = _seed_patrol_failure(failures=3)
    statements, stop_capture = _capture_sql()
    try:
        with Session() as session:
            result = schedule_folder_status_patrol(
                session,
                config=_patrol_config(),
                provider_factory=lambda acc: _FailingProvider(),
                now=datetime(2026, 11, 9, 15, 0, 0, tzinfo=timezone.utc),
            )
            session.commit()
    finally:
        stop_capture()

    assert result.failed == 1
    updates = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("UPDATE") and "folder_patrol_status" in sql
    ]
    assert any("coalesce" in sql.lower() and "+" in sql for sql in updates), updates
    with Session() as session:
        assert session.get(FolderPatrolStatus, folder_id).last_probe_failures == 4


def test_s7_patrol_failure_count_accumulates_across_workers():
    Session, folder_id = _seed_patrol_failure(failures=3)
    for _ in range(2):
        with Session() as session:
            result = schedule_folder_status_patrol(
                session,
                config=_patrol_config(),
                provider_factory=lambda acc: _FailingProvider(),
                now=datetime(2026, 11, 9, 15, 0, 0, tzinfo=timezone.utc),
            )
            session.commit()
            assert result.failed == 1
    with Session() as session:
        assert session.get(FolderPatrolStatus, folder_id).last_probe_failures == 5


def test_s7_patrol_upsert_survives_concurrent_first_probe():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(id=account_id, email=f"s7-{uuid.uuid4().hex[:6]}@example.test",
                    provider="stub", sync_enabled=True)
        )
        session.add(
            Folder(id=folder_id, account_id=account_id, remote_id="Sent", name="Sent",
                   role="sent", sync_status="idle")
        )
        session.flush()
        session.add(
            SyncCheckpoint(account_id=account_id, folder_id=folder_id, cursor={"modseq": 0},
                           full_scan_complete=True)
        )
        session.add(
            FolderPatrolStatus(folder_id=folder_id, last_status=None,
                                last_probe_failures=3)
        )
        session.commit()

    now = datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc)
    with Session() as real:
        folder = real.get(Folder, folder_id)
        account = real.get(Account, account_id)
        cp = real.get(
            SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id}
        )
        wrapped = _StaleFirstExecuteSession(real, [(folder, account, cp, None)])
        result = schedule_folder_status_patrol(
            wrapped,  # type: ignore[arg-type]
            config=PatrolConfig(enabled=True, interval_s=0.0, max_probes=10,
                                 max_unprobed_s=999999.0),
            provider_factory=lambda acc: _StubProvider(),
            now=now,
        )
        real.commit()

    assert result.failed == 0
    assert result.probed == 1
    with Session() as session:
        rows = list(session.scalars(select(FolderPatrolStatus)).all())
        assert len(rows) == 1
        assert rows[0].last_probe_failures == 0


def test_s7_patrol_creates_status_when_absent():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(id=account_id, email=f"s7b-{uuid.uuid4().hex[:6]}@example.test",
                    provider="stub", sync_enabled=True)
        )
        session.add(
            Folder(id=folder_id, account_id=account_id, remote_id="Sent", name="Sent",
                   role="sent", sync_status="idle")
        )
        session.commit()

    now = datetime(2026, 11, 4, 15, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        result = schedule_folder_status_patrol(
            session,
            config=PatrolConfig(enabled=True, interval_s=0.0, max_probes=10,
                                 max_unprobed_s=999999.0),
            provider_factory=lambda acc: _StubProvider(),
            now=now,
        )
        session.commit()
    assert result.probed == 1
    with Session() as session:
        rows = list(session.scalars(select(FolderPatrolStatus)).all())
        assert len(rows) == 1
        assert rows[0].folder_id == folder_id
