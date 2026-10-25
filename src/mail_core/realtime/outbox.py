"""Transactional outbox read/dispatch helpers (architecture §13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import OutboxEvent


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: int
    publication_seq: int | None
    event_type: str
    account_id: str | None
    payload: dict[str, Any]
    created_at: datetime


def head_event_id(session: Session) -> int:
    """Highest outbox event id (0 when empty)."""
    return int(session.scalar(select(func.max(OutboxEvent.id))) or 0)


def publication_head(session: Session) -> tuple[str, int]:
    """Return current publication stream epoch and highest publication_seq."""
    from mail_core.realtime.publication import get_publication_state

    state = get_publication_state(session)
    return str(state.epoch), int(state.next_seq - 1)


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


def fetch_undispatched(session: Session, *, limit: int = 100) -> list[OutboxEvent]:
    return list(
        session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.dispatched_at.is_(None))
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )


def fetch_since(
    session: Session,
    *,
    last_event_id: int,
    limit: int = 100,
    account_id=None,
) -> list[OutboxEvent]:
    """Replay rows after ``last_event_id``.

    When ``account_id`` is set, include that account's events **and** global
    rows (``account_id IS NULL``) so account-filtered SSE matches live fan-out,
    which already delivers NULL-account events to every subscriber.
    """
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


def mark_dispatched(session: Session, event_ids: Sequence[int], *, now: datetime | None = None) -> None:
    if not event_ids:
        return
    now = now or datetime.now(timezone.utc)
    session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id.in_(list(event_ids)))
        .values(dispatched_at=now)
    )


def prune_dispatched(
    session: Session,
    *,
    older_than: timedelta = timedelta(days=7),
    limit: int = 5000,
    now: datetime | None = None,
) -> int:
    """Delete old **dispatched** outbox rows (architecture §13 delayed trim).

    Never touches undispatched rows. Caps each call at ``limit`` ids so workers
    can prune incrementally without long locks.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    ids = list(
        session.scalars(
            select(OutboxEvent.id)
            .where(OutboxEvent.dispatched_at.is_not(None))
            .where(OutboxEvent.dispatched_at < cutoff)
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
        ).all()
    )
    if not ids:
        return 0
    session.execute(delete(OutboxEvent).where(OutboxEvent.id.in_(ids)))
    return len(ids)
