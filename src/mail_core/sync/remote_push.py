"""Push pending remote_operations via provider.apply_remote_operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from mail_core.mail.application.remote_ops import mark_remote_operation, reclaim_stale_in_progress
from mail_core.mail.domain.enums import (
    ExecutionOrigin,
    JobStatus,
    JobType,
    RemoteOperationStatus,
    normalize_execution_origin,
)
from mail_core.mail.domain.failures import StructuredFailure
from mail_core.mail.storage.models import Account, RemoteOperation
from mail_core.providers.connection_slots import (
    CAPACITY_ERRORS,
    TrafficClass,
    get_capacity_retry_seconds,
    is_capacity_error,
)
from mail_core.providers.factory import build_provider
from mail_core.security.credentials import CredentialStore, get_credential_store
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    heartbeat_lease,
    release_lease,
)
from mail_core.sync.remote_push_errors import (
    DEFAULT_MAX_REMOTE_OP_ATTEMPTS,
    get_retry_after_seconds,
    is_rate_limited_error,
    is_transient_error,
    resolve_push_op_failure as _resolve_push_op_failure,
)
from mail_core.sync.remote_push_move import (
    RemoteIdentityConflict,
    persist_move_remote_state as _persist_move_remote_state,
)

__all__ = [
    "DEFAULT_MAX_REMOTE_OP_ATTEMPTS",
    "RemoteIdentityConflict",
    "_persist_move_remote_state",
    "_resolve_push_op_failure",
    "get_retry_after_seconds",
    "get_unconverged_field_intents",
    "is_rate_limited_error",
    "is_transient_error",
    "push_remote_operations",
]

log = logging.getLogger("mail_core.sync.remote_push")

_FIELD_INTENT_NAMES = {"read": "is_read", "flag": "is_flagged"}


@dataclass(frozen=True)
class _PushContext:
    session_factory: Any
    account_id: uuid.UUID
    provider_type: str
    worker_id: str
    fencing: int
    origin: ExecutionOrigin
    lease_ttl: timedelta


def _get_session_factory():
    return __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()


def _release_lease_quietly(session: Session, *, account_id: uuid.UUID, worker_id: str, fencing: int) -> None:
    try:
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
    except FencingMismatch:
        pass


def _enqueue_followup_push(
    session: Session,
    *,
    account_id: uuid.UUID,
    origin: ExecutionOrigin,
    run_after: datetime | None = None,
):
    kwargs: dict[str, Any] = {
        "job_type": JobType.REMOTE_OPERATION_PUSH.value,
        "execution_origin": origin,
        "account_id": account_id,
        "payload": {},
        "priority": 40,
        "dedupe_key": f"remote-op-push:{account_id}",
    }
    if run_after is not None:
        kwargs["run_after"] = run_after
    return enqueue_job(session, **kwargs)


def _acquire_and_fetch_pending_ops(
    session_factory: Any,
    *,
    account_id: uuid.UUID,
    worker_id: str,
    limit: int,
    lease_ttl: timedelta,
) -> tuple[Account, int, list[tuple[uuid.UUID, str, dict]]] | dict[str, Any]:
    with session_factory() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError("account not found")
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            return {"status": "lease_busy"}
        reclaimed = reclaim_stale_in_progress(session, older_than=timedelta(minutes=15), limit=limit)
        if reclaimed:
            log.info("reclaimed %s stale in_progress remote op(s)", reclaimed)
        now = datetime.now(timezone.utc)
        ops = list(
            session.scalars(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == account_id)
                .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
                .where(
                    or_(
                        RemoteOperation.next_attempt_at.is_(None),
                        RemoteOperation.next_attempt_at <= now,
                    )
                )
                .order_by(RemoteOperation.created_at.asc())
                .limit(limit)
            ).all()
        )
        work = [(op.id, op.op_type, dict(op.desired_state or {})) for op in ops]
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )
        session.commit()
        return account_snapshot, lease.fencing_token, work


def _finish_empty_push_work(ctx: _PushContext) -> dict[str, Any]:
    with ctx.session_factory() as session:
        next_due = session.scalar(
            select(func.min(RemoteOperation.next_attempt_at))
            .where(RemoteOperation.account_id == ctx.account_id)
            .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
            .where(RemoteOperation.next_attempt_at.is_not(None))
        )
        if next_due is not None:
            _enqueue_followup_push(session, account_id=ctx.account_id, origin=ctx.origin, run_after=next_due)
        try:
            release_lease(session, account_id=ctx.account_id, owner_id=ctx.worker_id, fencing_token=ctx.fencing)
            session.commit()
        except FencingMismatch:
            pass
    return {"status": "ok", "pushed": 0, "failed": 0}


def _claim_ops_in_progress(
    ctx: _PushContext,
    work: list[tuple[uuid.UUID, str, dict]],
) -> tuple[dict[uuid.UUID, dict], dict[uuid.UUID, Any]] | None:
    claimed_desired: dict[uuid.UUID, dict] = {}
    claimed_updated_at: dict[uuid.UUID, Any] = {}
    with ctx.session_factory() as session:
        try:
            assert_fencing(session, account_id=ctx.account_id, fencing_token=ctx.fencing)
        except FencingMismatch:
            return None

        for op_id, _op_type, _desired in work:
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is not None and op.status == RemoteOperationStatus.PENDING.value:
                mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
                claimed_desired[op_id] = dict(op.desired_state or {})
                claimed_updated_at[op_id] = op.updated_at

        try:
            heartbeat_lease(
                session,
                account_id=ctx.account_id,
                owner_id=ctx.worker_id,
                fencing_token=ctx.fencing,
                ttl=ctx.lease_ttl,
            )
        except FencingMismatch:
            session.rollback()
            return None
        session.commit()
    return claimed_desired, claimed_updated_at


def _resolve_batch_trash_folder(
    ctx: _PushContext,
    work: list[tuple[uuid.UUID, str, dict]],
) -> str | None:
    if ctx.provider_type != "imap":
        return None
    if not any(op_type == "trash" for _, op_type, _ in work):
        return None
    try:
        from mail_core.mail.application.mutations import _resolve_imap_trash_folder

        with ctx.session_factory() as session:
            return _resolve_imap_trash_folder(session, ctx.account_id)
    except Exception:
        return None


def _build_provider_items(
    work: list[tuple[uuid.UUID, str, dict]],
    claimed_desired: dict[uuid.UUID, dict],
    real_trash: str | None,
) -> tuple[list[Any], list[Any], dict[Any, Any]]:
    from mail_core.providers.base import RemoteOperationItem, RemoteOperationResult

    items: list[RemoteOperationItem] = []
    valid_items: list[RemoteOperationItem] = []
    pre_failed_results: dict[Any, RemoteOperationResult] = {}

    for op_id, op_type, _desired in work:
        if op_id not in claimed_desired:
            continue
        effective_desired = dict(claimed_desired[op_id])
        if op_type == "trash" and real_trash and effective_desired.get("trash_folder_remote_id") in (None, "", "Trash"):
            effective_desired["trash_folder_remote_id"] = real_trash
        item = RemoteOperationItem(op_id=op_id, op_type=op_type, desired_state=effective_desired)
        items.append(item)
        rid = effective_desired.get("remote_id")
        if not isinstance(rid, str) or not rid.strip():
            pre_failed_results[op_id] = RemoteOperationResult(success=False, error="remote_id_missing")
        else:
            valid_items.append(item)

    return items, valid_items, pre_failed_results


def _defer_ops_for_capacity(
    ctx: _PushContext,
    claimed_desired: dict[uuid.UUID, dict],
    exc: BaseException,
) -> dict[str, Any]:
    delay = float(getattr(exc, "retry_after_seconds", None) or get_capacity_retry_seconds())
    next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
    with ctx.session_factory() as session:
        try:
            assert_fencing(session, account_id=ctx.account_id, fencing_token=ctx.fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
        for op_id in claimed_desired:
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is not None and op.status == RemoteOperationStatus.IN_PROGRESS.value:
                mark_remote_operation(
                    session, op, status=RemoteOperationStatus.PENDING, error=None, next_attempt_at=next_attempt
                )
                op.attempts = max(0, int(op.attempts) - 1)
        followup = _enqueue_followup_push(session, account_id=ctx.account_id, origin=ctx.origin, run_after=next_attempt)
        # The executing job carries the same dedupe key, so the followup
        # usually coalesces into its _queue_next. Settlement must know,
        # otherwise it strips the coalesced followup when marking the job
        # DONE and leaves the op PENDING with no executable job.
        followup_coalesced = followup.status == JobStatus.CLAIMED.value
        _release_lease_quietly(session, account_id=ctx.account_id, worker_id=ctx.worker_id, fencing=ctx.fencing)
        session.commit()
    return {
        "status": "capacity_unavailable",
        "retry_after": delay,
        "followup_scheduled": True,
        "followup_coalesced": followup_coalesced,
        "pushed": 0,
        "failed": 0,
    }


def _heartbeat_between_chunks(ctx: _PushContext) -> bool:
    with ctx.session_factory() as hb_session:
        try:
            heartbeat_lease(
                hb_session,
                account_id=ctx.account_id,
                owner_id=ctx.worker_id,
                fencing_token=ctx.fencing,
                ttl=ctx.lease_ttl,
            )
            hb_session.commit()
        except FencingMismatch:
            log.warning("fencing mismatch during batched remote push heartbeat for %s", ctx.account_id)
            return False
        except Exception as hb_exc:
            log.warning("lease heartbeat between chunks failed: %s", hb_exc)
    return True


def _apply_provider_chunk(provider: Any, chunk: list[Any], results_map: dict[Any, Any]) -> None:
    if hasattr(provider, "apply_remote_operations"):
        results_seq = provider.apply_remote_operations(chunk)
        results_map.update({res[0]: res[1] for res in results_seq})
    else:
        for item in chunk:
            results_map[item.op_id] = provider.apply_remote_operation(item.op_type, item.desired_state)


def _execute_provider_chunks(
    ctx: _PushContext,
    *,
    provider: Any,
    valid_items: list[Any],
    initial_results: dict[Any, Any],
) -> tuple[dict[Any, Any], Exception | None]:
    results_map: dict[Any, Any] = dict(initial_results)
    if not valid_items:
        return results_map, None

    chunk_size = 100
    caught_batch_exc: Exception | None = None
    for i in range(0, len(valid_items), chunk_size):
        chunk = valid_items[i : i + chunk_size]
        try:
            _apply_provider_chunk(provider, chunk, results_map)
        except Exception as exc:  # noqa: BLE001
            caught_batch_exc = exc
            failure = StructuredFailure.from_exception(exc)
            log.error("remote push batch failed: %s", failure)
            break

        if i + chunk_size < len(valid_items) and not _heartbeat_between_chunks(ctx):
            break
    return results_map, caught_batch_exc


def _compute_retry_schedule(
    attempts: int,
    err: StructuredFailure | str | None,
    remote_state: dict,
    caught_batch_exc: Exception | None,
) -> tuple[RemoteOperationStatus, StructuredFailure | str, datetime | None]:
    if attempts >= DEFAULT_MAX_REMOTE_OP_ATTEMPTS:
        return RemoteOperationStatus.FAILED, err or "push failed", None

    now_retry = datetime.now(timezone.utc)
    err_text = err.format() if isinstance(err, StructuredFailure) else err
    retry_after_sec = remote_state.get("retry_after") if isinstance(remote_state, dict) else None
    if retry_after_sec is None and isinstance(err, StructuredFailure):
        retry_after_sec = err.retry_after_s

    if retry_after_sec is not None or is_rate_limited_error(caught_batch_exc, err_text):
        delay = float(retry_after_sec or get_retry_after_seconds(caught_batch_exc, fallback=60.0))
        return RemoteOperationStatus.PENDING, err or "rate limited", now_retry + timedelta(seconds=delay)
    if is_transient_error(caught_batch_exc, err_text):
        delay = min(3600, 2 ** max(0, attempts - 1))
        return RemoteOperationStatus.PENDING, err or "transient failure", now_retry + timedelta(seconds=delay)
    return RemoteOperationStatus.FAILED, err or "push failed", None


def _schedule_retry_or_fail(
    session: Session,
    *,
    op: RemoteOperation,
    err: StructuredFailure | str | None,
    remote_state: dict,
    caught_batch_exc: Exception | None,
) -> None:
    status, final_err, next_attempt_at = _compute_retry_schedule(
        int(op.attempts), err, remote_state, caught_batch_exc
    )
    mark_remote_operation(session, op, status=status, error=final_err, next_attempt_at=next_attempt_at)


def _resolve_settlement_outcome(
    session: Session,
    *,
    ctx: _PushContext,
    item: Any,
    caught_batch_exc: Exception | None,
    results_map: dict[Any, Any],
) -> tuple[bool, StructuredFailure | str | None, dict]:
    from mail_core.providers.base import RemoteOperationResult

    if caught_batch_exc is not None:
        failure = StructuredFailure.from_exception(caught_batch_exc)
        result = RemoteOperationResult(success=False, error=failure.format(), failure=failure)
    else:
        result = results_map.get(item.op_id) or RemoteOperationResult(
            success=False, error="operation unhandled in provider batch"
        )

    ok = bool(result.success)
    err = _resolve_push_op_failure(caught_batch_exc, result)
    remote_state = getattr(result, "remote_state", {}) or {}
    if ok:
        try:
            _persist_move_remote_state(
                session,
                account_id=ctx.account_id,
                provider_type=ctx.provider_type,
                op_type=item.op_type,
                desired_state=item.desired_state,
                remote_state=remote_state,
            )
        except RemoteIdentityConflict as exc:
            ok = False
            err = StructuredFailure.from_exception(exc)
    return ok, err, remote_state


def _settle_single_push_op(
    session: Session,
    *,
    ctx: _PushContext,
    item: Any,
    claimed_desired: dict[uuid.UUID, dict],
    claimed_updated_at: dict[uuid.UUID, Any],
    results_map: dict[Any, Any],
    caught_batch_exc: Exception | None,
) -> tuple[int, int]:
    op_id = item.op_id
    op = session.get(RemoteOperation, op_id, with_for_update=True)
    if op is None:
        return 0, 0

    # CAS check: must still be IN_PROGRESS and desired_state / revision must match what was claimed
    cas_mismatch = (
        op.status != RemoteOperationStatus.IN_PROGRESS.value
        or dict(op.desired_state or {}) != claimed_desired[op_id]
        or op.updated_at != claimed_updated_at[op_id]
    )
    if cas_mismatch:
        log.info("remote op %s modified during push; preserving PENDING and reenqueuing push", op_id)
        op.status = RemoteOperationStatus.PENDING.value
        return 0, 0

    ok, err, remote_state = _resolve_settlement_outcome(
        session, ctx=ctx, item=item, caught_batch_exc=caught_batch_exc, results_map=results_map
    )
    if ok:
        applied = mark_remote_operation(
            session,
            op,
            status=RemoteOperationStatus.DONE,
            next_attempt_at=None,
            expected_revision=int(claimed_desired[op_id].get("revision") or 0),
        )
        if applied:
            return 1, 0
        op.status = RemoteOperationStatus.PENDING.value
        return 0, 0

    _schedule_retry_or_fail(
        session, op=op, err=err, remote_state=remote_state, caught_batch_exc=caught_batch_exc
    )
    return 0, 1


def _enqueue_push_followup(session: Session, *, account_id: uuid.UUID, origin: ExecutionOrigin) -> None:
    now_check = datetime.now(timezone.utc)
    immediate_pending = session.scalar(
        select(func.count(RemoteOperation.id))
        .where(RemoteOperation.account_id == account_id)
        .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
        .where(
            or_(
                RemoteOperation.next_attempt_at.is_(None),
                RemoteOperation.next_attempt_at <= now_check,
            )
        )
    )
    if immediate_pending and immediate_pending > 0:
        _enqueue_followup_push(session, account_id=account_id, origin=origin)
        return

    next_due = session.scalar(
        select(func.min(RemoteOperation.next_attempt_at))
        .where(RemoteOperation.account_id == account_id)
        .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
        .where(RemoteOperation.next_attempt_at.is_not(None))
    )
    if next_due is not None:
        _enqueue_followup_push(session, account_id=account_id, origin=origin, run_after=next_due)


def _settle_push_results(
    ctx: _PushContext,
    *,
    items: list[Any],
    claimed_desired: dict[uuid.UUID, dict],
    claimed_updated_at: dict[uuid.UUID, Any],
    results_map: dict[Any, Any],
    caught_batch_exc: Exception | None,
) -> dict[str, Any]:
    pushed = 0
    failed = 0
    with ctx.session_factory() as session:
        try:
            assert_fencing(session, account_id=ctx.account_id, fencing_token=ctx.fencing)
        except FencingMismatch:
            # AC-009: Side effect may have landed remotely; leave IN_PROGRESS for reconcile.
            return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}

        for item in items:
            pushed_delta, failed_delta = _settle_single_push_op(
                session,
                ctx=ctx,
                item=item,
                claimed_desired=claimed_desired,
                claimed_updated_at=claimed_updated_at,
                results_map=results_map,
                caught_batch_exc=caught_batch_exc,
            )
            pushed += pushed_delta
            failed += failed_delta

        _enqueue_push_followup(session, account_id=ctx.account_id, origin=ctx.origin)
        _release_lease_quietly(session, account_id=ctx.account_id, worker_id=ctx.worker_id, fencing=ctx.fencing)
        session.commit()

    return {"status": "ok", "pushed": pushed, "failed": failed}


def push_remote_operations(
    account_id: uuid.UUID,
    *,
    worker_id: str,
    execution_origin: ExecutionOrigin | str,
    store: CredentialStore | None = None,
    limit: int = 500,
    lease_ttl: timedelta = timedelta(seconds=120),
    traffic_class: TrafficClass = TrafficClass.FOREGROUND,
) -> dict:
    """Push pending remote ops in batches with per-op isolation and fencing *before* side effects.

    Batch execution (t064):
    1. assert fencing in a short TX and mark all batch operations ``in_progress``
    2. call provider.apply_remote_operations with all items
    3. assert fencing again before recording done/failed per operation with revision CAS

    If fencing is lost after the network call, operations stay ``in_progress`` for
    reconcile; no operation is marked DONE.
    """
    origin = normalize_execution_origin(execution_origin)
    session_factory = _get_session_factory()
    acquired = _acquire_and_fetch_pending_ops(
        session_factory, account_id=account_id, worker_id=worker_id, limit=limit, lease_ttl=lease_ttl
    )
    if isinstance(acquired, dict):
        return acquired
    account_snapshot, fencing, work = acquired
    ctx = _PushContext(
        session_factory=session_factory,
        account_id=account_id,
        provider_type=str(account_snapshot.provider or "").lower(),
        worker_id=worker_id,
        fencing=fencing,
        origin=origin,
        lease_ttl=lease_ttl,
    )

    if not work:
        return _finish_empty_push_work(ctx)

    claimed = _claim_ops_in_progress(ctx, work)
    if claimed is None:
        return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
    claimed_desired, claimed_updated_at = claimed

    real_trash = _resolve_batch_trash_folder(ctx, work)
    items, valid_items, pre_failed_results = _build_provider_items(work, claimed_desired, real_trash)

    try:
        provider = build_provider(account_snapshot, store or get_credential_store(), traffic_class=traffic_class)
    except CAPACITY_ERRORS as exc:
        return _defer_ops_for_capacity(ctx, claimed_desired, exc)
    except Exception:
        with session_factory() as session:
            _release_lease_quietly(session, account_id=account_id, worker_id=worker_id, fencing=fencing)
            session.commit()
        raise

    results_map, caught_batch_exc = _execute_provider_chunks(
        ctx, provider=provider, valid_items=valid_items, initial_results=pre_failed_results
    )
    if caught_batch_exc is not None and is_capacity_error(caught_batch_exc):
        return _defer_ops_for_capacity(ctx, claimed_desired, caught_batch_exc)

    return _settle_push_results(
        ctx,
        items=items,
        claimed_desired=claimed_desired,
        claimed_updated_at=claimed_updated_at,
        results_map=results_map,
        caught_batch_exc=caught_batch_exc,
    )


def _record_intent_if_applicable(intents: dict[str, dict[str, Any]], op: RemoteOperation) -> None:
    entity, separator, field = op.entity_key.rpartition(":")
    if not separator or not entity.startswith("msg:"):
        return
    field_name = _FIELD_INTENT_NAMES.get(field)
    if not field_name:
        return
    desired_state = op.desired_state or {}
    if field_name in desired_state:
        intents.setdefault(entity.removeprefix("msg:"), {})[field_name] = desired_state[field_name]


def get_unconverged_field_intents(
    session: Session,
    account_id: uuid.UUID,
    remote_ids: list[str],
    now: datetime | None = None,
    grace_seconds: float = 60.0,
) -> dict[str, dict[str, Any]]:
    """Return {remote_id: {"is_read": bool, "is_flagged": bool}} for unconverged local intents."""
    if not remote_ids:
        return {}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(seconds=grace_seconds)
    entity_keys = [key for remote_id in remote_ids for key in (f"msg:{remote_id}:read", f"msg:{remote_id}:flag")]

    ops = list(
        session.scalars(
            select(RemoteOperation)
            .where(RemoteOperation.account_id == account_id)
            .where(RemoteOperation.entity_key.in_(entity_keys))
            .where(
                or_(
                    RemoteOperation.status.in_([RemoteOperationStatus.PENDING.value, RemoteOperationStatus.IN_PROGRESS.value]),
                    and_(
                        RemoteOperation.status == RemoteOperationStatus.DONE.value,
                        RemoteOperation.updated_at >= cutoff,
                    ),
                )
            )
            .order_by(RemoteOperation.created_at.asc(), RemoteOperation.id.asc())
        ).all()
    )
    intents: dict[str, dict[str, Any]] = {}
    for op in ops:
        _record_intent_if_applicable(intents, op)
    return intents
