"""Checkpoint commits gated by fencing token (architecture §7.2 / §7.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from mail_core.mail.storage.models import SyncCheckpoint, SyncRequest, SyncRequestTarget
from mail_core.sync.leases import assert_fencing


class ScanGenerationMismatch(Exception):
    """A job from an older full-scan generation tried to write a checkpoint
    that a newer generation owns (design §5.3). The write is rejected; the
    newer generation's cursor state is left untouched."""


def _assert_scan_generation_current(
    session: Session,
    *,
    account_id: uuid.UUID,
    scan_generation: uuid.UUID,
) -> None:
    """Reject a full-scan generation superseded by a newer one (design §5.3).

    Generation UUIDs are unordered, so ``!=`` cannot tell a retry of the
    current generation from a requeued job of an OLDER one (fail/reschedule
    return the job payload, hence its ``scan_generation``, untouched).
    Root generations are allocated by ``create_sync_request`` and stamped
    on the full request's targets, so a generation's birth is the earliest
    ``created_at`` among its full targets for the account; a generation
    with a later-born sibling is stale and must neither re-enter
    (:func:`begin_scan_generation` would reset the cursor back to it) nor
    commit. Generations with no request record (legacy rows, direct
    engine use) cannot be ordered and keep the previous behaviour.

    The check is an existence query (A293): fetch this generation's
    birth once, then ask whether any sibling target is newer-born while
    its own generation has no target at or before that birth (i.e. the
    sibling's birth is strictly later) -- ``LIMIT 1``, no GROUP BY over
    every generation of the account on each checkpoint commit.

    Birth order is the stable total order ``(created_at, target id)``
    (A378): generations created in one transaction share a timestamp
    (Postgres ``now()`` is the transaction timestamp), so ``created_at``
    alone can tie and let an older generation pass as current. The
    earliest target's id breaks the tie deterministically for every
    observer.
    """
    own_key = session.execute(
        select(SyncRequestTarget.created_at, SyncRequestTarget.id)
        .join(SyncRequest, SyncRequest.id == SyncRequestTarget.request_id)
        .where(
            SyncRequest.mode == "full",
            SyncRequestTarget.account_id == account_id,
            SyncRequestTarget.requested_generation == scan_generation,
        )
        .order_by(SyncRequestTarget.created_at.asc(), SyncRequestTarget.id.asc())
        .limit(1)
    ).first()
    if own_key is None:
        return
    own_birth, own_tiebreak = own_key
    older_target = aliased(SyncRequestTarget)
    older_request = aliased(SyncRequest)
    sibling_has_no_older_birth = ~(
        select(1)
        .select_from(older_target)
        .join(older_request, older_request.id == older_target.request_id)
        .where(
            older_target.requested_generation == SyncRequestTarget.requested_generation,
            older_request.mode == "full",
            older_target.account_id == account_id,
            or_(
                older_target.created_at < own_birth,
                and_(
                    older_target.created_at == own_birth,
                    older_target.id <= own_tiebreak,
                ),
            ),
        )
        .exists()
    )
    newer_sibling = session.scalar(
        select(1)
        .select_from(SyncRequestTarget)
        .join(SyncRequest, SyncRequest.id == SyncRequestTarget.request_id)
        .where(
            SyncRequest.mode == "full",
            SyncRequestTarget.account_id == account_id,
            SyncRequestTarget.requested_generation != scan_generation,
            or_(
                SyncRequestTarget.created_at > own_birth,
                and_(
                    SyncRequestTarget.created_at == own_birth,
                    SyncRequestTarget.id > own_tiebreak,
                ),
            ),
            sibling_has_no_older_birth,
        )
        .limit(1)
    )
    if newer_sibling is not None:
        raise ScanGenerationMismatch(
            f"scan generation {scan_generation} is superseded by a newer "
            "full-scan generation for this account"
        )


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
    if scan_generation is not None:
        _assert_scan_generation_current(
            session, account_id=account_id, scan_generation=scan_generation
        )
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

    A generation superseded by a newer full-scan generation for the
    account is rejected with :class:`ScanGenerationMismatch` instead of
    resetting the cursor back to the stale generation.
    """
    assert_fencing(session, account_id=account_id, fencing_token=fencing_token)
    _assert_scan_generation_current(
        session, account_id=account_id, scan_generation=scan_generation
    )
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

