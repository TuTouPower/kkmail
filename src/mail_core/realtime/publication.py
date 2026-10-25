"""Committed outbox publication order sequence allocation (architecture §13, D07)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState


@dataclass(frozen=True, slots=True)
class PublicationBatch:
    count: int
    first_seq: int | None
    last_seq: int | None
    epoch: uuid.UUID


def get_publication_state(session: Session) -> OutboxPublicationState:
    """Return singleton outbox publication state row, creating one if not present."""
    state = session.scalar(select(OutboxPublicationState).where(OutboxPublicationState.id == 1))
    if state is None:
        state = OutboxPublicationState(id=1, epoch=uuid.uuid4(), next_seq=1)
        session.add(state)
        session.flush()
    return state


def publish_committed_batch(session: Session, *, limit: int = 100) -> PublicationBatch:
    """Lock state singleton, select committed unpublished outbox rows, and assign publication_seq.

    This ensures events are strictly ordered by commit arrival regardless of original transaction order.
    """
    state = session.scalar(
        select(OutboxPublicationState).where(OutboxPublicationState.id == 1).with_for_update()
    )
    if state is None:
        state = OutboxPublicationState(id=1, epoch=uuid.uuid4(), next_seq=1)
        session.add(state)
        session.flush()

    rows = list(
        session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.publication_seq.is_(None))
            .order_by(OutboxEvent.id.asc())
            .with_for_update()
            .limit(limit)
        ).all()
    )

    if not rows:
        return PublicationBatch(
            count=0,
            first_seq=None,
            last_seq=None,
            epoch=state.epoch,
        )

    now = datetime.now(timezone.utc)
    first_seq = state.next_seq
    current_seq = first_seq
    for row in rows:
        row.publication_seq = current_seq
        row.published_at = now
        current_seq += 1

    state.next_seq = current_seq
    session.flush()

    return PublicationBatch(
        count=len(rows),
        first_seq=first_seq,
        last_seq=current_seq - 1,
        epoch=state.epoch,
    )
