"""A352: get_publication_state must survive concurrent first-start.

Old code did select-then-insert with no conflict handling: two
processes first-starting together both saw "no row", both inserted
id=1, and one crashed with IntegrityError on the primary key. The fix
inserts with ON CONFLICT DO NOTHING and re-reads the row.

The race is simulated deterministically: a session wrapper whose first
scalar() returns a stale "no row" while the row already exists.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import OutboxPublicationState
from mail_core.realtime.publication import get_publication_state

_DDL = """
CREATE TABLE outbox_publication_state (
    id INTEGER PRIMARY KEY,
    epoch CHAR(36) NOT NULL,
    next_seq BIGINT NOT NULL,
    pruned_through_seq BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""


def _make_session():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_DDL))
    return sessionmaker(bind=engine)


class _StaleFirstReadSession:
    """Delegates to a real session, but the first scalar() lies (stale
    read: "no singleton row") to reproduce the two-process race."""

    def __init__(self, real):
        self._real = real
        self._scalar_calls = 0

    def scalar(self, *args, **kwargs):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return None
        return self._real.scalar(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_get_publication_state_creates_singleton_once():
    Session = _make_session()
    with Session() as session:
        state = get_publication_state(session)
        session.commit()
        assert state.id == 1
        assert state.next_seq == 1
        assert state.epoch is not None
        again = get_publication_state(session)
        assert again.epoch == state.epoch
        rows = list(session.scalars(select(OutboxPublicationState)).all())
        assert len(rows) == 1


def test_get_publication_state_survives_stale_read_race():
    Session = _make_session()
    existing_epoch = uuid.uuid4()
    with Session() as session:
        session.add(
            OutboxPublicationState(id=1, epoch=existing_epoch, next_seq=42, pruned_through_seq=0)
        )
        session.commit()

    with Session() as real:
        wrapped = _StaleFirstReadSession(real)
        # Old code: add + flush -> IntegrityError (duplicate PK id=1).
        state = get_publication_state(wrapped)  # type: ignore[arg-type]
        real.commit()
        # The pre-existing row wins; our conflicting insert was a no-op.
        assert state.id == 1
        assert state.epoch == existing_epoch
        assert state.next_seq == 42
