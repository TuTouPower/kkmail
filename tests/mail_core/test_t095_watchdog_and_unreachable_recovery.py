"""Tests for Q2 worker main-loop stall watchdog, stamp write warning, and Q3 UNREACHABLE recovery."""

from __future__ import annotations

import logging
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mail_core.worker import main as worker_main
from mail_core.worker.heartbeat import WorkerHeartbeatLoop


def _noop_session_factory():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# Q2: Liveness stamp warning log (Finding 7) & main-loop stall watchdog
# ---------------------------------------------------------------------------


def test_liveness_stamp_write_failure_logs_rate_limited_warning(monkeypatch, caplog):
    def boom(**_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("mail_core.liveness.write_liveness_stamp", boom)

    with caplog.at_level(logging.WARNING, logger="mail_core.worker"):
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=1,
            worker_id="w-1",
            now=100.0,
            last_warn_at=None,
        )
        assert last_warn == 100.0
        # Within 60s window: suppressed, no log flood.
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=2,
            worker_id="w-1",
            now=120.0,
            last_warn_at=last_warn,
        )
        assert last_warn == 100.0
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=3,
            worker_id="w-1",
            now=159.9,
            last_warn_at=last_warn,
        )
        assert last_warn == 100.0
        # Past 60s window: emits a second bounded warning.
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=4,
            worker_id="w-1",
            now=160.0,
            last_warn_at=last_warn,
        )
        assert last_warn == 160.0

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "OSError" in warnings[0].getMessage()


def test_watchdog_does_not_trigger_while_mark_progress_advances(caplog):
    stalls: list[float] = []
    clock = [0.0]

    loop = WorkerHeartbeatLoop(
        "w-watchdog-ok",
        _noop_session_factory,
        interval_s=15.0,
        watchdog_timeout_s=1.0,
        on_watchdog_stall=stalls.append,
        monotonic=lambda: clock[0],
    )
    with caplog.at_level(logging.CRITICAL, logger="mail_core.worker.heartbeat"):
        for step in range(1, 10):
            clock[0] = step * 0.5
            loop._tick()
            loop.mark_progress()
            clock[0] += 0.4
            loop._tick()

    assert stalls == []
    assert [r for r in caplog.records if r.levelno == logging.CRITICAL] == []


def test_watchdog_triggers_callback_once_per_stall_and_logs_critical(caplog):
    stalls: list[float] = []
    clock = [0.0]

    loop = WorkerHeartbeatLoop(
        "w-watchdog-stall",
        _noop_session_factory,
        interval_s=15.0,
        watchdog_timeout_s=10.0,
        on_watchdog_stall=stalls.append,
        monotonic=lambda: clock[0],
    )
    with caplog.at_level(logging.CRITICAL, logger="mail_core.worker.heartbeat"):
        clock[0] = 5.0
        loop._tick()
        assert stalls == []

        clock[0] = 10.0
        loop._tick()
        assert stalls == []

        # First tick past watchdog_timeout_s -> triggers exactly once.
        clock[0] = 10.5
        loop._tick()
        assert len(stalls) == 1
        assert stalls[0] == pytest.approx(10.5)

        # Repeated ticks during the same stall do not spam callback or CRITICAL logs.
        clock[0] = 25.0
        loop._tick()
        clock[0] = 40.0
        loop._tick()
        assert len(stalls) == 1

        # Recovery via mark_progress resets latch so a later stall can fire again.
        loop.mark_progress()
        clock[0] = 55.0
        loop._tick()
        assert len(stalls) == 2

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 2


def test_watchdog_disabled_when_timeout_non_positive(monkeypatch):
    stalls: list[float] = []
    clock = [0.0]

    for disabled in (None, 0.0, -5.0):
        loop = WorkerHeartbeatLoop(
            "w-disabled",
            _noop_session_factory,
            interval_s=15.0,
            watchdog_timeout_s=disabled,
            on_watchdog_stall=stalls.append,
            monotonic=lambda: clock[0],
        )
        assert loop.watchdog_timeout_s is None
        clock[0] += 10000.0
        loop._tick()
    assert stalls == []

    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "0")
    assert worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0) is None
    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "-10")
    assert worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0) is None

    monkeypatch.delenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", raising=False)
    monkeypatch.delenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raising=False)
    default_timeout = worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0)
    assert default_timeout is not None and default_timeout >= 180.0

    # Large max_idle_s (e.g. 60s) must push watchdog timeout well past idle sleep so
    # an idle worker never false-triggers.
    idle_timeout = worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=60.0)
    assert idle_timeout is not None and idle_timeout >= 240.0


def test_worker_run_wires_watchdog_and_calls_mark_progress(monkeypatch):
    created: list[dict] = []
    progressed = threading.Event()
    progress_calls = 0

    class _SpyHeartbeatLoop:
        def __init__(self, worker_id, session_factory, *, interval_s=15.0, watchdog_timeout_s=None, on_watchdog_stall=None):
            created.append(
                {
                    "worker_id": worker_id,
                    "interval_s": interval_s,
                    "watchdog_timeout_s": watchdog_timeout_s,
                    "on_watchdog_stall": on_watchdog_stall,
                }
            )

        def start(self):
            pass

        def stop(self, timeout=None):
            pass

        def mark_progress(self):
            nonlocal progress_calls
            progress_calls += 1
            if progress_calls >= 2:
                progressed.set()

    class _NoopInfra:
        def start(self):
            pass

        def stop(self, timeout=None):
            pass

    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: _noop_session_factory)
    monkeypatch.setattr("mail_core.worker.heartbeat.WorkerHeartbeatLoop", _SpyHeartbeatLoop)
    monkeypatch.setattr(worker_main, "UnifiedClaimHeartbeatLoop", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr(worker_main, "_schedule_periodic_sync_once", lambda: 0)
    monkeypatch.setattr(worker_main, "_reclaim_once", lambda: 0)
    monkeypatch.setattr(worker_main, "_tick", lambda *_a, **_k: worker_main.TickResult(claimed=0, handled=0))
    monkeypatch.setattr("mail_core.worker.wake.JobWakeListener", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr("mail_core.sync.idle_watcher.get_idle_manager", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr("mail_core.liveness.write_liveness_stamp", lambda **_k: None)
    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "123")

    t = threading.Thread(target=lambda: worker_main.run(poll_interval_s=0.01), daemon=True)
    t.start()
    try:
        assert progressed.wait(timeout=3.0)
    finally:
        worker_main.request_stop()
        t.join(timeout=3.0)
    assert not t.is_alive()
    assert len(created) == 1
    assert created[0]["watchdog_timeout_s"] == 123.0
    assert created[0]["on_watchdog_stall"] is worker_main._exit_on_watchdog_stall
    assert progress_calls >= 2


def test_watchdog_background_thread_fires_on_real_stall():
    triggered = threading.Event()
    calls: list[float] = []

    def on_stall(elapsed: float) -> None:
        calls.append(elapsed)
        triggered.set()

    loop = WorkerHeartbeatLoop(
        "w-thread-stall",
        _noop_session_factory,
        interval_s=0.02,
        watchdog_timeout_s=0.05,
        on_watchdog_stall=on_stall,
    )
    loop.start()
    try:
        assert triggered.wait(timeout=2.0)
        time.sleep(0.08)
        assert len(calls) == 1
    finally:
        loop.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# Q3: UNREACHABLE half-open real-probe closed loop (real PG tests)
# ---------------------------------------------------------------------------

_DB_REQUIRED = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_unreachable_account(
    session,
    *,
    with_inbox: bool = True,
    with_completed_baseline: bool = False,
    last_failure_at=None,
    timestamps: list | None = None,
    extra_config: dict | None = None,
    sync_enabled: bool = True,
):
    import uuid
    from datetime import datetime, timedelta, timezone

    from mail_core.accounts.health import CFG_FAILURE_TIMESTAMPS
    from mail_core.mail.domain.enums import (
        ConnectivityState,
        CredentialState,
        FolderRemoteState,
        FolderRole,
    )
    from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint

    base = last_failure_at or (datetime.now(timezone.utc) - timedelta(minutes=20))
    cfg = dict(extra_config or {})
    if timestamps is not None:
        cfg[CFG_FAILURE_TIMESTAMPS] = [t.isoformat() for t in timestamps]
    elif last_failure_at is not None or timestamps is None:
        # Default: overdue streak unless caller passes explicit empty list.
        cfg[CFG_FAILURE_TIMESTAMPS] = [(base - timedelta(minutes=5)).isoformat(), base.isoformat()]

    acc = Account(
        id=uuid.uuid4(),
        email=f"q3-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref="ref-q3",
        sync_enabled=sync_enabled,
        credential_state=CredentialState.VALID.value,
        connectivity_state=ConnectivityState.UNREACHABLE.value,
        config=cfg,
    )
    session.add(acc)
    session.flush()

    inbox = None
    if with_inbox:
        inbox = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id="INBOX",
            name="INBOX",
            role=FolderRole.INBOX.value,
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(inbox)
        session.flush()
        if with_completed_baseline:
            session.add(
                SyncCheckpoint(
                    account_id=acc.id,
                    folder_id=inbox.id,
                    cursor={"modseq": 1},
                    full_scan_complete=True,
                )
            )
            session.flush()
    return acc.id, (inbox.id if inbox is not None else None)


@_DB_REQUIRED
def test_unreachable_inbox_only_no_baseline_probe_zero_idle_tx_and_resumes_sync():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, text

    from mail_core.accounts.health import CFG_FAILURE_TIMESTAMPS
    from mail_core.db.session import get_engine, get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState, JobStatus, JobType
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.providers.base import FolderStatus

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    stale_at = now - timedelta(minutes=20)
    with Session() as session:
        acc_id, _inbox_id = _seed_unreachable_account(
            session,
            with_inbox=True,
            with_completed_baseline=False,
            last_failure_at=stale_at,
            extra_config={"display_hint": "keep-me"},
        )
        session.commit()

    idle_in_tx_counts: list[int] = []
    probe_calls: list[str] = []

    class _ProbeProvider:
        def probe_folder_status(self, folder_remote_id: str):
            probe_calls.append(folder_remote_id)
            # Verify zero idle-in-transaction sessions during network I/O and
            # commit a concurrent config edit that Phase 3 must not clobber.
            engine = get_engine()
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                idle_cnt = conn.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND state = 'idle in transaction' "
                        "AND pid <> pg_backend_pid()"
                    )
                ).scalar_one()
                idle_in_tx_counts.append(int(idle_cnt))
            with Session() as concurrent_session:
                concurrent_session.execute(
                    text(
                        "UPDATE accounts SET config = COALESCE(config, '{}'::jsonb) "
                        "|| '{\"concurrent_edit\": \"preserved\"}'::jsonb "
                        "WHERE id = :aid"
                    ),
                    {"aid": acc_id},
                )
                concurrent_session.commit()
            return FolderStatus(messages=3, uidnext=4, unseen=1, highestmodseq=5)

    probed = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda _acc: _ProbeProvider(),
        now=now,
    )
    assert probed == 1
    assert probe_calls == ["INBOX"]
    assert idle_in_tx_counts == [0]

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.connectivity_state == ConnectivityState.CONNECTED.value
        assert CFG_FAILURE_TIMESTAMPS not in (acc.config or {})
        assert "unreachable_probe_claimed_at" not in (acc.config or {})
        assert acc.config.get("display_hint") == "keep-me"
        assert acc.config.get("concurrent_edit") == "preserved"

        discovery_jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc_id,
                    WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
                    WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
                )
            ).all()
        )
        assert len(discovery_jobs) == 1


@_DB_REQUIRED
def test_unreachable_without_inbox_or_timestamps_probes_discovery_and_dedupes():
    from datetime import datetime, timezone
    from sqlalchemy import select

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState, JobStatus, JobType
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.providers.base import RemoteFolder

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        # Missing/empty timestamps AND no inbox folder yet.
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=False,
            timestamps=[],
        )
        # Seed existing active discovery job for a second account to verify no duplicate job.
        acc2_id, _ = _seed_unreachable_account(
            session,
            with_inbox=False,
            timestamps=[],
        )
        session.add(
            WorkerJob(
                account_id=acc2_id,
                job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                execution_origin="foreground",
                payload={},
                dedupe_key=f"sync-folders:{acc2_id}",
                status=JobStatus.PENDING.value,
            )
        )
        session.commit()

    discovery_calls: list[str] = []

    class _ListFoldersProvider:
        def __init__(self, email: str):
            self.email = email

        def list_folders(self):
            discovery_calls.append(self.email)
            return [RemoteFolder("INBOX", "INBOX", "inbox")]

    probed = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda acc: _ListFoldersProvider(acc.email),
        now=now,
    )
    assert probed == 2
    assert len(discovery_calls) == 2

    with Session() as session:
        for aid in (acc_id, acc2_id):
            acc = session.get(Account, aid)
            assert acc is not None
            assert acc.connectivity_state == ConnectivityState.CONNECTED.value
            jobs = list(
                session.scalars(
                    select(WorkerJob).where(
                        WorkerJob.account_id == aid,
                        WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
                        WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
                    )
                ).all()
            )
            assert len(jobs) == 1


@_DB_REQUIRED
def test_unreachable_probe_transport_failure_keeps_unreachable_and_refreshes_backoff():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select

    from mail_core.accounts.health import CFG_FAILURE_TIMESTAMPS
    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState, OutboxEventType
    from mail_core.mail.storage.models import Account, OutboxEvent

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    stale_at = now - timedelta(minutes=20)
    with Session() as session:
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=True,
            last_failure_at=stale_at,
        )
        session.commit()

    probe_count = 0

    class _FailingProvider:
        def probe_folder_status(self, _folder_remote_id: str):
            nonlocal probe_count
            probe_count += 1
            raise ConnectionError("network unreachable")

    probed = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda _acc: _FailingProvider(),
        now=now,
    )
    assert probed == 1
    assert probe_count == 1

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value
        assert "unreachable_probe_claimed_at" not in (acc.config or {})
        stamps = (acc.config or {}).get(CFG_FAILURE_TIMESTAMPS) or []
        assert stamps == [now.isoformat()]

        degraded_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.account_id == acc_id,
                    OutboxEvent.event_type == OutboxEventType.ACCOUNT_UPDATED.value,
                )
            ).all()
        )
        assert [
            e for e in degraded_events if (e.payload or {}).get("connectivity_state") == ConnectivityState.DEGRADED.value
        ] == []

    # Within 15m of the failed probe -> must NOT re-probe yet.
    probed_too_soon = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda _acc: _FailingProvider(),
        now=now + timedelta(minutes=5),
    )
    assert probed_too_soon == 0
    assert probe_count == 1


@_DB_REQUIRED
def test_unreachable_probe_auth_failure_marks_credential_invalid():
    from datetime import datetime, timedelta, timezone

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import CredentialState
    from mail_core.mail.storage.models import Account
    from mail_core.providers.http import PermanentAuthError

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=True,
            last_failure_at=now - timedelta(minutes=20),
        )
        session.commit()

    class _AuthFailProvider:
        def probe_folder_status(self, _folder_remote_id: str):
            raise PermanentAuthError("invalid_grant")

    probed = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda _acc: _AuthFailProvider(),
        now=now,
    )
    assert probed == 1

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.credential_state == CredentialState.INVALID.value
        assert acc.sync_enabled is False
        assert "unreachable_probe_claimed_at" not in (acc.config or {})


@_DB_REQUIRED
def test_unreachable_concurrent_two_worker_half_open_claim_probes_only_once():
    from datetime import datetime, timedelta, timezone

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState
    from mail_core.mail.storage.models import Account
    from mail_core.providers.base import FolderStatus

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=True,
            with_completed_baseline=True,
            last_failure_at=now - timedelta(minutes=20),
        )
        session.commit()

    probe_entered = threading.Event()
    allow_finish = threading.Event()
    probe_lock = threading.Lock()
    probe_calls = 0

    class _SlowProbeProvider:
        def probe_folder_status(self, _folder_remote_id: str):
            nonlocal probe_calls
            with probe_lock:
                probe_calls += 1
            probe_entered.set()
            assert allow_finish.wait(timeout=5.0)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    results: list[int] = []

    def run_worker1():
        results.append(
            worker_main.recheck_unreachable_with_probe(
                Session,
                provider_factory=lambda _acc: _SlowProbeProvider(),
                now=now,
            )
        )

    t1 = threading.Thread(target=run_worker1, daemon=True)
    t1.start()
    try:
        assert probe_entered.wait(timeout=5.0)
        # Worker 2 races while Worker 1 is in-flight outside any DB tx holding the claim lease.
        r2 = worker_main.recheck_unreachable_with_probe(
            Session,
            provider_factory=lambda _acc: _SlowProbeProvider(),
            now=now,
        )
        assert r2 == 0
    finally:
        allow_finish.set()
        t1.join(timeout=5.0)

    assert not t1.is_alive()
    assert results == [1]
    assert probe_calls == 1

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.connectivity_state == ConnectivityState.CONNECTED.value
        assert "unreachable_probe_claimed_at" not in (acc.config or {})


@_DB_REQUIRED
def test_unreachable_simultaneous_barrier_race_and_baseline_skip_discovery():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState, JobStatus, JobType
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.providers.base import FolderStatus

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        # Completed inbox baseline already present: probe recovery should restore
        # CONNECTED without scheduling an extra SYNC_ACCOUNT_FOLDERS job.
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=True,
            with_completed_baseline=True,
            last_failure_at=now - timedelta(minutes=20),
        )
        session.commit()

    barrier = threading.Barrier(2)
    orig_claim = worker_main._claim_unreachable_probe_lease
    probe_lock = threading.Lock()
    probe_calls = 0

    def synchronized_claim(*args, **kwargs):
        barrier.wait(timeout=5.0)
        return orig_claim(*args, **kwargs)

    class _FastProvider:
        def probe_folder_status(self, _folder_remote_id: str):
            nonlocal probe_calls
            with probe_lock:
                probe_calls += 1
            return FolderStatus(messages=2, uidnext=3, unseen=0, highestmodseq=2)

    orig_attr = worker_main._claim_unreachable_probe_lease
    worker_main._claim_unreachable_probe_lease = synchronized_claim
    counts: list[int] = []
    errors: list[BaseException] = []

    def _run():
        try:
            counts.append(
                worker_main.recheck_unreachable_with_probe(
                    Session,
                    provider_factory=lambda _acc: _FastProvider(),
                    now=now,
                )
            )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    t1 = threading.Thread(target=_run, daemon=True)
    t2 = threading.Thread(target=_run, daemon=True)
    try:
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)
    finally:
        worker_main._claim_unreachable_probe_lease = orig_attr

    assert errors == []
    assert sorted(counts) == [0, 1]
    assert probe_calls == 1

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.connectivity_state == ConnectivityState.CONNECTED.value
        jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc_id,
                    WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
                    WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
                )
            ).all()
        )
        assert jobs == []


def test_schedule_periodic_sync_once_wires_recheck_unreachable_with_probe(monkeypatch):
    calls: list[object] = []
    fake_session = _noop_session_factory()
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: (lambda: fake_session))
    monkeypatch.setattr("mail_core.sync.idle_watcher.held_idle_account_ids", lambda: set())
    monkeypatch.setattr(worker_main, "schedule_periodic_inbox_sync", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        "mail_core.sync.patrol.schedule_folder_status_patrol",
        lambda *_a, **_k: SimpleNamespace(probed=0, changed=0, failed=0),
    )
    monkeypatch.setattr(
        worker_main,
        "recheck_unreachable_with_probe",
        lambda session_factory, **_k: calls.append(session_factory) or 1,
    )

    assert worker_main._schedule_periodic_sync_once() == 0
    assert len(calls) == 1


@_DB_REQUIRED
def test_unreachable_expired_claim_lease_is_reclaimed_and_none_status_falls_back_to_list():
    from datetime import datetime, timedelta, timezone

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState
    from mail_core.mail.storage.models import Account
    from mail_core.providers.base import RemoteFolder

    Session = get_session_factory()
    now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    expired_claim = (now - timedelta(seconds=130)).isoformat()
    with Session() as session:
        acc_id, _ = _seed_unreachable_account(
            session,
            with_inbox=True,
            with_completed_baseline=True,
            last_failure_at=now - timedelta(minutes=20),
            extra_config={worker_main._CFG_UNREACHABLE_PROBE_CLAIMED_AT: expired_claim},
        )
        session.commit()

    events: list[str] = []

    class _FallbackProvider:
        def probe_folder_status(self, _folder_remote_id: str):
            events.append("probe_none")
            return None

        def list_folders(self):
            events.append("list_folders")
            return [RemoteFolder("INBOX", "INBOX", "inbox")]

    probed = worker_main.recheck_unreachable_with_probe(
        Session,
        provider_factory=lambda _acc: _FallbackProvider(),
        now=now,
        lease_s=120.0,
    )
    assert probed == 1
    assert events == ["probe_none", "list_folders"]

    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc is not None
        assert acc.connectivity_state == ConnectivityState.CONNECTED.value
        assert worker_main._CFG_UNREACHABLE_PROBE_CLAIMED_AT not in (acc.config or {})
