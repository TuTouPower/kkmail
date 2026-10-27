"""A122: get_dispatcher() must be a thread-safe lazy singleton.

The unlocked check-then-create let two threads racing the first call
build two dispatchers: the LISTEN thread held one while SSE routes took
the other, so subscribers listened on an instance that never fanned
out. Creation must happen once, under a lock (double-checked).
"""

from __future__ import annotations

import threading
import time

from mail_core.realtime import dispatcher as dispatcher_mod


class _SlowDispatcher:
    created = 0

    def __init__(self):
        type(self).created += 1
        # Widen the race window: without a lock every racing thread
        # observes _dispatcher is None and constructs its own instance.
        time.sleep(0.05)


def test_concurrent_first_access_creates_exactly_one_dispatcher(monkeypatch):
    _SlowDispatcher.created = 0
    monkeypatch.setattr(dispatcher_mod, "OutboxDispatcher", _SlowDispatcher)
    monkeypatch.setattr(dispatcher_mod, "_dispatcher", None)

    barrier = threading.Barrier(16)
    results: list = []

    def worker():
        barrier.wait(timeout=5)
        results.append(dispatcher_mod.get_dispatcher())

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(results) == 16
    assert _SlowDispatcher.created == 1
    assert all(result is results[0] for result in results)


def test_sequential_calls_return_the_same_instance(monkeypatch):
    monkeypatch.setattr(dispatcher_mod, "_dispatcher", None)
    first = dispatcher_mod.get_dispatcher()
    second = dispatcher_mod.get_dispatcher()
    assert first is second
