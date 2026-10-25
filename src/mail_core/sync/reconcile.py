"""Folder reconcile after a complete scan — only then may deletes be applied."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.domain.enums import OutboxEventType, SyncStatus
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, OutboxEvent
from mail_core.providers.connection_slots import (
    CAPACITY_ERRORS,
    CAPACITY_RETRY_SECONDS,
    TrafficClass,
)
from mail_core.providers.factory import build_provider
from mail_core.sync.engine import local_remote_ids_for_folder
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, heartbeat_lease, release_lease
from mail_core.mail.storage.models import SyncCheckpoint

log = logging.getLogger("mail_core.sync.reconcile")
RECONCILE_DELETE_BATCH_SIZE = 200


def reconcile_folder(
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(minutes=10),
    traffic_class: TrafficClass = TrafficClass.FOREGROUND,
) -> dict:
    """Reconcile local vs remote IDs after a complete scan.

    Provider I/O errors release the lease and surface as ``provider_error``
    (no silent empty-delete). Select/SEARCH failures in IMAP raise rather than
    returning an empty action list.
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
            return {"status": "skipped", "reason": "full_scan_incomplete"}
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            return {"status": "lease_busy"}
        session.commit()
        fencing = lease.fencing_token
        remote_folder = folder.remote_id
        local_ids = local_remote_ids_for_folder(session, folder_id)
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )

    try:
        provider = build_provider(account_snapshot, store or get_credential_store(), traffic_class=traffic_class)
        actions = list(provider.reconcile(remote_folder, local_ids))  # network / full scan inside provider
    except CAPACITY_ERRORS as exc:
        # Budget deferral: the worker reschedules this job without a
        # failure count; reconcile must not surface as provider_error.
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
        delay = float(getattr(exc, "retry_after_seconds", None) or CAPACITY_RETRY_SECONDS)
        return {"status": "capacity_unavailable", "retry_after": delay}
    except Exception as exc:
        from mail_core.security.redact import safe_provider_summary

        err_summary = safe_provider_summary(exc)
        log.error("reconcile provider I/O failed for folder %s: %s", folder_id, err_summary)
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
        return {"status": "provider_error", "error": err_summary}

    deleted = 0
    batch_starts = range(0, max(1, len(actions)), RECONCILE_DELETE_BATCH_SIZE)
    try:
        for start in batch_starts:
            batch = actions[start : start + RECONCILE_DELETE_BATCH_SIZE]
            is_last_batch = start + RECONCILE_DELETE_BATCH_SIZE >= len(actions)
            with Session() as session:
                try:
                    # Renew and lock the lease row in the same short transaction
                    # that applies this batch. A worker that lost the fence cannot
                    # apply deletes after a newer owner takes over.
                    heartbeat_lease(
                        session,
                        account_id=account_id,
                        owner_id=worker_id,
                        fencing_token=fencing,
                        ttl=lease_ttl,
                    )
                except FencingMismatch:
                    session.rollback()
                    return {"status": "fencing_mismatch", "deleted": deleted, "actions": len(actions)}

                batch_deleted = 0
                for action in batch:
                    if action.kind != "delete":
                        continue
                    msg = session.scalar(
                        select(Message).where(Message.account_id == account_id, Message.remote_id == action.remote_id)
                    )
                    if msg is None:
                        continue
                    # Remove only this folder location; delete message if orphaned.
                    loc = session.scalar(
                        select(MessageLocation).where(
                            MessageLocation.message_id == msg.id,
                            MessageLocation.folder_id == folder_id,
                        )
                    )
                    if loc is not None:
                        session.delete(loc)
                        session.flush()
                    remaining = session.scalar(
                        select(MessageLocation).where(MessageLocation.message_id == msg.id)
                    )
                    if remaining is None:
                        session.add(
                            OutboxEvent(
                                event_type=OutboxEventType.MESSAGE_REMOVED.value,
                                account_id=account_id,
                                payload={"message_id": str(msg.id), "remote_id": action.remote_id},
                            )
                        )
                        session.delete(msg)
                        batch_deleted += 1
                total_deleted = deleted + batch_deleted
                if batch_deleted or is_last_batch:
                    recompute_folder_stats(session, folder_id)
                    session.add(
                        OutboxEvent(
                            event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                            account_id=account_id,
                            payload={"folder_id": str(folder_id), "reconcile_deleted": total_deleted},
                        )
                    )
                if is_last_batch:
                    release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
                deleted = total_deleted
    except FencingMismatch:
        return {"status": "fencing_mismatch", "deleted": deleted, "actions": len(actions)}
    except Exception:
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
            except Exception:
                session.rollback()
                log.warning("could not release reconcile lease after batch failure for folder %s", folder_id)
        raise
    return {"status": "ok", "deleted": deleted, "actions": len(actions)}
