"""Push pending remote_operations via provider.apply_remote_operation."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.application.remote_ops import mark_remote_operation, reclaim_stale_in_progress
from mail_core.mail.domain.enums import JobStatus, JobType, OutboxEventType, RemoteOperationStatus
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, OutboxEvent, RemoteOperation
from mail_core.providers.connection_slots import (
    CAPACITY_ERRORS,
    CAPACITY_RETRY_SECONDS,
    TrafficClass,
    is_capacity_error,
)
from mail_core.providers.factory import build_provider
from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.providers.remote_writeback import OP_MOVE, OP_TRASH, normalize_op_type
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

_HTTP_STATUS_PREFIXES = (
    re.compile(
        r"^HTTP(?:Error)?(?:/\d+(?:\.\d+)?)?\s+(?:ERROR\s+)?(?P<status>\d{3})\b",
        re.IGNORECASE,
    ),
    re.compile(r"^[A-Za-z][A-Za-z0-9_.]*\s+status=(?P<status>\d{3})(?:\s|$)", re.IGNORECASE),
    re.compile(
        r"^(?P<status>429|5\d{2})\s+"
        r"(?:too many requests|server error|internal server error|bad gateway|"
        r"service unavailable|gateway timeout|temporarily unavailable)\b",
        re.IGNORECASE,
    ),
)
_TRANSIENT_ERROR_PREFIXES = (
    re.compile(
        r"^(?:TimeoutError|TimeoutException|ConnectTimeout|ReadTimeout|WriteTimeout|PoolTimeout|"
        r"NetworkError|SocketError)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:request|operation|connection|connect|read|write)\s+"
        r"(?:timed out|timeout|reset|refused|closed|failed|error)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:server error|internal server error|service unavailable|temporarily unavailable|"
        r"gateway timeout|bad gateway)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:temporary|transient)\s+(?:server|provider)\s+(?:failure|error)\b",
        re.IGNORECASE,
    ),
)
_RATE_LIMIT_ERROR_PREFIXES = (
    re.compile(
        r"^(?:rate[- ]limited(?:error)?|ratelimited(?:error)?|rate limit(?:ed)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^too many requests\b", re.IGNORECASE),
)


class RemoteIdentityConflict(ValueError):
    """The provider returned a remote id already owned by another local message."""


def _coerce_status_code(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isdigit():
        return int(value)
    return None


def _exception_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None and hasattr(exc, "response"):
        status = getattr(getattr(exc, "response"), "status_code", None)
    return _coerce_status_code(status)


def _error_text_status_code(err_msg: str) -> int | None:
    for pattern in _HTTP_STATUS_PREFIXES:
        match = pattern.match(err_msg.strip())
        if match:
            return int(match.group("status"))
    return None


def _is_transient_status(status_code: int | None) -> bool:
    return status_code == 429 or (status_code is not None and 500 <= status_code < 600)


def _persist_move_remote_state(
    session,
    *,
    account_id: uuid.UUID,
    provider_type: str,
    op_type: str,
    desired_state: dict,
    remote_state: dict,
) -> bool:
    if normalize_op_type(op_type) not in (OP_MOVE, OP_TRASH) or not isinstance(remote_state, dict):
        return False
    source_remote_id = desired_state.get("remote_id")
    if not isinstance(source_remote_id, str) or not source_remote_id.strip():
        return False
    message = session.scalar(
        select(Message)
        .where(Message.account_id == account_id, Message.remote_id == source_remote_id)
        .with_for_update()
    )
    # Local-first trash may have deleted the message before remote delivery.
    if message is None:
        return False

    new_remote_id = remote_state.get("remote_id") or remote_state.get("id")
    if not isinstance(new_remote_id, str) or not new_remote_id.strip():
        new_remote_id = None
    if new_remote_id and new_remote_id != message.remote_id:
        conflict = session.scalar(
            select(Message.id)
            .where(
                Message.account_id == account_id,
                Message.remote_id == new_remote_id,
                Message.id != message.id,
            )
            .limit(1)
        )
        if conflict is not None:
            raise RemoteIdentityConflict("provider move returned a remote id already owned by another message")

    target_remote_folder = remote_state.get("folder_remote_id")
    if not isinstance(target_remote_folder, str) or not target_remote_folder.strip():
        target_remote_folder = None
    source_remote_folder = desired_state.get("folder_remote_id")
    source_folder = None
    if isinstance(source_remote_folder, str) and source_remote_folder:
        source_folder = session.scalar(
            select(Folder).where(Folder.account_id == account_id, Folder.remote_id == source_remote_folder)
        )
    target_folder = None
    if target_remote_folder:
        target_folder = session.scalar(
            select(Folder).where(Folder.account_id == account_id, Folder.remote_id == target_remote_folder)
        )

    if (
        target_remote_folder
        and target_remote_folder != source_remote_folder
        and provider_type == "imap"
        and not new_remote_id
    ):
        # An IMAP UID is scoped to its source folder/UIDVALIDITY. Without COPYUID
        # the destination identity is unknown; do not report the move as done.
        raise RemoteIdentityConflict("IMAP MOVE succeeded without a destination UID (COPYUID)")

    changed = False
    if new_remote_id and new_remote_id != message.remote_id:
        message.remote_id = new_remote_id
        changed = True

    affected_folder_ids: set[uuid.UUID] = set()
    if target_remote_folder and target_folder is None:
        # Keep the message row (and its new identity) while folder discovery
        # creates the destination; metadata sync then reattaches the location.
        if source_folder is not None:
            source_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == message.id,
                    MessageLocation.folder_id == source_folder.id,
                )
            )
            if source_location is not None:
                session.delete(source_location)
                affected_folder_ids.add(source_folder.id)
                changed = True
        enqueue_job(
            session,
            job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
            account_id=account_id,
            payload={},
            priority=50,
            dedupe_key=f"sync-folders:{account_id}",
        )
    elif target_folder is not None:
        if source_folder is not None and source_folder.id != target_folder.id:
            source_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == message.id,
                    MessageLocation.folder_id == source_folder.id,
                )
            )
            if source_location is not None:
                session.delete(source_location)
                affected_folder_ids.add(source_folder.id)
                changed = True
        destination_location = session.scalar(
            select(MessageLocation).where(
                MessageLocation.message_id == message.id,
                MessageLocation.folder_id == target_folder.id,
            )
        )
        raw_uid = remote_state.get("uid")
        uid = raw_uid if isinstance(raw_uid, int) and not isinstance(raw_uid, bool) else None
        if destination_location is None:
            session.add(MessageLocation(message_id=message.id, folder_id=target_folder.id, uid=uid))
            changed = True
        elif uid is not None and destination_location.uid != uid:
            destination_location.uid = uid
            changed = True
        if changed:
            affected_folder_ids.add(target_folder.id)

    if not changed:
        return False
    session.flush()
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_UPSERTED.value,
            account_id=account_id,
            payload={"message_id": str(message.id), "remote_id": message.remote_id},
        )
    )
    for folder_id in affected_folder_ids:
        recompute_folder_stats(session, folder_id)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
            )
        )
    return True


def is_transient_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    if exc is not None:
        if isinstance(exc, RateLimitedError):
            return True
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        status_code = _exception_status_code(exc)
        if status_code is not None:
            return _is_transient_status(status_code)
        name = type(exc).__name__.lower()
        if any(term in name for term in ("timeout", "connect", "network", "socket")):
            return True
    if err_msg:
        if _is_transient_status(_error_text_status_code(err_msg)):
            return True
        if any(pattern.match(err_msg.strip()) for pattern in _TRANSIENT_ERROR_PREFIXES):
            return True
    return False


def is_rate_limited_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    if exc is not None:
        if isinstance(exc, RateLimitedError):
            return True
        status_code = _exception_status_code(exc)
        if status_code is not None:
            return status_code == 429
    if err_msg:
        if _error_text_status_code(err_msg) == 429:
            return True
        if any(pattern.match(err_msg.strip()) for pattern in _RATE_LIMIT_ERROR_PREFIXES):
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
    from mail_core.providers.base import RemoteOperationItem, RemoteOperationResult

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
            next_due = session.scalar(
                select(func.min(RemoteOperation.next_attempt_at))
                .where(RemoteOperation.account_id == account_id)
                .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
                .where(RemoteOperation.next_attempt_at.is_not(None))
            )
            if next_due is not None:
                enqueue_job(
                    session,
                    job_type=JobType.REMOTE_OPERATION_PUSH.value,
                    account_id=account_id,
                    payload={},
                    priority=40,
                    run_after=next_due,
                    dedupe_key=f"remote-op-push:{account_id}",
                )
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                pass
        return {"status": "ok", "pushed": 0, "failed": 0}

    # Pre-network TX: Mark all batch operations IN_PROGRESS under fencing
    claimed_desired = {}
    claimed_updated_at = {}
    with Session() as session:
        try:
            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}

        for op_id, op_type, desired in work:
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is not None and op.status == RemoteOperationStatus.PENDING.value:
                mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
                claimed_desired[op_id] = dict(op.desired_state or {})
                claimed_updated_at[op_id] = op.updated_at

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
            return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
        session.commit()

    # Resolve IMAP trash folder once for the entire batch if needed
    real_trash = None
    if str(account_snapshot.provider or "").lower() == "imap":
        if any(op_type == "trash" for _, op_type, _ in work):
            try:
                from mail_core.mail.application.mutations import _resolve_imap_trash_folder

                with Session() as s:
                    real_trash = _resolve_imap_trash_folder(s, account_id)
            except Exception:
                pass

    items: list[RemoteOperationItem] = []
    for op_id, op_type, desired in work:
        if op_id not in claimed_desired:
            continue
        effective_desired = dict(claimed_desired[op_id])
        if op_type == "trash" and real_trash:
            if effective_desired.get("trash_folder_remote_id") in (None, "", "Trash"):
                effective_desired["trash_folder_remote_id"] = real_trash
        items.append(RemoteOperationItem(op_id=op_id, op_type=op_type, desired_state=effective_desired))

    try:
        provider = build_provider(account_snapshot, store or get_credential_store(), traffic_class=traffic_class)
    except CAPACITY_ERRORS as exc:
        delay = float(getattr(exc, "retry_after_seconds", None) or CAPACITY_RETRY_SECONDS)
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
        with Session() as session:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
            for op_id in claimed_desired:
                op = session.get(RemoteOperation, op_id, with_for_update=True)
                if op is not None and op.status == RemoteOperationStatus.IN_PROGRESS.value:
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=None,
                        next_attempt_at=next_attempt,
                    )
                    op.attempts = max(0, int(op.attempts) - 1)
            enqueue_job(
                session,
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id,
                payload={},
                priority=40,
                run_after=next_attempt,
                dedupe_key=f"remote-op-push:{account_id}",
            )
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            except FencingMismatch:
                pass
            session.commit()
        return {"status": "capacity_unavailable", "retry_after": delay, "pushed": 0, "failed": 0}
    except Exception:
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                pass
        raise

    valid_items: list[RemoteOperationItem] = []
    pre_failed_results: dict[Any, RemoteOperationResult] = {}
    for it in items:
        rid = it.desired_state.get("remote_id")
        if not isinstance(rid, str) or not rid.strip():
            pre_failed_results[it.op_id] = RemoteOperationResult(success=False, error="remote_id_missing")
        else:
            valid_items.append(it)

    # Execute network call in batch for valid items with lease heartbeats between chunks
    results_map: dict[Any, RemoteOperationResult] = dict(pre_failed_results)
    caught_batch_exc: Exception | None = None
    if valid_items:
        chunk_size = 100
        for i in range(0, len(valid_items), chunk_size):
            chunk = valid_items[i : i + chunk_size]
            try:
                if hasattr(provider, "apply_remote_operations"):
                    results_seq = provider.apply_remote_operations(chunk)
                    results_map.update({res[0]: res[1] for res in results_seq})
                else:
                    for it in chunk:
                        res = provider.apply_remote_operation(it.op_type, it.desired_state)
                        results_map[it.op_id] = res
            except Exception as exc:  # noqa: BLE001
                caught_batch_exc = exc
                err_summary = safe_provider_summary(exc)
                log.error("remote push batch failed: %s", err_summary)
                break

            # Heartbeat lease between chunks to prevent TTL expiration on large batches
            if i + chunk_size < len(valid_items):
                with Session() as hb_session:
                    try:
                        heartbeat_lease(
                            hb_session,
                            account_id=account_id,
                            owner_id=worker_id,
                            fencing_token=fencing,
                            ttl=lease_ttl,
                        )
                        hb_session.commit()
                    except FencingMismatch:
                        log.warning("fencing mismatch during batched remote push heartbeat for %s", account_id)
                        break
                    except Exception as hb_exc:
                        log.warning("lease heartbeat between chunks failed: %s", hb_exc)

    if is_capacity_error(caught_batch_exc):
        delay = float(getattr(caught_batch_exc, "retry_after_seconds", None) or CAPACITY_RETRY_SECONDS)
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
        with Session() as session:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
            for op_id in claimed_desired:
                op = session.get(RemoteOperation, op_id, with_for_update=True)
                if op is not None and op.status == RemoteOperationStatus.IN_PROGRESS.value:
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=None,
                        next_attempt_at=next_attempt,
                    )
                    op.attempts = max(0, int(op.attempts) - 1)
            enqueue_job(
                session,
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id,
                payload={},
                priority=40,
                run_after=next_attempt,
                dedupe_key=f"remote-op-push:{account_id}",
            )
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            except FencingMismatch:
                pass
            session.commit()
        return {"status": "capacity_unavailable", "retry_after": delay, "pushed": 0, "failed": 0}

    # Post-network settlement under fencing
    pushed = 0
    failed = 0
    followup_needed = False

    with Session() as session:
        try:
            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            # AC-009: Side effect may have landed remotely; leave IN_PROGRESS for reconcile.
            return {"status": "fencing_mismatch", "pushed": 0, "failed": 0}

        for item in items:
            op_id = item.op_id
            op = session.get(RemoteOperation, op_id, with_for_update=True)
            if op is None:
                continue

            # CAS check: must still be IN_PROGRESS and desired_state / revision must match what was claimed
            if (
                op.status != RemoteOperationStatus.IN_PROGRESS.value
                or dict(op.desired_state or {}) != claimed_desired[op_id]
                or op.updated_at != claimed_updated_at[op_id]
            ):
                log.info(
                    "remote op %s modified during push; preserving PENDING and reenqueuing push",
                    op_id,
                )
                op.status = RemoteOperationStatus.PENDING.value
                followup_needed = True
                continue

            if caught_batch_exc is not None:
                result = RemoteOperationResult(success=False, error=safe_provider_summary(caught_batch_exc))
            else:
                result = results_map.get(op_id)
                if result is None:
                    result = RemoteOperationResult(success=False, error="operation unhandled in provider batch")

            ok = bool(result.success)
            err = safe_provider_summary(result.error) if result.error else None
            remote_state = getattr(result, "remote_state", {}) or {}

            if ok:
                try:
                    _persist_move_remote_state(
                        session,
                        account_id=account_id,
                        provider_type=str(account_snapshot.provider or "").lower(),
                        op_type=item.op_type,
                        desired_state=item.desired_state,
                        remote_state=remote_state,
                    )
                except RemoteIdentityConflict as exc:
                    ok = False
                    err = safe_provider_summary(exc)

            if ok:
                applied = mark_remote_operation(
                    session,
                    op,
                    status=RemoteOperationStatus.DONE,
                    next_attempt_at=None,
                    expected_revision=int(claimed_desired[op_id].get("revision") or 0),
                )
                if applied:
                    pushed += 1
                else:
                    op.status = RemoteOperationStatus.PENDING.value
                    followup_needed = True
            else:
                failed += 1
                now_retry = datetime.now(timezone.utc)
                retry_after_sec = remote_state.get("retry_after") if isinstance(remote_state, dict) else None
                is_rate_limit = (retry_after_sec is not None) or is_rate_limited_error(caught_batch_exc, err)

                if is_rate_limit and int(op.attempts) < DEFAULT_MAX_REMOTE_OP_ATTEMPTS:
                    delay = float(retry_after_sec or get_retry_after_seconds(caught_batch_exc, fallback=60.0))
                    next_attempt = now_retry + timedelta(seconds=delay)
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=err or "rate limited",
                        next_attempt_at=next_attempt,
                    )
                    followup_needed = True
                elif is_transient_error(caught_batch_exc, err) and int(op.attempts) < DEFAULT_MAX_REMOTE_OP_ATTEMPTS:
                    delay = min(3600, 2 ** max(0, int(op.attempts) - 1))
                    next_attempt = now_retry + timedelta(seconds=delay)
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.PENDING,
                        error=err or "transient failure",
                        next_attempt_at=next_attempt,
                    )
                    followup_needed = True
                else:
                    mark_remote_operation(
                        session,
                        op,
                        status=RemoteOperationStatus.FAILED,
                        error=err or "push failed",
                        next_attempt_at=None,
                    )

        # Re-check if remaining pending operations exist (AC-012)
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
                .where(RemoteOperation.next_attempt_at.is_not(None))
            )
            if next_due is not None:
                enqueue_job(
                    session,
                    job_type=JobType.REMOTE_OPERATION_PUSH.value,
                    account_id=account_id,
                    payload={},
                    priority=40,
                    run_after=next_due,
                    dedupe_key=f"remote-op-push:{account_id}",
                )

        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        except FencingMismatch:
            pass
        session.commit()

    return {"status": "ok", "pushed": pushed, "failed": failed}


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
            .order_by(RemoteOperation.created_at.asc(), RemoteOperation.id.asc())
        ).all()
    )
    intents: dict[str, dict[str, Any]] = {}
    for op in ops:
        entity, separator, field = op.entity_key.rpartition(":")
        if not separator or not entity.startswith("msg:"):
            continue
        rem_id = entity.removeprefix("msg:")
        field_name = "is_read" if field == "read" else ("is_flagged" if field == "flag" else None)
        if field_name and field_name in (op.desired_state or {}):
            intents.setdefault(rem_id, {})[field_name] = op.desired_state[field_name]
    return intents


