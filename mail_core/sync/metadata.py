"""Apply provider metadata pages into local authority + checkpoint (same TX)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import ArchiveState, OutboxEventType
from mail_core.mail.storage.models import (
    FolderStats,
    Message,
    MessageArchiveState,
    MessageLocation,
    OutboxEvent,
)
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync.checkpoints import commit_checkpoint
from mail_core.sync.leases import assert_fencing
from mail_core.search.index import upsert_message_search
from mail_core.threading.rules import assign_thread_for_message
from mail_core.realtime.notify import try_notify_outbox


@dataclass(frozen=True, slots=True)
class MetadataApplyResult:
    upserted: int
    exhausted: bool
    cursor: dict


def _upsert_message(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    meta: RemoteMessageMeta,
) -> Message:
    existing = session.scalar(
        select(Message).where(Message.account_id == account_id, Message.remote_id == meta.remote_id)
    )
    if existing is None:
        existing = Message(account_id=account_id, remote_id=meta.remote_id, sort_time=meta.sort_time)
        session.add(existing)
        session.flush()
        session.add(MessageArchiveState(message_id=existing.id, state=ArchiveState.METADATA_SYNCED.value))
        session.add(
            MessageLocation(message_id=existing.id, folder_id=folder_id, uid=meta.uid)
        )
    else:
        loc = session.scalar(
            select(MessageLocation).where(
                MessageLocation.message_id == existing.id,
                MessageLocation.folder_id == folder_id,
            )
        )
        if loc is None:
            session.add(MessageLocation(message_id=existing.id, folder_id=folder_id, uid=meta.uid))
        elif meta.uid is not None:
            loc.uid = meta.uid

    existing.subject = meta.subject
    existing.from_address = meta.from_address
    existing.from_name = meta.from_name
    existing.sort_time = meta.sort_time
    existing.is_read = meta.is_read
    existing.has_attachments = meta.has_attachments
    existing.internet_message_id = meta.internet_message_id
    existing.snippet = meta.snippet
    existing.size_bytes = meta.size_bytes
    existing.to_addresses = list(meta.to_addresses)
    existing.cc_addresses = list(meta.cc_addresses)
    existing.updated_at = datetime.now(timezone.utc)
    session.flush()
    return existing


def recompute_folder_stats(session: Session, folder_id: uuid.UUID) -> None:
    """Aggregate folder totals via SQL COUNT (no full ORM load)."""
    from sqlalchemy import func

    total = (
        session.scalar(
            select(func.count())
            .select_from(MessageLocation)
            .where(MessageLocation.folder_id == folder_id)
        )
        or 0
    )
    unread = (
        session.scalar(
            select(func.count())
            .select_from(MessageLocation)
            .join(Message, Message.id == MessageLocation.message_id)
            .where(MessageLocation.folder_id == folder_id)
            .where(Message.is_read.is_(False))
        )
        or 0
    )
    stats = session.get(FolderStats, folder_id)
    if stats is None:
        stats = FolderStats(folder_id=folder_id)
        session.add(stats)
    stats.total_count = int(total)
    stats.unread_count = int(unread)
    stats.updated_at = datetime.now(timezone.utc)


# Back-compat alias for sync internals still calling the private name.
_recompute_folder_stats = recompute_folder_stats


def apply_metadata_page(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    fencing_token: int,
    page: MetadataPage,
) -> MetadataApplyResult:
    """Network I/O must happen *before* this call. Writes + cursor share one TX."""
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    for meta in page.items:
        msg = _upsert_message(session, account_id=account_id, folder_id=folder_id, meta=meta)
        upsert_message_search(session, message_id=msg.id, body_text=meta.snippet or "")
        if meta.internet_message_id or meta.provider_thread_key:
            assign_thread_for_message(
                session,
                message=msg,
                provider_thread_key=meta.provider_thread_key,
            )
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.MESSAGE_UPSERTED.value,
                account_id=account_id,
                payload={"message_id": str(msg.id), "folder_id": str(folder_id)},
            )
        )
    _recompute_folder_stats(session, folder_id)
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
        )
    )
    cursor = page.next_cursor or {}
    commit_checkpoint(
        session,
        account_id=account_id,
        folder_id=folder_id,
        fencing_token=fencing_token,
        cursor=cursor,
        uidvalidity=cursor.get("uidvalidity"),
        full_scan_complete=page.exhausted,
    )
    try_notify_outbox(session)
    session.flush()
    return MetadataApplyResult(upserted=len(page.items), exhausted=page.exhausted, cursor=cursor)
