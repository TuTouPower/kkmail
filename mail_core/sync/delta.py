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
from mail_core.sync.checkpoints import commit_checkpoint
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, assert_fencing, release_lease
from mail_core.sync.metadata import _recompute_folder_stats, _upsert_message

log = logging.getLogger("mail_core.sync.delta")


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
    for change in page.changes:
        if change.kind == "upsert" and change.meta is not None:
            msg = _upsert_message(session, account_id=account_id, folder_id=folder_id, meta=change.meta)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.MESSAGE_UPSERTED.value,
                    account_id=account_id,
                    payload={"message_id": str(msg.id), "folder_id": str(folder_id)},
                )
            )
            upserted += 1
        elif change.kind == "flag" and change.meta is not None:
            msg = _upsert_message(session, account_id=account_id, folder_id=folder_id, meta=change.meta)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.MESSAGE_UPSERTED.value,
                    account_id=account_id,
                    payload={"message_id": str(msg.id), "folder_id": str(folder_id), "flag": True},
                )
            )
            flagged += 1
        elif change.kind == "delete":
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
        modseq=cursor.get("modseq"),
        full_scan_complete=True,  # delta assumes baseline already complete
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
    lease_ttl: timedelta = timedelta(seconds=60),
    max_pages: int = 20,
) -> dict:
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        folder = session.get(Folder, folder_id)
        if account is None or folder is None:
            raise ValueError("account/folder not found")
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
    while pages < max_pages:
        page = provider.delta_changes(remote_id, cursor)  # network
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
            # Schedule next poll
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=70,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
    return {"status": "ok", "exhausted": exhausted, "pages": pages, **totals}
