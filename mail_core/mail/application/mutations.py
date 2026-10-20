"""Local-first message mutations that enqueue remote_operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import JobType, OutboxEventType
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Folder, Message, MessageLocation, OutboxEvent
from mail_core.sync.jobs import enqueue_job


@dataclass(frozen=True, slots=True)
class MutationResult:
    message_id: uuid.UUID
    account_id: uuid.UUID
    operation_id: uuid.UUID
    is_read: bool | None = None
    is_flagged: bool | None = None


def _primary_location(session: Session, message_id: uuid.UUID) -> tuple[Folder | None, MessageLocation | None]:
    loc = session.scalar(select(MessageLocation).where(MessageLocation.message_id == message_id).limit(1))
    if loc is None:
        return None, None
    folder = session.get(Folder, loc.folder_id)
    return folder, loc


def _wake_push(session: Session, account_id: uuid.UUID) -> None:
    enqueue_job(
        session,
        job_type=JobType.REMOTE_OPERATION_PUSH.value,
        account_id=account_id,
        payload={},
        priority=40,
        dedupe_key=f"remote-op-push:{account_id}",
    )


def set_message_read(
    session: Session,
    message_id: uuid.UUID,
    *,
    is_read: bool = True,
) -> MutationResult:
    msg = session.get(Message, message_id)
    if msg is None:
        raise LookupError("message not found")
    msg.is_read = is_read
    folder, _loc = _primary_location(session, message_id)
    desired = {
        "remote_id": msg.remote_id,
        "folder_remote_id": folder.remote_id if folder else "INBOX",
        "is_read": is_read,
    }
    op = enqueue_remote_operation(
        session,
        account_id=msg.account_id,
        entity_key=f"msg:{msg.remote_id}:read",
        op_type="mark_read",
        desired_state=desired,
        idempotency_key=f"{msg.id}:read:{int(is_read)}",
    )
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_UPSERTED.value,
            account_id=msg.account_id,
            payload={"message_id": str(msg.id), "is_read": is_read},
        )
    )
    if folder is not None:
        recompute_folder_stats(session, folder.id)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=msg.account_id,
                payload={"folder_id": str(folder.id)},
            )
        )
    _wake_push(session, msg.account_id)
    session.flush()
    return MutationResult(
        message_id=msg.id,
        account_id=msg.account_id,
        operation_id=op.id,
        is_read=is_read,
    )


def set_message_flagged(
    session: Session,
    message_id: uuid.UUID,
    *,
    is_flagged: bool = True,
) -> MutationResult:
    msg = session.get(Message, message_id)
    if msg is None:
        raise LookupError("message not found")
    msg.is_flagged = is_flagged
    folder, _loc = _primary_location(session, message_id)
    desired = {
        "remote_id": msg.remote_id,
        "folder_remote_id": folder.remote_id if folder else "INBOX",
        "is_flagged": is_flagged,
    }
    op = enqueue_remote_operation(
        session,
        account_id=msg.account_id,
        entity_key=f"msg:{msg.remote_id}:flag",
        op_type="set_flag",
        desired_state=desired,
        idempotency_key=f"{msg.id}:flag:{int(is_flagged)}",
    )
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_UPSERTED.value,
            account_id=msg.account_id,
            payload={"message_id": str(msg.id), "is_flagged": is_flagged},
        )
    )
    _wake_push(session, msg.account_id)
    session.flush()
    return MutationResult(
        message_id=msg.id,
        account_id=msg.account_id,
        operation_id=op.id,
        is_flagged=is_flagged,
    )


def trash_message(session: Session, message_id: uuid.UUID) -> MutationResult:
    """Local-first trash: remove message metadata locally and enqueue remote trash.

    Archive interaction: deleting the message cascades ``message_archive_state`` /
    blob links (FK ON DELETE CASCADE). An in-flight archive batch re-reads the state
    row and skips messages that vanished, so no FSM transition is needed here.
    Read/flag mutations do not affect MIME archiving.
    """
    msg = session.get(Message, message_id)
    if msg is None:
        raise LookupError("message not found")
    folder, _loc = _primary_location(session, message_id)
    desired = {
        "remote_id": msg.remote_id,
        "folder_remote_id": folder.remote_id if folder else "INBOX",
        "trash_folder_remote_id": "Trash",
    }
    op = enqueue_remote_operation(
        session,
        account_id=msg.account_id,
        entity_key=f"msg:{msg.remote_id}:trash",
        op_type="trash",
        desired_state=desired,
        idempotency_key=f"{msg.id}:trash",
    )
    account_id = msg.account_id
    folder_id = folder.id if folder else None
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_REMOVED.value,
            account_id=account_id,
            payload={"message_id": str(message_id)},
        )
    )
    # Drop local rows (cascade attachments/locations via ORM relationships or explicit).
    for loc in list(
        session.scalars(select(MessageLocation).where(MessageLocation.message_id == message_id)).all()
    ):
        session.delete(loc)
    session.delete(msg)
    if folder_id is not None:
        recompute_folder_stats(session, folder_id)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
            )
        )
    _wake_push(session, account_id)
    session.flush()
    return MutationResult(
        message_id=message_id,
        account_id=account_id,
        operation_id=op.id,
    )
