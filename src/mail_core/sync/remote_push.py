"""Push pending remote_operations via provider.apply_remote_operation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.application.remote_ops import mark_remote_operation, reclaim_stale_in_progress
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Account, Folder, RemoteOperation, WorkerJob
from mail_core.providers.factory import build_provider
from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.security.redact import safe_provider_summary
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    heartbeat_lease,
    release_lease,
)

log = logging.getLogger("mail_core.sync.remote_push")

DEFAULT_MAX_REMOTE_OP_ATTEMPTS = 5


def is_transient_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    if exc is not None:
        if isinstance(exc, RateLimitedError):
            return True
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        name = type(exc).__name__.lower()
        if any(term in name for term in ("timeout", "connect", "network", "socket")):
            return True
        status_code = getattr(exc, "status", None)
        if status_code is None:
            status_code = getattr(exc, "status_code", None)
        if status_code is None and hasattr(exc, "response"):
            status_code = getattr(getattr(exc, "response"), "status_code", None)
        if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
            return True
    if err_msg:
        err_lower = err_msg.lower()
        if any(
            term in err_lower
            for term in (
                "timeout",
                "timed out",
                "connection",
                "rate limit",
                "ratelimited",
                "429",
                "500",
                "502",
                "503",
                "504",
                "server error",
                "temporar",
            )
        ):
            return True
    return False


def is_rate_limited_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    if exc is not None:
        if isinstance(exc, RateLimitedError):
            return True
        status_code = getattr(exc, "status", None)
        if status_code is None:
            status_code = getattr(exc, "status_code", None)
        if status_code is None and hasattr(exc, "response"):
            status_code = getattr(getattr(exc, "response"), "status_code", None)
        if status_code == 429:
            return True
    if err_msg:
        err_lower = err_msg.lower()
        if "rate limit" in err_lower or "429" in err_lower or "ratelimited" in err_lower:
            return True
    return False


def get_retry_after_seconds(exc: Exception | None, fallback: float = 60.0) -> float:
    if exc is not None:
        sec = getattr(exc, "retry_after_seconds", None)
        if sec is not None:
            try:
                val = float(sec)
                if val > 0:
                    return max(1.0, min(val, 86400.0))
            except (ValueError, TypeError):
                pass
    return max(1.0, min(fallback, 86400.0))


def push_remote_operations(
    account_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    limit: int = 20,
    lease_ttl: timedelta = timedelta(seconds=120),
) -> dict:
    """Push pending remote ops with per-op isolation and fencing *before* side effects.

    For each operation:
    1. assert fencing in a short TX and mark ``in_progress``
    2. call the provider (network) inside try/except so one failure cannot abort the batch
    3. assert fencing again before recording done/failed

    If fencing is lost after a network call, that op stays ``in_progress`` for
    reconcile; later ops are not attempted.
    """
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
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
        work: list[tuple[uuid.UUID, str, dict]] = [
            (op.id, op.op_type, dict(op.desired_state or {})) for op in ops
        ]
        fencing = lease.fencing_token
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )
        session.commit()

    if not work:
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                pass
        return {"status": "ok", "pushed": 0, "failed": 0}

    try:
        provider = build_provider(account_snapshot, store or get_credential_store())
    except Exception:
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                pass
        raise

    pushed = 0
    failed = 0

    for op_id, op_type, desired in work:
        # Fencing gate *before* any provider side effect for this op.
        with Session() as session:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                return {"status": "fencing_mismatch", "pushed": pushed, "failed": failed}
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is None or op.status != RemoteOperationStatus.PENDING.value:
                continue
            mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
            claimed_desired = dict(op.desired_state or {})
            claimed_updated_at = op.updated_at
            try:
                heartbeat_lease(
                    session,
                    account_id=account_id,
                    owner_id=worker_id,
                    fencing_token=fencing,
                    ttl=lease_ttl,
                )
            except FencingMismatch:
                session.rollback()
                return {"status": "fencing_mismatch", "pushed": pushed, "failed": failed}
            session.commit()

        caught_exc: Exception | None = None
        remote_id = claimed_desired.get("remote_id")
        if not isinstance(remote_id, str) or not remote_id.strip():
            ok = False
            err = "remote_id_missing"
        else:
            try:
                result = provider.apply_remote_operation(op_type, claimed_desired)  # network
                ok = bool(result.success)
                err = safe_provider_summary(result.error) if result.error else None
            except Exception as exc:  # noqa: BLE001 — isolate per-op provider failures
                err_summary = safe_provider_summary(exc)
                log.exception("remote push op %s failed: %s", op_id, err_summary)
                caught_exc = exc
                ok = False
                err = err_summary

        with Session() as session:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                # Side effect may have landed remotely; leave IN_PROGRESS for reconcile.
                return {"status": "fencing_mismatch", "pushed": pushed, "failed": failed}
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is None:
                continue

            # CAS check: must still be IN_PROGRESS and desired_state / revision must match what was claimed
            if (
                op.status != RemoteOperationStatus.IN_PROGRESS.value
                or dict(op.desired_state or {}) != claimed_desired
                or op.updated_at != claimed_updated_at
            ):
                log.info(
                    "remote op %s modified during push; preserving PENDING and reenqueuing push",
                    op_id,
                )
                op.status = RemoteOperationStatus.PENDING.value
                enqueue_job(
                    session,
                    job_type=JobType.REMOTE_OPERATION_PUSH.value,
                    account_id=account_id,
                    payload={},
                    priority=40,
                    dedupe_key=f"remote-op-push:{account_id}",
                )
                session.commit()
                continue
            if ok:
                mark_remote_operation(session, op, status=RemoteOperationStatus.DONE, next_attempt_at=None)
                pushed += 1
            else:
                now_retry = datetime.now(timezone.utc)
                if is_rate_limited_error(caught_exc, err):
                    delay = get_retry_after_seconds(caught_exc, fallback=60.0)
                    next_attempt = now_retry + timedelta(seconds=delay)
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=err or "rate limited",
                        next_attempt_at=next_attempt,
                    )
                    enqueue_job(
                        session,
                        job_type=JobType.REMOTE_OPERATION_PUSH.value,
                        account_id=account_id,
                        payload={},
                        priority=40,
                        run_after=next_attempt,
                        dedupe_key=f"remote-op-push:{account_id}",
                    )
                elif is_transient_error(caught_exc, err) and int(op.attempts) < DEFAULT_MAX_REMOTE_OP_ATTEMPTS:
                    delay = min(3600, 2 ** max(0, int(op.attempts) - 1))
                    next_attempt = now_retry + timedelta(seconds=delay)
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=err or "transient failure",
                        next_attempt_at=next_attempt,
                    )
                    enqueue_job(
                        session,
                        job_type=JobType.REMOTE_OPERATION_PUSH.value,
                        account_id=account_id,
                        payload={},
                        priority=40,
                        run_after=next_attempt,
                        dedupe_key=f"remote-op-push:{account_id}",
                    )
                else:
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.FAILED,
                        error=err or "push failed",
                        next_attempt_at=None,
                    )
                    failed += 1
            try:
                heartbeat_lease(
                    session,
                    account_id=account_id,
                    owner_id=worker_id,
                    fencing_token=fencing,
                    ttl=lease_ttl,
                )
            except FencingMismatch:
                session.rollback()
                return {"status": "fencing_mismatch", "pushed": pushed, "failed": failed}
            session.commit()

    with Session() as session:
        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        except FencingMismatch:
            pass
        now_end = datetime.now(timezone.utc)
        next_due = None
        has_due_pending = session.scalar(
            select(RemoteOperation.id)
            .where(RemoteOperation.account_id == account_id)
            .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
            .where(
                or_(
                    RemoteOperation.next_attempt_at.is_(None),
                    RemoteOperation.next_attempt_at <= now_end,
                )
            )
            .limit(1)
        ) is not None
        if has_due_pending:
            enqueue_job(
                session,
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id,
                payload={},
                priority=40,
                dedupe_key=f"remote-op-push:{account_id}",
            )
        else:
            next_due = session.scalar(
                select(func.min(RemoteOperation.next_attempt_at))
                .where(RemoteOperation.account_id == account_id)
                .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
                .where(RemoteOperation.next_attempt_at > now_end)
            )
            if next_due:
                enqueue_job(
                    session,
                    job_type=JobType.REMOTE_OPERATION_PUSH.value,
                    account_id=account_id,
                    payload={},
                    priority=40,
                    run_after=next_due,
                    dedupe_key=f"remote-op-push:{account_id}",
                )
        session.commit()
    return {
        "status": "ok",
        "pushed": pushed,
        "failed": failed,
        "has_more": has_due_pending,
        "next_run_after": next_due,
    }


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
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=grace_seconds)
    entity_keys: list[str] = []
    for r in remote_ids:
        entity_keys.append(f"msg:{r}:read")
        entity_keys.append(f"msg:{r}:flag")

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
        ).all()
    )
    intents: dict[str, dict[str, Any]] = {}
    for op in ops:
        parts = op.entity_key.split(":")
        if len(parts) >= 3 and parts[0] == "msg":
            rem_id = parts[1]
            field_name = "is_read" if parts[2] == "read" else ("is_flagged" if parts[2] == "flag" else None)
            if field_name and field_name in (op.desired_state or {}):
                intents.setdefault(rem_id, {})[field_name] = op.desired_state[field_name]
    return intents


def reconcile_account_writeback_and_stats(
    session: Session, account_id: uuid.UUID
) -> dict[str, int]:
    """Recover orphan pending writebacks and recompute drifted folder stats for an account."""
    pending_count = session.scalar(
        select(func.count(RemoteOperation.id))
        .where(RemoteOperation.account_id == account_id)
        .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
    ) or 0

    active_job = session.scalar(
        select(WorkerJob.id)
        .where(WorkerJob.account_id == account_id)
        .where(WorkerJob.dedupe_key == f"remote-op-push:{account_id}")
        .where(WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]))
        .limit(1)
    )
    enqueued = 0
    if pending_count > 0 and not active_job:
        enqueue_job(
            session,
            job_type=JobType.REMOTE_OPERATION_PUSH.value,
            account_id=account_id,
            payload={},
            priority=40,
            dedupe_key=f"remote-op-push:{account_id}",
        )
        enqueued = 1

    folders = list(session.scalars(select(Folder).where(Folder.account_id == account_id)).all())
    for f in folders:
        recompute_folder_stats(session, f.id)

    session.flush()
    return {
        "pending_ops": pending_count,
        "enqueued_jobs": enqueued,
        "folders_recomputed": len(folders),
    }


push_pending_remote_operations = push_remote_operations
