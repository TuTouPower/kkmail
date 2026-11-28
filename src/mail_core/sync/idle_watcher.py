"""IMAP IDLE inbox watcher runtime (t061 AC-001..AC-007, t100).

Maintains at most one long-lived IDLE connection per eligible IMAP
account, on the inbox only. IDLE is a wake-up signal: a change notice
enqueues the existing ``SYNC_FOLDER_DELTA`` job under its existing
dedupe key; all fetching still flows through the delta pipeline
(baseline gate, account lease, fencing untouched). Every successful
session establishment (first connect, reconnect, credential or seat
rebuild) also enqueues one catch-up delta under the same key, because
IDLE only reports changes observed after subscription and the held
account skips t057 polling; catch-up enqueue failures are retried with
bounded backoff, and exhausting the budget drops the subscription so
t057 polling covers the account until the next reconnect.

Responsibilities are split three ways (t100):

- ``idle_policy`` — the pure seat policy (candidate ranking,
  hysteresis, backoff curve). No I/O.
- ``IdleWatchSession`` — one per account; alone owns its provider
  connection: establishment, renewal, reconnect, change notification
  and the bounded catch-up compensation.
- ``IdleWatcherManager`` — alone owns seat allocation, the registry
  of closing resources and state publication. A session may commit
  state or release its seat only while it is the instance registered
  for its account, so a stale thread can never overwrite or tear down
  its successor.

Two notions are kept distinct throughout: a session whose threads
have not exited still *occupies* a quota seat (the seat is handed
over only once both the execution thread and the provider reader
thread have exited), while only a session with a live subscription
*suppresses polling* for its account. A session in backoff or in
closing therefore still consumes quota but no longer holds the
account back from t057 polling.

Long-lived connections live under their own quota (independent of
the ``connection_slots`` task budget). Accounts beyond the quota,
accounts whose servers do not advertise IDLE, and accounts in
failure backoff simply keep the t057 polling behaviour — the watcher
never marks an account failed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from sqlalchemy import func, select

from mail_core.mail.domain.enums import ExecutionOrigin, FolderRemoteState, JobType
from mail_core.mail.storage.models import (
    Account,
    AppSetting,
    Folder,
    Message,
    MessageLocation,
    SyncCheckpoint,
    syncable_folder_clauses,
)
from mail_core.providers.base import IdleNotSupportedError
from mail_core.sync.idle_policy import (
    IdleCandidate,
    IdleWatcherConfig,
    backoff_delay,
    rank_key,
    select_idle_holders,
)
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.sync.idle_watcher")

# Bounded retry for the connect-time catch-up only. A transient DB error
# must not strand a held account; after the budget, releasing the seat is
# cheaper than keeping it without a successful reconciliation.
_CATCHUP_RETRY_ATTEMPTS = 3
_CATCHUP_RETRY_BASE_S = 0.2
_CATCHUP_RETRY_MAX_S = 2.0

_IDLE_STATE_KEY = "worker:idle_state"
# States in which the session's IDLE subscription is live: only these
# suppress t057 inbox polling for the account. Occupying a seat is a
# separate notion (see _ClosingResource).
_SUBSCRIBED_STATES = frozenset({"idling", "changed"})
# A blocked fingerprint (no IDLE capability / permanent auth error) is
# retried after this interval even if the fingerprint never changes, so
# an out-of-band credential fix cannot leave an account blocked forever.
_BLOCKED_RETRY_S = 3600.0


class _SessionHost(Protocol):
    """The manager side of the session contract.

    Both callbacks are ownership-checked by the manager: they take
    effect only while ``session`` is the instance registered for its
    account.
    """

    def session_state_changed(self, session: "IdleWatchSession", state: str) -> None: ...

    def session_blocked(self, session: "IdleWatchSession") -> None: ...


class IdleWatchSession:
    """One account's IDLE watch: owns its connection end to end.

    The session alone establishes, renews and re-establishes the
    provider IDLE connection, turns change notifications into delta
    enqueues, and runs the bounded catch-up compensation after every
    successful (re)subscription. It reports state transitions and
    capability/auth blocks to its host; whether a report is committed
    is the host's decision (ownership guard), never the session's.
    """

    def __init__(
        self,
        *,
        account_id: uuid.UUID,
        folder_id: uuid.UUID,
        fingerprint: str,
        account_snapshot: Account,
        folder_snapshot: Folder,
        session_factory: Callable[[], Any],
        idle_session_factory: Callable[[Account, Folder], Any],
        config: IdleWatcherConfig,
        host: _SessionHost | None = None,
    ) -> None:
        self.account_id = account_id
        self.folder_id = folder_id
        self.fingerprint = fingerprint
        self.account_snapshot = account_snapshot
        self.folder_remote_id = folder_snapshot.remote_id
        self._folder_snapshot = folder_snapshot
        self._session_factory = session_factory
        self._idle_session_factory = idle_session_factory
        self._config = config
        self._host = host
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        # The live provider IDLE session and its reader thread, owned
        # by this watch's execution thread; the manager reads them to
        # abort a stuck close and to know when the seat is truly free.
        self.provider_session: Any | None = None
        self.last_reader: threading.Thread | None = None
        self.state = "connecting"

    # -- lifecycle, driven by the manager -----------------------------------

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name=f"imap-idle-{self.account_id}",
            daemon=True,
        )
        self.thread.start()

    def request_stop(self) -> None:
        self.stop_event.set()

    def abort_provider(self) -> None:
        abort = getattr(self.provider_session, "abort", None)
        if callable(abort):
            try:
                abort()
            except Exception:
                pass

    def reader_thread(self) -> threading.Thread | None:
        reader = getattr(self.provider_session, "reader_thread", None)
        if isinstance(reader, threading.Thread):
            return reader
        return self.last_reader

    def has_live_threads(self) -> bool:
        if self.thread is not None and self.thread.is_alive():
            return True
        reader = self.reader_thread()
        return reader is not None and reader.is_alive()

    # -- state reporting ------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.state = state
        if self._host is not None:
            self._host.session_state_changed(self, state)

    def _register_blocked(self) -> None:
        if self._host is not None:
            self._host.session_blocked(self)

    # -- the watch loop ---------------------------------------------------------

    def _run(self) -> None:
        from mail_core.providers.http import PermanentAuthError

        attempts = 0
        while not self.stop_event.is_set():
            provider = None
            try:
                provider = self._idle_session_factory(self.account_snapshot, self._folder_snapshot)
            except (IdleNotSupportedError, PermanentAuthError):
                self._register_blocked()
                return
            except Exception as exc:
                from mail_core.security.redact import safe_error

                log.warning(
                    "idle connect failed for account %s: %s",
                    self.account_id,
                    safe_error(exc),
                )
                attempts += 1
                self._set_state("backoff")
                if self.stop_event.wait(backoff_delay(attempts, self._config)):
                    return
                continue

            reader = getattr(provider, "reader_thread", None)
            self.provider_session = provider
            if isinstance(reader, threading.Thread):
                self.last_reader = reader
            catchup_ok = True
            try:
                if self.stop_event.is_set():
                    return
                attempts = 0
                self._record_connect_success()
                self._set_state("idling")
                if not self._enqueue_catchup():
                    # Persistent enqueue failure: drop the subscription
                    # so t057 inbox polling can cover the account until
                    # the next reconnect retries the catch-up.
                    self._set_state("backoff")
                    attempts += 1
                    catchup_ok = False
                else:
                    while not self.stop_event.is_set():
                        outcome = provider.wait_for_change(
                            timeout_s=self._config.max_duration_s,
                            stop_event=self.stop_event,
                        )
                        if outcome == "changed":
                            self._set_state("changed")
                            self._enqueue_delta()
                            self._set_state("idling")
                        elif outcome == "stopped":
                            return
                        # "timeout": fall through and re-enter IDLE.
            except Exception as exc:
                from mail_core.providers.imap import IdleSessionDisconnected
                from mail_core.security.redact import safe_error

                if not isinstance(exc, IdleSessionDisconnected):
                    log.warning(
                        "idle session error for account %s: %s",
                        self.account_id,
                        safe_error(exc),
                    )
                attempts += 1
                self._set_state("backoff")
            finally:
                if provider is not None:
                    try:
                        provider.close()
                    except Exception:
                        pass
                self.provider_session = None
            if not catchup_ok and self.stop_event.is_set():
                return
            if self.stop_event.wait(backoff_delay(attempts, self._config)):
                return

    def _record_connect_success(self) -> None:
        """A successful IDLE session is a provider round-trip: close the breaker."""

        from mail_core.accounts.health import record_connectivity_success

        try:
            with self._session_factory() as db_session:
                record_connectivity_success(db_session, self.account_id)
                db_session.commit()
        except Exception:
            log.debug("idle connectivity reset failed for account %s", self.account_id, exc_info=True)

    def _enqueue_catchup(self) -> bool:
        """Reconcile the gap before this IDLE session reports changes.

        IDLE only signals changes observed after the subscription starts;
        ``SELECT``'s current EXISTS snapshot is discarded by the provider.
        Anything that arrived while no session was active is therefore
        invisible unless a delta runs. Enqueue the same deduplicated
        delta used by IDLE wake-ups and t057 so a reconnect always
        converges without bypassing the baseline gate, lease or fencing.

        Retries a transient enqueue failure with bounded backoff. Returns
        False when the budget is exhausted or the watch is stopping; the
        caller must then drop the subscription so t057 polling covers
        the account and the next reconnect retries the catch-up.
        """
        for attempt in range(1, _CATCHUP_RETRY_ATTEMPTS + 1):
            try:
                self._enqueue_delta()
                return True
            except Exception:
                if attempt == _CATCHUP_RETRY_ATTEMPTS:
                    log.exception(
                        "idle catch-up delta enqueue failed for account %s; "
                        "releasing the IDLE seat for polling",
                        self.account_id,
                    )
                    return False
                delay = min(
                    _CATCHUP_RETRY_BASE_S * (2 ** (attempt - 1)),
                    _CATCHUP_RETRY_MAX_S,
                )
                log.warning(
                    "idle catch-up delta enqueue failed for account %s; "
                    "retrying in %.2fs (%d/%d)",
                    self.account_id,
                    delay,
                    attempt,
                    _CATCHUP_RETRY_ATTEMPTS,
                )
                if self.stop_event.wait(delay):
                    return False
        return False

    def _enqueue_delta(self) -> None:
        with self._session_factory() as db_session:
            enqueue_job(
                db_session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                execution_origin=ExecutionOrigin.BACKGROUND,
                account_id=self.account_id,
                payload={"folder_id": str(self.folder_id)},
                priority=60,
                dedupe_key=f"delta:{self.account_id}:{self.folder_id}",
            )
            db_session.commit()


@dataclass
class _ClosingResource:
    """A retired watch session whose threads have not fully exited.

    The resource keeps occupying its quota seat until BOTH the watch
    execution thread and the provider reader thread have exited; only
    then may the seat be handed to a new watch. The subscription is
    already gone at this point, so the account polls again while the
    seat is still occupied.
    """

    watch: IdleWatchSession

    def is_exited(self) -> bool:
        return not self.watch.has_live_threads()

    def abort_provider(self) -> None:
        self.watch.abort_provider()


class IdleWatcherManager:
    """Owns all IDLE watch sessions for this worker process.

    The manager alone allocates quota seats (via ``idle_policy``),
    tracks closing resources until their threads exit, and publishes
    the aggregate state. Sessions report through the host callbacks;
    a report is committed only while the reporting session is the
    instance registered for its account.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        idle_session_factory: Callable[[Account, Folder], Any] | None = None,
        config: IdleWatcherConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._idle_session_factory = idle_session_factory or _default_idle_session_factory
        if config is None:
            from mail_core.config import get_config

            config = IdleWatcherConfig.from_app_config(get_config())
        self._config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: dict[uuid.UUID, IdleWatchSession] = {}
        self._closing: list[_ClosingResource] = []
        self._states: dict[uuid.UUID, str] = {}
        # account_id -> (fingerprint, blocked_at monotonic)
        self._blocked: dict[uuid.UUID, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # -- session host callbacks (ownership-guarded) ---------------------------

    def session_state_changed(self, session: IdleWatchSession, state: str) -> None:
        """Commit a session's state, guarded by watch identity.

        A stale thread (replaced while stuck in connect) must not
        overwrite its successor's state.
        """
        with self._lock:
            if self._sessions.get(session.account_id) is session:
                self._states[session.account_id] = state

    def session_blocked(self, session: IdleWatchSession) -> None:
        """Record a capability/auth block and deregister this session.

        Deregistration is load-bearing: while a dead session entry
        stays registered, reconcile's open loop skips the account
        before ever consulting ``_blocked``, so neither a fingerprint
        change nor the blocked-age expiry could ever retry it. The
        account keeps polling (t057) in the meantime. A stale session
        whose successor is already registered must not clobber the
        successor's state or block record.
        """
        with self._lock:
            current = self._sessions.get(session.account_id)
            if current is not None and current is not session:
                return
            self._blocked[session.account_id] = (session.fingerprint, time.monotonic())
            if current is session:
                self._sessions.pop(session.account_id, None)
            self._states[session.account_id] = "fallback"

    # -- public surface ----------------------------------------------------

    def start(self) -> None:
        if not self._config.enabled:
            log.info("idle watcher disabled by configuration")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._reconcile_loop, name="imap-idle-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._prune_closing_locked()
            closing = list(self._closing)
        # Wake every session before joining: a catch-up enqueue runs on
        # these threads, so serial set+join would multiply the shutdown
        # latency by the number of held seats.
        for session in sessions:
            session.request_stop()
        deadline = time.monotonic() + 5.0
        for session in sessions:
            # A session registered by _open_session just before start()
            # returns has no OS thread yet; joining it raises
            # RuntimeError. Its loop observes the stop flags as soon as
            # it starts.
            thread = session.thread
            if thread is None or thread.ident is None:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=min(remaining, self._config.close_timeout_s))
            if thread.is_alive():
                session.abort_provider()
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        for resource in closing:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread = resource.watch.thread
            if thread is not None and thread.ident is not None and thread.is_alive():
                resource.abort_provider()
                thread.join(timeout=remaining)
        with self._lock:
            for session in sessions:
                if session.has_live_threads():
                    self._record_closing_locked(session)
            self._prune_closing_locked()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def held_account_ids(self) -> set[uuid.UUID]:
        """Accounts whose live subscription suppresses inbox polling.

        This is subscription validity, not seat occupancy: a session
        in backoff or in closing no longer suppresses polling even
        while its threads still occupy a quota seat. The set is
        derived from the committed states, so it can never disagree
        with the published aggregate state.
        """
        with self._lock:
            return {
                account_id
                for account_id in self._sessions
                if self._states.get(account_id) in _SUBSCRIBED_STATES
            }

    def snapshot(self) -> dict[uuid.UUID, str]:
        with self._lock:
            return dict(self._states)

    # -- closing-resource registry -------------------------------------------

    def _prune_closing_locked(self) -> int:
        self._closing = [r for r in self._closing if not r.is_exited()]
        return len(self._closing)

    def _record_closing_locked(self, session: IdleWatchSession) -> None:
        if not session.has_live_threads():
            return
        if any(r.watch is session for r in self._closing):
            return
        self._closing.append(_ClosingResource(watch=session))

    def _occupied_seats_locked(self) -> int:
        """Active sessions plus closing resources: the quota charge."""
        return len(self._sessions) + len(self._closing)

    # -- reconcile ----------------------------------------------------------

    def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._reconcile_once()
            except Exception:
                log.exception("idle watcher reconcile failed")
            self._stop.wait(self._config.reconcile_interval_s)

    def _reconcile_once(self) -> None:
        if self._stop.is_set():
            return
        candidates = self._load_candidates()
        if self._stop.is_set():
            return
        now = datetime.now(timezone.utc)
        # Sweep residual state for accounts that left the candidate set
        # while blocked (disabled / paused / deleted): their deregistered
        # sessions never pass through the close loop below, so without
        # this their fallback state and block record would linger in the
        # published snapshot for the process lifetime.
        candidate_ids = {c.account_id for c in candidates}
        with self._lock:
            self._prune_closing_locked()
            stale_ids = (set(self._states) | set(self._blocked)) - candidate_ids - set(self._sessions)
            for stale_id in stale_ids:
                self._states.pop(stale_id, None)
                self._blocked.pop(stale_id, None)
            current = set(self._sessions)
        desired = select_idle_holders(
            candidates,
            current_holders=current,
            quota=self._config.quota,
            hysteresis_s=self._config.hysteresis_s,
            now=now,
        )
        ranked_candidates = sorted(candidates, key=rank_key)
        by_id = {c.account_id: c for c in ranked_candidates}

        # Close sessions that lost their seat, became ineligible, or
        # whose credential fingerprint changed.
        with self._lock:
            sessions = dict(self._sessions)
        to_close: list[uuid.UUID] = []
        for account_id, session in sessions.items():
            candidate = by_id.get(account_id)
            if (
                account_id not in desired
                or candidate is None
                or candidate.credential_fingerprint != session.fingerprint
            ):
                session.request_stop()
                to_close.append(account_id)
        for account_id in to_close:
            self._close_session(account_id)
            with self._lock:
                self._states.pop(account_id, None)

        # Open sessions for desired accounts not yet watched and not
        # blocked under their current fingerprint. Closing resources
        # continue to occupy quota seats until their threads exit.
        for candidate in ranked_candidates:
            if self._stop.is_set():
                return
            account_id = candidate.account_id
            if account_id not in desired:
                continue
            with self._lock:
                self._prune_closing_locked()
                if self._occupied_seats_locked() >= self._config.quota:
                    break
                if account_id in self._sessions:
                    continue
                blocked = self._blocked.get(account_id)
                if blocked is not None:
                    blocked_fingerprint, blocked_at = blocked
                    still_blocked = blocked_fingerprint == candidate.credential_fingerprint and (
                        time.monotonic() - blocked_at
                    ) < _BLOCKED_RETRY_S
                    if still_blocked:
                        self._states[account_id] = "fallback"
                        continue
                    # Fingerprint changed or the block aged out: retry.
                    self._blocked.pop(account_id, None)
            self._open_session(candidate)
        self._publish_state()

    def _load_candidates(self) -> list[IdleCandidate]:
        with self._session_factory() as session:
            rows = list(
                session.execute(
                    select(Account, Folder, SyncCheckpoint)
                    .join(Folder, Folder.account_id == Account.id)
                    .join(
                        SyncCheckpoint,
                        (SyncCheckpoint.account_id == Account.id)
                        & (SyncCheckpoint.folder_id == Folder.id),
                    )
                    .where(
                        Account.sync_enabled.is_(True),
                        Account.provider == "imap",
                        Folder.role == "inbox",
                        *syncable_folder_clauses(),
                        SyncCheckpoint.full_scan_complete.is_(True),
                    )
                ).all()
            )
            if not rows:
                return []
            inbox_folder_ids = [folder.id for _account, folder, _cp in rows]
            account_ids = [account.id for account, _folder, _cp in rows]
            # Seat keys come from the mail itself, aggregated in SQL:
            # per inbox folder, the newest server arrival time
            # (Message.sort_time, i.e. IMAP INTERNALDATE) over the
            # messages currently located there. A folder whose located
            # messages all lack an arrival timestamp still forms a
            # GROUP BY group (max is NULL), which is how "inbox holds
            # mail" is told apart from "inbox is empty".
            inbox_latest: dict[uuid.UUID, datetime | None] = dict(
                session.execute(
                    select(MessageLocation.folder_id, func.max(Message.sort_time))
                    .join(Message, Message.id == MessageLocation.message_id)
                    .where(MessageLocation.folder_id.in_(inbox_folder_ids))
                    .group_by(MessageLocation.folder_id)
                ).all()
            )
            other_latest: dict[uuid.UUID, datetime | None] = dict(
                session.execute(
                    select(Folder.account_id, func.max(Message.sort_time))
                    .select_from(Folder)
                    .join(MessageLocation, MessageLocation.folder_id == Folder.id)
                    .join(Message, Message.id == MessageLocation.message_id)
                    .where(
                        Folder.account_id.in_(account_ids),
                        Folder.id.notin_(inbox_folder_ids),
                        Folder.remote_state == FolderRemoteState.ACTIVE.value,
                    )
                    .group_by(Folder.account_id)
                ).all()
            )
            candidates: list[IdleCandidate] = []
            for account, folder, _cp in rows:
                created_at = _aware(account.created_at)
                if created_at is None:  # created_at is server-defaulted; defensive only
                    created_at = datetime.min.replace(tzinfo=timezone.utc)
                candidates.append(
                    IdleCandidate(
                        account_id=account.id,
                        folder_id=folder.id,
                        inbox_latest_arrival_at=_aware(inbox_latest.get(folder.id)),
                        inbox_has_messages=folder.id in inbox_latest,
                        other_latest_arrival_at=_aware(other_latest.get(account.id)),
                        account_created_at=created_at,
                        credential_fingerprint=_fingerprint(account, folder),
                    )
                )
            return candidates

    # -- per-account session lifecycle -----------------------------------------

    def _open_session(self, candidate: IdleCandidate) -> None:
        with self._session_factory() as db_session:
            account = db_session.get(Account, candidate.account_id)
            folder = db_session.get(Folder, candidate.folder_id)
            if account is None or folder is None:
                return
            account_snapshot = Account(
                id=account.id,
                email=account.email,
                provider=account.provider,
                credential_ref=account.credential_ref,
                config=dict(account.config or {}),
            )
            folder_snapshot = Folder(
                id=folder.id,
                account_id=folder.account_id,
                remote_id=folder.remote_id,
                name=folder.name,
                role=folder.role,
                kind=folder.kind,
                selectable=folder.selectable,
                remote_state=folder.remote_state,
            )
        session = IdleWatchSession(
            account_id=candidate.account_id,
            folder_id=candidate.folder_id,
            fingerprint=candidate.credential_fingerprint,
            account_snapshot=account_snapshot,
            folder_snapshot=folder_snapshot,
            session_factory=self._session_factory,
            idle_session_factory=self._idle_session_factory,
            config=self._config,
            host=self,
        )
        with self._lock:
            self._prune_closing_locked()
            if (
                self._stop.is_set()
                or candidate.account_id in self._sessions
                or self._occupied_seats_locked() >= self._config.quota
            ):
                return
            self._sessions[candidate.account_id] = session
            self._states[candidate.account_id] = "connecting"
            session.start()

    def _close_session(self, account_id: uuid.UUID) -> None:
        with self._lock:
            session = self._sessions.pop(account_id, None)
        if session is None:
            return
        session.request_stop()
        thread = session.thread
        if thread is None or thread.ident is None:
            return
        thread.join(timeout=self._config.close_timeout_s)
        if thread.is_alive():
            session.abort_provider()
            thread.join(timeout=0.5)
        with self._lock:
            self._record_closing_locked(session)
            self._prune_closing_locked()

    # -- state publication ------------------------------------------------------

    def _publish_state(self) -> None:
        """Expose watcher states on the existing AppSetting status store."""
        try:
            states = self.snapshot()
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "states": {str(k): v for k, v in states.items()},
                "held": [str(k) for k in self.held_account_ids()],
            }
            with self._session_factory() as db_session:
                row = db_session.get(AppSetting, _IDLE_STATE_KEY)
                if row is None:
                    db_session.add(AppSetting(key=_IDLE_STATE_KEY, value=json.dumps(payload, sort_keys=True)))
                else:
                    row.value = json.dumps(payload, sort_keys=True)
                db_session.commit()
        except Exception:
            log.debug("idle watcher state publish failed", exc_info=True)


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a DB timestamp to tz-aware UTC (SQLite returns naive)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _fingerprint(account: Account, folder: Folder) -> str:
    # Stable credential identity only. Account ``updated_at`` changes on
    # health bookkeeping after a successful connect, so including it made
    # every reconcile rotate the IDLE seat even though credentials were
    # unchanged (t073 churn / retry-count failures).
    return f"{account.credential_ref or ''}|{account.provider}|{account.id}|{folder.id}"


def _default_idle_session_factory(account: Account, folder: Folder) -> Any:
    from mail_core.providers.factory import build_provider

    provider = build_provider(account)
    return provider.open_idle_session(folder.remote_id)


# Module-level singleton used by the worker process (embedded + standalone).
_manager: IdleWatcherManager | None = None
_manager_lock = threading.Lock()


def get_idle_manager(session_factory: Callable[[], Any] | None = None) -> IdleWatcherManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            if session_factory is None:
                from mail_core.db.session import get_session_factory

                session_factory = get_session_factory()
            _manager = IdleWatcherManager(session_factory)
        return _manager


def held_idle_account_ids() -> set[uuid.UUID]:
    """Accounts currently holding a live IDLE subscription (empty outside the worker)."""
    with _manager_lock:
        manager = _manager
    if manager is None:
        return set()
    return manager.held_account_ids()
