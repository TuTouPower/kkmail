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
from mail_core.providers.http import CursorInvalidError, RateLimitedError
from mail_core.security.redact import safe_provider_summary
from mail_core.sync.checkpoints import invalidate_checkpoint_for_rebuild
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    heartbeat_lease,
    release_lease,
)
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
    lease_ttl: timedelta = timedelta(seconds=120),
) -> dict:
    """Discover remote folders, upsert local Folder rows, enqueue metadata jobs.

    ``lease_ttl`` defaults to 120s to cover folder-list RTT; callers that hold the
    lease across multi-page metadata/delta loops must also call ``heartbeat_lease``.
    """
    Session = _session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"account {account_id} not found")
        if not account.sync_enabled:
            return {"status": "sync_disabled"}
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

    try:
        provider = build_provider(account_snapshot, store or get_credential_store())
        try:
            remote_folders = list(provider.list_folders())  # network
        except RateLimitedError as exc:
            delay = float(exc.retry_after_seconds or 60)
            delay = max(1.0, min(delay, 86400.0))
            with Session() as session:
                acc = session.get(Account, account_id)
                if acc is not None:
                    acc.sync_status = "failed"
                    cfg = dict(acc.config or {})
                    cfg["last_synced_at"] = datetime.now(timezone.utc).isoformat()
                    cfg["last_sync_error"] = safe_provider_summary(exc)
                    acc.config = cfg
                    if hasattr(acc, "last_synced_at"):
                        setattr(acc, "last_synced_at", datetime.now(timezone.utc))
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                    account_id=account_id,
                    payload={},
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
                )
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            return {"status": "rate_limited", "retry_after": delay}
        except Exception as exc:
            with Session() as session:
                try:
                    acc = session.get(Account, account_id)
                    if acc is not None:
                        acc.sync_status = "failed"
                        cfg = dict(acc.config or {})
                        cfg["last_synced_at"] = datetime.now(timezone.utc).isoformat()
                        cfg["last_sync_error"] = safe_provider_summary(exc)
                        acc.config = cfg
                        if hasattr(acc, "last_synced_at"):
                            setattr(acc, "last_synced_at", datetime.now(timezone.utc))
                    release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                    session.commit()
                except FencingMismatch:
                    session.rollback()
                except Exception:
                    session.rollback()
            raise
    except Exception as exc:
        with Session() as session:
            try:
                acc = session.get(Account, account_id)
                if acc is not None:
                    acc.sync_status = "failed"
                    cfg = dict(acc.config or {})
                    cfg["last_synced_at"] = datetime.now(timezone.utc).isoformat()
                    cfg["last_sync_error"] = safe_provider_summary(exc)
                    acc.config = cfg
                    if hasattr(acc, "last_synced_at"):
                        setattr(acc, "last_synced_at", datetime.now(timezone.utc))
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
            except Exception:
                session.rollback()
        raise

    with Session() as session:
        try:
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
        by_remote = {
            f.remote_id: f
            for f in session.scalars(select(Folder).where(Folder.account_id == account_id)).all()
        }
        for rf in remote_folders:
            existing = by_remote.get(rf.remote_id)
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
        acc = session.get(Account, account_id)
        if acc is not None and acc.sync_status not in ("failed", "auth_failed"):
            acc.sync_status = "idle"
            cfg = dict(acc.config or {})
            cfg["last_synced_at"] = datetime.now(timezone.utc).isoformat()
            cfg.pop("last_sync_error", None)
            acc.config = cfg
            if hasattr(acc, "last_synced_at"):
                setattr(acc, "last_synced_at", datetime.now(timezone.utc))
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
        return {"status": "ok", "folders": len(folder_ids), "upserted": upserted}


def _release_lease_quiet(
    session,
    *,
    account_id: uuid.UUID,
    worker_id: str,
    fencing_token: int,
) -> None:
    try:
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing_token)
    except FencingMismatch:
        session.rollback()


def sync_folder_metadata(
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(seconds=120),
    max_pages: int = 20,
) -> dict:
    """Pull metadata pages until exhausted or max_pages; enqueue reconcile when done.

    Heartbeats the account lease between pages so long folders do not expire the
    120s default TTL mid-loop (architecture §7.5). Provider I/O exceptions always
    release the lease before propagating.
    """
    Session = _session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        folder = session.get(Folder, folder_id)
        if account is None or folder is None:
            raise ValueError("account/folder not found")
        if not account.sync_enabled:
            return {"status": "sync_disabled"}
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
        if cp is not None and cp.uidvalidity is not None and "uidvalidity" not in cursor:
            cursor["uidvalidity"] = int(cp.uidvalidity)
        session.commit()

    total = 0
    exhausted = False
    pages = 0
    try:
        provider = build_provider(account_snapshot, store or get_credential_store())
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
                # Heartbeat after each page commit so long scans keep the lease.
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
                    return {"status": "fencing_mismatch", "upserted": total}
                session.commit()
                total += result.upserted
                cursor = result.cursor
                exhausted = result.exhausted
            pages += 1
            if exhausted:
                break
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
                )
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
                return {"status": "fencing_mismatch", "upserted": total}
        return {"status": "cursor_invalid", "upserted": total, "pages": pages}
    except RateLimitedError as exc:
        delay = float(exc.retry_after_seconds or 60)
        delay = max(1.0, min(delay, 86400.0))
        with Session() as session:
            enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=50,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
            )
            _release_lease_quiet(session, account_id=account_id, worker_id=worker_id, fencing_token=fencing)
            session.commit()
        return {"status": "rate_limited", "retry_after": delay, "upserted": total, "pages": pages}
    except Exception:
        with Session() as session:
            _release_lease_quiet(session, account_id=account_id, worker_id=worker_id, fencing_token=fencing)
            session.commit()
        raise

    with Session() as session:
        try:
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
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=account_id,
                priority=40,
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


def local_remote_ids_for_folder(
    session: Session,
    folder_id: uuid.UUID,
    *,
    batch_size: int = 5_000,
    max_ids: int | None = 500_000,
) -> list[str]:
    """Collect remote_ids for a folder using chunked fetches (bounded).

    ``max_ids`` caps memory; reconcile callers should treat truncation as a signal
    to re-run with a higher cap or folder-scoped strategy.
    """
    out: list[str] = []
    stmt = (
        select(Message.remote_id)
        .join(MessageLocation, MessageLocation.message_id == Message.id)
        .where(
            MessageLocation.folder_id == folder_id,
            Message.remote_id.is_not(None),
            Message.remote_id != "",
        )
        .order_by(Message.id.asc())
        .execution_options(yield_per=batch_size)
    )
    for (rid,) in session.execute(stmt):
        if not isinstance(rid, str) or not rid.strip():
            continue
        out.append(rid)
        if max_ids is not None and len(out) >= max_ids:
            break
    return out
