"""Folder reconcile after a complete scan — only then may deletes be applied."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import Account, Folder, FolderStats, Message, MessageLocation, OutboxEvent
from mail_core.providers.factory import build_provider
from mail_core.sync.engine import local_remote_ids_for_folder
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, assert_fencing, release_lease
from mail_core.mail.storage.models import SyncCheckpoint

log = logging.getLogger("mail_core.sync.reconcile")


def reconcile_folder(
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    lease_ttl: timedelta = timedelta(seconds=120),
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

    provider = build_provider(account_snapshot, store or get_credential_store())
    try:
        actions = list(provider.reconcile(remote_folder, local_ids))  # network / full scan inside provider
    except Exception as exc:
        log.exception("reconcile provider I/O failed for folder %s: %s", folder_id, type(exc).__name__)
        with Session() as session:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                session.commit()
            except FencingMismatch:
                session.rollback()
        return {"status": "provider_error", "error": f"{type(exc).__name__}: {exc}"}

    deleted = 0
    with Session() as session:
        try:
            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch"}
        for action in actions:
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
                deleted += 1
        # refresh stats
        rows = session.scalars(
            select(Message)
            .join(MessageLocation, MessageLocation.message_id == Message.id)
            .where(MessageLocation.folder_id == folder_id)
        ).all()
        stats = session.get(FolderStats, folder_id) or FolderStats(folder_id=folder_id)
        session.add(stats)
        stats.total_count = len(rows)
        stats.unread_count = sum(1 for m in rows if not m.is_read)
        stats.updated_at = datetime.now(timezone.utc)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.FOLDER_STATS_UPDATED.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id), "reconcile_deleted": deleted},
            )
        )
        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        session.commit()
    return {"status": "ok", "deleted": deleted, "actions": len(actions)}
