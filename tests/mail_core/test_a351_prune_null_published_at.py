"""A351: prune_published must not stall forever on a published row whose
published_at is NULL — fall back to created_at for the retention check.

Retention is exercised against the real PostgreSQL schema built by Alembic
(no hand-written DDL), so timestamptz / JSONB / UUID semantics are the
production ones.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState
from mail_core.realtime.outbox import prune_published

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

EPOCH = str(uuid.uuid4())
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)
FRESH = NOW - timedelta(hours=1)


def _seed(Session, rows):
    """rows: list of (seq, published_at, created_at)."""
    with Session() as session:
        session.add(OutboxPublicationState(
            id=1, epoch=uuid.UUID(EPOCH),
            next_seq=max(s for s, _, _ in rows) + 1, pruned_through_seq=0))
        for seq, published_at, created_at in rows:
            session.add(OutboxEvent(
                event_type="sync.progress", payload={"seq": seq},
                publication_seq=seq, published_at=published_at,
                created_at=created_at))
        session.commit()


def _remaining(Session):
    with Session() as session:
        return sorted(s for s in session.scalars(select(OutboxEvent.publication_seq)).all() if s is not None)


def test_null_published_at_old_created_at_is_pruned():
    Session = get_session_factory()
    _seed(Session, [(1, None, OLD), (2, OLD, OLD)])
    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    assert deleted == 2
    assert _remaining(Session) == []


def test_null_published_at_fresh_created_at_blocks_prefix():
    Session = get_session_factory()
    _seed(Session, [(1, None, FRESH), (2, OLD, OLD)])
    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    assert deleted == 0
    assert _remaining(Session) == [1, 2]
