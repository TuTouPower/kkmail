"""A86: dispatch_once must drain a backlog in one call.

Previously one call published and fanned out at most 100 rows, then
waited for the next NOTIFY or the listener's 30s idle tick, so a burst
took many wake-ups to deliver. The dispatcher also carried a
poll_interval_s field that nothing consumed. These tests drive
dispatch_once through stateful fakes honouring the limit=100 contract
of publish_committed_batch / fetch_published_since.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from mail_core.realtime import outbox as outbox_mod
from mail_core.realtime.dispatcher import OutboxDispatcher

EPOCH = str(uuid.uuid4())
NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        pass


class _Stream:
    """In-memory publication stream: unpublished backlog + published seqs."""

    def __init__(self, *, unpublished: int = 0, published: int = 0):
        self.unpublished = unpublished
        self.seqs: list[int] = list(range(1, published + 1))
        self.head = published

    def publish(self, session, *, limit=100):
        count = min(limit, self.unpublished)
        first = self.head + 1 if count else None
        for _ in range(count):
            self.head += 1
            self.seqs.append(self.head)
        self.unpublished -= count
        return SimpleNamespace(
            count=count,
            first_seq=first,
            last_seq=self.head if count else None,
            epoch=uuid.UUID(EPOCH),
        )

    def fetch(self, session, *, after_seq, limit=100, account_id=None):
        rows = []
        for seq in self.seqs:
            if seq > after_seq:
                rows.append(
                    SimpleNamespace(
                        id=1000 + seq,
                        publication_seq=seq,
                        event_type="sync.progress",
                        account_id=None,
                        payload={"seq": seq},
                        created_at=NOW,
                    )
                )
            if len(rows) >= limit:
                break
        return rows


def _patch_stream(monkeypatch, stream: _Stream):
    monkeypatch.setattr(
        "mail_core.db.session.get_session_factory", lambda: (lambda: _FakeSession())
    )
    monkeypatch.setattr("mail_core.realtime.publication.publish_committed_batch", stream.publish)
    monkeypatch.setattr(outbox_mod, "publication_head", lambda session: (EPOCH, stream.head))
    monkeypatch.setattr(outbox_mod, "pruned_through_seq", lambda session: 0)
    monkeypatch.setattr(outbox_mod, "fetch_published_since", stream.fetch)


def _drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_dispatch_once_drains_published_backlog_over_100(monkeypatch):
    stream = _Stream(published=250)
    _patch_stream(monkeypatch, stream)
    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True

    async def run():
        queue = dispatcher.subscribe()
        count = dispatcher.dispatch_once()
        received = _drain(queue)
        dispatcher.unsubscribe(queue)
        return count, received

    count, received = asyncio.run(run())
    assert count == 250
    assert len(received) == 250
    assert dispatcher._last_dispatched_seq == 250


def test_dispatch_once_drains_unpublished_backlog_over_100(monkeypatch):
    stream = _Stream(unpublished=250)
    _patch_stream(monkeypatch, stream)
    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True

    async def run():
        queue = dispatcher.subscribe()
        count = dispatcher.dispatch_once()
        received = _drain(queue)
        dispatcher.unsubscribe(queue)
        return count, received

    count, received = asyncio.run(run())
    assert count == 250
    assert len(received) == 250
    assert stream.unpublished == 0
    assert dispatcher._last_dispatched_seq == 250


def test_dispatch_once_stops_when_a_live_subscriber_pins_the_cursor(monkeypatch):
    stream = _Stream(published=250)
    _patch_stream(monkeypatch, stream)
    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True

    def rejecting_fanout(event):
        dispatcher._last_fanout_targets = 1
        return False

    dispatcher._fanout = rejecting_fanout  # type: ignore[method-assign]

    async def run():
        queue = dispatcher.subscribe()
        try:
            return dispatcher.dispatch_once()
        finally:
            dispatcher.unsubscribe(queue)

    # Must terminate (no spin re-reading the pinned page) and report 0.
    assert asyncio.run(run()) == 0
    assert dispatcher._last_dispatched_seq == 0


def test_poll_interval_field_is_gone():
    field_names = {f.name for f in dataclasses.fields(OutboxDispatcher)}
    assert "poll_interval_s" not in field_names
