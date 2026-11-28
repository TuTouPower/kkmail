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

Account-level runtime state (t097): the patrol cooldown and the
half-open probe lease live in the dedicated ``account_patrol_state``
table — never in ``Account.config``, which is user-edited settings.
Provider build results settle per account: a build failure produces
exactly one account-level settlement and zero folder probe records,
while an actual folder probe settles its own folder record and, for
account-level auth/transport faults, the account state. The half-open
lease carries a unique token; every settlement that touches the lease
or cooldown is fenced by that token, so a result arriving after the
lease expired and was re-claimed cannot clear or overwrite the current
holder's state. Transactions owned by the patrol cover only short DB
operations: the read transaction and the half-open claim transaction
both end before any provider build or STATUS network call.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import Integer, cast, delete, exists, func, literal, null, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert as pg_insert
from sqlalchemy.orm import Session

from mail_core.accounts.health import mark_credential_invalid
from mail_core.config import get_config
from mail_core.mail.domain.enums import ExecutionOrigin, JobType
from mail_core.mail.domain.failures import FailureDomain
from mail_core.mail.storage.models import (
    Account,
    AccountPatrolState,
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

# t095 AC-004 introduced the account-level patrol cooldown; t097 moves it
# (and the half-open lease) into account_patrol_state. A failed account is
# not re-probed for PATROL_COOLDOWN_S; a half-open claim after expiry holds
# the lease for the same span, so concurrent sweeps see exactly one holder.
PATROL_COOLDOWN_S = 300.0


@dataclass(frozen=True, slots=True)
class _PatrolState:
    cooldown_until: datetime | None
    lease_token: str | None
    lease_expires_at: datetime | None


def _load_patrol_states(
    session: Session, account_ids: set[uuid.UUID]
) -> dict[uuid.UUID, _PatrolState]:
    if not account_ids:
        return {}
    rows = session.execute(
        select(AccountPatrolState).where(AccountPatrolState.account_id.in_(account_ids))
    ).scalars()
    return {
        row.account_id: _PatrolState(
            cooldown_until=row.cooldown_until,
            lease_token=row.lease_token,
            lease_expires_at=row.lease_expires_at,
        )
        for row in rows
    }


def _claim_half_open(
    session: Session,
    account_id: uuid.UUID,
    *,
    expected: _PatrolState,
    now: datetime,
) -> str | None:
    """Atomically claim the half-open lease for an expired cooldown.

    Compare-and-swap on the exact state read during selection: a competing
    claim, a fresh cooldown or a settlement landing first makes this claim
    lose. The winner owns a unique lease token until ``lease_expires_at``;
    after that instant another sweep may re-claim (the token rotates, which
    is what fences the expired holder's late settlements).
    """
    token = uuid.uuid4().hex
    expires = now + timedelta(seconds=PATROL_COOLDOWN_S)
    conditions = [
        AccountPatrolState.account_id == account_id,
        AccountPatrolState.cooldown_until == expected.cooldown_until,
        AccountPatrolState.cooldown_until <= now,
    ]
    if expected.lease_token is None:
        conditions.append(AccountPatrolState.lease_token.is_(None))
    else:
        conditions.append(AccountPatrolState.lease_token == expected.lease_token)
    stmt = (
        update(AccountPatrolState)
        .where(*conditions)
        .values(
            lease_token=token,
            lease_expires_at=expires,
            cooldown_until=expires,
            updated_at=func.now(),
        )
        .returning(AccountPatrolState.account_id)
        .execution_options(synchronize_session=False)
    )
    return token if session.scalar(stmt) is not None else None


def _set_cooldown(
    session: Session,
    account_id: uuid.UUID,
    now: datetime,
    *,
    lease_token: str | None,
    self_cleared: bool = False,
) -> bool:
    """Persist a fresh patrol cooldown after an account-level failure.

    Fenced by the lease token when the caller holds one: if the lease was
    lost (expired and re-claimed), the late failure must not overwrite or
    resurrect the current holder's state. The only legitimate miss is
    ``self_cleared`` — this same holder cleared the row with an earlier
    success in the same sweep — in which case the cooldown is
    re-established without stomping a row a newer generation has since
    inserted. Without a lease, the upsert still refuses to stomp a live
    foreign lease.
    """
    until = now + timedelta(seconds=PATROL_COOLDOWN_S)
    if lease_token is not None:
        stmt = (
            update(AccountPatrolState)
            .where(
                AccountPatrolState.account_id == account_id,
                AccountPatrolState.lease_token == lease_token,
            )
            .values(
                cooldown_until=until,
                lease_token=None,
                lease_expires_at=None,
                updated_at=func.now(),
            )
            .returning(AccountPatrolState.account_id)
            .execution_options(synchronize_session=False)
        )
        if session.scalar(stmt) is not None:
            return True
        if not self_cleared:
            # The row no longer carries our token: a newer lease
            # generation owns this account's patrol state — it settled
            # its own cooldown (token cleared) or cleared the row on
            # success. A late failure must not touch either outcome.
            return False
        stmt = (
            pg_insert(AccountPatrolState)
            .values(
                account_id=account_id,
                cooldown_until=until,
                lease_token=None,
                lease_expires_at=None,
            )
            .on_conflict_do_nothing(
                index_elements=[AccountPatrolState.account_id],
            )
            .returning(AccountPatrolState.account_id)
        )
        return session.scalar(stmt) is not None
    stmt = pg_insert(AccountPatrolState).values(
        account_id=account_id,
        cooldown_until=until,
        lease_token=None,
        lease_expires_at=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[AccountPatrolState.account_id],
        set_={
            "cooldown_until": until,
            "lease_token": None,
            "lease_expires_at": None,
            "updated_at": func.now(),
        },
        where=(
            AccountPatrolState.lease_token.is_(None)
            | (AccountPatrolState.lease_expires_at <= now)
        ),
    ).returning(AccountPatrolState.account_id)
    return session.scalar(stmt) is not None


def _clear_cooldown(
    session: Session,
    account_id: uuid.UUID,
    *,
    lease_token: str,
) -> bool:
    """Current holder's success clears the cooldown, fenced by its token.

    A late success from an expired holder matches no row and clears
    nothing, so the current holder's lease/cooldown survives intact.
    """
    stmt = (
        delete(AccountPatrolState)
        .where(
            AccountPatrolState.account_id == account_id,
            AccountPatrolState.lease_token == lease_token,
        )
        .returning(AccountPatrolState.account_id)
        .execution_options(synchronize_session=False)
    )
    return session.scalar(stmt) is not None


def _settle_account_failure(
    session: Session,
    account_id: uuid.UUID,
    *,
    domain: FailureDomain,
    lease_token: str | None,
    now: datetime,
    self_cleared: bool = False,
) -> None:
    """The single account-level settlement shared by build and probe faults.

    Permanent auth failure invalidates the credential (t090, any origin);
    a background transport failure stays health-isolated and never touches
    ``connectivity_state``. Both record the patrol cooldown in the
    patrol-owned state table.
    """
    if domain == FailureDomain.AUTH:
        mark_credential_invalid(session, account_id)
    _set_cooldown(
        session,
        account_id,
        now,
        lease_token=lease_token,
        self_cleared=self_cleared,
    )


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

    def _run_short_tx(fn: Callable[[], Any]) -> Any:
        try:
            value = fn()
            _end_tx_if_owned()
            return value
        except Exception:
            _rollback_if_owned()
            raise

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
    states = _load_patrol_states(session, {account.id for _f, account, _c, _p in rows})

    due: list[tuple[float, Folder, Account, SyncCheckpoint | None, FolderPatrolStatus | None]] = []
    for folder, account, cp, fps in rows:
        # t095 AC-004 / t097: skip the whole account while its patrol
        # cooldown is active (one failure must not hammer every folder of
        # the account). The cooldown lives in account_patrol_state, never
        # in Account.config.
        state = states.get(account.id)
        if (
            state is not None
            and state.cooldown_until is not None
            and current_time < state.cooldown_until
        ):
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
            )
        )

    # Close the read transaction before any claim, build or probe when the
    # caller did not open a fixture transaction (t095 Finding 4 / t097 AC-005).
    _end_tx_if_owned()

    # Half-open claim phase (t097 AC-003/AC-005): accounts whose cooldown
    # expired are claimed in one short transaction, strictly before any
    # provider build or STATUS call. Exactly one competing sweep wins each
    # lease; losers sit this sweep out for that account.
    leases: dict[uuid.UUID, str] = {}
    self_cleared: set[uuid.UUID] = set()
    claim_lost: set[uuid.UUID] = set()
    claim_candidates = {
        target.account_id
        for target in targets
        if (state := states.get(target.account_id)) is not None
        and state.cooldown_until is not None
        and state.cooldown_until <= current_time
    }
    if claim_candidates:

        def _claims() -> None:
            for account_id in claim_candidates:
                token = _claim_half_open(
                    session,
                    account_id,
                    expected=states[account_id],
                    now=current_time,
                )
                if token is None:
                    claim_lost.add(account_id)
                else:
                    leases[account_id] = token

        _run_short_tx(_claims)
    if claim_lost:
        targets = [t for t in targets if t.account_id not in claim_lost]

    providers: dict[uuid.UUID, Any] = {}
    short_circuited: set[uuid.UUID] = set()

    def _persist_probe_failure(
        target: _ProbeTarget,
        *,
        exc: Exception | None = None,
    ) -> None:
        """Settle one ACTUAL probe: its own folder record, plus the account
        settlement only for account-level auth/transport faults."""

        def _write() -> None:
            if exc is not None:
                domain = classify_failure(exc).domain
                if domain in (FailureDomain.TRANSPORT, FailureDomain.AUTH):
                    _settle_account_failure(
                        session,
                        target.account_id,
                        domain=domain,
                        lease_token=leases.get(target.account_id),
                        now=current_time,
                        self_cleared=target.account_id in self_cleared,
                    )
                    short_circuited.add(target.account_id)
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

                def _settle_build_failure(
                    account_id: uuid.UUID = target.account_id,
                    domain: FailureDomain = classify_failure(exc).domain,
                ) -> None:
                    _settle_account_failure(
                        session,
                        account_id,
                        domain=domain,
                        lease_token=leases.get(account_id),
                        now=current_time,
                        self_cleared=account_id in self_cleared,
                    )

                # t097 AC-001: a build failure settles ONCE at account level
                # — no folder probe record for any folder of the account,
                # no STATUS call — and the account is done for this sweep.
                _run_short_tx(_settle_build_failure)
                short_circuited.add(target.account_id)
                result.failed += 1
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
            _persist_probe_failure(target, exc=exc)
            continue

        if status is None:
            _persist_probe_failure(target)
            continue

        result.probed += 1
        is_changed = (
            target.baseline is not None
            and target.baseline_ready
            and bool(changed_dimensions(target.baseline, status))
        )

        def _persist_success(
            target: _ProbeTarget = target,
            status: FolderStatus = status,
            is_changed: bool = is_changed,
        ) -> None:
            lease_token = leases.get(target.account_id)
            if lease_token is not None:
                # Only the current lease holder clears the cooldown, and
                # only its own lease (t097 AC-003). Remember self-clears:
                # a later account-level failure in this same sweep may
                # legitimately re-establish the cooldown (see
                # _set_cooldown's self_cleared path).
                if _clear_cooldown(
                    session, target.account_id, lease_token=lease_token
                ):
                    self_cleared.add(target.account_id)
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
