"""Tests for committed outbox publication order sequence allocation (P1-04, D07)."""

import os
import threading
import uuid

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState
from mail_core.realtime.publication import publish_committed_batch

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_outbox_publication_assigns_monotonic_seq_across_out_of_order_commits():
    """P1-04: Out-of-order transaction commits receive monotonic publication_seq."""
    Session = get_session_factory()

    tx1_started = threading.Event()
    tx2_committed = threading.Event()
    tx1_can_commit = threading.Event()

    row1_id = None
    row2_id = None

    def worker_tx1():
        nonlocal row1_id
        with Session() as s1:
            row1 = OutboxEvent(
                event_type=OutboxEventType.SYNC_PROGRESS.value,
                payload={"tx": 1},
            )
            s1.add(row1)
            s1.flush()
            row1_id = row1.id
            tx1_started.set()

            # Wait for tx2 to commit and first publish to run
            tx1_can_commit.wait(timeout=5)
            s1.commit()

    t1 = threading.Thread(target=worker_tx1)
    t1.start()

    tx1_started.wait(timeout=5)

    # Tx2 starts, inserts row2, and commits FIRST
    with Session() as s2:
        row2 = OutboxEvent(
            event_type=OutboxEventType.SYNC_PROGRESS.value,
            payload={"tx": 2},
        )
        s2.add(row2)
        s2.flush()
        row2_id = row2.id
        s2.commit()

    # Run publisher: it can only see row2 (tx1 is not committed yet)
    with Session() as sp:
        batch1 = publish_committed_batch(sp, limit=10)
        sp.commit()

    assert batch1.count == 1
    assert batch1.first_seq is not None
    seq_row2 = batch1.first_seq

    # Allow tx1 to commit now
    tx1_can_commit.set()
    t1.join(timeout=5)

    # Run publisher again: now it publishes row1
    with Session() as sp:
        batch2 = publish_committed_batch(sp, limit=10)
        sp.commit()

    assert batch2.count == 1
    assert batch2.first_seq is not None
    seq_row1 = batch2.first_seq

    # Verify: Even though row1 had smaller/earlier id, because it committed later,
    # it received a STRICTLY GREATER publication_seq than row2!
    assert seq_row1 > seq_row2, f"Expected seq_row1 ({seq_row1}) > seq_row2 ({seq_row2})"

    # Verify rows in database
    with Session() as s:
        r1 = s.scalar(select(OutboxEvent).where(OutboxEvent.id == row1_id))
        r2 = s.scalar(select(OutboxEvent).where(OutboxEvent.id == row2_id))
        assert r1.publication_seq == seq_row1
        assert r2.publication_seq == seq_row2
        assert r1.published_at is not None
        assert r2.published_at is not None


def test_publication_batch_rollback_does_not_advance_committed_seq():
    """Rollback inside publish transaction preserves next_seq."""
    Session = get_session_factory()
    with Session() as s:
        row = OutboxEvent(
            event_type=OutboxEventType.SYNC_PROGRESS.value,
            payload={"probe": "rollback"},
        )
        s.add(row)
        s.commit()
        row_id = row.id

    with Session() as s:
        batch = publish_committed_batch(s, limit=10)
        assert batch.count == 1
        # Rollback
        s.rollback()

    with Session() as s:
        # Re-check: row still has publication_seq IS NULL
        r = s.scalar(select(OutboxEvent).where(OutboxEvent.id == row_id))
        assert r.publication_seq is None
        # Publish properly now
        batch2 = publish_committed_batch(s, limit=10)
        s.commit()
        assert batch2.count == 1
        assert batch2.first_seq == batch.first_seq
