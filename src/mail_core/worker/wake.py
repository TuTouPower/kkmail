"""PostgreSQL LISTEN thread on mail_core_jobs that wakes the worker main loop."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from mail_core.realtime.notify import JOB_CHANNEL
from mail_core.security.redact import safe_error

log = logging.getLogger("mail_core.worker.wake")


class JobWakeListener:
    """LISTEN thread that signals a wake event whenever a runnable job is enqueued."""

    def __init__(
        self,
        wake_callback: Callable[[], None],
        *,
        dsn: str | None = None,
        reconnect_s: float = 2.0,
    ) -> None:
        self.wake_callback = wake_callback
        self.dsn = dsn
        self.reconnect_s = reconnect_s
        self._stop = threading.Event()
        self._started = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active_conn = None

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait_started(self, timeout: float = 5.0) -> bool:
        return self._started.wait(timeout)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._started.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="mail-core-worker-job-wake",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
            conn = self._active_conn
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        if thread:
            thread.join(timeout=timeout)

    def _run(self) -> None:
        import psycopg

        resolved_dsn = self.dsn
        if not resolved_dsn:
            from mail_core.realtime.listener import _dsn_from_settings

            try:
                resolved_dsn = _dsn_from_settings()
            except Exception as exc:
                log.info("job wake listener disabled: %s", exc)
                return

        while not self._stop.is_set():
            conn = None
            try:
                conn = psycopg.connect(resolved_dsn, autocommit=True, connect_timeout=5)
                self._active_conn = conn
                conn.execute(f"LISTEN {JOB_CHANNEL}")
                log.info("LISTEN %s started", JOB_CHANNEL)
                self._started.set()

                while not self._stop.is_set():
                    for notify in conn.notifies(timeout=0.2, stop_after=50):
                        if notify.channel == JOB_CHANNEL:
                            self.wake_callback()
            except Exception as exc:
                if not self._stop.is_set():
                    log.warning("job wake listener connection lost: %s", safe_error(exc))
            finally:
                self._active_conn = None
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            if not self._stop.is_set():
                self._started.clear()
                self._stop.wait(self.reconnect_s)
