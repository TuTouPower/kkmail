"""Local-first message mutations that enqueue remote_operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import JobType, OutboxEventType
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Account, AccountGroup, Folder, Message, MessageLocation, OutboxEvent
from mail_core.realtime.notify import try_notify_outbox
from mail_core.sync.jobs import enqueue_job

MARK_ALL_READ_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class MutationResult:
    message_id: uuid.UUID
    account_id: uuid.UUID
    operation_id: uuid.UUID | None
    is_read: bool | None = None
    is_flagged: bool | None = None


@dataclass(frozen=True, slots=True)
class MarkAllReadBatchResult:
    count: int
    last_message_id: uuid.UUID | None


class UnaddressableMessageError(ValueError):
    """Raised when an operation requires a provider ID that is unknown."""


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


def _has_provider_remote_id(msg: Message) -> bool:
    return isinstance(msg.remote_id, str) and bool(msg.remote_id.strip())


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
    operation_id = None
    if _has_provider_remote_id(msg):
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
        operation_id = op.id
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_UPSERTED.value,
            account_id=msg.account_id,
            payload={"message_id": str(msg.id), "is_read": is_read},
        )
    )
    _recompute_stats_for_folders(session, account_id=msg.account_id, folder_ids=folder_ids)
    if operation_id is not None:
        _wake_push(session, msg.account_id)
    try_notify_outbox(session)
    session.flush()
    return MutationResult(
        message_id=msg.id,
        account_id=msg.account_id,
        operation_id=operation_id,
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
    operation_id = None
    if _has_provider_remote_id(msg):
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
        operation_id = op.id
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.MESSAGE_UPSERTED.value,
            account_id=msg.account_id,
            payload={"message_id": str(msg.id), "is_flagged": is_flagged},
        )
    )
    if operation_id is not None:
        _wake_push(session, msg.account_id)
    try_notify_outbox(session)
    session.flush()
    return MutationResult(
        message_id=msg.id,
        account_id=msg.account_id,
        operation_id=operation_id,
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
    if not _has_provider_remote_id(msg):
        raise UnaddressableMessageError("message has no verified provider remote id")
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


def _mark_all_read_query(
    session: Session,
    *,
    account_id: uuid.UUID | None,
    folder_role: str | None,
    folder_id: uuid.UUID | None,
    is_flagged: bool | None,
    group_id: uuid.UUID | None,
    account_ids: list[uuid.UUID] | None,
    after_message_id: uuid.UUID | None,
    limit: int,
):
    if group_id is not None and account_ids is None and session.get(AccountGroup, group_id) is None:
        raise LookupError("group not found")
    if folder_id is not None:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise LookupError(f"folder {folder_id} not found")
        if account_id is not None and folder.account_id != account_id:
            raise LookupError(f"folder {folder_id} does not belong to specified account")
        if group_id is not None:
            account = session.get(Account, folder.account_id)
            if account is None or account.group_id != group_id:
                raise LookupError("folder does not belong to specified group")
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
    if account_ids is not None:
        stmt = stmt.where(Message.account_id.in_(account_ids))
    elif group_id is not None:
        stmt = stmt.where(Message.account_id.in_(select(Account.id).where(Account.group_id == group_id)))
    if is_flagged is not None:
        stmt = stmt.where(Message.is_flagged == is_flagged)
    if after_message_id is not None:
        stmt = stmt.where(Message.id > after_message_id)
    return stmt.distinct().order_by(Message.id).limit(limit)


def mark_all_messages_read(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    folder_role: str | None = "inbox",
    folder_id: uuid.UUID | None = None,
    is_flagged: bool | None = None,
    group_id: uuid.UUID | None = None,
    account_ids: list[uuid.UUID] | None = None,
    after_message_id: uuid.UUID | None = None,
    limit: int = MARK_ALL_READ_BATCH_SIZE,
) -> MarkAllReadBatchResult:
    """Mark one bounded keyset batch; callers commit and continue after its last message ID."""
    limit = min(max(limit, 1), MARK_ALL_READ_BATCH_SIZE)
    stmt = _mark_all_read_query(
        session,
        account_id=account_id,
        folder_role=folder_role,
        folder_id=folder_id,
        is_flagged=is_flagged,
        group_id=group_id,
        account_ids=account_ids,
        after_message_id=after_message_id,
        limit=limit,
    )

    messages = list(session.scalars(stmt).all())
    if not messages:
        return MarkAllReadBatchResult(count=0, last_message_id=None)

    loc_rows = session.execute(
        select(MessageLocation.message_id, MessageLocation.folder_id, Folder.remote_id)
        .join(Folder, MessageLocation.folder_id == Folder.id)
        .where(MessageLocation.message_id.in_([m.id for m in messages]))
    ).all()

    msg_folders: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for mid, fid, f_remote_id in loc_rows:
        msg_folders.setdefault(mid, []).append((fid, f_remote_id or "INBOX"))

    affected_accounts: set[uuid.UUID] = set()
    remote_operation_accounts: set[uuid.UUID] = set()
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

        if _has_provider_remote_id(msg):
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
            remote_operation_accounts.add(msg.account_id)
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

    for acc_id in remote_operation_accounts:
        _wake_push(session, acc_id)

    try_notify_outbox(session)
    session.flush()
    return MarkAllReadBatchResult(count=len(messages), last_message_id=messages[-1].id)

