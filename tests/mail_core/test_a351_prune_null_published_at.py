"""A351: prune_published must not stall forever on a published row whose
published_at is NULL — fall back to created_at for the retention check."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState
from mail_core.realtime.outbox import prune_published

EPOCH = str(uuid.uuid4())
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)
FRESH = NOW - timedelta(hours=1)


def _make_session_factory():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE outbox_publication_state (
                id INTEGER PRIMARY KEY, epoch CHAR(36) NOT NULL,
                next_seq BIGINT NOT NULL DEFAULT 1,
                pruned_through_seq BIGINT NOT NULL DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)
            """))
        conn.execute(text("""
            CREATE TABLE outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(64) NOT NULL, account_id CHAR(36),
                payload JSON NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                publication_seq BIGINT, published_at DATETIME)
            """))
        conn.execute(text("CREATE UNIQUE INDEX ix_outbox_publication_seq ON outbox (publication_seq)"))
    return sessionmaker(bind=engine)


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
    Session = _make_session_factory()
    _seed(Session, [(1, None, OLD), (2, OLD, OLD)])
    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    assert deleted == 2
    assert _remaining(Session) == []


def test_null_published_at_fresh_created_at_blocks_prefix():
    Session = _make_session_factory()
    _seed(Session, [(1, None, FRESH), (2, OLD, OLD)])
    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    assert deleted == 0
    assert _remaining(Session) == [1, 2]
