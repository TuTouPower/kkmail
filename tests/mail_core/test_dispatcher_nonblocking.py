import asyncio

from mail_core.realtime.dispatcher import OutboxDispatcher


class DeferredLoop:
    def call_soon_threadsafe(self, callback):
        self.callback = callback


def test_fanout_schedules_other_loop_without_waiting_for_callback():
    dispatcher = OutboxDispatcher()
    loop = DeferredLoop()
    queue = asyncio.Queue()
    event = {"id": 17, "event": "message.updated"}

    assert dispatcher._fanout_one(loop, queue, event) is True
    assert queue.empty()

    loop.callback()

    assert queue.get_nowait() == event


def test_fanout_isolates_a_queue_full_consumer_on_its_loop():
    dispatcher = OutboxDispatcher()
    loop = DeferredLoop()
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"id": 16})
    dispatcher._subs["*"].append((loop, queue))
    event = {"id": 17, "event": "message.updated"}

    assert dispatcher._fanout_one(loop, queue, event) is True
    assert dispatcher.has_local_subscribers()

    loop.callback()

    assert not dispatcher.has_local_subscribers()
    assert queue.get_nowait()["event"] == "client.resync_hint"
