"""Database move/trash state persistence helpers for remote push."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from mail_core.mail.domain.enums import ExecutionOrigin, JobType, OutboxEventType
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Folder, Message, MessageLocation, OutboxEvent
from mail_core.providers.remote_writeback import OP_MOVE, OP_TRASH, normalize_op_type
from mail_core.sync.jobs import enqueue_job


class RemoteIdentityConflict(ValueError):
    """The provider returned a remote id already owned by another local message."""


def _clean_nonempty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _assert_valid_move_identity(
    session,
    *,
    account_id: uuid.UUID,
    provider_type: str,
    message: Message,
    new_remote_id: str | None,
    source_remote_folder: Any,
    target_remote_folder: str | None,
) -> None:
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
            raise RemoteIdentityConflict(
                "provider move returned a remote id already owned by another message"
            )

    missing_copyuid = (
        target_remote_folder
        and target_remote_folder != source_remote_folder
        and provider_type == "imap"
        and not new_remote_id
    )
    if missing_copyuid:
        # An IMAP UID is scoped to its source folder/UIDVALIDITY. Without COPYUID
        # the destination identity is unknown; do not report the move as done.
        raise RemoteIdentityConflict("IMAP MOVE succeeded without a destination UID (COPYUID)")


def _load_move_folders(
    session,
    *,
    account_id: uuid.UUID,
    source_remote_folder: Any,
    target_remote_folder: str | None,
) -> tuple[Folder | None, Folder | None]:
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
    return source_folder, target_folder


def _delete_source_location(
    session,
    *,
    message_id: uuid.UUID,
    source_folder: Folder | None,
    affected_folder_ids: set[uuid.UUID],
) -> bool:
    if source_folder is None:
        return False
    source_location = session.scalar(
        select(MessageLocation).where(
            MessageLocation.message_id == message_id,
            MessageLocation.folder_id == source_folder.id,
        )
    )
    if source_location is None:
        return False
    session.delete(source_location)
    affected_folder_ids.add(source_folder.id)
    return True


def _upsert_target_location(
    session,
    *,
    message_id: uuid.UUID,
    target_folder: Folder,
    remote_state: dict,
) -> bool:
    destination_location = session.scalar(
        select(MessageLocation).where(
            MessageLocation.message_id == message_id,
            MessageLocation.folder_id == target_folder.id,
        )
    )
    raw_uid = remote_state.get("uid")
    uid = raw_uid if isinstance(raw_uid, int) and not isinstance(raw_uid, bool) else None
    if destination_location is None:
        session.add(MessageLocation(message_id=message_id, folder_id=target_folder.id, uid=uid))
        return True
    if uid is not None and destination_location.uid != uid:
        destination_location.uid = uid
        return True
    return False


def _sync_move_locations(
    session,
    *,
    account_id: uuid.UUID,
    message: Message,
    source_folder: Folder | None,
    target_folder: Folder | None,
    target_remote_folder: str | None,
    remote_state: dict,
    changed: bool,
) -> tuple[bool, set[uuid.UUID]]:
    affected_folder_ids: set[uuid.UUID] = set()
    if target_remote_folder and target_folder is None:
        # Keep the message row (and its new identity) while folder discovery
        # creates the destination; metadata sync then reattaches the location.
        changed = _delete_source_location(
            session,
            message_id=message.id,
            source_folder=source_folder,
            affected_folder_ids=affected_folder_ids,
        ) or changed
        enqueue_job(
            session,
            job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=account_id,
            payload={},
            priority=50,
            dedupe_key=f"sync-folders:{account_id}",
        )
        return changed, affected_folder_ids

    if target_folder is None:
        return changed, affected_folder_ids

    if source_folder is not None and source_folder.id != target_folder.id:
        changed = _delete_source_location(
            session,
            message_id=message.id,
            source_folder=source_folder,
            affected_folder_ids=affected_folder_ids,
        ) or changed
    if _upsert_target_location(session, message_id=message.id, target_folder=target_folder, remote_state=remote_state):
        changed = True
    if changed:
        affected_folder_ids.add(target_folder.id)
    return changed, affected_folder_ids


def _emit_move_outbox_events(
    session,
    *,
    account_id: uuid.UUID,
    message: Message,
    affected_folder_ids: set[uuid.UUID],
) -> None:
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


def persist_move_remote_state(
    session,
    *,
    account_id: uuid.UUID,
    provider_type: str,
    op_type: str,
    desired_state: dict,
    remote_state: dict,
) -> bool:
    """Persist remote identity and folder location changes after a remote move/trash."""
    if normalize_op_type(op_type) not in (OP_MOVE, OP_TRASH) or not isinstance(remote_state, dict):
        return False
    source_remote_id = _clean_nonempty_str(desired_state.get("remote_id"))
    if not source_remote_id:
        return False
    message = session.scalar(
        select(Message)
        .where(Message.account_id == account_id, Message.remote_id == source_remote_id)
        .with_for_update()
    )
    # Local-first trash may have deleted the message before remote delivery.
    if message is None:
        return False

    new_remote_id = _clean_nonempty_str(remote_state.get("remote_id") or remote_state.get("id"))
    target_remote_folder = _clean_nonempty_str(remote_state.get("folder_remote_id"))
    source_remote_folder = desired_state.get("folder_remote_id")
    _assert_valid_move_identity(
        session,
        account_id=account_id,
        provider_type=provider_type,
        message=message,
        new_remote_id=new_remote_id,
        source_remote_folder=source_remote_folder,
        target_remote_folder=target_remote_folder,
    )

    changed = False
    if new_remote_id and new_remote_id != message.remote_id:
        message.remote_id = new_remote_id
        changed = True

    source_folder, target_folder = _load_move_folders(
        session,
        account_id=account_id,
        source_remote_folder=source_remote_folder,
        target_remote_folder=target_remote_folder,
    )
    changed, affected_folder_ids = _sync_move_locations(
        session,
        account_id=account_id,
        message=message,
        source_folder=source_folder,
        target_folder=target_folder,
        target_remote_folder=target_remote_folder,
        remote_state=remote_state,
        changed=changed,
    )
    if not changed:
        return False
    _emit_move_outbox_events(
        session,
        account_id=account_id,
        message=message,
        affected_folder_ids=affected_folder_ids,
    )
    return True
