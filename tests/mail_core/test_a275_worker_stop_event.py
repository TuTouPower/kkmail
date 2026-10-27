"""A275: worker main loop must wake immediately on stop, not sleep max_idle."""

from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock

from mail_core.worker import main as worker_main


def _stub_run_infrastructure(monkeypatch):
    class _FakeHeartbeatLoop:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            pass

        def stop(self, timeout=None):
            pass

    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: (lambda: MagicMock()))
    monkeypatch.setattr("mail_core.worker.heartbeat.WorkerHeartbeatLoop", _FakeHeartbeatLoop)
    monkeypatch.setattr("mail_core.blobs.crypto.load_keyring_from_env", lambda: {})


def test_stop_signals_set_the_stop_event():
    worker_main._stop_event.clear()
    worker_main._stop = False
    try:
        worker_main.request_stop()
        assert worker_main._stop is True
        assert worker_main._stop_event.is_set()

        worker_main._stop_event.clear()
        worker_main._stop = False
        worker_main._handle_stop(signal.SIGTERM, None)
        assert worker_main._stop_event.is_set()
    finally:
        worker_main._stop_event.clear()
        worker_main._stop = False


def test_run_exits_promptly_when_stopped_during_long_idle_wait(monkeypatch):
    _stub_run_infrastructure(monkeypatch)
    monkeypatch.setattr(worker_main, "_reclaim_once", lambda: 0)
    monkeypatch.setattr(
        worker_main,
        "_tick",
        lambda _worker_id: worker_main.TickResult(claimed=0, handled=0),
    )

    thread = threading.Thread(
        target=lambda: worker_main.run(poll_interval_s=5.0), daemon=True
    )
    started = time.monotonic()
    thread.start()
    time.sleep(0.3)
    worker_main.request_stop()
    thread.join(timeout=3)

    assert not thread.is_alive(), "run() kept sleeping after stop was requested"
    assert time.monotonic() - started < 3
