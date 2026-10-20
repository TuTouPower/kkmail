"""Apply provider metadata pages into local authority + checkpoint (same TX)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import ArchiveState, OutboxEventType
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import (
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


_META_FIELDS = (
    "subject",
    "from_address",
    "from_name",
    "sort_time",
    "is_read",
    "has_attachments",
    "internet_message_id",
    "snippet",
    "size_bytes",
)


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    message: Message
    created: bool
    changed: bool


def upsert_messages(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    metas: list[RemoteMessageMeta],
) -> list[UpsertOutcome]:
    """Upsert a page of remote metadata with two batched lookups.

    Rows whose metadata did not change are left untouched (no UPDATE), so callers can
    skip search/thread/outbox work for them.
    """
    if not metas:
        return []
    remote_ids = [m.remote_id for m in metas]
    existing = {
        m.remote_id: m
        for m in session.scalars(
            select(Message).where(Message.account_id == account_id, Message.remote_id.in_(remote_ids))
        )
    }
    locs: dict[uuid.UUID, MessageLocation] = {}
    if existing:
        locs = {
            loc.message_id: loc
            for loc in session.scalars(
                select(MessageLocation).where(
                    MessageLocation.folder_id == folder_id,
                    MessageLocation.message_id.in_([m.id for m in existing.values()]),
                )
            )
        }
    now = datetime.now(timezone.utc)
    out: list[UpsertOutcome] = []
    for meta in metas:
        msg = existing.get(meta.remote_id)
        created = msg is None
        if created:
            msg = Message(account_id=account_id, remote_id=meta.remote_id, sort_time=meta.sort_time)
            session.add(msg)
            session.flush()
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.METADATA_SYNCED.value))
            session.add(MessageLocation(message_id=msg.id, folder_id=folder_id, uid=meta.uid))
            existing[meta.remote_id] = msg
        else:
            loc = locs.get(msg.id)
            if loc is None:
                loc = MessageLocation(message_id=msg.id, folder_id=folder_id, uid=meta.uid)
                session.add(loc)
                locs[msg.id] = loc
            elif meta.uid is not None and loc.uid != meta.uid:
                loc.uid = meta.uid
        changed = created
        for field in _META_FIELDS:
            value = getattr(meta, field)
            if getattr(msg, field) != value:
                setattr(msg, field, value)
                changed = True
        for field in ("to_addresses", "cc_addresses"):
            value = list(getattr(meta, field))
            if list(getattr(msg, field) or []) != value:
                setattr(msg, field, value)
                changed = True
        if changed:
            msg.updated_at = now
        out.append(UpsertOutcome(message=msg, created=created, changed=changed))
    session.flush()
    return out


def messages_upserted_event(account_id: uuid.UUID, folder_id: uuid.UUID, ids: list[uuid.UUID]) -> OutboxEvent:
    """One outbox event per page (not per message)."""
    return OutboxEvent(
        event_type=OutboxEventType.MESSAGE_UPSERTED.value,
        account_id=account_id,
        payload={"folder_id": str(folder_id), "message_ids": [str(i) for i in ids]},
    )


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
    outcomes = upsert_messages(session, account_id=account_id, folder_id=folder_id, metas=list(page.items))
    touched: list[uuid.UUID] = []
    for o, meta in zip(outcomes, page.items):
        if not o.changed:
            continue
        touched.append(o.message.id)
        # body_text=None → prefer MessageBody.text_plain; never clobber FTS with snippet.
        upsert_message_search(session, message_id=o.message.id)
        if o.created and (
            meta.internet_message_id
            or meta.provider_thread_key
            or meta.in_reply_to
            or meta.references
        ):
            assign_thread_for_message(
                session,
                message=o.message,
                in_reply_to=meta.in_reply_to,
                references=meta.references,
                provider_thread_key=meta.provider_thread_key,
            )
    if touched:
        session.add(messages_upserted_event(account_id, folder_id, touched))
        recompute_folder_stats(session, folder_id)
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
        modseq=cursor.get("modseq"),
        history_id=cursor.get("historyId") or cursor.get("history_id"),
        delta_link=cursor.get("delta_link"),
        full_scan_complete=page.exhausted,
    )
    try_notify_outbox(session)
    session.flush()
    return MetadataApplyResult(upserted=len(page.items), exhausted=page.exhausted, cursor=cursor)
