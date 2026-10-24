"""PostgreSQL LISTEN thread that wakes the outbox dispatcher."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from mail_core.realtime.notify import CHANNEL

if TYPE_CHECKING:
    from mail_core.realtime.dispatcher import OutboxDispatcher

log = logging.getLogger("mail_core.realtime.listener")
_NOTIFY_WAIT_POLL_S = 0.5


def _dsn_from_settings() -> str:
    from mail_core.db.session import database_url

    url = database_url()
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


class OutboxListenThread:
    """LISTEN thread that dispatches only while local SSE subscribers are active."""

    def __init__(
        self,
        dispatcher: OutboxDispatcher,
        *,
        dsn: str | None = None,
        idle_timeout_s: float = 30.0,
        reconnect_s: float = 2.0,
    ) -> None:
        self.dispatcher = dispatcher
        self.dsn = dsn or _dsn_from_settings()
        self.idle_timeout_s = idle_timeout_s
        self.reconnect_s = reconnect_s
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def listen_ready(self) -> bool:
        """True only after a successful LISTEN (not merely that the reconnect thread runs)."""
        return self.is_alive and self._started.is_set()

    def start(self) -> None:
        with self._lifecycle_lock:
            previous = self._thread
            if previous and previous.is_alive():
                if not self._stop.is_set():
                    return
                previous.join()
            self._stop.clear()
            self._started.clear()
            self._thread = threading.Thread(target=self._run, name="mail-core-outbox-listen", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
        if thread:
            thread.join(timeout=timeout)

    def wait_started(self, timeout: float = 5.0) -> bool:
        return self._started.wait(timeout)

    def _run(self) -> None:
        import psycopg

        while not self._stop.is_set():
            conn = None
            try:
                conn = psycopg.connect(self.dsn, autocommit=True)
                conn.execute(f"LISTEN {CHANNEL}")
                log.info("LISTEN %s started", CHANNEL)
                self._started.set()
                try:
                    self.dispatcher.dispatch_once(require_subscribers=True)
                except Exception:
                    log.exception("initial dispatch after LISTEN failed")

                while not self._stop.is_set():
                    # Poll in short waits so stop is responsive without changing idle drain cadence.
                    deadline = time.monotonic() + self.idle_timeout_s
                    got = False
                    while not self._stop.is_set():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        for notify in conn.notifies(
                            timeout=min(remaining, _NOTIFY_WAIT_POLL_S), stop_after=50
                        ):
                            got = True
                            log.debug("NOTIFY %s (%d bytes)", notify.channel, len(notify.payload or ""))
                            if self._stop.is_set():
                                break
                            try:
                                self.dispatcher.dispatch_once(require_subscribers=True)
                            except Exception:
                                log.exception("dispatch after NOTIFY failed")
                    if self._stop.is_set():
                        break
                    if not got:
                        try:
                            self.dispatcher.dispatch_once(require_subscribers=True)
                        except Exception:
                            log.exception("idle dispatch failed")
            except Exception as exc:
                self._started.clear()
                if self._stop.is_set():
                    break
                # Type only: driver messages can embed DSN fragments / payloads.
                log.warning("LISTEN loop error (%s); reconnecting in %ss", type(exc).__name__, self.reconnect_s)
                self._stop.wait(self.reconnect_s)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


_listener: OutboxListenThread | None = None
_listener_lock = threading.Lock()


def get_outbox_listener(dispatcher: OutboxDispatcher | None = None) -> OutboxListenThread:
    global _listener
    from mail_core.realtime.dispatcher import get_dispatcher

    with _listener_lock:
        if _listener is None:
            _listener = OutboxListenThread(dispatcher or get_dispatcher())
        return _listener


def start_outbox_listener() -> OutboxListenThread:
    listener = get_outbox_listener()
    listener.start()
    return listener


def stop_outbox_listener() -> None:
    with _listener_lock:
        if _listener is not None:
            _listener.stop()
