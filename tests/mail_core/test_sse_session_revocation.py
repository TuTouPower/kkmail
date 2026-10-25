from __future__ import annotations

import asyncio
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from mail_core.api import sse as sse_module
from mail_core.security.auth import AuthPrincipal
from mail_core.realtime.dispatcher import OutboxDispatcher, SSE_STREAM_CLOSE
from mail_core.realtime.listener import OutboxListenThread
from mail_core.realtime.notify import (
    CHANNEL,
    SESSION_REVOCATION_CHANNEL,
    notify_session_revocation,
    try_notify_session_revocation,
)


def test_dispatcher_closes_old_session_streams_from_listener_thread():
    dispatcher = OutboxDispatcher()

    async def verify():
        global_queue = dispatcher.subscribe(session_epoch=1)
        account_queue = dispatcher.subscribe(account_id="account-1", session_epoch=2)
        current_session_queue = dispatcher.subscribe(session_epoch=3)
        api_key_queue = dispatcher.subscribe(account_id="account-2")
        assert dispatcher.has_local_subscribers()

        close_thread = threading.Thread(
            target=dispatcher.close_session_streams,
            kwargs={"current_epoch": 3},
        )
        close_thread.start()
        close_thread.join(timeout=1)
        assert not close_thread.is_alive()

        assert await asyncio.wait_for(global_queue.get(), timeout=1) is SSE_STREAM_CLOSE
        assert await asyncio.wait_for(account_queue.get(), timeout=1) is SSE_STREAM_CLOSE
        assert current_session_queue.empty()
        assert api_key_queue.empty()
        assert dispatcher.has_local_subscribers()

    asyncio.run(verify())


def test_session_revocation_notify_uses_a_savepoint_and_epoch_payload():
    session = MagicMock()

    try_notify_session_revocation(session, session_epoch=7)

    session.begin_nested.assert_called_once_with()
    statement, parameters = session.execute.call_args.args
    assert "pg_notify(:channel, :payload)" in str(statement)
    assert parameters == {"channel": SESSION_REVOCATION_CHANNEL, "payload": "7"}


def test_listener_routes_session_revocation_notifications_to_stream_closure():
    dispatcher = Mock()
    listener = OutboxListenThread(dispatcher, dsn="postgresql://unused")

    listener._handle_notification(SESSION_REVOCATION_CHANNEL, "7")
    listener._handle_notification(CHANNEL)

    dispatcher.close_session_streams.assert_called_once_with(current_epoch=7)
    dispatcher.dispatch_once.assert_called_once_with(require_subscribers=True)


def test_sse_fallback_closes_stream_when_database_epoch_changes(monkeypatch):
    epochs = iter((10, 11))
    monkeypatch.setattr(sse_module, "_get_session_epoch", lambda _force_refresh=False: next(epochs))
    monkeypatch.setattr(sse_module, "SESSION_EPOCH_RECHECK_INTERVAL_S", 0.0)
    monkeypatch.setattr(sse_module, "_acquire_sse_slot", lambda: True)
    monkeypatch.setattr(sse_module, "_release_sse_slot", lambda: None)
    monkeypatch.setattr(sse_module, "_build_replay", lambda *_args, **_kwargs: sse_module._ReplayPlan([], 0))

    class FakeDispatcher:
        def subscribe(self, **_kwargs):
            return asyncio.Queue()

        def unsubscribe(self, *_args, **_kwargs):
            return None

    class FakeRequest:
        async def is_disconnected(self):
            return False

    monkeypatch.setattr(sse_module, "get_dispatcher", lambda: FakeDispatcher())

    async def collect_stream():
        response = await sse_module.stream_events(
            FakeRequest(), last_event_id=None, after=None, account_id=None,
            principal=AuthPrincipal(via="session", csrf_token="csrf", session_epoch=10),
        )
        return [frame async for frame in response.body_iterator]

    assert asyncio.run(collect_stream()) == []


def test_listener_registers_outbox_and_revocation_channels(monkeypatch):
    dispatcher = Mock()
    listener = OutboxListenThread(dispatcher, dsn="postgresql://unused")
    commands = []

    class FakeConnection:
        def execute(self, statement):
            commands.append(statement)

        def notifies(self, **_kwargs):
            listener._stop.set()
            return []

        def close(self):
            return None

    connection = FakeConnection()
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *_args, **_kwargs: connection))

    listener._run()

    assert commands == [f"LISTEN {CHANNEL}", f"LISTEN {SESSION_REVOCATION_CHANNEL}"]
    dispatcher.dispatch_once.assert_called_once_with(require_subscribers=True)


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")
def test_session_revocation_notify_reaches_each_api_listener_connection():
    import psycopg

    from mail_core.db.session import database_url, get_session_factory
    from mail_core.realtime.listener import _normalize_listen_dsn

    dsn = _normalize_listen_dsn(database_url())
    listeners = [psycopg.connect(dsn, autocommit=True) for _ in range(2)]
    try:
        for connection in listeners:
            connection.execute(f"LISTEN {SESSION_REVOCATION_CHANNEL}")

        Session = get_session_factory()
        with Session() as session:
            notify_session_revocation(session, session_epoch=987654321)
            session.commit()

        notifications = [
            next(connection.notifies(timeout=3, stop_after=1), None)
            for connection in listeners
        ]
        assert all(
            notification is not None
            and notification.channel == SESSION_REVOCATION_CHANNEL
            and notification.payload == "987654321"
            for notification in notifications
        )
    finally:
        for connection in listeners:
            connection.close()
