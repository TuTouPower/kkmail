"""A57: the dispatcher's subscription table must not grow without bound.

_subs keys are client-controlled account ids; previously unsubscribe,
_isolate and close_session_streams left the key behind with an empty
list forever, so every random UUID a client ever subscribed with stayed
in the table (and in every has_local_subscribers scan) for the life of
the process. Empty keys must be deleted.
"""

from __future__ import annotations

import asyncio
import uuid

from mail_core.realtime.dispatcher import OutboxDispatcher


def test_unsubscribe_deletes_the_empty_key():
    dispatcher = OutboxDispatcher()

    async def run():
        queue = dispatcher.subscribe(account_id="acct-1")
        assert "acct-1" in dispatcher._subs
        dispatcher.unsubscribe(queue, account_id="acct-1")

    asyncio.run(run())
    assert "acct-1" not in dispatcher._subs
    assert dict(dispatcher._subs) == {}
    assert not dispatcher.has_local_subscribers()


def test_many_random_account_subscriptions_leave_no_keys():
    dispatcher = OutboxDispatcher()

    async def run():
        for _ in range(50):
            account_id = str(uuid.uuid4())
            queue = dispatcher.subscribe(account_id=account_id)
            dispatcher.unsubscribe(queue, account_id=account_id)

    asyncio.run(run())
    assert dict(dispatcher._subs) == {}


def test_unsubscribe_keeps_key_while_other_subscribers_remain():
    dispatcher = OutboxDispatcher()

    async def run():
        first = dispatcher.subscribe(account_id="acct-1")
        second = dispatcher.subscribe(account_id="acct-1")
        dispatcher.unsubscribe(first, account_id="acct-1")
        remaining = dispatcher._subs.get("acct-1")
        assert remaining is not None and [q for _, q in remaining] == [second]
        dispatcher.unsubscribe(second, account_id="acct-1")

    asyncio.run(run())
    assert "acct-1" not in dispatcher._subs


def test_isolate_deletes_the_empty_key():
    dispatcher = OutboxDispatcher()
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    dispatcher._subs["acct-9"].append((loop, queue))

    dispatcher._isolate(queue, signal_stream=False)

    assert "acct-9" not in dispatcher._subs
    loop.close()


def test_close_session_streams_deletes_emptied_keys():
    dispatcher = OutboxDispatcher()
    holder = {}

    async def run():
        holder["queue"] = dispatcher.subscribe(account_id="acct-old", session_epoch=1)
        dispatcher.subscribe(account_id="acct-keep", session_epoch=2)

    asyncio.run(run())
    dispatcher.close_session_streams(current_epoch=2)

    assert "acct-old" not in dispatcher._subs
    assert "acct-keep" in dispatcher._subs
