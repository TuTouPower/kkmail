"""Apply incremental DeltaPage under fencing; drive sync_folder_delta jobs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.domain.enums import JobStatus, JobType, OutboxEventType, SyncPhase, SyncStatus
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, OutboxEvent, SyncCheckpoint
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.providers.factory import build_provider
from mail_core.providers.http import CursorInvalidError, RateLimitedError
from mail_core.security.redact import safe_provider_summary
from mail_core.sync.checkpoints import commit_checkpoint, invalidate_checkpoint_for_rebuild
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    heartbeat_lease,
    release_lease,
)
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.sync.metadata import messages_upserted_event, upsert_messages
from mail_core.search.index import upsert_message_search
from mail_core.threading.rules import assign_thread_for_message

log = logging.getLogger("mail_core.sync.delta")


def _flag_patch_values(change: DeltaChange) -> dict[str, object]:
    flags = dict(change.flags or {})
    if not flags and change.meta is not None:
        for field_name in ("is_read", "is_flagged"):
            value = getattr(change.meta, field_name)
            if value is not None:
                flags[field_name] = value
    return flags


def _apply_flag_patches(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    changes: list,
) -> tuple[int, list[uuid.UUID]]:
    """Patch is_read / is_flagged only — never upsert stub meta that wipes subject/from."""
    from mail_core.sync.remote_push import get_unconverged_field_intents

    patches: list[tuple[str, dict]] = []
    for change in changes:
        flags = _flag_patch_values(change)
        if flags:
            patches.append((change.remote_id, flags))
    if not patches:
        return 0, []

    remote_ids = list(dict.fromkeys(remote_id for remote_id, _ in patches))
    now = datetime.now(timezone.utc)
    intents = get_unconverged_field_intents(session, account_id, remote_ids, now=now)
    messages = {
        message.remote_id: message
        for message in session.scalars(
            select(Message).where(
                Message.account_id == account_id,
                Message.remote_id.in_(remote_ids),
            )
        )
    }

    touched: list[uuid.UUID] = []
    flagged = 0
    for remote_id, flags in patches:
        msg = messages.get(remote_id)
        if msg is None:
            continue
        changed = False
        if "is_read" in flags:
            want = bool(flags["is_read"])
            if remote_id in intents and "is_read" in intents[remote_id]:
                want = bool(intents[remote_id]["is_read"])
            if msg.is_read != want:
                msg.is_read = want
                changed = True
        if "is_flagged" in flags:
            want = bool(flags["is_flagged"])
            if remote_id in intents and "is_flagged" in intents[remote_id]:
                want = bool(intents[remote_id]["is_flagged"])
            if msg.is_flagged != want:
                msg.is_flagged = want
                changed = True
        if changed:
            msg.updated_at = now
            touched.append(msg.id)
            flagged += 1
    if flagged > 0:
        session.flush()
    return flagged, touched




@dataclass(frozen=True, slots=True)
class DeltaApplyResult:
    upserted: int
    deleted: int
    flagged: int
    exhausted: bool
    cursor: dict


def apply_delta_page(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    fencing_token: int,
    page: DeltaPage,
) -> DeltaApplyResult:
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    upserted = deleted = flagged = 0
    # Coalesce supplied fields in response order; a delete discards earlier patches.
    last_kind = {c.remote_id: c.kind for c in page.changes}
    merged: dict[str, RemoteMessageMeta] = {}
    pending_flags: dict[str, dict] = {}
    meta_fields = {f.name for f in fields(RemoteMessageMeta)} - {"remote_id", "supplied_fields"}
    for change in page.changes:
        rid = change.remote_id
        if change.kind == "delete":
            merged.pop(rid, None)
            pending_flags.pop(rid, None)
        elif change.kind == "flag":
            patch = _flag_patch_values(change)
            pending_flags.setdefault(rid, {}).update(patch)
        elif change.kind == "upsert" and change.meta is not None:
            newer = change.meta
            older = merged.get(rid)
            flags = pending_flags.pop(rid, {})
            if older is not None:
                supplied = older.supplied_fields
                older = replace(older, **flags, supplied_fields=None if supplied is None else supplied | flags.keys())
                supplied = newer.supplied_fields if newer.supplied_fields is not None else meta_fields
                # Unknown parsed values never erase earlier known facts.
                values = {
                    name: getattr(newer, name)
                    for name in supplied
                    if getattr(newer, name) is not None
                    or name not in {"sort_time", "is_read", "is_flagged", "has_attachments"}
                }
                newer = replace(
                    older, **values,
                    supplied_fields=None if older.supplied_fields is None or newer.supplied_fields is None
                    else older.supplied_fields | supplied,
                )
            elif flags:
                supplied = newer.supplied_fields if newer.supplied_fields is not None else meta_fields
                missing_flags = {name: value for name, value in flags.items() if name not in supplied or getattr(newer, name) is None}
                newer = replace(newer, **missing_flags, supplied_fields=None if newer.supplied_fields is None else supplied | missing_flags.keys())
            merged[rid] = newer
    upserts = [DeltaChange(kind="upsert", remote_id=rid, meta=meta) for rid, meta in merged.items() if last_kind[rid] != "delete"]
    flag_changes = [DeltaChange(kind="flag", remote_id=rid, flags=flags) for rid, flags in pending_flags.items() if last_kind[rid] != "delete"]
    outcomes = upsert_messages(session, account_id=account_id, folder_id=folder_id, metas=[c.meta for c in upserts])
    touched: list[uuid.UUID] = []
    message_event_ids: list[uuid.UUID] = []
    for o, change in zip(outcomes, upserts):
        if o.changed:
            upserted += 1
            touched.append(o.message.id)
            message_event_ids.append(o.message.id)
            upsert_message_search(session, message_id=o.message.id)
        meta = change.meta
        # A repeated upsert can carry headers needed to resolve a newly arrived parent.
        if meta is not None and (
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
    flag_count, flag_touched = _apply_flag_patches(
        session, account_id=account_id, folder_id=folder_id, changes=flag_changes
    )
    flagged = flag_count
    touched.extend(flag_touched)
    message_event_ids.extend(flag_touched)
    if message_event_ids:
        session.add(messages_upserted_event(account_id, folder_id, list(dict.fromkeys(message_event_ids))))
    location_removed_count = 0
    for change in page.changes:
        if change.kind in ("upsert", "flag"):
            continue
        if change.kind == "delete" and last_kind.get(change.remote_id) == "delete":
            # Explicit delete from provider delta only (never inferred from incomplete scan).
            msg = session.scalar(
                select(Message).where(Message.account_id == account_id, Message.remote_id == change.remote_id)
            )
            if msg is None:
                continue
            loc = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == msg.id,
                    MessageLocation.folder_id == folder_id,
                )
            )
            if loc is not None:
                session.delete(loc)
                session.flush()
                location_removed_count += 1
            remaining = session.scalar(select(MessageLocation).where(MessageLocation.message_id == msg.id))
            if remaining is None:
                session.add(
                    OutboxEvent(
                        event_type=OutboxEventType.MESSAGE_REMOVED.value,
                        account_id=account_id,
                        payload={"message_id": str(msg.id), "remote_id": change.remote_id},
                    )
                )
                session.delete(msg)
                deleted += 1
            elif loc is not None:
                session.add(
                    OutboxEvent(
                        event_type=OutboxEventType.MESSAGE_UPSERTED.value,
                        account_id=account_id,
                        payload={"folder_id": str(folder_id), "message_ids": [str(msg.id)]},
                    )
                )
    dirty_folder_ids = {folder_id} if (touched or deleted or location_removed_count > 0) else set()
    if touched:
        shared_folders = session.scalars(
            select(MessageLocation.folder_id).where(MessageLocation.message_id.in_(touched))
        ).all()
        dirty_folder_ids.update(shared_folders)

    if dirty_folder_ids:
        session.flush()
        for fid in sorted(dirty_folder_ids):
            recompute_folder_stats(session, fid)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                    account_id=account_id,
                    payload={"folder_id": str(fid)},
                )
            )
    cursor = page.next_cursor or {}
    # Never force full_scan_complete=True here — preserve baseline flag set by metadata sync.
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
        full_scan_complete=None,
    )
    session.flush()
    return DeltaApplyResult(
        upserted=upserted,
        deleted=deleted,
        flagged=flagged,
        exhausted=page.exhausted,
        cursor=cursor,
    )


def sync_folder_delta(
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(seconds=120),
    max_pages: int = 20,
    poll_round: int = 0,
) -> dict:
    """Apply provider delta pages under fencing.

    Heartbeats between pages (default TTL 120s). On ``CursorInvalidError`` the
    checkpoint is cleared and a metadata rebuild is enqueued. Generic provider
    errors release the lease and re-raise after an explicit retry job.
    """
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        folder = session.get(Folder, folder_id)
        if account is None or folder is None:
            raise ValueError("account/folder not found")
        if not account.sync_enabled:
            return {"status": "sync_disabled"}
        if folder.sync_status == SyncStatus.PAUSED.value:
            return {"status": "skipped", "reason": "folder_not_selectable"}
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        if cp is None or not cp.full_scan_complete:
            # Delta needs a completed baseline (design §5.3): bind the
            # in-flight initialization scan when one exists; otherwise return
            # an explicit baseline_required — a list-view delta must never
            # implicitly start a heavy full scan.
            from mail_core.sync.execution import find_active_job

            init_job = find_active_job(session, f"metadata:{account_id}:{folder_id}")
            scan_in_progress = cp is not None and cp.scan_generation is not None
            if init_job is not None or scan_in_progress:
                return {"status": "skipped", "reason": "baseline_pending", "await_initialization": True}
            return {"status": "skipped", "reason": "baseline_required", "baseline_required": True}
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            followup = enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=60,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=5),
                dedupe_key=f"delta:{account_id}:{folder_id}",
            )
            followup_coalesced = followup.status == JobStatus.CLAIMED.value
            session.commit()
            return {
                "status": "lease_busy",
                "followup_scheduled": True,
                "followup_coalesced": followup_coalesced,
            }
        fencing = lease.fencing_token
        remote_id = folder.remote_id
        cursor = dict(cp.cursor or {})
        if cp.modseq is not None and "modseq" not in cursor:
            cursor["modseq"] = int(cp.modseq)
        if cp.history_id and "historyId" not in cursor and "history_id" not in cursor:
            cursor["historyId"] = cp.history_id
        if cp.delta_link and "delta_link" not in cursor and "next_link" not in cursor:
            cursor["delta_link"] = cp.delta_link
        if cp.uidvalidity is not None and "uidvalidity" not in cursor:
            cursor["uidvalidity"] = int(cp.uidvalidity)
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )
        session.commit()

    def _release_quiet(session) -> None:
        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        except FencingMismatch:
            session.rollback()

    try:
        provider = build_provider(account_snapshot, store or get_credential_store())
    except Exception:
        with Session() as session:
            _release_quiet(session)
            session.commit()
        raise

    totals = {"upserted": 0, "deleted": 0, "flagged": 0}
    exhausted = False
    pages = 0

    while pages < max_pages:
        try:
            page = provider.delta_changes(remote_id, cursor)  # network
        except CursorInvalidError as exc:
            with Session() as session:
                try:
                    assert_fencing(session, account_id=account_id, fencing_token=fencing)
                    invalidate_checkpoint_for_rebuild(
                        session, account_id=account_id, folder_id=folder_id, fencing_token=fencing
                    )
                    enqueue_job(
                        session,
                        job_type=JobType.SYNC_FOLDER_METADATA.value,
                        account_id=account_id,
                        payload={
                            "folder_id": str(folder_id),
                            "reason": "cursor_invalid",
                            "detail": safe_provider_summary(exc),
                        },
                        priority=40,
                        dedupe_key=f"metadata:{account_id}:{folder_id}",
                    )
                    release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                    session.commit()
                except FencingMismatch:
                    session.rollback()
                    return {"status": "fencing_mismatch", "pages": pages, **totals}
            return {"status": "cursor_invalid", "followup_scheduled": True, "pages": pages, **totals}
        except RateLimitedError as exc:
            delay = float(exc.retry_after_seconds or 60)
            delay = max(1.0, min(delay, 86400.0))
            with Session() as session:
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    account_id=account_id,
                    payload={"folder_id": str(folder_id)},
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
                    dedupe_key=f"delta:{account_id}:{folder_id}",
                )
                _release_quiet(session)
                session.commit()
            return {"status": "rate_limited", "retry_after": delay, "pages": pages, **totals}
        except Exception as exc:
            err_summary = safe_provider_summary(exc)
            log.error("delta provider I/O failed for folder %s: %s", folder_id, err_summary)
            with Session() as session:
                followup = enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    account_id=account_id,
                    payload={
                        "folder_id": str(folder_id),
                        "reason": "provider_error",
                        "detail": err_summary,
                    },
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=15),
                    dedupe_key=f"delta:{account_id}:{folder_id}",
                )
                followup_coalesced = followup.status == JobStatus.CLAIMED.value
                _release_quiet(session)
                session.commit()
            return {
                "status": "provider_error",
                "error": err_summary,
                "followup_scheduled": True,
                "followup_coalesced": followup_coalesced,
                "pages": pages,
                **totals,
            }

        with Session() as session:
            try:
                result = apply_delta_page(
                    session,
                    account_id=account_id,
                    folder_id=folder_id,
                    fencing_token=fencing,
                    page=page,
                )
            except FencingMismatch:
                return {"status": "fencing_mismatch", **totals}
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.SYNC_PROGRESS.value,
                    account_id=account_id,
                    payload={
                        "phase": SyncPhase.INCREMENTAL_READY.value,
                        "folder_id": str(folder_id),
                        "upserted": result.upserted,
                        "deleted": result.deleted,
                    },
                )
            )
            try:
                heartbeat_lease(
                    session,
                    account_id=account_id,
                    owner_id=worker_id,
                    fencing_token=fencing,
                    ttl=lease_ttl,
                )
            except FencingMismatch:
                session.rollback()
                return {"status": "fencing_mismatch", **totals}
            session.commit()
            totals["upserted"] += result.upserted
            totals["deleted"] += result.deleted
            totals["flagged"] += result.flagged
            cursor = result.cursor
            exhausted = result.exhausted
        pages += 1
        if exhausted:
            break

    with Session() as session:
        try:
            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch", **totals}
        if not exhausted:
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=60,
                dedupe_key=f"delta:{account_id}:{folder_id}",
            )
        else:
            # Schedule next poll and periodic reconcile
            next_round = poll_round + 1
            if next_round >= 20:
                enqueue_job(
                    session,
                    job_type=JobType.RECONCILE_FOLDER.value,
                    account_id=account_id,
                    payload={"folder_id": str(folder_id)},
                    priority=80,
                    dedupe_key=f"reconcile:{account_id}:{folder_id}",
                )
                next_round = 0
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id), "poll_round": next_round},
                priority=75,
                dedupe_key=f"delta:{account_id}:{folder_id}",
                run_after=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
    return {"status": "ok", "exhausted": exhausted, "pages": pages, **totals}
