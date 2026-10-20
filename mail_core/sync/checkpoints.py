"""Checkpoint commits gated by fencing token (architecture §7.2 / §7.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.storage.models import SyncCheckpoint
from mail_core.sync.leases import assert_fencing


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
) -> SyncCheckpoint:
    """Write cursor only if the caller's fencing_token still owns the lease."""
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    row = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
    if row is None:
        row = SyncCheckpoint(account_id=account_id, folder_id=folder_id)
        session.add(row)
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
