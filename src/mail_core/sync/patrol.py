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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import Integer, Text, cast, exists, func, literal, null, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, insert as pg_insert
from sqlalchemy.orm import Session

from mail_core.accounts.health import mark_credential_invalid
from mail_core.config import get_config
from mail_core.mail.domain.enums import ExecutionOrigin, JobType
from mail_core.mail.domain.failures import FailureDomain
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderPatrolStatus,
    SyncCheckpoint,
    syncable_folder_clauses,
)
from mail_core.providers.base import FolderStatus
from mail_core.providers.factory import build_provider
from mail_core.security.redact import safe_error
from mail_core.sync.context import classify_failure
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.sync.patrol")

_DIMENSIONS = ("messages", "uidnext", "unseen", "highestmodseq")

# t095 AC-004: account-level patrol cooldown. Held in account.config so it
# survives across sweeps and processes, deliberately separate from
# connectivity_state (t090 isolates background transport failures from account
# health display). Key-level atomic JSONB updates and half-open claims keep
# concurrent config edits intact and prevent concurrent half-open probing.
_CFG_PATROL_COOLDOWN = "patrol_cooldown_until"
PATROL_COOLDOWN_S = 300.0


def _cooldown_active(account: Account, now: datetime) -> bool:
    raw = (account.config or {}).get(_CFG_PATROL_COOLDOWN)
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return now < until


def _set_cooldown(account: Account, now: datetime) -> None:
    cfg = dict(account.config or {})
    cfg[_CFG_PATROL_COOLDOWN] = (now + timedelta(seconds=PATROL_COOLDOWN_S)).isoformat()
    account.config = cfg


def _clear_cooldown(account: Account) -> None:
    cfg = account.config
    if not cfg or _CFG_PATROL_COOLDOWN not in cfg:
        return
    updated = dict(cfg)
    updated.pop(_CFG_PATROL_COOLDOWN, None)
    account.config = updated


def _expire_cached_account_config(session: Session, account_id: uuid.UUID) -> None:
    identity_map = getattr(session, "identity_map", None)
    if identity_map is None:
        return
    cached = identity_map.get((Account, (account_id,), None))
    if cached is not None:
        session.expire(cached, ["config"])


def _jsonb_set_cooldown_expr(until_iso: str) -> Any:
    return func.jsonb_set(
        func.coalesce(Account.config, text("'{}'::jsonb")),
        literal([_CFG_PATROL_COOLDOWN], ARRAY(Text)),
        func.to_jsonb(cast(until_iso, Text)),
        True,
    )


def _db_set_cooldown(session: Session, account_id: uuid.UUID, now: datetime) -> None:
    until_iso = (now + timedelta(seconds=PATROL_COOLDOWN_S)).isoformat()
    stmt = (
        update(Account)
        .where(Account.id == account_id)
        .values(config=_jsonb_set_cooldown_expr(until_iso))
        .execution_options(synchronize_session=False)
    )
    session.execute(stmt)
    _expire_cached_account_config(session, account_id)


def _db_clear_cooldown(session: Session, account_id: uuid.UUID) -> None:
    key = cast(_CFG_PATROL_COOLDOWN, Text)
    stmt = (
        update(Account)
        .where(
            Account.id == account_id,
            func.jsonb_exists(func.coalesce(Account.config, text("'{}'::jsonb")), key),
        )
        .values(config=func.coalesce(Account.config, text("'{}'::jsonb")).op("-")(key))
        .execution_options(synchronize_session=False)
    )
    session.execute(stmt)
    _expire_cached_account_config(session, account_id)


def _db_claim_half_open(
    session: Session,
    account_id: uuid.UUID,
    *,
    expected_raw: str,
    now: datetime,
) -> bool:
    """Atomically advance an expired cooldown to claim single-holder half-open probe rights."""
    key = cast(_CFG_PATROL_COOLDOWN, Text)
    claim_until_iso = (now + timedelta(seconds=PATROL_COOLDOWN_S)).isoformat()
    stmt = (
        update(Account)
        .where(
            Account.id == account_id,
            Account.sync_enabled.is_(True),
            func.jsonb_exists(func.coalesce(Account.config, text("'{}'::jsonb")), key),
            Account.config.op("->>")(key) == expected_raw,
        )
        .values(config=_jsonb_set_cooldown_expr(claim_until_iso))
        .returning(Account.id)
        .execution_options(synchronize_session=False)
    )
    claimed = session.scalar(stmt) is not None
    if claimed:
        _expire_cached_account_config(session, account_id)
    return claimed


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


@dataclass(frozen=True, slots=True)
class _ProbeTarget:
    folder_id: uuid.UUID
    folder_remote_id: str
    account_id: uuid.UUID
    account_snapshot: Account
    had_fps: bool
    baseline: FolderStatus | None
    baseline_ready: bool
    raw_cooldown_until: str | None


def _snapshot_account(account: Account) -> Account:
    return Account(
        id=account.id,
        email=account.email,
        provider=account.provider,
        display_name=account.display_name,
        credential_ref=account.credential_ref,
        group_id=account.group_id,
        sync_enabled=account.sync_enabled,
        credential_state=account.credential_state,
        connectivity_state=account.connectivity_state,
        sync_activity=account.sync_activity,
        config=dict(account.config or {}),
    )


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
    return build_provider(account)


def _record_attempt(
    session: Session,
    folder_id: uuid.UUID,
    *,
    had_fps: bool,
    current_time: datetime,
    failed: bool,
    last_status: dict[str, Any] | None = None,
) -> None:
    """Advance the probe-attempt clock for success AND failure in one SQL write."""
    if had_fps:
        values: dict[str, Any] = {
            "last_probe_at": current_time,
            "last_probe_failures": (
                func.coalesce(FolderPatrolStatus.last_probe_failures, 0) + 1
                if failed
                else 0
            ),
            "updated_at": func.now(),
        }
        if not failed and last_status is not None:
            values["last_status"] = last_status
        session.execute(
            update(FolderPatrolStatus)
            .where(FolderPatrolStatus.folder_id == folder_id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        return

    status_expr = (
        null().cast(JSONB)
        if failed or last_status is None
        else cast(literal(last_status, JSONB), JSONB)
    )
    stmt = pg_insert(FolderPatrolStatus).from_select(
        ["folder_id", "last_status", "last_probe_at", "last_probe_failures"],
        select(
            cast(literal(folder_id), UUID(as_uuid=True)),
            status_expr,
            literal(current_time),
            cast(literal(1 if failed else 0), Integer),
        ).where(exists().where(Folder.id == folder_id)),
    )
    conflict_set: dict[str, Any] = {
        "last_probe_at": stmt.excluded.last_probe_at,
        "last_probe_failures": (
            func.coalesce(FolderPatrolStatus.last_probe_failures, 0) + 1
            if failed
            else 0
        ),
        "updated_at": func.now(),
    }
    if not failed and last_status is not None:
        conflict_set["last_status"] = stmt.excluded.last_status
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[FolderPatrolStatus.folder_id],
            set_=conflict_set,
        )
    )


def schedule_folder_status_patrol(
    session: Session,
    *,
    config: PatrolConfig | None = None,
    provider_factory: Callable[[Account], Any] | None = None,
    now: datetime | None = None,
) -> PatrolResult:
    """Run one patrol sweep over due folders (oldest-probed first)."""
    if config is None:
        config = PatrolConfig.from_app_config(get_config())
    result = PatrolResult()
    if not config.enabled:
        return result
    factory = provider_factory or _default_provider_factory
    current_time = now or datetime.now(timezone.utc)
    now_epoch = current_time.timestamp()
    caller_had_tx = bool(session.in_transaction())

    def _end_tx_if_owned() -> None:
        if not caller_had_tx and session.in_transaction():
            session.commit()

    def _rollback_if_owned() -> None:
        if not caller_had_tx and session.in_transaction():
            session.rollback()

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
                *syncable_folder_clauses(),
                Folder.role != "inbox",
            )
            .order_by(Account.id, Folder.id)
        ).all()
    )

    due: list[tuple[float, Folder, Account, SyncCheckpoint | None, FolderPatrolStatus | None]] = []
    for folder, account, cp, fps in rows:
        # t095 AC-004: skip the whole account while its patrol cooldown is
        # active (one failure must not hammer every folder of the account).
        if _cooldown_active(account, current_time):
            result.skipped_not_due += 1
            continue
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

    account_snapshots: dict[uuid.UUID, Account] = {}
    targets: list[_ProbeTarget] = []
    for _epoch, folder, account, cp, fps in selected:
        snapshot = account_snapshots.get(account.id)
        if snapshot is None:
            snapshot = _snapshot_account(account)
            account_snapshots[account.id] = snapshot
        raw_cd = (account.config or {}).get(_CFG_PATROL_COOLDOWN)
        raw_cooldown_until = str(raw_cd) if raw_cd not in (None, "") else None
        baseline = (
            FolderStatus.from_dict(fps.last_status)
            if fps is not None and fps.last_status is not None
            else None
        )
        targets.append(
            _ProbeTarget(
                folder_id=folder.id,
                folder_remote_id=folder.remote_id,
                account_id=account.id,
                account_snapshot=snapshot,
                had_fps=fps is not None,
                baseline=baseline,
                baseline_ready=bool(cp.full_scan_complete) if cp is not None else False,
                raw_cooldown_until=raw_cooldown_until,
            )
        )

    # Close the read transaction before any network I/O when caller did not
    # open a fixture transaction (Finding 4).
    _end_tx_if_owned()

    providers: dict[uuid.UUID, Any] = {}
    short_circuited: set[uuid.UUID] = set()
    claimed_half_open: set[uuid.UUID] = set()
    account_has_cooldown: set[uuid.UUID] = set()

    def _run_short_tx(fn: Callable[[], Any]) -> Any:
        try:
            value = fn()
            _end_tx_if_owned()
            return value
        except Exception:
            _rollback_if_owned()
            raise

    def _mark_account_failure(
        account_id: uuid.UUID,
        exc: Exception,
        *,
        domain: FailureDomain | None = None,
    ) -> None:
        resolved_domain = domain if domain is not None else classify_failure(exc).domain
        if resolved_domain == FailureDomain.AUTH:
            mark_credential_invalid(session, account_id)
        _db_set_cooldown(session, account_id, current_time)
        account_has_cooldown.add(account_id)
        short_circuited.add(account_id)

    def _persist_failed_attempt(
        target: _ProbeTarget,
        *,
        exc: Exception | None = None,
        domain: FailureDomain | None = None,
    ) -> None:
        def _write() -> None:
            if exc is not None:
                resolved = domain if domain is not None else classify_failure(exc).domain
                if getattr(resolved, "value", str(resolved)) in ("transport", "auth"):
                    _mark_account_failure(target.account_id, exc, domain=resolved)
            _record_attempt(
                session,
                target.folder_id,
                had_fps=target.had_fps,
                current_time=current_time,
                failed=True,
            )

        _run_short_tx(_write)
        result.failed += 1

    for target in targets:
        if target.account_id in short_circuited:
            continue

        if target.raw_cooldown_until is not None and target.account_id not in claimed_half_open:
            claimed = _run_short_tx(
                lambda: _db_claim_half_open(
                    session,
                    target.account_id,
                    expected_raw=target.raw_cooldown_until,
                    now=current_time,
                )
            )
            if not claimed:
                short_circuited.add(target.account_id)
                continue
            claimed_half_open.add(target.account_id)
            account_has_cooldown.add(target.account_id)

        provider = providers.get(target.account_id)
        if provider is None:
            try:
                provider = factory(target.account_snapshot)
            except Exception as exc:  # credential/config errors isolate per account
                log.warning(
                    "patrol provider build failed for account %s: %s",
                    target.account_id,
                    safe_error(exc),
                )
                _persist_failed_attempt(target, exc=exc, domain=classify_failure(exc).domain)
                continue
            providers[target.account_id] = provider

        try:
            status = provider.probe_folder_status(target.folder_remote_id)
        except Exception as exc:
            log.warning(
                "patrol probe failed for folder %s of account %s: %s",
                target.folder_id,
                target.account_id,
                safe_error(exc),
            )
            _persist_failed_attempt(target, exc=exc, domain=classify_failure(exc).domain)
            continue

        if status is None:
            _persist_failed_attempt(target)
            continue

        result.probed += 1
        is_changed = (
            target.baseline is not None
            and target.baseline_ready
            and bool(changed_dimensions(target.baseline, status))
        )

        def _persist_success() -> None:
            if target.account_id in account_has_cooldown:
                _db_clear_cooldown(session, target.account_id)
                account_has_cooldown.discard(target.account_id)
            _record_attempt(
                session,
                target.folder_id,
                had_fps=target.had_fps,
                current_time=current_time,
                failed=False,
                last_status=status.to_dict(),
            )
            if is_changed:
                # No-baseline folders only record state (AC-012): the delta
                # pipeline owns convergence, and baseline establishment
                # stays with account discovery / manual sync.
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    execution_origin=ExecutionOrigin.BACKGROUND,
                    account_id=target.account_id,
                    payload={"folder_id": str(target.folder_id)},
                    priority=75,
                    dedupe_key=f"delta:{target.account_id}:{target.folder_id}",
                )
                result.changed += 1

        _run_short_tx(_persist_success)

    return result
