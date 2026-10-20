"""Desired-state remote_operations queue (architecture §9). Local-first."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import OutboxEventType, RemoteOperationStatus
from mail_core.mail.storage.models import OutboxEvent, RemoteOperation


def enqueue_remote_operation(
    session: Session,
    *,
    account_id: uuid.UUID,
    entity_key: str,
    op_type: str,
    desired_state: dict,
    idempotency_key: str | None = None,
) -> RemoteOperation:
    """Enqueue or upsert by ``idempotency_key`` (unique) to avoid IntegrityError storms."""
    if idempotency_key:
        existing = session.scalar(
            select(RemoteOperation).where(RemoteOperation.idempotency_key == idempotency_key).limit(1)
        )
        if existing is not None:
            existing.desired_state = desired_state
            existing.op_type = op_type
            existing.entity_key = entity_key
            existing.status = RemoteOperationStatus.PENDING.value
            existing.updated_at = datetime.now(timezone.utc)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.REMOTE_OPERATION_UPDATED.value,
                    account_id=account_id,
                    payload={"operation_id": str(existing.id), "status": existing.status, "op_type": op_type, "upsert": True},
                )
            )
            session.flush()
            return existing

    op = RemoteOperation(
        account_id=account_id,
        entity_key=entity_key,
        op_type=op_type,
        desired_state=desired_state,
        status=RemoteOperationStatus.PENDING.value,
        idempotency_key=idempotency_key,
    )
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
) -> None:
    op.status = status.value
    op.updated_at = datetime.now(timezone.utc)
    if error:
        op.last_error = error[:2000]
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
