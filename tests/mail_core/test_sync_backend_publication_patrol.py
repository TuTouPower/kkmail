"""Adoption fixes for outbox publication and folder patrol (S6/S7).

Both fixes replace a select-then-insert with a conflict-safe upsert; the
races are reproduced deterministically on SQLite with a stale first read
(same technique as test_a352_publication_state_race.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import (
    Account,
    Base,
    Folder,
    FolderPatrolStatus,
    OutboxEvent,
    OutboxPublicationState,
    SyncCheckpoint,
)
from mail_core.providers.base import FolderStatus
from mail_core.realtime.publication import publish_committed_batch
from mail_core.sync.patrol import PatrolConfig, schedule_folder_status_patrol

_PUB_DDL = [
    """
    CREATE TABLE outbox_publication_state (
        id INTEGER PRIMARY KEY,
        epoch CHAR(36) NOT NULL,
        next_seq BIGINT NOT NULL,
        pruned_through_seq BIGINT NOT NULL DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type VARCHAR(64) NOT NULL,
        account_id CHAR(36),
        payload JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        publication_seq BIGINT,
        published_at DATETIME
    )
    """,
]

_ACCOUNTS_DDL = """
CREATE TABLE accounts (
    id CHAR(36) PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    provider VARCHAR(32) NOT NULL,
    display_name VARCHAR(255),
    credential_ref VARCHAR(512),
    group_id CHAR(36),
    master_order INTEGER,
    group_order INTEGER,
    sync_enabled BOOLEAN NOT NULL DEFAULT 1,
    sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    config TEXT NOT NULL DEFAULT '{}',
    recipient_addresses TEXT NOT NULL DEFAULT '[]',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_CHECKPOINTS_DDL = """
CREATE TABLE sync_checkpoints (
    account_id CHAR(36) NOT NULL,
    folder_id CHAR(36) NOT NULL,
    cursor TEXT NOT NULL DEFAULT '{}',
    uidvalidity BIGINT,
    modseq BIGINT,
    history_id VARCHAR(128),
    delta_link TEXT,
    full_scan_complete BOOLEAN NOT NULL DEFAULT 0,
    scan_generation CHAR(36),
    fencing_token BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (account_id, folder_id)
)
"""

_PATROL_STATUS_DDL = """
CREATE TABLE folder_patrol_status (
    folder_id CHAR(36) PRIMARY KEY,
    last_status JSON,
    last_probe_at DATETIME,
    last_probe_failures INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""


def _pub_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _PUB_DDL:
            conn.execute(text(ddl))
    return engine


def _patrol_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_ACCOUNTS_DDL))
        conn.execute(text(_CHECKPOINTS_DDL))
        conn.execute(text(_PATROL_STATUS_DDL))
    Base.metadata.create_all(engine, tables=[Folder.__table__])
    return engine


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
    engine = _pub_engine()
    Session = sessionmaker(bind=engine)
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
    engine = _pub_engine()
    Session = sessionmaker(bind=engine)
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
    engine = _patrol_engine()
    Session = sessionmaker(bind=engine)
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
    return engine, Session, folder_id


def _patrol_config():
    return PatrolConfig(
        enabled=True, interval_s=0.0, max_probes=10, max_unprobed_s=999999.0
    )


def test_s7_patrol_failure_count_is_atomic_sql_increment():
    engine, Session, folder_id = _seed_patrol_failure(failures=3)
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
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
        event.remove(engine, "before_cursor_execute", capture)

    assert result.failed == 1
    updates = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("UPDATE") and "folder_patrol_status" in sql
    ]
    assert any("coalesce" in sql.lower() and "+" in sql for sql in updates), updates
    with Session() as session:
        assert session.get(FolderPatrolStatus, folder_id).last_probe_failures == 4


def test_s7_patrol_failure_count_accumulates_across_workers():
    _engine, Session, folder_id = _seed_patrol_failure(failures=3)
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
    engine = _patrol_engine()
    Session = sessionmaker(bind=engine)
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
    engine = _patrol_engine()
    Session = sessionmaker(bind=engine)
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
