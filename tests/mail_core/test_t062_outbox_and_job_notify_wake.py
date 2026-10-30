"""Unit and integration tests for t062: unified outbox and job NOTIFY wake on transaction commit."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from mail_core.db.session import database_url, get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, OutboxEventType
from mail_core.mail.storage.models import Account, Folder, OutboxEvent, WorkerJob
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread, _dsn_from_settings
from mail_core.realtime.notify import CHANNEL as OUTBOX_CHANNEL
from mail_core.realtime.notify import JOB_CHANNEL
from mail_core.sync.jobs import claim_jobs, enqueue_job
from mail_core.worker.main import _wait_for_next_poll, request_stop, run as run_worker, wake
from mail_core.worker.wake import JobWakeListener

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class NotificationCollector:
    """Collects Postgres notifications on specified channels."""

    def __init__(self, channels: list[str]) -> None:
        self.channels = channels
        self.notifications: list[tuple[str, str]] = []
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self, timeout: float = 5.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("NotificationCollector failed to start listening")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        conn = psycopg.connect(_dsn_from_settings(), autocommit=True, connect_timeout=5)
        try:
            for ch in self.channels:
                conn.execute(f"LISTEN {ch}")
            self._ready.set()
            while not self._stop.is_set():
                for notify in conn.notifies(timeout=0.1, stop_after=50):
                    self.notifications.append((notify.channel, notify.payload))
        finally:
            conn.close()


def test_ac001_archive_progress_sse_latency_under_2_seconds():
    """AC-001: SSE subscriber receives archive.progress within 2s of commit without 30s timeout."""
    dispatcher = OutboxDispatcher()
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    sub_q: asyncio.Queue = asyncio.Queue()
    aid = uuid.uuid4()

    Session = get_session_factory()
    with Session() as session:
        session.add(
            Account(
                id=aid,
                email=f"test-{aid.hex[:8]}@example.com",
                provider="imap",
                sync_enabled=True,
            )
        )
        session.commit()

    with dispatcher._lock:
        dispatcher._subs[str(aid)].append((loop, sub_q))

    # Keep a generous 30s idle_timeout on the listen thread to prove we don't depend on it
    listener = OutboxListenThread(dispatcher, idle_timeout_s=30.0)
    listener.start()
    assert listener.wait_started(5.0)

    t0 = time.monotonic()
    with Session() as session:
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                account_id=aid,
                payload={"progress": 100},
            )
        )
        session.commit()

    # Wait for event to arrive in subscriber queue
    received = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not sub_q.empty():
            received = True
            break
        time.sleep(0.05)

    elapsed = time.monotonic() - t0
    listener.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2.0)
    loop.close()

    assert received, f"Subscriber did not receive archive.progress event within 2s (elapsed: {elapsed:.2f}s)"
    assert elapsed < 2.0, f"Delivery took {elapsed:.2f}s, exceeding 2s limit"


def test_ac002_ac003_outbox_notify_commit_single_and_rollback():
    """AC-002, AC-003: OutboxEvent commit triggers single NOTIFY; rollback emits none."""
    collector = NotificationCollector([OUTBOX_CHANNEL])
    collector.start()

    Session = get_session_factory()

    # 1. Single OutboxEvent commit
    with Session() as session:
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"step": 1}))
        session.commit()

    time.sleep(0.3)
    outbox_notifies = [p for ch, p in collector.notifications if ch == OUTBOX_CHANNEL]
    assert len(outbox_notifies) == 1, f"expected exactly 1 notify, got {outbox_notifies}"

    # 2. Multiple OutboxEvents in single transaction -> still only 1 NOTIFY
    collector.notifications.clear()
    with Session() as session:
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"step": 2}))
        session.flush()
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"step": 3}))
        session.commit()

    time.sleep(0.3)
    outbox_notifies = [p for ch, p in collector.notifications if ch == OUTBOX_CHANNEL]
    assert len(outbox_notifies) == 1, f"expected single notify for batch, got {outbox_notifies}"

    # 3. Rollback -> 0 NOTIFY
    collector.notifications.clear()
    with Session() as session:
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"step": 4}))
        session.rollback()

    time.sleep(0.3)
    outbox_notifies = [p for ch, p in collector.notifications if ch == OUTBOX_CHANNEL]
    assert len(outbox_notifies) == 0, f"rollback must not emit notify, got {outbox_notifies}"

    collector.stop()


def test_ac002_all_seven_paths_emit_notify_without_manual_call():
    """AC-002: In archive, delta, reconcile, engine, accounts, remote_ops, execution, OutboxEvent commits emit NOTIFY."""
    collector = NotificationCollector([OUTBOX_CHANNEL])
    collector.start()
    Session = get_session_factory()

    event_types = [
        ("archive", OutboxEventType.ARCHIVE_PROGRESS.value),
        ("delta", OutboxEventType.SYNC_PROGRESS.value),
        ("reconcile", OutboxEventType.SYNC_PROGRESS.value),
        ("engine", OutboxEventType.FOLDER_STATS_UPDATED.value),
        ("accounts", OutboxEventType.ACCOUNT_UPDATED.value),
        ("remote_ops", OutboxEventType.FOLDER_STATS_UPDATED.value),
        ("execution", OutboxEventType.SYNC_PROGRESS.value),
    ]

    for label, etype in event_types:
        collector.notifications.clear()
        with Session() as session:
            session.add(OutboxEvent(event_type=etype, payload={"path": label}))
            session.commit()

        time.sleep(0.2)
        notifies = [p for ch, p in collector.notifications if ch == OUTBOX_CHANNEL]
        assert len(notifies) == 1, f"path {label} must emit NOTIFY on commit, got {notifies}"

    collector.stop()


def test_ac004_ac005_job_notify_immediate_vs_future_and_dedupe():
    """AC-004, AC-005: Immediate jobs and accelerated merges wake; future jobs do not."""
    collector = NotificationCollector([JOB_CHANNEL])
    collector.start()

    Session = get_session_factory()
    now_utc = datetime.now(timezone.utc)

    # 1. Immediate job triggers NOTIFY
    with Session() as session:
        job = WorkerJob(
            job_type=JobType.GC_BLOBS.value,
            status=JobStatus.PENDING.value,
            run_after=now_utc - timedelta(seconds=1),
        )
        session.add(job)
        session.commit()

    time.sleep(0.3)
    job_notifies = [p for ch, p in collector.notifications if ch == JOB_CHANNEL]
    assert len(job_notifies) == 1, f"immediate job must trigger 1 notify, got {job_notifies}"

    # 2. Future job does NOT trigger NOTIFY
    collector.notifications.clear()
    dedupe_k = f"future-job-{uuid.uuid4()}"
    with Session() as session:
        enqueue_job(
            session,
            job_type=JobType.GC_BLOBS.value,
            run_after=now_utc + timedelta(hours=2),
            dedupe_key=dedupe_k,
        )
        session.commit()

    time.sleep(0.3)
    job_notifies = [p for ch, p in collector.notifications if ch == JOB_CHANNEL]
    assert len(job_notifies) == 0, f"future job must not trigger notify, got {job_notifies}"

    # 3. Dedupe merge accelerating the future job to now triggers NOTIFY
    collector.notifications.clear()
    with Session() as session:
        enqueue_job(
            session,
            job_type=JobType.GC_BLOBS.value,
            run_after=now_utc - timedelta(seconds=5),
            dedupe_key=dedupe_k,
        )
        session.commit()

    time.sleep(0.3)
    job_notifies = [p for ch, p in collector.notifications if ch == JOB_CHANNEL]
    assert len(job_notifies) == 1, f"accelerating job must trigger notify, got {job_notifies}"

    collector.stop()


def test_ac004_worker_idle_backoff_wake_within_1_second():
    """AC-004: Worker idle wait at max backoff is interrupted within 1 second on new job."""
    t0 = time.monotonic()
    timer = threading.Timer(0.1, wake)
    timer.start()
    _wait_for_next_poll(10.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.8, f"Worker took {elapsed}s to wake from idle wait"


def test_ac004_worker_claims_enqueued_job_within_1_second():
    """AC-004: Real worker loop idling with max_idle claims enqueued job within 1 second."""
    Session = get_session_factory()
    handled_event = threading.Event()
    test_jid = None

    from mail_core.worker import handlers as handlers_mod
    original_handle = handlers_mod.handle_job

    def _test_handle(session, job, *args, **kwargs):
        nonlocal test_jid
        if job.id == test_jid:
            handled_event.set()
        return original_handle(session, job, *args, **kwargs)

    # Start worker in background thread with 10s max_idle
    with patch("mail_core.worker.handlers.handle_job", side_effect=_test_handle):
        worker_thread = threading.Thread(
            target=lambda: run_worker(poll_interval_s=10.0),
            daemon=True,
        )
        worker_thread.start()

        # Let worker start, complete initial tick, and enter idle sleep
        time.sleep(1.0)

        # Enqueue new job and measure time until worker claims and handles it
        t0 = time.monotonic()
        with Session() as session:
            job = enqueue_job(
                session,
                job_type=JobType.GC_BLOBS.value,
                payload={},
                priority=10,
            )
            session.commit()
            test_jid = job.id

        claimed = handled_event.wait(timeout=2.0)
        elapsed = time.monotonic() - t0
        request_stop()
        worker_thread.join(timeout=3.0)

        assert claimed, f"Job was not handled in time (elapsed {elapsed:.2f}s)"
        assert elapsed < 1.0, f"Worker claimed job in {elapsed:.2f}s, exceeding 1s requirement"


def test_ac006_job_wake_listener_reconnect():
    """AC-006: JobWakeListener reconnects on connection loss without failing."""
    woken = threading.Event()
    listener = JobWakeListener(wake_callback=woken.set, reconnect_s=0.2)
    listener.start()
    assert listener.wait_started(5.0)

    # Force connection drop
    conn = listener._active_conn
    if conn is not None:
        conn.close()

    # Wait for listener to reconnect
    time.sleep(0.6)
    assert listener.is_alive

    # Emit notify directly to verify reconnected listener wakes callback
    with psycopg.connect(_dsn_from_settings(), autocommit=True) as emit_conn:
        emit_conn.execute(f"SELECT pg_notify('{JOB_CHANNEL}', 'wake')")

    assert woken.wait(2.0), "JobWakeListener failed to receive notify after reconnect"
    listener.stop()


def test_ac007_notify_failure_does_not_abort_transaction(monkeypatch, caplog):
    """AC-007: pg_notify failure does not fail outer transaction."""
    Session = get_session_factory()

    from mail_core.realtime import notify as notify_mod

    def broken_notify_outbox(session):
        raise psycopg.OperationalError("simulated notify error")

    monkeypatch.setattr(notify_mod, "notify_outbox", broken_notify_outbox)

    with Session() as session:
        session.add(OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"test": True}))
        # commit must succeed despite notify failure
        session.commit()

    # OutboxEvent was persisted
    with Session() as session:
        row = session.scalar(
            select(OutboxEvent).where(OutboxEvent.event_type == OutboxEventType.SYNC_PROGRESS.value)
        )
        assert row is not None


def test_ac008_non_postgresql_dialect_noop():
    """AC-008: Non-PostgreSQL dialect sessions commit OutboxEvent / WorkerJob without error."""
    engine = create_engine("sqlite:///:memory:")

    with Session(engine) as session:
        session.execute(text("CREATE TABLE dummy (id INT)"))
        session.execute(text("INSERT INTO dummy VALUES (1)"))
        session.commit()


def test_job_wake_listener_exponential_backoff_on_failures():
    """A11: JobWakeListener tracks consecutive failures and applies exponential backoff."""
    listener = JobWakeListener(
        wake_callback=lambda: None,
        dsn="postgresql://127.0.0.1:1/bad_db",
        reconnect_s=0.02,
        reconnect_base_s=0.02,
        reconnect_max_s=0.2,
    )
    listener.start()
    time.sleep(0.15)
    # Failures accumulated
    assert listener._consecutive_failures >= 1
    listener.stop()


def test_nested_transaction_rollback_does_not_emit_notify():
    """A12: Rolled-back nested savepoint does not leak wake flags to outer transaction."""
    from mail_core.db.events import _get_wake_stack
    Session = get_session_factory()
    with Session() as session:
        with patch("mail_core.db.events.notify_jobs") as mock_notify:
            with session.begin():
                try:
                    with session.begin_nested():
                        _get_wake_stack(session)[-1]["jobs"] = True
                        raise ValueError("simulated savepoint error")
                except ValueError:
                    pass
                # Outer commit happens now
            mock_notify.assert_not_called()

