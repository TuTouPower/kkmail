"""Desired-state remote_operations queue (architecture §9). Local-first."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import OutboxEvent, RemoteOperation
from mail_core.mail.domain.enums import OutboxEventType


def enqueue_remote_operation(
    session: Session,
    *,
    account_id: uuid.UUID,
    entity_key: str,
    op_type: str,
    desired_state: dict,
    idempotency_key: str | None = None,
) -> RemoteOperation:
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
        op.last_error = error
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
