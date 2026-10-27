"""A327: OutboxListenThread.start() must not join the previous thread
without a timeout.

Old code called ``previous.join()`` bare in the restart branch: a
previous thread stuck in a slow DB call blocked start() forever while
holding ``_lifecycle_lock``, so even stop() could no longer get in.
The fix joins with a timeout and, on timeout, abandons this start
attempt and logs an error (the thread is a daemon, so it cannot block
process exit).
"""

from __future__ import annotations

import logging
import threading
import time

from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread


def test_start_abandons_restart_when_previous_thread_stuck(caplog):
    listener = OutboxListenThread(
        OutboxDispatcher(), dsn="postgresql://test", restart_join_timeout_s=0.1
    )
    release = threading.Event()
    stuck = threading.Thread(target=release.wait, daemon=True, name="stuck-previous")
    stuck.start()
    listener._thread = stuck
    listener._stop.set()  # start() enters the restart branch only when stopping

    started_at = time.monotonic()
    with caplog.at_level(logging.ERROR, logger="mail_core.realtime.listener"):
        listener.start()
    elapsed = time.monotonic() - started_at

    # Returned promptly instead of blocking forever on join().
    assert elapsed < 2.0
    # No new thread was started; the stuck daemon thread is untouched.
    assert listener._thread is stuck
    assert stuck.is_alive()
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    release.set()
    stuck.join(timeout=1)


def test_start_still_restarts_when_previous_thread_exits_in_time():
    listener = OutboxListenThread(
        OutboxDispatcher(), dsn="postgresql://test", restart_join_timeout_s=2.0
    )
    finished = threading.Thread(target=lambda: None, daemon=True)
    finished.start()
    finished.join(timeout=1)
    listener._thread = finished
    listener._stop.set()

    # _run would try to connect; only verify start() replaces the thread
    # and returns — stop it immediately.
    listener.start()
    try:
        assert listener._thread is not finished
    finally:
        listener.stop(timeout=1)
