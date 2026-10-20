"""Apply incremental DeltaPage under fencing; drive sync_folder_delta jobs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.domain.enums import JobType, OutboxEventType, SyncPhase
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, OutboxEvent, SyncCheckpoint
from mail_core.providers.base import DeltaPage
from mail_core.providers.factory import build_provider
from mail_core.providers.http import CursorInvalidError, RateLimitedError
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

def _apply_flag_patches(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    changes: list,
) -> tuple[int, list[uuid.UUID]]:
    """Patch is_read / is_flagged only — never upsert stub meta that wipes subject/from."""
    touched: list[uuid.UUID] = []
    flagged = 0
    for change in changes:
        flags = dict(change.flags or {})
        if change.meta is not None:
            # Prefer explicit flags dict; fall back to meta.is_read when providers only set meta.
            if "is_read" not in flags:
                flags["is_read"] = change.meta.is_read
        if not flags:
            continue
        msg = session.scalar(
            select(Message).where(Message.account_id == account_id, Message.remote_id == change.remote_id)
        )
        if msg is None:
            continue
        changed = False
        if "is_read" in flags:
            want = bool(flags["is_read"])
            if msg.is_read != want:
                msg.is_read = want
                changed = True
        if "is_flagged" in flags:
            want = bool(flags["is_flagged"])
            if msg.is_flagged != want:
                msg.is_flagged = want
                changed = True
        if changed:
            msg.updated_at = datetime.now(timezone.utc)
            touched.append(msg.id)
            flagged += 1
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
    # Changes are batched; the *last* change per remote id wins (upsert→delete deletes,
    # delete→upsert keeps the message), matching sequential application.
    last_kind = {c.remote_id: c.kind for c in page.changes}
    upserts = [
        c
        for c in page.changes
        if c.kind == "upsert" and c.meta is not None and last_kind.get(c.remote_id) != "delete"
    ]
    flag_changes = [
        c
        for c in page.changes
        if c.kind == "flag" and last_kind.get(c.remote_id) == "flag"
    ]
    outcomes = upsert_messages(session, account_id=account_id, folder_id=folder_id, metas=[c.meta for c in upserts])
    touched: list[uuid.UUID] = []
    for o, change in zip(outcomes, upserts):
        if not o.changed:
            continue
        touched.append(o.message.id)
        upsert_message_search(session, message_id=o.message.id)
        meta = change.meta
        if meta is not None and (
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
    upserted = len(upserts)
    flag_count, flag_touched = _apply_flag_patches(
        session, account_id=account_id, folder_id=folder_id, changes=flag_changes
    )
    flagged = flag_count
    touched.extend(flag_touched)
    if touched:
        session.add(messages_upserted_event(account_id, folder_id, touched))
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
    # Only emit stats/outbox when something actually changed (idempotent replay).
    if touched or deleted:
        recompute_folder_stats(session, folder_id)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
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
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        if cp is None or not cp.full_scan_complete:
            return {"status": "skipped", "reason": "baseline_incomplete"}
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=60,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=5),
            )
            session.commit()
            return {"status": "lease_busy"}
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

    provider = build_provider(account_snapshot, store or get_credential_store())
    totals = {"upserted": 0, "deleted": 0, "flagged": 0}
    exhausted = False
    pages = 0

    def _release_quiet(session) -> None:
        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        except FencingMismatch:
            session.rollback()

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
                            "detail": str(exc),
                        },
                        priority=40,
                    )
                    release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                    session.commit()
                except FencingMismatch:
                    session.rollback()
                    return {"status": "fencing_mismatch", "pages": pages, **totals}
            return {"status": "cursor_invalid", "pages": pages, **totals}
        except RateLimitedError as exc:
            delay = float(exc.retry_after_seconds or 60)
            with Session() as session:
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    account_id=account_id,
                    payload={"folder_id": str(folder_id)},
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
                )
                _release_quiet(session)
                session.commit()
            return {"status": "rate_limited", "retry_after": delay, "pages": pages, **totals}
        except Exception as exc:
            log.exception("delta provider I/O failed for folder %s: %s", folder_id, type(exc).__name__)
            with Session() as session:
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    account_id=account_id,
                    payload={
                        "folder_id": str(folder_id),
                        "reason": "provider_error",
                        "detail": f"{type(exc).__name__}: {exc}",
                    },
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=15),
                )
                _release_quiet(session)
                session.commit()
            return {
                "status": "provider_error",
                "error": f"{type(exc).__name__}: {exc}",
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
                priority=70,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
    return {"status": "ok", "exhausted": exhausted, "pages": pages, **totals}
