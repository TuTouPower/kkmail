"""Independent worker process skeleton (empty poll loop).

API must not run long sync I/O; workers claim jobs via SKIP LOCKED later.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [mail-core-worker] %(message)s")
log = logging.getLogger("mail_core.worker")

_stop = False


def _handle_stop(signum: int, _frame: object) -> None:
    global _stop
    log.info("received signal %s; stopping", signum)
    _stop = True


def request_stop() -> None:
    """Test/helper hook to stop the loop without signals."""
    global _stop
    _stop = True


def run(poll_interval_s: float | None = None) -> None:
    global _stop
    _stop = False
    interval = poll_interval_s if poll_interval_s is not None else float(os.environ.get("MAIL_CORE_WORKER_POLL_S", "2"))
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)
    log.info("worker loop starting (poll=%ss); job claim not wired yet", interval)
    while not _stop:
        # Milestone later: SKIP LOCKED claim + lease + sync/archive handlers.
        time.sleep(interval)
    log.info("worker loop stopped")


if __name__ == "__main__":
    run()
