"""t100: IDLE seat policy / session lifecycle split.

The pure seat policy lives in ``idle_policy`` (covered by the t061
selection tests); these tests pin the runtime ownership contract with
real threads, a fake DB session factory and fake provider sessions:

- a seat is handed over only after the retired session's execution
  thread AND provider reader thread have both exited (AC-002);
- a stale session's late state/block reports cannot overwrite or
  release its successor's seat (AC-002);
- seat occupancy and subscription validity are distinct: a session
  in backoff or in closing still occupies its seat, but its account
  already polls again (AC-004);
- first connect, reconnect and change notifications all enqueue via
  the existing background delta dedupe key (AC-003);
- a stopped manager accepts no new sessions (AC-004).

The PostgreSQL-backed variants (real enqueue dedupe/merge, candidate
loading SQL) stay in test_t061_idle_watcher.py as db_only tests.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from mail_core.mail.domain.enums import ExecutionOrigin, FolderRemoteState, JobType
from mail_core.mail.storage.models import Account, Folder
from mail_core.providers.base import IdleNotSupportedError
from mail_core.sync import idle_watcher as idle_watcher_mod
from mail_core.sync.idle_policy import IdleCandidate, IdleWatcherConfig
from mail_core.sync.idle_watcher import IdleWatcherManager


def _wait_until(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class _FakeDbSession:
    """Minimal session double: get() over fixed Account/Folder rows."""

    def __init__(self, accounts: dict, folders: dict):
        self._accounts = accounts
        self._folders = folders

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, key):  # noqa: ANN001, ANN202
        if model is Account:
            return self._accounts.get(key)
        if model is Folder:
            return self._folders.get(key)
        return None

    def scalar(self, statement):  # noqa: ANN001, ANN202
        return None

    def add(self, obj) -> None:
        pass

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        pass


class _FakeProviderSession:
    """Fake IDLE provider session: replays outcomes, then idles."""

    def __init__(self, *, outcomes: list[str] | None = None, fail_with: Exception | None = None):
        self._outcomes = list(outcomes or [])
        self._fail_with = fail_with
        self.closed = False

    def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
        if self._fail_with is not None:
            raise self._fail_with
        if self._outcomes:
            return self._outcomes.pop(0)
        stop_event.wait(min(timeout_s, 0.05))
        return "stopped" if stop_event.is_set() else "timeout"

    def close(self) -> None:
        self.closed = True


def _account(acc_id: uuid.UUID) -> Account:
    return Account(
        id=acc_id,
        email=f"t100-{acc_id.hex[:8]}@example.test",
        provider="imap",
        credential_ref=f"ref-{acc_id.hex[:6]}",
        sync_enabled=True,
        config={},
    )


def _folder(folder_id: uuid.UUID, acc_id: uuid.UUID) -> Folder:
    return Folder(
        id=folder_id,
        account_id=acc_id,
        remote_id="INBOX",
        name="Inbox",
        role="inbox",
        remote_state=FolderRemoteState.ACTIVE.value,
    )


def _candidate(acc_id: uuid.UUID, folder_id: uuid.UUID, *, minutes_ago: float, fingerprint: str) -> IdleCandidate:
    now = datetime.now(timezone.utc)
    return IdleCandidate(
        account_id=acc_id,
        folder_id=folder_id,
        inbox_latest_arrival_at=now - timedelta(minutes=minutes_ago),
        inbox_has_messages=True,
        other_latest_arrival_at=None,
        account_created_at=now - timedelta(hours=1),
        credential_fingerprint=fingerprint,
    )


def _manager(accounts, folders, factory, **cfg_overrides) -> IdleWatcherManager:
    options = {
        "enabled": True,
        "quota": 1,
        "max_duration_s": 30.0,
        "backoff_base_s": 0.01,
        "backoff_max_s": 0.02,
        "hysteresis_s": 300.0,
        "reconcile_interval_s": 60.0,
        "close_timeout_s": 0.2,
    }
    options.update(cfg_overrides)
    return IdleWatcherManager(
        lambda: _FakeDbSession(accounts, folders),
        idle_session_factory=factory,
        config=IdleWatcherConfig(**options),
    )


class _SlowCloseProvider:
    """Provider whose close() blocks until released, with a reader
    thread that lingers independently of the watch thread."""

    def __init__(self) -> None:
        self.close_release = threading.Event()
        self.reader_release = threading.Event()
        self.reader_thread = threading.Thread(
            target=lambda: self.reader_release.wait(timeout=30.0),
            name="imap-idle-reader-t100",
            daemon=True,
        )
        self.reader_thread.start()

    def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
        stop_event.wait(min(timeout_s, 0.05))
        return "stopped" if stop_event.is_set() else "timeout"

    def close(self) -> None:
        self.close_release.wait(timeout=30.0)


def test_seat_handover_waits_for_thread_and_reader_exit():
    """AC-002: the seat changes hands only once the retired session's
    execution thread and reader thread have both exited; meanwhile
    the retired account already polls again (subscription gone) while
    its seat is still occupied."""
    acc_a, folder_a = uuid.uuid4(), uuid.uuid4()
    acc_b, folder_b = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_a: _account(acc_a), acc_b: _account(acc_b)}
    folders = {folder_a: _folder(folder_a, acc_a), folder_b: _folder(folder_b, acc_b)}
    cand_a = _candidate(acc_a, folder_a, minutes_ago=10, fingerprint="fp-a")
    cand_b = _candidate(acc_b, folder_b, minutes_ago=1, fingerprint="fp-b")

    slow = _SlowCloseProvider()
    providers: dict[uuid.UUID, object] = {acc_a: slow, acc_b: _FakeProviderSession()}
    manager = _manager(accounts, folders, lambda account, folder_row: providers[account.id])
    state_candidates = [cand_a]
    manager._load_candidates = lambda: list(state_candidates)  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc_a})

        # Rotate the seat to the hotter B: A is retired into closing.
        state_candidates[:] = [cand_a, cand_b]
        manager._reconcile_once()  # noqa: SLF001
        assert acc_a not in manager._sessions  # noqa: SLF001
        assert len(manager._closing) == 1  # noqa: SLF001
        # Subscription is gone (polling resumes) but the seat is still
        # occupied, so B must not open yet — across repeated reconciles.
        assert manager.held_account_ids() == set()
        assert acc_b not in manager._sessions  # noqa: SLF001
        manager._reconcile_once()  # noqa: SLF001
        assert acc_b not in manager._sessions  # noqa: SLF001
        assert len(manager._closing) == 1  # noqa: SLF001

        # Execution thread exits, reader still alive: seat still held.
        slow.close_release.set()
        assert _wait_until(lambda: not manager._closing[0].watch.thread.is_alive())  # noqa: SLF001
        manager._reconcile_once()  # noqa: SLF001
        assert acc_b not in manager._sessions  # noqa: SLF001
        assert len(manager._closing) == 1  # noqa: SLF001

        # Reader exits too: the next reconcile hands the seat to B.
        slow.reader_release.set()
        assert _wait_until(lambda: not slow.reader_thread.is_alive())
        manager._reconcile_once()  # noqa: SLF001
        assert manager._closing == []  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc_b})
    finally:
        slow.close_release.set()
        slow.reader_release.set()
        manager.stop()


def test_stale_session_late_block_cannot_clobber_successor():
    """AC-002: a session stuck in connect while its seat was rebuilt
    exits late via the blocked path; its report must not overwrite
    the successor's state, block record or seat."""
    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_id: _account(acc_id)}
    folders = {folder_id: _folder(folder_id, acc_id)}
    manager = _manager(accounts, folders, lambda account, folder_row: _FakeProviderSession())

    from mail_core.sync.idle_watcher import IdleWatchSession

    def _session(fingerprint: str, factory) -> IdleWatchSession:
        return IdleWatchSession(
            account_id=acc_id,
            folder_id=folder_id,
            fingerprint=fingerprint,
            account_snapshot=accounts[acc_id],
            folder_snapshot=folders[folder_id],
            session_factory=lambda: _FakeDbSession(accounts, folders),
            idle_session_factory=factory,
            config=IdleWatcherConfig(enabled=True, backoff_base_s=0.01, backoff_max_s=0.02),
            host=manager,
        )

    connect_release = threading.Event()

    def stuck_factory(account, folder_row):
        connect_release.wait(timeout=30.0)
        raise IdleNotSupportedError("late capability failure")

    stale = _session("fp-old", stuck_factory)
    stale.start()
    try:
        # The successor is registered and subscribed in the meantime.
        fresh = _session("fp-new", lambda a, f: _FakeProviderSession())
        manager._sessions[acc_id] = fresh  # noqa: SLF001
        fresh._set_state("idling")  # noqa: SLF001
        assert manager.held_account_ids() == {acc_id}

        connect_release.set()
        assert _wait_until(lambda: stale.thread is not None and not stale.thread.is_alive())
        assert manager._sessions[acc_id] is fresh  # noqa: SLF001
        assert manager.snapshot()[acc_id] == "idling"
        assert acc_id not in manager._blocked  # noqa: SLF001
        assert manager.held_account_ids() == {acc_id}
    finally:
        connect_release.set()
        manager.stop()


def test_backoff_session_occupies_seat_but_allows_polling():
    """AC-004: a session in failure backoff keeps its seat (no second
    session is opened for the account, no other account takes it)
    while the account is already back on polling."""
    acc_a, folder_a = uuid.uuid4(), uuid.uuid4()
    acc_b, folder_b = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_a: _account(acc_a), acc_b: _account(acc_b)}
    folders = {folder_a: _folder(folder_a, acc_a), folder_b: _folder(folder_b, acc_b)}
    cand_a = _candidate(acc_a, folder_a, minutes_ago=10, fingerprint="fp-a")
    cand_b = _candidate(acc_b, folder_b, minutes_ago=60, fingerprint="fp-b")

    calls: list[uuid.UUID] = []

    def failing_factory(account, folder_row):
        calls.append(account.id)
        raise ConnectionError("server unreachable")

    manager = _manager(accounts, folders, failing_factory)
    manager._load_candidates = lambda: [cand_a, cand_b]  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        assert _wait_until(lambda: manager.snapshot().get(acc_a) == "backoff")
        # Subscription invalid -> polling covers the account again...
        assert manager.held_account_ids() == set()
        # ...but the seat stays occupied by the backing-off session.
        assert set(manager._sessions) == {acc_a}  # noqa: SLF001
        manager._reconcile_once()  # noqa: SLF001
        assert set(manager._sessions) == {acc_a}  # noqa: SLF001
        # The session keeps retrying on its own (recovery path).
        assert _wait_until(lambda: len(calls) >= 2)
    finally:
        manager.stop()


def test_reconnect_and_change_enqueue_via_background_dedupe_key(monkeypatch):
    """AC-003: first connect, reconnect after a drop, and a change
    notification each enqueue the inbox delta under the existing
    background dedupe key."""
    from mail_core.providers.imap import IdleSessionDisconnected

    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_id: _account(acc_id)}
    folders = {folder_id: _folder(folder_id, acc_id)}
    cand = _candidate(acc_id, folder_id, minutes_ago=5, fingerprint="fp")

    enqueued: list[dict] = []

    def recording_enqueue(session, **kwargs):
        enqueued.append(kwargs)

    monkeypatch.setattr(idle_watcher_mod, "enqueue_job", recording_enqueue)

    built: list[_FakeProviderSession] = []

    def factory(account, folder_row):
        if not built:
            fake = _FakeProviderSession(fail_with=IdleSessionDisconnected("drop"))
        else:
            fake = _FakeProviderSession(outcomes=["changed"])
        built.append(fake)
        return fake

    manager = _manager(accounts, folders, factory)
    manager._load_candidates = lambda: [cand]  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        # catch-up (connect) + catch-up (reconnect) + change notice.
        assert _wait_until(lambda: len(enqueued) >= 3)
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        for call in enqueued:
            assert call["job_type"] == JobType.SYNC_FOLDER_DELTA.value
            assert call["execution_origin"] is ExecutionOrigin.BACKGROUND
            assert call["dedupe_key"] == f"delta:{acc_id}:{folder_id}"
            assert call["payload"] == {"folder_id": str(folder_id)}
            assert call["priority"] == 60
    finally:
        manager.stop()


def test_catchup_budget_exhaustion_drops_subscription_but_keeps_retrying(monkeypatch):
    """AC-003: when the catch-up enqueue budget is exhausted, the
    subscription drops (polling covers the account) but the session
    itself survives and retries on the next reconnect cycle."""
    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_id: _account(acc_id)}
    folders = {folder_id: _folder(folder_id, acc_id)}
    cand = _candidate(acc_id, folder_id, minutes_ago=5, fingerprint="fp")

    def failing_enqueue(session, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(idle_watcher_mod, "enqueue_job", failing_enqueue)

    built: list[_FakeProviderSession] = []

    def factory(account, folder_row):
        fake = _FakeProviderSession()
        built.append(fake)
        return fake

    manager = _manager(accounts, folders, factory)
    manager._load_candidates = lambda: [cand]  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        # Budget exhausted -> backoff state, account back on polling.
        assert _wait_until(lambda: manager.snapshot().get(acc_id) == "backoff")
        assert manager.held_account_ids() == set()
        # The session was not deregistered: it reconnects and retries
        # the catch-up on its own cycle.
        assert set(manager._sessions) == {acc_id}  # noqa: SLF001
        assert _wait_until(lambda: len(built) >= 2)
    finally:
        manager.stop()


def test_stopped_manager_accepts_no_new_sessions():
    """AC-004: after stop(), neither reconcile nor a direct open may
    create a session."""
    acc_id, folder_id = uuid.uuid4(), uuid.uuid4()
    accounts = {acc_id: _account(acc_id)}
    folders = {folder_id: _folder(folder_id, acc_id)}
    cand = _candidate(acc_id, folder_id, minutes_ago=5, fingerprint="fp")
    calls: list[uuid.UUID] = []

    def factory(account, folder_row):
        calls.append(account.id)
        return _FakeProviderSession()

    manager = _manager(accounts, folders, factory)
    manager._load_candidates = lambda: [cand]  # noqa: SLF001
    manager._reconcile_once()  # noqa: SLF001
    assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
    manager.stop()
    calls_after_stop = len(calls)
    manager._reconcile_once()  # noqa: SLF001 - returns early on stop
    manager._open_session(cand)  # noqa: SLF001 - guarded by the stop flag
    assert manager._sessions == {}  # noqa: SLF001
    assert len(calls) == calls_after_stop
