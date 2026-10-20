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


def _dsn_from_settings() -> str:
    from mail_core.db.session import database_url

    url = database_url()
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


class OutboxListenThread:
    """Daemon thread: LISTEN mail_core_outbox → dispatcher.dispatch_once()."""

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
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._started.clear()
        self._thread = threading.Thread(target=self._run, name="mail-core-outbox-listen", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

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
                    self.dispatcher.dispatch_once()
                except Exception:
                    log.exception("initial dispatch after LISTEN failed")

                while not self._stop.is_set():
                    # Block until NOTIFY or idle timeout (then opportunistic drain).
                    got = False
                    for notify in conn.notifies(timeout=self.idle_timeout_s, stop_after=50):
                        got = True
                        log.debug("NOTIFY %s payload=%r", notify.channel, notify.payload)
                        if self._stop.is_set():
                            break
                        try:
                            self.dispatcher.dispatch_once()
                        except Exception:
                            log.exception("dispatch after NOTIFY failed")
                    if self._stop.is_set():
                        break
                    if not got:
                        try:
                            self.dispatcher.dispatch_once()
                        except Exception:
                            log.exception("idle dispatch failed")
            except Exception:
                self._started.clear()
                if self._stop.is_set():
                    break
                log.exception("LISTEN loop error; reconnecting in %ss", self.reconnect_s)
                time.sleep(self.reconnect_s)
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
