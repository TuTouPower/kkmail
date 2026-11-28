"""Checkpoint commits gated by fencing token (architecture §7.2 / §7.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
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


# t094: result statuses that represent a completed delta execution-chain
# settlement (the chain has ended, not merely deferred). These advance the
# authoritative scheduling watermark. Deferrals (rate_limited,
# capacity_unavailable, lease_busy), handoffs (cursor_invalid ->
# metadata rebuild), stale executions (fencing_mismatch) and in-flight
# continuations (a followup_scheduled delta that has not exhausted the chain)
# are deliberately excluded: advancing on them would suppress a due re-pull.
_DELTA_SETTLED_STATUSES: frozenset[str] = frozenset({"ok", "skipped", "sync_disabled"})


def is_delta_settled_result(result: dict[str, Any] | None) -> bool:
    """Whether a delta result ends the execution chain (advances the watermark).

    ``ok`` only settles when the page chain is exhausted; an ``ok`` with a
    scheduled followup is a continuation, not a settlement.
    """
    if not result:
        return False
    if result.get("followup_scheduled"):
        return False
    status = str(result.get("status") or "")
    if status == "ok" and not result.get("exhausted", False):
        return False
    return status in _DELTA_SETTLED_STATUSES


def advance_delta_settlement_watermark(
    session: Session,
    *,
    account_id: uuid.UUID,
    folder_id: uuid.UUID,
    settled_at: datetime | None = None,
    fencing_token: int | None = None,
) -> bool:
    """Monotonically advance ``SyncCheckpoint.last_delta_settled_at``.

    Called from the same transaction that settles the delta job, so the
    watermark and the job's terminal status commit atomically. Executes a
    single atomic conditional SQL ``UPDATE`` so concurrent transactions or
    stale ORM snapshots in ``session.identity_map`` can never regress the
    watermark or let an older fencing token overwrite a newer execution. Any
    cached ``SyncCheckpoint`` instance in ``session`` is expired afterward so
    callers never read stale values.

    Returns True when the watermark moved.
    """
    settled_at = settled_at or datetime.now(timezone.utc)
    if settled_at.tzinfo is None:
        settled_at = settled_at.replace(tzinfo=timezone.utc)

    # Flush pending ORM changes (e.g. a newly bumped fencing_token in the
    # caller's transaction) before evaluating the conditional SQL predicate.
    if hasattr(session, "flush"):
        session.flush()

    conditions = [
        SyncCheckpoint.account_id == account_id,
        SyncCheckpoint.folder_id == folder_id,
        or_(
            SyncCheckpoint.last_delta_settled_at.is_(None),
            SyncCheckpoint.last_delta_settled_at < settled_at,
        ),
    ]
    values: dict[str, Any] = {"last_delta_settled_at": settled_at}
    if fencing_token is not None:
        tok = int(fencing_token)
        conditions.append(SyncCheckpoint.fencing_token.is_not(None))
        conditions.append(SyncCheckpoint.fencing_token <= tok)
        values["fencing_token"] = tok

    stmt = (
        update(SyncCheckpoint)
        .where(*conditions)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    moved = int(getattr(result, "rowcount", 0) or 0) > 0

    identity_map = getattr(session, "identity_map", None)
    if identity_map is not None and hasattr(identity_map, "get") and hasattr(session, "expire"):
        from sqlalchemy.orm.util import identity_key

        cached = identity_map.get(identity_key(SyncCheckpoint, (account_id, folder_id)))
        if cached is not None:
            session.expire(cached)

    return moved

