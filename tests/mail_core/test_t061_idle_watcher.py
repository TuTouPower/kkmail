"""t061 AC-001..AC-007: IDLE watcher holder selection, backoff, manager.

Pure selection/backoff logic is tested without a database; manager
behaviour (wake -> delta enqueue, quota, eligibility follow, failure
degradation) uses the shared DB fixtures and fake IDLE sessions.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob
from mail_core.providers.base import IdleNotSupportedError
from mail_core.sync.idle_watcher import (
    AccountActivity,
    IdleWatcherConfig,
    IdleWatcherManager,
    backoff_delay,
    select_idle_holders,
)

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)


def _activity(account_id: uuid.UUID, *, seconds_ago: float) -> AccountActivity:
    return AccountActivity(
        account_id=account_id,
        folder_id=uuid.uuid4(),
        last_activity_at=NOW - timedelta(seconds=seconds_ago),
        credential_fingerprint=f"fp-{account_id}",
    )


# ---------------------------------------------------------------------------
# Holder selection (AC-005) — pure
# ---------------------------------------------------------------------------


def test_select_holders_top_quota_by_activity():
    ids = [uuid.uuid4() for _ in range(5)]
    candidates = [_activity(ids[i], seconds_ago=100 * (i + 1)) for i in range(5)]
    holders = select_idle_holders(candidates, current_holders=set(), quota=2, hysteresis_s=300, now=NOW)
    assert holders == {ids[0], ids[1]}


def test_select_holders_hysteresis_keeps_incumbent():
    hot, warm, cold = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    candidates = [
        _activity(hot, seconds_ago=60),
        _activity(warm, seconds_ago=200),
        _activity(cold, seconds_ago=400),
    ]
    # cold currently holds the seat; warm is newer but only by 200s,
    # inside the 300s hysteresis margin, so cold keeps its seat.
    holders = select_idle_holders(
        candidates, current_holders={cold}, quota=2, hysteresis_s=300, now=NOW
    )
    assert holders == {hot, cold}


def test_select_holders_hysteresis_yields_when_challenger_clearly_hotter():
    hot, warm, cold = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    candidates = [
        _activity(hot, seconds_ago=10),
        _activity(warm, seconds_ago=20),
        _activity(cold, seconds_ago=4000),
    ]
    holders = select_idle_holders(
        candidates, current_holders={cold}, quota=2, hysteresis_s=300, now=NOW
    )
    assert holders == {hot, warm}


def test_select_holders_drops_ineligible_incumbent():
    a, b = uuid.uuid4(), uuid.uuid4()
    candidates = [_activity(a, seconds_ago=10)]
    holders = select_idle_holders(
        candidates, current_holders={b}, quota=4, hysteresis_s=300, now=NOW
    )
    assert holders == {a}


def test_backoff_delay_grows_and_caps_with_jitter():
    cfg = IdleWatcherConfig(backoff_base_s=5.0, backoff_max_s=60.0)
    d0 = [backoff_delay(0, cfg, jitter_fraction=f) for f in (0.0, 0.5, 1.0)]
    assert d0 == [5.0, 7.5, 10.0]
    assert backoff_delay(1, cfg, jitter_fraction=0.0) == 10.0
    assert backoff_delay(50, cfg, jitter_fraction=0.0) == 60.0
    assert backoff_delay(50, cfg, jitter_fraction=1.0) == 120.0


# ---------------------------------------------------------------------------
# Manager behaviour with fake sessions (DB)
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, *, outcomes: list[str] | None = None, fail_with: Exception | None = None):
        self._outcomes = list(outcomes or [])
        self._fail_with = fail_with
        self.closed = False
        self.waits = 0

    def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
        self.waits += 1
        if self._fail_with is not None:
            raise self._fail_with
        if self._outcomes:
            return self._outcomes.pop(0)
        # Default: block briefly then report a timeout cycle.
        stop_event.wait(min(timeout_s, 0.05))
        return "stopped" if stop_event.is_set() else "timeout"

    def close(self) -> None:
        self.closed = True


def _seed_idle_account(
    session,
    *,
    provider: str = "imap",
    sync_enabled: bool = True,
    baseline: bool = True,
    paused: bool = False,
    activity_seconds_ago: float = 60.0,
) -> tuple[Account, Folder]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"idle-{uuid.uuid4().hex[:8]}@example.com",
        provider=provider,
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=sync_enabled,
        config={"imap_host": "imap.example.com"},
    )
    session.add(acc)
    session.flush()
    folder = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id="INBOX",
        name="Inbox",
        role="inbox",
        sync_status=SyncStatus.PAUSED.value if paused else SyncStatus.IDLE.value,
    )
    session.add(folder)
    session.flush()
    cp = SyncCheckpoint(
        account_id=acc.id,
        folder_id=folder.id,
        full_scan_complete=baseline,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=activity_seconds_ago),
    )
    session.add(cp)
    session.flush()
    return acc, folder


def _manager(session_factory, factory, **cfg_overrides) -> IdleWatcherManager:
    cfg = IdleWatcherConfig(
        enabled=True,
        quota=32,
        max_duration_s=30.0,
        backoff_base_s=0.05,
        backoff_max_s=0.2,
        hysteresis_s=300.0,
        reconcile_interval_s=0.05,
    )
    for key, value in cfg_overrides.items():
        setattr(cfg, key, value)
    return IdleWatcherManager(session_factory, idle_session_factory=factory, config=cfg)


def _wait_until(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


db_only = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@db_only
def test_ac001_ac002_wake_enqueues_delta():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_idle_account(session)
        acc_id, folder_id = acc.id, folder.id
        session.commit()

    fake = _FakeSession(outcomes=["changed"])
    manager = _manager(Session, lambda account, folder_row: fake)
    manager.start()
    try:
        def _job_enqueued() -> bool:
            with Session() as session:
                job = session.scalar(
                    select(WorkerJob).where(
                        WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}",
                        WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                    )
                )
                return job is not None

        assert _wait_until(_job_enqueued), "IDLE wake did not enqueue a delta job"
        assert manager.held_account_ids() == {acc_id}
        assert manager.snapshot()[acc_id] in ("idling", "changed")
    finally:
        manager.stop()


@db_only
def test_ac001_no_idle_capability_falls_back_to_polling():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, _folder = _seed_idle_account(session)
        acc_id = acc.id
        session.commit()

    def factory(account, folder_row):
        raise IdleNotSupportedError("no IDLE here")

    manager = _manager(Session, factory)
    manager.start()
    try:
        assert _wait_until(lambda: manager.snapshot().get(acc_id) == "fallback")
        assert manager.held_account_ids() == set()
        with Session() as session:
            row = session.get(Account, acc_id)
            # Fallback must not poison the account status (AC-007).
            assert row.sync_status != "failed"
    finally:
        manager.stop()


@db_only
def test_ac005_quota_limits_sessions():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    account_ids: list[uuid.UUID] = []
    with Session() as session:
        for i in range(3):
            acc, _folder = _seed_idle_account(session, activity_seconds_ago=30.0 * (i + 1))
            account_ids.append(acc.id)
        session.commit()

    sessions: dict[uuid.UUID, _FakeSession] = {}

    def factory(account, folder_row):
        fake = _FakeSession()
        sessions[account.id] = fake
        return fake

    manager = _manager(Session, factory, quota=2)
    manager.start()
    try:
        assert _wait_until(lambda: len(manager.held_account_ids()) == 2)
        # The two most recently active accounts hold the seats.
        assert manager.held_account_ids() == {account_ids[0], account_ids[1]}
    finally:
        manager.stop()


@db_only
def test_ac006_disabled_account_session_closed():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, _folder = _seed_idle_account(session)
        acc_id = acc.id
        session.commit()

    fake = _FakeSession()
    manager = _manager(Session, lambda account, folder_row: fake)
    manager.start()
    try:
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        with Session() as session:
            row = session.get(Account, acc_id)
            row.sync_enabled = False
            session.commit()
        assert _wait_until(lambda: manager.held_account_ids() == set())
        assert fake.closed is True
    finally:
        manager.stop()


class _FakeDbSession:
    """Minimal session double so manager tests can run without a DB."""

    def __init__(self, account: Account, folder: Folder):
        self._account = account
        self._folder = folder

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, key):  # noqa: ANN001, ANN202
        if model is Account:
            return self._account
        if model is Folder:
            return self._folder
        return None

    def add(self, obj) -> None:
        pass

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        pass


def test_blocked_watch_deregisters_and_retries_after_expiry():
    """AC-006 regression (code review Round 2 f003): a watch that exits
    via the blocked path must deregister itself, otherwise reconcile
    skips the account before consulting the block and neither a
    fingerprint change nor the 3600s block expiry can ever retry it."""
    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    account = Account(
        id=acc_id,
        email="blocked@example.com",
        provider="imap",
        credential_ref="ref-1",
        config={},
    )
    folder = Folder(
        id=folder_id,
        account_id=acc_id,
        remote_id="INBOX",
        name="Inbox",
        role="inbox",
        sync_status=SyncStatus.IDLE.value,
    )
    candidate = AccountActivity(
        account_id=acc_id,
        folder_id=folder_id,
        last_activity_at=datetime.now(timezone.utc),
        credential_fingerprint="fp-1",
    )
    calls: list[int] = []
    mode = {"fail": True}

    def idle_factory(account_snapshot, folder_row):
        calls.append(1)
        if mode["fail"]:
            raise IdleNotSupportedError("server does not advertise IDLE")
        return _FakeSession()

    manager = IdleWatcherManager(
        lambda: _FakeDbSession(account, folder),
        idle_session_factory=idle_factory,
        config=IdleWatcherConfig(
            enabled=True, quota=4, reconcile_interval_s=60.0,
            backoff_base_s=0.01, backoff_max_s=0.02,
        ),
    )
    manager._load_candidates = lambda: [candidate]  # noqa: SLF001 - test seam
    try:
        manager._reconcile_once()  # noqa: SLF001 - drive one cycle directly
        assert _wait_until(lambda: manager.snapshot().get(acc_id) == "fallback")
        assert len(calls) == 1
        # Still blocked and not aged: another cycle must not retry.
        manager._reconcile_once()  # noqa: SLF001
        assert len(calls) == 1
        # Age the block past the retry window; the "server" recovers
        # out-of-band with an unchanged credential fingerprint.
        fingerprint, _blocked_at = manager._blocked[acc_id]  # noqa: SLF001
        manager._blocked[acc_id] = (fingerprint, time.monotonic() - 7200)  # noqa: SLF001
        mode["fail"] = False
        manager._reconcile_once()  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        assert len(calls) == 2
        assert manager.snapshot()[acc_id] == "idling"
    finally:
        manager.stop()


def test_register_blocked_stale_thread_cannot_clobber_new_watch():
    """Code review Round 3 f004: a stale watch thread (replaced while
    stuck in connect) exiting via the blocked path must not overwrite
    the newer watch's state or block record."""
    from mail_core.sync.idle_watcher import _Watch

    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    account = Account(
        id=acc_id, email="stale@example.com", provider="imap",
        credential_ref="ref", config={},
    )
    folder = Folder(
        id=folder_id, account_id=acc_id, remote_id="INBOX", name="Inbox",
        role="inbox", sync_status=SyncStatus.IDLE.value,
    )
    manager = IdleWatcherManager(
        lambda: _FakeDbSession(account, folder),
        idle_session_factory=lambda a, f: _FakeSession(),
        config=IdleWatcherConfig(enabled=True),
    )
    fresh = _Watch(
        account_id=acc_id, folder_id=folder_id, fingerprint="fp-new",
        account_snapshot=account, folder_remote_id="INBOX",
    )
    stale = _Watch(
        account_id=acc_id, folder_id=folder_id, fingerprint="fp-old",
        account_snapshot=account, folder_remote_id="INBOX",
    )
    manager._watches[acc_id] = fresh  # noqa: SLF001 - white-box seam
    manager._states[acc_id] = "idling"  # noqa: SLF001
    manager._register_blocked(stale)  # noqa: SLF001
    assert manager._watches[acc_id] is fresh  # noqa: SLF001
    assert manager._states[acc_id] == "idling"  # noqa: SLF001
    assert acc_id not in manager._blocked  # noqa: SLF001
    # f006: the generic _set_state path carries the same identity guard.
    manager._set_state(stale, "backoff")  # noqa: SLF001
    assert manager._states[acc_id] == "idling"  # noqa: SLF001
    manager._set_state(fresh, "changed")  # noqa: SLF001
    assert manager._states[acc_id] == "changed"  # noqa: SLF001
    manager._set_state(fresh, "idling")  # noqa: SLF001
    # The current watch blocking itself still registers + deregisters.
    manager._register_blocked(fresh)  # noqa: SLF001
    assert acc_id not in manager._watches  # noqa: SLF001
    assert manager._states[acc_id] == "fallback"  # noqa: SLF001
    assert manager._blocked[acc_id][0] == "fp-new"  # noqa: SLF001


def test_reconcile_sweeps_blocked_state_for_departed_accounts():
    """Code review Round 3 f005: an account that leaves the candidate
    set while blocked must not keep a residual fallback state/block."""
    acc_id = uuid.uuid4()
    account = Account(
        id=acc_id, email="gone@example.com", provider="imap",
        credential_ref="ref", config={},
    )
    folder = Folder(
        id=uuid.uuid4(), account_id=acc_id, remote_id="INBOX", name="Inbox",
        role="inbox", sync_status=SyncStatus.IDLE.value,
    )
    manager = IdleWatcherManager(
        lambda: _FakeDbSession(account, folder),
        idle_session_factory=lambda a, f: _FakeSession(),
        config=IdleWatcherConfig(enabled=True),
    )
    manager._states[acc_id] = "fallback"  # noqa: SLF001 - white-box seam
    manager._blocked[acc_id] = ("fp", time.monotonic())  # noqa: SLF001
    manager._load_candidates = lambda: []  # noqa: SLF001 - account departed
    manager._reconcile_once()  # noqa: SLF001
    assert manager.snapshot() == {}
    assert manager._blocked == {}  # noqa: SLF001


def test_disabled_manager_is_noop():
    """AC-015: IDLE switch off -> start() builds nothing (test f005)."""
    calls: list = []

    def factory(account, folder_row):  # pragma: no cover - must not run
        calls.append(account.id)
        return _FakeSession()

    def forbidden_session_factory():  # pragma: no cover - must not run
        raise AssertionError("session factory used while disabled")

    manager = IdleWatcherManager(
        forbidden_session_factory,
        idle_session_factory=factory,
        config=IdleWatcherConfig(enabled=False),
    )
    manager.start()
    assert manager.held_account_ids() == set()
    assert manager.snapshot() == {}
    assert calls == []
    manager.stop()


@db_only
def test_ac003_manager_recovers_after_disconnect():
    """AC-003 manager level (test f002): a session that drops once is
    rebuilt after backoff and the account returns to held/idling."""
    from mail_core.db.session import get_session_factory
    from mail_core.providers.imap import IdleSessionDisconnected

    Session = get_session_factory()
    with Session() as session:
        acc, _folder = _seed_idle_account(session)
        acc_id = acc.id
        session.commit()

    class _DropOnceSession(_FakeSession):
        def wait_for_change(self, *, timeout_s, stop_event):
            raise IdleSessionDisconnected("server closed the connection")

    built: list[_FakeSession] = []

    def factory(account, folder_row):
        fake = _DropOnceSession() if not built else _FakeSession()
        built.append(fake)
        return fake

    manager = _manager(Session, factory)
    manager.start()
    try:
        assert _wait_until(lambda: len(built) >= 2), "manager never rebuilt the session"
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        assert manager.snapshot()[acc_id] == "idling"
    finally:
        manager.stop()


@db_only
def test_ac006_credential_change_rebuilds_session():
    """AC-006 (test f004): credential fingerprint change closes the old
    session and establishes a new one."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, _folder = _seed_idle_account(session)
        acc_id = acc.id
        session.commit()

    built: list[_FakeSession] = []

    def factory(account, folder_row):
        fake = _FakeSession()
        built.append(fake)
        return fake

    manager = _manager(Session, factory)
    manager.start()
    try:
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        with Session() as session:
            row = session.get(Account, acc_id)
            row.credential_ref = f"ref-rotated-{uuid.uuid4().hex[:6]}"
            session.commit()
        assert _wait_until(lambda: len(built) >= 2), "session not rebuilt after credential change"
        assert built[0].closed is True
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
    finally:
        manager.stop()


@db_only
def test_ac006_paused_inbox_closes_session_and_disable_recovers():
    """AC-006 (test f004): paused inbox closes the session; disabling
    then re-enabling the account rebuilds it."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_idle_account(session)
        acc_id, folder_id = acc.id, folder.id
        session.commit()

    fake = _FakeSession()
    manager = _manager(Session, lambda account, folder_row: fake)
    manager.start()
    try:
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        with Session() as session:
            row = session.get(Folder, folder_id)
            row.sync_status = SyncStatus.PAUSED.value
            session.commit()
        assert _wait_until(lambda: manager.held_account_ids() == set())
        assert fake.closed is True

        with Session() as session:
            row = session.get(Folder, folder_id)
            row.sync_status = SyncStatus.IDLE.value
            acc_row = session.get(Account, acc_id)
            acc_row.sync_enabled = False
            session.commit()
        assert manager.held_account_ids() == set()
        with Session() as session:
            acc_row = session.get(Account, acc_id)
            acc_row.sync_enabled = True
            session.commit()
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
    finally:
        manager.stop()


@db_only
def test_ac005_held_accounts_skip_inbox_polling():
    """AC-005 (test f003): the t057 scheduler skips IDLE-held accounts
    and resumes polling them once they no longer hold a seat."""
    from mail_core.db.session import get_session_factory
    from mail_core.worker.main import schedule_periodic_inbox_sync

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_idle_account(session, activity_seconds_ago=99999.0)
        acc_id, folder_id = acc.id, folder.id
        session.commit()

    with Session() as session:
        enqueued = schedule_periodic_inbox_sync(
            session, idle_held_account_ids={acc_id}, now=datetime.now(timezone.utc)
        )
        session.commit()
        assert enqueued == 0
    with Session() as session:
        enqueued = schedule_periodic_inbox_sync(
            session, idle_held_account_ids=set(), now=datetime.now(timezone.utc)
        )
        session.commit()
        assert enqueued == 1
        job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}"
            )
        )
        assert job is not None


@db_only
def test_ac007_repeated_failures_degrade_without_poisoning_account():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, _folder = _seed_idle_account(session)
        acc_id = acc.id
        session.commit()

    attempts = {"count": 0}

    def factory(account, folder_row):
        attempts["count"] += 1
        raise ConnectionError("server unreachable")

    manager = _manager(Session, factory)
    manager.start()
    try:
        assert _wait_until(lambda: manager.snapshot().get(acc_id) in ("backoff", "fallback"))
        with Session() as session:
            row = session.get(Account, acc_id)
            assert row.sync_status != "failed"
    finally:
        manager.stop()
