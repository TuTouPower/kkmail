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
    Account,
    FolderStats,
    Message,
    MessageArchiveState,
    MessageLocation,
    OutboxEvent,
)
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync.checkpoints import commit_checkpoint
from mail_core.sync.leases import assert_fencing
from mail_core.search.index import upsert_message_search_batch
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
    "is_flagged",
    "internet_message_id",
    "snippet",
    "size_bytes",
)


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    message: Message
    created: bool
    changed: bool
    location_created: bool = False
    read_changed: bool = False


def _dedupe_metas(metas: list[RemoteMessageMeta]) -> list[RemoteMessageMeta]:
    """First occurrence wins for a repeated remote_id within one page (A146).

    Providers occasionally repeat a remote_id in a single page; feeding the
    duplicate through the upsert would create a second MessageLocation for
    the same (message, folder) and hit the unique constraint, poisoning
    the whole page transaction.
    """
    seen: set[str] = set()
    out: list[RemoteMessageMeta] = []
    for meta in metas:
        if meta.remote_id in seen:
            continue
        seen.add(meta.remote_id)
        out.append(meta)
    return out


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
    metas = _dedupe_metas(list(metas))
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
    from mail_core.sync.remote_push import get_unconverged_field_intents

    intents = get_unconverged_field_intents(session, account_id, remote_ids, now=now)
    out: list[UpsertOutcome] = []
    for meta in metas:
        msg = existing.get(meta.remote_id)
        created = msg is None
        location_created = False
        if created:
            msg = Message(
                id=uuid.uuid4(),
                account_id=account_id,
                remote_id=meta.remote_id,
                sort_time=meta.sort_time,
            )
            session.add(msg)
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.METADATA_SYNCED.value))
            new_loc = MessageLocation(message_id=msg.id, folder_id=folder_id, uid=meta.uid)
            session.add(new_loc)
            # Register the just-created location so any later reference to
            # this message in the same page reuses it (A146).
            locs[msg.id] = new_loc
            existing[meta.remote_id] = msg
            location_created = True
        else:
            loc = locs.get(msg.id)
            if loc is None:
                loc = MessageLocation(message_id=msg.id, folder_id=folder_id, uid=meta.uid)
                session.add(loc)
                locs[msg.id] = loc
                location_created = True
            elif meta.uid is not None and loc.uid != meta.uid:
                loc.uid = meta.uid
        changed = created or location_created
        read_changed = False
        for field in _META_FIELDS:
            if meta.supplied_fields is not None and field not in meta.supplied_fields:
                continue
            value = getattr(meta, field)
            if field == "sort_time" and value is None:
                continue
            if field in ("is_read", "is_flagged", "has_attachments") and value is None:
                continue
            if (
                field in ("is_read", "is_flagged")
                and meta.remote_id in intents
                and field in intents[meta.remote_id]
            ):
                value = intents[meta.remote_id][field]
            if getattr(msg, field) != value:
                if field == "is_read":
                    read_changed = True
                setattr(msg, field, value)
                changed = True
        for field in ("to_addresses", "cc_addresses"):
            if meta.supplied_fields is not None and field not in meta.supplied_fields:
                continue
            value = list(getattr(meta, field))
            if list(getattr(msg, field) or []) != value:
                setattr(msg, field, value)
                changed = True
        if changed:
            msg.updated_at = now
        out.append(
            UpsertOutcome(
                message=msg,
                created=created,
                changed=changed,
                location_created=location_created,
                read_changed=read_changed,
            )
        )
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
    scan_generation: uuid.UUID | None = None,
) -> MetadataApplyResult:
    """Network I/O must happen *before* this call. Writes + cursor share one TX."""
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    items = _dedupe_metas(list(page.items))
    outcomes = upsert_messages(session, account_id=account_id, folder_id=folder_id, metas=items)
    touched: list[uuid.UUID] = []
    touched_messages: dict[uuid.UUID, Message] = {}
    message_event_ids: list[uuid.UUID] = []
    folder_stats_dirty = False
    for o, meta in zip(outcomes, items):
        if o.location_created:
            folder_stats_dirty = True
        if o.changed:
            touched.append(o.message.id)
            touched_messages[o.message.id] = o.message
            message_event_ids.append(o.message.id)
        # Thread headers are not stored locally, so an unchanged outcome may
        # still need re-evaluation after its parent arrives in a later scan.
        if (
            meta.provider_thread_key
            or meta.in_reply_to
            or meta.references
            or (o.created and meta.internet_message_id)
        ):
            previous_thread_id = o.message.thread_id
            assignment = assign_thread_for_message(
                session,
                message=o.message,
                in_reply_to=meta.in_reply_to,
                references=meta.references,
                provider_thread_key=meta.provider_thread_key,
            )
            if assignment.thread_id != previous_thread_id:
                message_event_ids.append(o.message.id)
    if touched:
        # body_text=None → prefer MessageBody.text_plain; never clobber FTS with snippet.
        upsert_message_search_batch(session, messages=list(touched_messages.values()))
        folder_stats_dirty = True

    new_recipients: set[str] = set()
    for o in outcomes:
        if o.created or o.changed:
            for item in (getattr(o.message, "to_addresses", None) or []):
                if isinstance(item, str) and item.strip():
                    new_recipients.add(item.strip())
                elif isinstance(item, dict) and item.get("address"):
                    new_recipients.add(str(item["address"]).strip())
    if new_recipients:
        account = session.get(Account, account_id)
        if account is not None:
            current_raw = list(getattr(account, "recipient_addresses", None) or [])
            current_lowers = {a.lower() for a in current_raw}
            added = [r for r in sorted(new_recipients) if r.lower() not in current_lowers]
            if added:
                account.recipient_addresses = current_raw + added

    if message_event_ids:
        session.add(messages_upserted_event(account_id, folder_id, list(dict.fromkeys(message_event_ids))))

    affected_folders = {folder_id} if folder_stats_dirty or session.get(FolderStats, folder_id) is None else set()
    read_changed_ids = [o.message.id for o in outcomes if o.read_changed]
    if read_changed_ids:
        shared_folders = session.scalars(
            select(MessageLocation.folder_id).where(MessageLocation.message_id.in_(read_changed_ids))
        ).all()
        affected_folders.update(shared_folders)

    if affected_folders:
        session.flush()
        for fid in sorted(affected_folders):
            recompute_folder_stats(session, fid)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                    account_id=account_id,
                    payload={"folder_id": str(fid)},
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
        scan_generation=scan_generation,
    )
    try_notify_outbox(session)
    session.flush()
    return MetadataApplyResult(upserted=len(items), exhausted=page.exhausted, cursor=cursor)
