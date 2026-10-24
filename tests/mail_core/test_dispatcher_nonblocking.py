import asyncio
import sys
import threading
from types import SimpleNamespace

from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread


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
    hint = queue.get_nowait()
    assert hint["event"] == "client.resync_hint"
    assert hint["_mail_core_close_after_delivery"] is True


def test_listener_requires_subscribers_for_initial_notify_and_idle_dispatch(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.notify_calls = 0
            self.statements = []
            self.closed = False

        def execute(self, statement):
            self.statements.append(statement)

        def notifies(self, timeout, stop_after):
            self.notify_calls += 1
            if self.notify_calls == 1:
                yield SimpleNamespace(channel="mail_core_outbox", payload="")
            else:
                threading.Event().wait(timeout)

        def close(self):
            self.closed = True

    class FakeDispatcher:
        def __init__(self):
            self.calls = []
            self.listener = None

        def dispatch_once(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 3:
                self.listener._stop.set()

    connection = FakeConnection()
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: connection),
    )
    dispatcher = FakeDispatcher()
    listener = OutboxListenThread(dispatcher, dsn="postgresql://test", idle_timeout_s=0.01)
    dispatcher.listener = listener

    listener._run()

    assert dispatcher.calls == [{"require_subscribers": True}] * 3
    assert connection.statements == ["LISTEN mail_core_outbox"]
    assert connection.closed


def test_listener_stop_restart_waits_for_old_thread(monkeypatch):
    connections = []
    release_first_wait = threading.Event()

    class FakeConnection:
        def __init__(self):
            self.waiting = threading.Event()
            self.notify_calls = 0

        def execute(self, statement):
            pass

        def notifies(self, timeout, stop_after):
            self.notify_calls += 1
            self.waiting.set()
            if self.notify_calls == 1 and len(connections) == 1:
                release_first_wait.wait()
            else:
                threading.Event().wait(timeout)
            return []

        def close(self):
            pass

    def connect(*_args, **_kwargs):
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    listener = OutboxListenThread(OutboxDispatcher(), dsn="postgresql://test", idle_timeout_s=10)
    listener.start()
    assert listener.wait_started(1)
    assert connections[0].waiting.wait(1)

    listener.stop(timeout=0)
    assert listener.is_alive

    restart_done = threading.Event()
    restart_thread = threading.Thread(target=lambda: (listener.start(), restart_done.set()))
    restart_thread.start()
    assert not restart_done.wait(0.05)

    release_first_wait.set()
    assert restart_done.wait(1)
    restart_thread.join(timeout=1)
    assert len(connections) == 2
    assert listener.wait_started(1)

    listener.stop()
    assert not listener.is_alive


def test_listener_stop_interrupts_reconnect_wait(monkeypatch):
    connect_attempted = threading.Event()

    def fail_connect(*_args, **_kwargs):
        connect_attempted.set()
        raise OSError("connection unavailable")

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=fail_connect))
    listener = OutboxListenThread(
        OutboxDispatcher(), dsn="postgresql://test", reconnect_s=30
    )
    listener.start()
    assert connect_attempted.wait(1)

    listener.stop(timeout=1)

    assert not listener.is_alive
