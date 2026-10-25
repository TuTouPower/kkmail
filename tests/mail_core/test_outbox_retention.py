"""Package G-part-2 PostgreSQL coverage for outbox retention (R13, §9.2).

Skipped in unit mode (no MAIL_CORE_DATABASE_URL). All assertions are
relative to the shared publication stream state observed at runtime, so
the tests stay deterministic under the suite's shuffled order: before the
prefix assertions, every already-published row above the watermark is
backdated so the continuous-prefix computation has a known starting state.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from mail_core.api import sse as sse_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.outbox import prune_published, pruned_through_seq, publication_head
from mail_core.realtime.publication import get_publication_state, publish_committed_batch

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

OLD = timedelta(days=30)


def _publish(session, payloads):
    for payload in payloads:
        session.add(OutboxEvent(event_type="sync.progress", payload=payload))
    session.commit()
    batch = publish_committed_batch(session, limit=1000)
    session.commit()
    return batch


def test_prune_published_prefix_blocker_and_unpublished_survivor():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        _, head_before = publication_head(session)
        watermark_before = pruned_through_seq(session)
        # Known starting state: every published row still retained becomes
        # expired, so the prefix runs until the fresh blocker inserted next.
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq.is_not(None))
            .where(OutboxEvent.publication_seq > watermark_before)
            .values(published_at=now - OLD)
        )
        session.commit()
        prior_retained = head_before - watermark_before

        unpublished = OutboxEvent(event_type="sync.progress", payload={"kind": "unpublished"})
        session.add(unpublished)
        session.commit()
        unpublished_id = unpublished.id

        batch = _publish(session, [{"kind": "blocker"}])
        blocker_seq = batch.last_seq
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == blocker_seq)
            .values(published_at=now)
        )
        session.commit()

        tail = _publish(session, [{"kind": "tail-old"}])
        tail_seq = tail.last_seq
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == tail_seq)
            .values(published_at=now - OLD)
        )
        session.commit()

    with Session() as session:
        deleted = prune_published(session, now=now)
        session.commit()
        # The expired prefix (all prior retained rows) is deleted; the
        # fresh blocker stops the prefix, so the old tail row behind it and
        # the unpublished row both survive.
        assert deleted == prior_retained
        assert pruned_through_seq(session) == blocker_seq - 1
        assert session.get(OutboxEvent, unpublished_id) is not None
        tail_row = session.scalar(
            select(OutboxEvent).where(OutboxEvent.publication_seq == tail_seq)
        )
        assert tail_row is not None

    # Backdate the blocker too: the rest of the prefix now drains, while
    # the unpublished row still survives regardless of age.
    with Session() as session:
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == blocker_seq)
            .values(published_at=now - OLD)
        )
        session.commit()
        deleted = prune_published(session, now=now)
        session.commit()
        assert deleted == 2
        assert pruned_through_seq(session) == tail_seq
        assert session.get(OutboxEvent, unpublished_id) is not None
        assert session.get(OutboxEvent, unpublished_id).publication_seq is None


def test_replay_cursor_below_watermark_gets_retention_gap():
    Session = get_session_factory()
    with Session() as session:
        epoch, head_seq = publication_head(session)
        watermark = pruned_through_seq(session)

    if watermark == 0:
        pytest.skip("retention watermark not advanced in this database yet")

    # Cursor one below the watermark: the gap to head may be tiny, but the
    # next row the client needs has been pruned.
    plan = sse_mod._build_replay(f"v2:{epoch}:{watermark - 1}", None)
    assert len(plan.frames) == 1
    _, event, payload = plan.frames[0]
    assert event == "client.resync_hint"
    assert payload["reason"] == "retention_gap"

    # A cursor at the head replays normally (nothing to send, no hint).
    plan = sse_mod._build_replay(f"v2:{epoch}:{head_seq}", None)
    assert plan.frames == []
    assert plan.cursor_seq == head_seq


def test_two_dispatchers_with_established_baselines_both_receive_events():
    Session = get_session_factory()
    dispatchers = [OutboxDispatcher(), OutboxDispatcher()]

    async def run():
        queues = [dispatcher.subscribe() for dispatcher in dispatchers]
        try:
            # Establish both baselines against the current head.
            for dispatcher in dispatchers:
                dispatcher.dispatch_once()
            baselines = [dispatcher._last_dispatched_seq for dispatcher in dispatchers]

            with Session() as session:
                batch = _publish(session, [{"kind": "dual", "n": 1}, {"kind": "dual", "n": 2}])
                dual_seqs = {batch.first_seq, batch.last_seq}

            for dispatcher in dispatchers:
                dispatcher.dispatch_once()
            received = []
            for queue in queues:
                ids = []
                while not queue.empty():
                    ids.append(queue.get_nowait()["publication_seq"])
                received.append(ids)
            return baselines, dual_seqs, received
        finally:
            for dispatcher, queue in zip(dispatchers, queues):
                dispatcher.unsubscribe(queue)

    baselines, dual_seqs, received = asyncio.run(run())
    for events in received:
        assert dual_seqs <= set(events), f"dual events missing from {events}"
