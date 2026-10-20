"""Sync engine: folder discovery + metadata pages wired for the Worker.

Network I/O runs outside DB transactions; checkpoint/message writes are short
fencing-gated transactions (architecture §7.6).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.domain.enums import JobType, OutboxEventType, SyncPhase
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, OutboxEvent, SyncCheckpoint, SyncRun
from mail_core.providers.factory import build_provider
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, release_lease
from mail_core.sync.metadata import apply_metadata_page

log = logging.getLogger("mail_core.sync.engine")


def _session_factory():
    from mail_core.db.session import get_session_factory

    return get_session_factory()


def sync_account_folders(
    account_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(seconds=60),
) -> dict:
    """Discover remote folders, upsert local Folder rows, enqueue metadata jobs."""
    Session = _session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"account {account_id} not found")
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            return {"status": "lease_busy"}
        session.commit()
        fencing = lease.fencing_token
        # Detach config for network I/O
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )

    provider = build_provider(account_snapshot, store or get_credential_store())
    remote_folders = list(provider.list_folders())  # network

    with Session() as session:
        try:
            from mail_core.sync.leases import assert_fencing

            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch"}

        run = SyncRun(
            account_id=account_id,
            phase=SyncPhase.FOLDER_DISCOVERY.value,
            status="running",
            fencing_token=fencing,
        )
        session.add(run)
        upserted = 0
        folder_ids: list[uuid.UUID] = []
        for rf in remote_folders:
            existing = session.scalar(
                select(Folder).where(Folder.account_id == account_id, Folder.remote_id == rf.remote_id)
            )
            if existing is None:
                existing = Folder(
                    account_id=account_id,
                    remote_id=rf.remote_id,
                    name=rf.name,
                    role=rf.role,
                    parent_remote_id=rf.parent_remote_id,
                )
                session.add(existing)
                session.flush()
                upserted += 1
            else:
                existing.name = rf.name
                existing.role = rf.role
                existing.parent_remote_id = rf.parent_remote_id
            folder_ids.append(existing.id)
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                payload={"folder_id": str(existing.id)},
                priority=50,
            )
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.SYNC_PROGRESS.value,
                account_id=account_id,
                payload={"phase": SyncPhase.FOLDER_DISCOVERY.value, "folders": len(folder_ids)},
            )
        )
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        run.stats = {"folders": len(folder_ids), "upserted": upserted}
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
        return {"status": "ok", "folders": len(folder_ids), "upserted": upserted}


def sync_folder_metadata(
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(seconds=60),
    max_pages: int = 20,
) -> dict:
    """Pull metadata pages until exhausted or max_pages; enqueue reconcile when done."""
    Session = _session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        folder = session.get(Folder, folder_id)
        if account is None or folder is None:
            raise ValueError("account/folder not found")
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            # Re-queue later
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=50,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=5),
            )
            session.commit()
            return {"status": "lease_busy"}
        fencing = lease.fencing_token
        remote_id = folder.remote_id
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        cursor = dict(cp.cursor) if cp else {}
        session.commit()

    provider = build_provider(account_snapshot, store or get_credential_store())
    total = 0
    exhausted = False
    pages = 0
    while pages < max_pages:
        page = provider.fetch_metadata_page(remote_id, cursor)  # network
        with Session() as session:
            try:
                result = apply_metadata_page(
                    session,
                    account_id=account_id,
                    folder_id=folder_id,
                    fencing_token=fencing,
                    page=page,
                )
            except FencingMismatch:
                return {"status": "fencing_mismatch", "upserted": total}
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.SYNC_PROGRESS.value,
                    account_id=account_id,
                    payload={
                        "phase": SyncPhase.METADATA.value,
                        "folder_id": str(folder_id),
                        "upserted": result.upserted,
                        "exhausted": result.exhausted,
                    },
                )
            )
            session.commit()
            total += result.upserted
            cursor = result.cursor
            exhausted = result.exhausted
        pages += 1
        if exhausted:
            break

    with Session() as session:
        try:
            from mail_core.sync.leases import assert_fencing

            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch", "upserted": total}
        if exhausted:
            enqueue_job(
                session,
                job_type=JobType.RECONCILE_FOLDER.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=80,
            )
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=60,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=2),
            )
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.SYNC_COMPLETED.value,
                    account_id=account_id,
                    payload={"folder_id": str(folder_id), "kind": "metadata"},
                )
            )
        else:
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=50,
            )
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
    return {"status": "ok", "upserted": total, "exhausted": exhausted, "pages": pages}


def local_remote_ids_for_folder(session: Session, folder_id: uuid.UUID) -> list[str]:
    rows = session.execute(
        select(Message.remote_id)
        .join(MessageLocation, MessageLocation.message_id == Message.id)
        .where(MessageLocation.folder_id == folder_id)
    ).all()
    return [r[0] for r in rows]
