"""Transactional outbox read/dispatch helpers (architecture §13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState

# Retention deletes at most this many rows per call (design §9.2); larger
# backlogs are drained incrementally by repeated worker sweeps.
MAX_PRUNE_BATCH = 5000
RETENTION_WINDOW = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: int
    publication_seq: int | None
    event_type: str
    account_id: str | None
    payload: dict[str, Any]
    created_at: datetime


def publication_head(session: Session) -> tuple[str, int]:
    """Return current publication stream epoch and highest publication_seq."""
    from mail_core.realtime.publication import get_publication_state

    state = get_publication_state(session)
    return str(state.epoch), int(state.next_seq - 1)


def pruned_through_seq(session: Session) -> int:
    """Highest publication_seq deleted by retention (0 when nothing pruned).

    Same-epoch replay/dispatch cursors below this watermark reference rows
    that no longer exist and must resync instead of replaying partially.
    """
    from mail_core.realtime.publication import get_publication_state

    state = get_publication_state(session)
    return int(state.pruned_through_seq or 0)


def fetch_published_since(
    session: Session,
    *,
    after_seq: int,
    limit: int = 100,
    account_id: Any = None,
) -> list[OutboxEvent]:
    """Fetch committed events ordered strictly by publication_seq."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.publication_seq.is_not(None))
        .where(OutboxEvent.publication_seq > after_seq)
        .order_by(OutboxEvent.publication_seq.asc())
        .limit(limit)
    )
    if account_id is not None:
        stmt = stmt.where(
            or_(OutboxEvent.account_id == account_id, OutboxEvent.account_id.is_(None))
        )
    return list(session.scalars(stmt).all())


def to_item(row: OutboxEvent) -> OutboxItem:
    return OutboxItem(
        id=int(row.id),
        publication_seq=int(row.publication_seq) if row.publication_seq is not None else None,
        event_type=str(row.event_type),
        account_id=str(row.account_id) if row.account_id else None,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


def fetch_since(
    session: Session,
    *,
    last_event_id: int,
    limit: int = 100,
    account_id=None,
) -> list[OutboxEvent]:
    """Replay rows after ``last_event_id``.

    .. deprecated::
        v1 legacy replay API (A380): it orders by row ``id`` and therefore
        bypasses the v2 publication order (``publication_seq``) that SSE
        cursors, retention watermarks, and resync hints are built on. Do
        not use in new code — use :func:`fetch_published_since`. Retained
        only for the legacy PG-gated replay tests; calling it emits a
        ``DeprecationWarning``.

    When ``account_id`` is set, include that account's events **and** global
    rows (``account_id IS NULL``) so account-filtered SSE matches live fan-out,
    which already delivers NULL-account events to every subscriber.
    """
    import warnings

    warnings.warn(
        "fetch_since is deprecated (v1 id-ordered replay bypasses the v2 "
        "publication order); use fetch_published_since instead",
        DeprecationWarning,
        stacklevel=2,
    )
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.id > last_event_id)
        .order_by(OutboxEvent.id.asc())
        .limit(limit)
    )
    if account_id is not None:
        stmt = stmt.where(
            or_(OutboxEvent.account_id == account_id, OutboxEvent.account_id.is_(None))
        )
    return list(session.scalars(stmt).all())


def _as_utc(value: datetime) -> datetime:
    """Normalize a stored timestamp for comparison (SQLite drops tzinfo)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def prune_published(
    session: Session,
    *,
    older_than: timedelta = RETENTION_WINDOW,
    limit: int = MAX_PRUNE_BATCH,
    now: datetime | None = None,
) -> int:
    """Delete the expired continuous prefix of published outbox rows.

    Retention is defined over the v2 publication stream (design §9.2), not
    the removed single-consumer ``dispatched_at`` marker:

    - Only rows with ``publication_seq IS NOT NULL`` are candidates; an
      unpublished row is never deleted, regardless of age.
    - Candidates are scanned in ``publication_seq`` order starting just
      above the ``pruned_through_seq`` watermark. Deletion stops at the
      first candidate whose ``published_at`` is inside the retention
      window — a newer row interleaved in sequence order blocks every
      later row, so the retained stream never develops a hole below the
      watermark.
    - At most ``limit`` rows (hard-capped at 5000) are deleted per call.
    - The prefix deletion and the ``pruned_through_seq`` advance happen in
      the caller's transaction (this function flushes but does not commit),
      so the watermark never claims rows that were not deleted and never
      lags rows that were.

    Returns the number of rows deleted in this call.
    """
    if limit <= 0:
        return 0
    batch = min(int(limit), MAX_PRUNE_BATCH)
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than

    # Lock the singleton first: publication also locks this row before
    # assigning sequences, so pruning is serialized against publishing and
    # against concurrent pruners.
    state = session.scalar(
        select(OutboxPublicationState)
        .where(OutboxPublicationState.id == 1)
        .with_for_update()
    )
    if state is None:
        from mail_core.realtime.publication import get_publication_state

        state = get_publication_state(session)
    watermark = int(state.pruned_through_seq or 0)

    rows = list(
        session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.publication_seq.is_not(None))
            .where(OutboxEvent.publication_seq > watermark)
            .order_by(OutboxEvent.publication_seq.asc())
            .limit(batch)
        ).all()
    )

    prefix: list[OutboxEvent] = []
    for row in rows:
        # A351: a published row (publication_seq set) whose published_at
        # is NULL must not stall the whole prefix forever — fall back to
        # created_at, which bounds how long the row has existed.
        effective_at = row.published_at if row.published_at is not None else row.created_at
        if effective_at is None or _as_utc(effective_at) >= cutoff:
            break
        prefix.append(row)

    if not prefix:
        return 0

    session.execute(delete(OutboxEvent).where(OutboxEvent.id.in_([r.id for r in prefix])))
    state.pruned_through_seq = int(prefix[-1].publication_seq)
    session.flush()
    return len(prefix)
