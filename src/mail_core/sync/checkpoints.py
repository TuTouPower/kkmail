"""Checkpoint commits gated by fencing token (architecture §7.2 / §7.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.storage.models import SyncCheckpoint
from mail_core.sync.leases import assert_fencing


class ScanGenerationMismatch(Exception):
    """A job from an older full-scan generation tried to write a checkpoint
    that a newer generation owns (design §5.3). The write is rejected; the
    newer generation's cursor state is left untouched."""


def commit_checkpoint(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    fencing_token: int,
    cursor: dict[str, Any],
    uidvalidity: int | None = None,
    modseq: int | None = None,
    history_id: str | None = None,
    delta_link: str | None = None,
    full_scan_complete: bool | None = None,
    scan_generation: uuid.UUID | None = None,
) -> SyncCheckpoint:
    """Write cursor only if the caller's fencing_token still owns the lease.

    When ``scan_generation`` is given, the checkpoint must already belong to
    that full-scan generation; a stale-generation job is rejected instead of
    overwriting the newer generation's cursor.
    """
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    row = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
    if row is None:
        row = SyncCheckpoint(account_id=account_id, folder_id=folder_id)
        session.add(row)
    if scan_generation is not None and row.scan_generation != scan_generation:
        raise ScanGenerationMismatch(
            f"checkpoint scan_generation={row.scan_generation} != job generation {scan_generation}"
        )
    row.cursor = cursor
    if uidvalidity is not None:
        row.uidvalidity = uidvalidity
    if modseq is not None:
        row.modseq = modseq
    if history_id is not None:
        row.history_id = history_id
    if delta_link is not None:
        row.delta_link = delta_link
    if full_scan_complete is not None:
        row.full_scan_complete = full_scan_complete
    row.fencing_token = fencing_token
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def begin_scan_generation(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    fencing_token: int,
    scan_generation: uuid.UUID,
) -> SyncCheckpoint:
    """Enter ``scan_generation`` for a folder under the account scan lease.

    First entry resets the scan cursor state (cursor, uid_next/MODSEQ/
    history/delta state, full_scan_complete) and stamps ``scan_generation``;
    retries of the same generation keep the cursor and continue from it
    (design §5.3). Must be called while the caller holds the account lease.
    """
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    row = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
    if row is None:
        row = SyncCheckpoint(account_id=account_id, folder_id=folder_id)
        session.add(row)
    if row.scan_generation != scan_generation:
        row.cursor = {}
        row.uidvalidity = None
        row.modseq = None
        row.history_id = None
        row.delta_link = None
        row.full_scan_complete = False
        row.scan_generation = scan_generation
    row.fencing_token = fencing_token
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def invalidate_checkpoint_for_rebuild(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    fencing_token: int,
) -> SyncCheckpoint:
    """Clear cursor tokens after UIDVALIDITY / historyId / delta invalidation.

    Forces a controlled metadata rebuild; never silent-delete (architecture §7.3).
    """
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    row = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
    if row is None:
        row = SyncCheckpoint(account_id=account_id, folder_id=folder_id)
        session.add(row)
    row.cursor = {}
    row.uidvalidity = None
    row.modseq = None
    row.history_id = None
    row.delta_link = None
    row.full_scan_complete = False
    row.scan_generation = None
    row.fencing_token = fencing_token
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row

