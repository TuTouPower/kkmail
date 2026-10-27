"""IMAP IDLE inbox watcher (t061 AC-001..AC-007).

Maintains at most one long-lived IDLE connection per eligible IMAP
account, on the inbox only. IDLE is a wake-up signal: a change notice
enqueues the existing ``SYNC_FOLDER_DELTA`` job under its existing
dedupe key; all fetching still flows through the delta pipeline
(baseline gate, account lease, fencing untouched).

Long-lived connections live under their own quota (independent of the
``connection_slots`` task budget): quota seats go to the most recently
active accounts, with hysteresis so borderline accounts do not churn
connections. Accounts beyond the quota, accounts whose servers do not
advertise IDLE, and accounts in failure backoff simply keep the t057
polling behaviour — the watcher never marks an account failed.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, AppSetting, Folder, SyncCheckpoint
from mail_core.providers.base import IdleNotSupportedError
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.sync.idle_watcher")

_IDLE_STATE_KEY = "worker:idle_state"
_LIVE_STATES = frozenset({"connecting", "idling", "changed"})
# A blocked fingerprint (no IDLE capability / permanent auth error) is
# retried after this interval even if the fingerprint never changes, so
# an out-of-band credential fix cannot leave an account blocked forever.
_BLOCKED_RETRY_S = 3600.0



@dataclass(frozen=True)
class IdleWatcherConfig:
    enabled: bool = True
    quota: int = 32
    max_duration_s: float = 1680.0
    backoff_base_s: float = 5.0
    backoff_max_s: float = 300.0
    hysteresis_s: float = 300.0
    reconcile_interval_s: float = 15.0

    @classmethod
    def from_app_config(cls, cfg: Any) -> "IdleWatcherConfig":
        return cls(
            enabled=bool(cfg.idle_enabled),
            quota=int(cfg.idle_quota),
            max_duration_s=float(cfg.idle_max_duration_s),
            backoff_base_s=float(cfg.idle_backoff_base_s),
            backoff_max_s=float(cfg.idle_backoff_max_s),
            hysteresis_s=float(cfg.idle_hysteresis_s),
        )


@dataclass(frozen=True)
class AccountActivity:
    account_id: uuid.UUID
    folder_id: uuid.UUID
    last_activity_at: datetime
    credential_fingerprint: str


def backoff_delay(attempt: int, config: IdleWatcherConfig, *, jitter_fraction: float | None = None) -> float:
    """Exponential backoff with up to +100% jitter (AC-003 spreading)."""
    base = min(config.backoff_max_s, config.backoff_base_s * (2**attempt))
    fraction = random.random() if jitter_fraction is None else jitter_fraction
    return base * (1.0 + fraction)


def select_idle_holders(
    candidates: list[AccountActivity],
    *,
    current_holders: set[uuid.UUID],
    quota: int,
    hysteresis_s: float,
    now: datetime,
) -> set[uuid.UUID]:
    """Choose which accounts hold IDLE seats (AC-005).

    Top-``quota`` by recent activity wins; an incumbent outside the top
    set keeps its seat unless the weakest challenger is hotter by more
    than ``hysteresis_s`` — this prevents connection churn when two
    accounts have near-identical activity.
    """
    ranked = sorted(
        candidates,
        key=lambda c: (-c.last_activity_at.timestamp(), str(c.account_id)),
    )
    by_id = {c.account_id: c for c in ranked}
    selected: set[uuid.UUID] = {c.account_id for c in ranked[:quota]}

    for incumbent in ranked:
        if incumbent.account_id not in current_holders or incumbent.account_id in selected:
            continue
        challengers = [aid for aid in selected if aid not in current_holders]
        if not challengers:
            break
        weakest = min(
            challengers, key=lambda aid: by_id[aid].last_activity_at.timestamp()
        )
        advantage = (
            by_id[weakest].last_activity_at - incumbent.last_activity_at
        ).total_seconds()
        if advantage <= hysteresis_s:
            selected.discard(weakest)
            selected.add(incumbent.account_id)
    return selected


@dataclass
class _Watch:
    account_id: uuid.UUID
    folder_id: uuid.UUID
    fingerprint: str
    account_snapshot: Account
    folder_remote_id: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class IdleWatcherManager:
    """Owns all IDLE watch threads for this worker process."""

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
        self._watches: dict[uuid.UUID, _Watch] = {}
        self._states: dict[uuid.UUID, str] = {}
        # account_id -> (fingerprint, blocked_at monotonic)
        self._blocked: dict[uuid.UUID, tuple[str, float]] = {}
        self._lock = threading.Lock()

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
            watches = list(self._watches.values())
            self._watches.clear()
        for watch in watches:
            watch.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def held_account_ids(self) -> set[uuid.UUID]:
        with self._lock:
            return {
                account_id
                for account_id, state in self._states.items()
                if state in _LIVE_STATES and account_id in self._watches
            }

    def snapshot(self) -> dict[uuid.UUID, str]:
        with self._lock:
            return dict(self._states)

    # -- reconcile ----------------------------------------------------------

    def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._reconcile_once()
            except Exception:
                log.exception("idle watcher reconcile failed")
            self._stop.wait(self._config.reconcile_interval_s)

    def _reconcile_once(self) -> None:
        candidates = self._load_candidates()
        now = datetime.now(timezone.utc)
        # Sweep residual state for accounts that left the candidate set
        # while blocked (disabled / paused / deleted): their deregistered
        # watches never pass through the close loop below, so without
        # this their fallback state and block record would linger in the
        # published snapshot for the process lifetime.
        candidate_ids = {c.account_id for c in candidates}
        with self._lock:
            stale_ids = (set(self._states) | set(self._blocked)) - candidate_ids - set(self._watches)
            for stale_id in stale_ids:
                self._states.pop(stale_id, None)
                self._blocked.pop(stale_id, None)
            current = set(self._watches)
        desired = select_idle_holders(
            candidates,
            current_holders=current,
            quota=self._config.quota,
            hysteresis_s=self._config.hysteresis_s,
            now=now,
        )
        by_id = {c.account_id: c for c in candidates}

        # Close watches that lost their seat, became ineligible, or whose
        # credential fingerprint changed (AC-006).
        with self._lock:
            watches = dict(self._watches)
        for account_id, watch in watches.items():
            candidate = by_id.get(account_id)
            if (
                account_id not in desired
                or candidate is None
                or candidate.credential_fingerprint != watch.fingerprint
            ):
                self._close_watch(account_id)
                with self._lock:
                    self._states.pop(account_id, None)

        # Open watches for desired accounts not yet watched and not
        # blocked under their current fingerprint.
        for account_id in desired:
            candidate = by_id[account_id]
            with self._lock:
                if account_id in self._watches:
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
            self._open_watch(candidate)
        self._publish_state()

    def _load_candidates(self) -> list[AccountActivity]:
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
                        Folder.sync_status != SyncStatus.PAUSED.value,
                        SyncCheckpoint.full_scan_complete.is_(True),
                    )
                ).all()
            )
            candidates: list[AccountActivity] = []
            for account, folder, cp in rows:
                activity = cp.updated_at or account.updated_at or account.created_at
                if activity is not None and activity.tzinfo is None:
                    activity = activity.replace(tzinfo=timezone.utc)
                fingerprint = _fingerprint(account, folder)
                candidates.append(
                    AccountActivity(
                        account_id=account.id,
                        folder_id=folder.id,
                        last_activity_at=activity,
                        credential_fingerprint=fingerprint,
                    )
                )
            return candidates

    # -- per-account watch ---------------------------------------------------

    def _open_watch(self, candidate: AccountActivity) -> None:
        with self._session_factory() as session:
            account = session.get(Account, candidate.account_id)
            folder = session.get(Folder, candidate.folder_id)
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
                sync_status=folder.sync_status,
            )
        watch = _Watch(
            account_id=candidate.account_id,
            folder_id=candidate.folder_id,
            fingerprint=candidate.credential_fingerprint,
            account_snapshot=account_snapshot,
            folder_remote_id=folder_snapshot.remote_id,
        )
        watch.thread = threading.Thread(
            target=self._watch_loop,
            args=(watch, folder_snapshot),
            name=f"imap-idle-{candidate.account_id}",
            daemon=True,
        )
        with self._lock:
            self._watches[candidate.account_id] = watch
            self._states[candidate.account_id] = "connecting"
        watch.thread.start()

    def _close_watch(self, account_id: uuid.UUID) -> None:
        with self._lock:
            watch = self._watches.pop(account_id, None)
        if watch is not None:
            watch.stop_event.set()
            if watch.thread is not None:
                watch.thread.join(timeout=5.0)

    def _watch_loop(self, watch: _Watch, folder_snapshot: Folder) -> None:
        from mail_core.providers.http import PermanentAuthError

        attempts = 0
        while not self._stop.is_set() and not watch.stop_event.is_set():
            session = None
            try:
                session = self._idle_session_factory(watch.account_snapshot, folder_snapshot)
            except IdleNotSupportedError:
                self._register_blocked(watch)
                return
            except PermanentAuthError:
                self._register_blocked(watch)
                return
            except Exception as exc:
                from mail_core.security.redact import safe_error

                log.warning(
                    "idle connect failed for account %s: %s",
                    watch.account_id,
                    safe_error(exc),
                )
                attempts += 1
                self._set_state(watch, "backoff")
                if watch.stop_event.wait(backoff_delay(attempts, self._config)):
                    return
                continue

            attempts = 0
            self._set_state(watch, "idling")
            try:
                while not self._stop.is_set() and not watch.stop_event.is_set():
                    outcome = session.wait_for_change(
                        timeout_s=self._config.max_duration_s,
                        stop_event=watch.stop_event,
                    )
                    if outcome == "changed":
                        self._set_state(watch, "changed")
                        self._enqueue_delta(watch)
                        self._set_state(watch, "idling")
                    elif outcome == "stopped":
                        return
                    # "timeout": fall through and re-enter IDLE.
            except Exception as exc:
                from mail_core.providers.imap import IdleSessionDisconnected
                from mail_core.security.redact import safe_error

                if not isinstance(exc, IdleSessionDisconnected):
                    log.warning(
                        "idle session error for account %s: %s",
                        watch.account_id,
                        safe_error(exc),
                    )
                attempts += 1
                self._set_state(watch, "backoff")
            finally:
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
            if watch.stop_event.wait(backoff_delay(attempts, self._config)):
                return

    def _register_blocked(self, watch: _Watch) -> None:
        """Record a capability/auth block and deregister this watch.

        Deregistration is load-bearing: while a dead watch entry stays
        in ``_watches``, reconcile's open loop skips the account before
        ever consulting ``_blocked``, so neither a fingerprint change
        nor the blocked-age expiry could ever retry it (AC-006). The
        account keeps polling (t057) in the meantime.
        """
        with self._lock:
            current = self._watches.get(watch.account_id)
            if current is not None and current is not watch:
                # A newer watch already replaced this thread (it was
                # stuck in connect while reconcile rotated the seat):
                # the stale thread must not clobber the new watch's
                # state or block record.
                return
            self._blocked[watch.account_id] = (watch.fingerprint, time.monotonic())
            if current is watch:
                self._watches.pop(watch.account_id, None)
            self._states[watch.account_id] = "fallback"

    def _enqueue_delta(self, watch: _Watch) -> None:
        with self._session_factory() as session:
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=watch.account_id,
                payload={"folder_id": str(watch.folder_id)},
                priority=60,
                dedupe_key=f"delta:{watch.account_id}:{watch.folder_id}",
            )
            session.commit()

    def _set_state(self, watch: _Watch, state: str) -> None:
        """Write a watch state, guarded by watch identity.

        A stale thread (replaced while stuck in connect) must not
        overwrite its successor's state — same guard as
        ``_register_blocked``.
        """
        with self._lock:
            if self._watches.get(watch.account_id) is watch:
                self._states[watch.account_id] = state

    def _publish_state(self) -> None:
        """Expose watcher states on the existing AppSetting status store."""
        try:
            states = self.snapshot()
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "states": {str(k): v for k, v in states.items()},
                "held": [str(k) for k in self.held_account_ids()],
            }
            with self._session_factory() as session:
                row = session.get(AppSetting, _IDLE_STATE_KEY)
                if row is None:
                    session.add(AppSetting(key=_IDLE_STATE_KEY, value=json.dumps(payload, sort_keys=True)))
                else:
                    row.value = json.dumps(payload, sort_keys=True)
                session.commit()
        except Exception:
            log.debug("idle watcher state publish failed", exc_info=True)


def _fingerprint(account: Account, folder: Folder) -> str:
    updated = account.updated_at.isoformat() if account.updated_at else ""
    return f"{account.credential_ref or ''}|{updated}|{folder.id}"


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
    """Accounts currently holding an IDLE seat (empty outside the worker)."""
    with _manager_lock:
        manager = _manager
    if manager is None:
        return set()
    return manager.held_account_ids()
