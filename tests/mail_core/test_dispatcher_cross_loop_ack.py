"""A173: cross-loop fan-out must not treat call_soon_threadsafe success
as delivery with no trace when the callback never runs.

The dispatcher now tracks unacknowledged cross-loop deliveries: the
callback acknowledges on execution, and when a later delivery finds the
subscriber loop closed — proving the queued callbacks can never run —
the loss is reported as a warning count (those events were reported
delivered and the cursor advanced past them) instead of vanishing
silently.
"""

from __future__ import annotations

import asyncio
import logging

from mail_core.realtime.dispatcher import OutboxDispatcher


class _DeferredLoop:
    """Loop double: accepts callbacks but only runs them when told."""

    def __init__(self):
        self.callbacks = []

    def call_soon_threadsafe(self, callback):
        self.callbacks.append(callback)


class _ClosingLoop:
    """Accepts the first callback, then the loop 'closes'."""

    def __init__(self):
        self.callbacks = []
        self.closed = False

    def call_soon_threadsafe(self, callback):
        if self.closed:
            raise RuntimeError("Event loop is closed.")
        self.callbacks.append(callback)


def test_cross_loop_delivery_is_unacked_until_the_callback_runs():
    dispatcher = OutboxDispatcher()
    loop = _DeferredLoop()
    queue: asyncio.Queue = asyncio.Queue()
    event = {"id": 17, "event": "message.updated"}

    assert dispatcher._fanout_one(loop, queue, event) is True
    assert dispatcher.unacked_cross_loop_deliveries == 1
    assert queue.empty()

    loop.callbacks.pop(0)()

    assert dispatcher.unacked_cross_loop_deliveries == 0
    assert queue.get_nowait() == event


def test_unacked_deliveries_are_reported_when_the_loop_turns_out_closed(caplog):
    dispatcher = OutboxDispatcher()
    loop = _ClosingLoop()
    queue: asyncio.Queue = asyncio.Queue()

    assert dispatcher._fanout_one(loop, queue, {"id": 1, "event": "message.updated"}) is True
    assert dispatcher.unacked_cross_loop_deliveries == 1

    loop.closed = True
    with caplog.at_level(logging.WARNING, logger="mail_core.realtime.dispatcher"):
        assert dispatcher._fanout_one(loop, queue, {"id": 2, "event": "message.updated"}) is False

    # The previously "delivered" event is provably lost now: warned, counted,
    # and no longer tracked as pending.
    assert dispatcher.unacked_cross_loop_deliveries == 0
    assert any(
        "never acknowledged" in record.message and "1" in record.message
        for record in caplog.records
    )


def test_same_loop_delivery_never_creates_unacked_entries():
    dispatcher = OutboxDispatcher()

    async def run():
        queue = dispatcher.subscribe()
        try:
            loop = asyncio.get_running_loop()
            assert dispatcher._fanout_one(loop, queue, {"id": 3, "event": "message.updated"}) is True
            assert dispatcher.unacked_cross_loop_deliveries == 0
            assert queue.get_nowait()["id"] == 3
        finally:
            dispatcher.unsubscribe(queue)

    asyncio.run(run())
