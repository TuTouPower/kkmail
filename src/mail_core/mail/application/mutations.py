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
from mail_core.realtime.notify import try_notify_outbox
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


def _all_location_folder_ids(session: Session, message_id: uuid.UUID) -> list[uuid.UUID]:
    """Every folder that currently holds this message (multi-location safe)."""
    return list(
        session.scalars(
            select(MessageLocation.folder_id).where(MessageLocation.message_id == message_id).distinct()
        ).all()
    )


def _recompute_stats_for_folders(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_ids: list[uuid.UUID],
) -> None:
    for folder_id in folder_ids:
        recompute_folder_stats(session, folder_id)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
            )
        )


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
    folder_ids = _all_location_folder_ids(session, message_id)
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
    _recompute_stats_for_folders(session, account_id=msg.account_id, folder_ids=folder_ids)
    _wake_push(session, msg.account_id)
    try_notify_outbox(session)
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
    try_notify_outbox(session)
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
    folder_ids = _all_location_folder_ids(session, message_id)
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
    session.flush()
    _recompute_stats_for_folders(session, account_id=account_id, folder_ids=folder_ids)
    _wake_push(session, account_id)
    try_notify_outbox(session)
    session.flush()
    return MutationResult(
        message_id=message_id,
        account_id=account_id,
        operation_id=op.id,
    )


def mark_all_messages_read(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    folder_role: str | None = "inbox",
    folder_id: uuid.UUID | None = None,
    is_flagged: bool | None = None,
) -> int:
    """Batch mark messages read matching the scope (account/folder_role/folder_id/flag). Returns updated count."""
    if folder_id is not None:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise LookupError(f"folder {folder_id} not found")
        if account_id is not None and folder.account_id != account_id:
            raise LookupError(f"folder {folder_id} does not belong to specified account")
        stmt = (
            select(Message)
            .join(MessageLocation, MessageLocation.message_id == Message.id)
            .where(MessageLocation.folder_id == folder_id)
            .where(Message.is_read.is_(False))
        )
    else:
        stmt = (
            select(Message)
            .join(MessageLocation, MessageLocation.message_id == Message.id)
            .join(Folder, MessageLocation.folder_id == Folder.id)
            .where(Folder.role == (folder_role or "inbox"))
            .where(Message.is_read.is_(False))
        )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    if is_flagged is not None:
        stmt = stmt.where(Message.is_flagged == is_flagged)

    messages = list(session.scalars(stmt.distinct()).all())
    if not messages:
        return 0

    loc_rows = session.execute(
        select(MessageLocation.message_id, MessageLocation.folder_id, Folder.remote_id)
        .join(Folder, MessageLocation.folder_id == Folder.id)
        .where(MessageLocation.message_id.in_([m.id for m in messages]))
    ).all()

    msg_folders: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for mid, fid, f_remote_id in loc_rows:
        msg_folders.setdefault(mid, []).append((fid, f_remote_id or "INBOX"))

    affected_accounts: set[uuid.UUID] = set()
    affected_folders_by_account: dict[uuid.UUID, set[uuid.UUID]] = {}

    for msg in messages:
        msg.is_read = True
        affected_accounts.add(msg.account_id)
        folders = msg_folders.get(msg.id, [])
        folder_ids = [fid for fid, _ in folders]
        primary_folder_remote = folders[0][1] if folders else "INBOX"

        if msg.account_id not in affected_folders_by_account:
            affected_folders_by_account[msg.account_id] = set()
        affected_folders_by_account[msg.account_id].update(folder_ids)

        desired = {
            "remote_id": msg.remote_id,
            "folder_remote_id": primary_folder_remote,
            "is_read": True,
        }
        enqueue_remote_operation(
            session,
            account_id=msg.account_id,
            entity_key=f"msg:{msg.remote_id}:read",
            op_type="mark_read",
            desired_state=desired,
            idempotency_key=f"{msg.id}:read:1",
        )
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.MESSAGE_UPSERTED.value,
                account_id=msg.account_id,
                payload={"message_id": str(msg.id), "is_read": True},
            )
        )

    for acc_id in affected_accounts:
        fids = affected_folders_by_account.get(acc_id, set())
        _recompute_stats_for_folders(session, account_id=acc_id, folder_ids=list(fids))
        _wake_push(session, acc_id)

    try_notify_outbox(session)
    session.flush()
    return len(messages)

