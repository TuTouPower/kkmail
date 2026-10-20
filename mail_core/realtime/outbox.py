"""Transactional outbox read/dispatch helpers (architecture §13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import OutboxEvent


@dataclass(frozen=True, slots=True)
class OutboxItem:
    id: int
    event_type: str
    account_id: str | None
    payload: dict[str, Any]
    created_at: datetime


def head_event_id(session: Session) -> int:
    """Highest outbox event id (0 when empty)."""
    return int(session.scalar(select(func.max(OutboxEvent.id))) or 0)


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
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.id > last_event_id)
        .order_by(OutboxEvent.id.asc())
        .limit(limit)
    )
    if account_id is not None:
        stmt = stmt.where(OutboxEvent.account_id == account_id)
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


def to_item(row: OutboxEvent) -> OutboxItem:
    return OutboxItem(
        id=int(row.id),
        event_type=row.event_type,
        account_id=str(row.account_id) if row.account_id else None,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )
