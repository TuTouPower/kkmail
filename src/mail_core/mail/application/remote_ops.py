"""Desired-state remote_operations queue (architecture §9). Local-first."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import OutboxEventType, RemoteOperationStatus
from mail_core.mail.storage.models import OutboxEvent, RemoteOperation
from mail_core.security.redact import redact


def _ensure_operation_owner(
    existing: RemoteOperation,
    *,
    account_id: uuid.UUID,
    entity_key: str,
    op_type: str,
) -> None:
    if existing.account_id != account_id or existing.entity_key != entity_key or existing.op_type != op_type:
        raise ValueError("cannot coalesce remote operation owned by another account or operation")


def _coalesce_existing(
    session: Session,
    existing: RemoteOperation,
    *,
    account_id: uuid.UUID,
    entity_key: str,
    op_type: str,
    desired_state: dict,
) -> RemoteOperation:
    _ensure_operation_owner(
        existing,
        account_id=account_id,
        entity_key=entity_key,
        op_type=op_type,
    )
    now = datetime.now(timezone.utc)
    if existing.status == RemoteOperationStatus.DONE.value:
        existing.created_at = now
    new_desired = dict(desired_state)
    current_rev = int((existing.desired_state or {}).get("revision") or 0)
    new_desired["revision"] = current_rev + 1
    existing.desired_state = new_desired
    existing.status = RemoteOperationStatus.PENDING.value
    existing.next_attempt_at = None
    existing.updated_at = now
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.REMOTE_OPERATION_UPDATED.value,
            account_id=account_id,
            payload={
                "operation_id": str(existing.id),
                "status": existing.status,
                "op_type": op_type,
                "revision": new_desired["revision"],
                "upsert": True,
            },
        )
    )
    session.flush()
    return existing


def enqueue_remote_operation(
    session: Session,
    *,
    account_id: uuid.UUID,
    entity_key: str,
    op_type: str,
    desired_state: dict,
    idempotency_key: str | None = None,
) -> RemoteOperation:
    """Enqueue or upsert by ``idempotency_key`` / pending ``entity_key`` (desired-state).

    Concurrent inserts with the same key are coalesced via a savepoint: the loser
    of the UNIQUE race reloads the winner and refreshes desired_state.

    Pending ops for the same ``entity_key`` (e.g. read True then False) collapse
    into one row so the worker pushes the latest desired_state only.
    """
    if idempotency_key:
        existing = session.scalar(
            select(RemoteOperation)
            .where(RemoteOperation.account_id == account_id)
            .where(RemoteOperation.idempotency_key == idempotency_key)
            .limit(1)
            .with_for_update()
        )
        if existing is not None:
            return _coalesce_existing(
                session,
                existing,
                account_id=account_id,
                entity_key=entity_key,
                op_type=op_type,
                desired_state=desired_state,
            )

    active_op = session.scalar(
        select(RemoteOperation)
        .where(RemoteOperation.account_id == account_id)
        .where(RemoteOperation.entity_key == entity_key)
        .where(
            RemoteOperation.status.in_(
                [
                    RemoteOperationStatus.PENDING.value,
                    RemoteOperationStatus.IN_PROGRESS.value,
                ]
            )
        )
        .order_by(
            case(
                (RemoteOperation.status == RemoteOperationStatus.PENDING.value, 0),
                else_=1,
            ),
            RemoteOperation.created_at.asc(),
        )
        .limit(1)
        .with_for_update()
    )
    if active_op is not None:
        return _coalesce_existing(
            session,
            active_op,
            account_id=account_id,
            entity_key=entity_key,
            op_type=op_type,
            desired_state=desired_state,
        )

    initial_desired = dict(desired_state)
    if "revision" not in initial_desired:
        initial_desired["revision"] = 1

    op = RemoteOperation(
        account_id=account_id,
        entity_key=entity_key,
        op_type=op_type,
        desired_state=initial_desired,
        status=RemoteOperationStatus.PENDING.value,
        idempotency_key=idempotency_key,
    )
    if idempotency_key:
        try:
            with session.begin_nested():
                session.add(op)
                session.flush()
        except IntegrityError:
            existing = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.idempotency_key == idempotency_key)
                .limit(1)
                .with_for_update()
            )
            if existing is None:
                raise
            return _coalesce_existing(
                session,
                existing,
                account_id=account_id,
                entity_key=entity_key,
                op_type=op_type,
                desired_state=desired_state,
            )
    else:
        session.add(op)
        session.flush()

    session.add(
        OutboxEvent(
            event_type=OutboxEventType.REMOTE_OPERATION_UPDATED.value,
            account_id=account_id,
            payload={"operation_id": str(op.id), "status": op.status, "op_type": op_type},
        )
    )
    return op


def mark_remote_operation(
    session: Session,
    op: RemoteOperation,
    *,
    status: RemoteOperationStatus,
    error: str | None = None,
    next_attempt_at: datetime | None = None,
) -> None:
    op.status = status.value
    op.updated_at = datetime.now(timezone.utc)
    op.next_attempt_at = next_attempt_at
    if status in (RemoteOperationStatus.DONE, RemoteOperationStatus.IN_PROGRESS):
        op.last_error = None
    elif error:
        op.last_error = redact(error[:2000])
    if status == RemoteOperationStatus.IN_PROGRESS:
        op.attempts = int(op.attempts) + 1
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.REMOTE_OPERATION_UPDATED.value,
            account_id=op.account_id,
            payload={"operation_id": str(op.id), "status": op.status},
        )
    )
    session.flush()


def reclaim_stale_in_progress(
    session: Session,
    *,
    older_than: timedelta = timedelta(minutes=15),
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    """Reset stuck ``in_progress`` remote ops back to ``pending`` after a crash/fence loss.

    Ops left ``in_progress`` when fencing is lost mid-push (side effect may or may
    not have landed) are retried; providers must be idempotent on desired_state.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    rows = list(
        session.scalars(
            select(RemoteOperation)
            .where(RemoteOperation.status == RemoteOperationStatus.IN_PROGRESS.value)
            .where(RemoteOperation.updated_at < cutoff)
            .order_by(RemoteOperation.updated_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for op in rows:
        op.status = RemoteOperationStatus.PENDING.value
        op.next_attempt_at = None
        op.updated_at = now
        op.last_error = (op.last_error or "")[:1800]
        suffix = "|reclaimed_stale_in_progress"
        if not (op.last_error or "").endswith(suffix):
            op.last_error = ((op.last_error or "") + suffix)[:2000]
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.REMOTE_OPERATION_UPDATED.value,
                account_id=op.account_id,
                payload={"operation_id": str(op.id), "status": op.status, "reclaimed": True},
            )
        )
    session.flush()
    return len(rows)
