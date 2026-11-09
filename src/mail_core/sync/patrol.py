"""All-folder STATUS patrol (t061 AC-008..AC-014, adoption A14).

Extends the t057 periodic scheduling idea beyond the inbox: every
non-paused folder of every sync-enabled account is probed on a cycle
with a cheap provider STATUS call. Only a probe whose comparable
dimensions differ from the stored baseline enqueues a
``SYNC_FOLDER_DELTA``; the delta job then converges the folder through
the existing pipeline. The probe baseline and probe tracking live in
the dedicated ``folder_patrol_status`` table, completely separated
from the ``SyncCheckpoint.cursor`` protocol sync cursor.

The patrol itself never writes message data, never triggers a full
metadata scan, and isolates per-folder failures.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, FolderPatrolStatus, SyncCheckpoint
from mail_core.providers.base import FolderStatus
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.sync.patrol")

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
            select(Folder, Account, SyncCheckpoint, FolderPatrolStatus)
            .join(Account, Account.id == Folder.account_id)
            .outerjoin(
                SyncCheckpoint,
                (SyncCheckpoint.account_id == Folder.account_id)
                & (SyncCheckpoint.folder_id == Folder.id),
            )
            .outerjoin(
                FolderPatrolStatus,
                FolderPatrolStatus.folder_id == Folder.id,
            )
            .where(
                Account.sync_enabled.is_(True),
                Folder.sync_status != SyncStatus.PAUSED.value,
                Folder.role != "inbox",
            )
            .order_by(Account.id, Folder.id)
        ).all()
    )

    due: list[tuple[float, Folder, Account, SyncCheckpoint | None, FolderPatrolStatus | None]] = []
    for folder, account, cp, fps in rows:
        last_epoch: float | None = None
        if fps is not None and fps.last_probe_at is not None:
            last_epoch = fps.last_probe_at.timestamp()
        if last_epoch is not None and now_epoch - last_epoch < config.interval_s:
            result.skipped_not_due += 1
            continue
        due.append((last_epoch if last_epoch is not None else 0.0, folder, account, cp, fps))

    # Rotation (AC-013): folders that have never been probed or whose
    # last attempt is older than the max-unprobed bound go first; within
    # each group, least-recently attempted first; capped per sweep.
    def _rotation_key(
        item: tuple[float, Folder, Account, SyncCheckpoint | None, FolderPatrolStatus | None],
    ) -> tuple[int, float, str]:
        last_epoch = item[0]
        critical = last_epoch == 0.0 or (now_epoch - last_epoch) > config.max_unprobed_s
        return (0 if critical else 1, last_epoch, str(item[1].id))

    due.sort(key=_rotation_key)
    selected = due[: config.max_probes]

    def _record_attempt(
        folder: Folder,
        fps: FolderPatrolStatus | None,
        *,
        failed: bool,
    ) -> FolderPatrolStatus:
        """Advance the probe-attempt clock for success AND failure.

        A failed folder must not stay permanently "most overdue":
        retrying it on every 60s scheduler sweep would hammer a
        rate-limited server and starve every other folder (AC-013 /
        AC-014). The attempt timestamp is the due-clock; failures are
        counted separately and cleared on the next success.
        """
        if fps is None:
            values = dict(
                folder_id=folder.id,
                last_status=None,
                last_probe_at=current_time,
                last_probe_failures=0,
            )
            session.execute(
                pg_insert(FolderPatrolStatus).values(**values).on_conflict_do_nothing()
            )
            fps = session.get(FolderPatrolStatus, folder.id)
        failure_count = (
            func.coalesce(FolderPatrolStatus.last_probe_failures, 0) + 1 if failed else 0
        )
        session.execute(
            update(FolderPatrolStatus)
            .where(FolderPatrolStatus.folder_id == folder.id)
            .values(
                last_probe_at=current_time,
                last_probe_failures=failure_count,
                updated_at=func.now(),
            )
        )
        session.flush()
        return fps

    providers: dict[uuid.UUID, Any] = {}
    provider_errors: dict[uuid.UUID, Exception] = {}
    for _epoch, folder, account, cp, fps in selected:
        if account.id in provider_errors:
            _record_attempt(folder, fps, failed=True)
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
                _record_attempt(folder, fps, failed=True)
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
            _record_attempt(folder, fps, failed=True)
            result.failed += 1
            continue
        if status is None:
            # Unsupported probe or unparseable response: treat as a
            # failed probe (retried next patrol cycle), never as
            # "no change".
            _record_attempt(folder, fps, failed=True)
            result.failed += 1
            continue

        result.probed += 1
        fps = _record_attempt(folder, fps, failed=False)
        baseline = (
            FolderStatus.from_dict(fps.last_status)
            if fps.last_status is not None
            else None
        )
        baseline_ready = bool(cp.full_scan_complete) if cp is not None else False
        is_changed = (
            baseline is not None
            and baseline_ready
            and bool(changed_dimensions(baseline, status))
        )
        fps.last_status = status.to_dict()
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
