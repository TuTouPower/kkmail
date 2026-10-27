"""All-folder STATUS patrol (t061 AC-008..AC-014).

Extends the t057 periodic scheduling idea beyond the inbox: every
non-paused folder of every sync-enabled account is probed on a cycle
with a cheap provider STATUS call. Only a probe whose comparable
dimensions differ from the stored baseline enqueues a
``SYNC_FOLDER_DELTA``; the delta job then converges the folder through
the existing pipeline. The probe baseline lives in the checkpoint
cursor JSONB (``last_status`` / ``last_probe_at``) — no migration.

The patrol itself never writes message data, never triggers a full
metadata scan, and isolates per-folder failures.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint
from mail_core.providers.base import FolderStatus
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.sync.patrol")

_CURSOR_STATUS_KEY = "last_status"
_CURSOR_PROBE_AT_KEY = "last_probe_at"
_CURSOR_FAILURES_KEY = "last_probe_failures"
_DIMENSIONS = ("messages", "uidnext", "unseen", "highestmodseq")


@dataclass
class PatrolConfig:
    enabled: bool = True
    interval_s: float = 1200.0
    max_probes: int = 200
    max_unprobed_s: float = 2400.0

    @classmethod
    def from_app_config(cls, cfg: Any) -> "PatrolConfig":
        return cls(
            enabled=bool(cfg.folder_patrol_enabled),
            interval_s=float(cfg.folder_patrol_interval_s),
            max_probes=int(cfg.folder_patrol_max_probes),
            max_unprobed_s=float(cfg.folder_patrol_max_unprobed_s),
        )


@dataclass
class PatrolResult:
    probed: int = 0
    changed: int = 0
    failed: int = 0
    skipped_not_due: int = 0


def changed_dimensions(baseline: FolderStatus, probe: FolderStatus) -> tuple[str, ...]:
    """Dimensions that provably changed between two snapshots.

    Only dimensions carrying a value on BOTH sides are compared, so a
    server that omits UIDNEXT (Coremail) falls back to count-based
    detection instead of firing on every probe.
    """
    changed: list[str] = []
    for dimension in _DIMENSIONS:
        before = getattr(baseline, dimension)
        after = getattr(probe, dimension)
        if before is not None and after is not None and before != after:
            changed.append(dimension)
    return tuple(changed)


def _default_provider_factory(account: Account):
    from mail_core.providers.factory import build_provider

    return build_provider(account)


def schedule_folder_status_patrol(
    session: Session,
    *,
    config: PatrolConfig | None = None,
    provider_factory: Callable[[Account], Any] | None = None,
    now: datetime | None = None,
) -> PatrolResult:
    """Run one patrol sweep over due folders (oldest-probed first)."""
    if config is None:
        from mail_core.config import get_config

        config = PatrolConfig.from_app_config(get_config())
    result = PatrolResult()
    if not config.enabled:
        return result
    factory = provider_factory or _default_provider_factory
    current_time = now or datetime.now(timezone.utc)
    now_epoch = current_time.timestamp()

    rows = list(
        session.execute(
            select(Folder, Account, SyncCheckpoint)
            .join(Account, Account.id == Folder.account_id)
            .outerjoin(
                SyncCheckpoint,
                (SyncCheckpoint.account_id == Folder.account_id)
                & (SyncCheckpoint.folder_id == Folder.id),
            )
            .where(
                Account.sync_enabled.is_(True),
                Folder.sync_status != SyncStatus.PAUSED.value,
                Folder.role != "inbox",
            )
            .order_by(Account.id, Folder.id)
        ).all()
    )

    due: list[tuple[float, Folder, Account, SyncCheckpoint | None]] = []
    for folder, account, cp in rows:
        cursor = dict(cp.cursor or {}) if cp is not None else {}
        last_probe_at = cursor.get(_CURSOR_PROBE_AT_KEY)
        last_epoch = (
            float(last_probe_at)
            if isinstance(last_probe_at, (int, float)) and not isinstance(last_probe_at, bool)
            else None
        )
        if last_epoch is not None and now_epoch - last_epoch < config.interval_s:
            result.skipped_not_due += 1
            continue
        due.append((last_epoch if last_epoch is not None else 0.0, folder, account, cp))

    # Rotation (AC-013): folders that have never been probed or whose
    # last attempt is older than the max-unprobed bound go first; within
    # each group, least-recently attempted first; capped per sweep.
    def _rotation_key(item: tuple[float, Folder, Account, SyncCheckpoint | None]) -> tuple[int, float, str]:
        last_epoch = item[0]
        critical = last_epoch == 0.0 or (now_epoch - last_epoch) > config.max_unprobed_s
        return (0 if critical else 1, last_epoch, str(item[1].id))

    due.sort(key=_rotation_key)
    selected = due[: config.max_probes]

    def _record_attempt(folder: Folder, account: Account, cp: SyncCheckpoint | None, *, failed: bool) -> SyncCheckpoint:
        """Advance the probe-attempt clock for success AND failure.

        A failed folder must not stay permanently "most overdue":
        retrying it on every 60s scheduler sweep would hammer a
        rate-limited server and starve every other folder (AC-013 /
        AC-014). The attempt timestamp is the due-clock; failures are
        counted separately and cleared on the next success.
        """
        if cp is None:
            cp = SyncCheckpoint(account_id=account.id, folder_id=folder.id, cursor={})
            session.add(cp)
            session.flush()
        cursor = dict(cp.cursor or {})
        cursor[_CURSOR_PROBE_AT_KEY] = now_epoch
        if failed:
            cursor[_CURSOR_FAILURES_KEY] = int(cursor.get(_CURSOR_FAILURES_KEY) or 0) + 1
        else:
            cursor.pop(_CURSOR_FAILURES_KEY, None)
        cp.cursor = cursor
        session.flush()
        return cp

    providers: dict[uuid.UUID, Any] = {}
    provider_errors: dict[uuid.UUID, Exception] = {}
    for _epoch, folder, account, cp in selected:
        if account.id in provider_errors:
            _record_attempt(folder, account, cp, failed=True)
            result.failed += 1
            continue
        provider = providers.get(account.id)
        if provider is None:
            try:
                provider = factory(account)
            except Exception as exc:  # credential/config errors isolate per account
                from mail_core.security.redact import safe_error

                log.warning(
                    "patrol provider build failed for account %s: %s",
                    account.id,
                    safe_error(exc),
                )
                provider_errors[account.id] = exc
                _record_attempt(folder, account, cp, failed=True)
                result.failed += 1
                continue
            providers[account.id] = provider

        try:
            status = provider.probe_folder_status(folder.remote_id)
        except Exception as exc:
            from mail_core.security.redact import safe_error

            log.warning(
                "patrol probe failed for folder %s of account %s: %s",
                folder.id,
                account.id,
                safe_error(exc),
            )
            _record_attempt(folder, account, cp, failed=True)
            result.failed += 1
            continue
        if status is None:
            # Unsupported probe or unparseable response: treat as a
            # failed probe (retried next patrol cycle), never as
            # "no change".
            _record_attempt(folder, account, cp, failed=True)
            result.failed += 1
            continue

        result.probed += 1
        cp = _record_attempt(folder, account, cp, failed=False)
        cursor = dict(cp.cursor or {})
        baseline = FolderStatus.from_dict(cursor.get(_CURSOR_STATUS_KEY))
        baseline_ready = bool(cp.full_scan_complete)
        is_changed = (
            baseline is not None
            and baseline_ready
            and bool(changed_dimensions(baseline, status))
        )
        cursor[_CURSOR_STATUS_KEY] = status.to_dict()
        cp.cursor = cursor
        session.flush()

        if is_changed:
            # No-baseline folders only record state (AC-012): the delta
            # pipeline owns convergence, and baseline establishment
            # stays with account discovery / manual sync.
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account.id,
                payload={"folder_id": str(folder.id)},
                priority=75,
                dedupe_key=f"delta:{account.id}:{folder.id}",
            )
            result.changed += 1

    return result
