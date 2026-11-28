"""Tests for Q2 worker main-loop stall watchdog, stamp write warning, and Q3 UNREACHABLE recovery."""

from __future__ import annotations

import logging
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mail_core.worker import main as worker_main
from mail_core.worker.heartbeat import WorkerHeartbeatLoop


def _noop_session_factory():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# Q2: Liveness stamp warning log (Finding 7) & main-loop stall watchdog
# ---------------------------------------------------------------------------


def test_liveness_stamp_write_failure_logs_rate_limited_warning(monkeypatch, caplog):
    def boom(**_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("mail_core.liveness.write_liveness_stamp", boom)

    with caplog.at_level(logging.WARNING, logger="mail_core.worker"):
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=1,
            worker_id="w-1",
            now=100.0,
            last_warn_at=None,
        )
        assert last_warn == 100.0
        # Within 60s window: suppressed, no log flood.
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=2,
            worker_id="w-1",
            now=120.0,
            last_warn_at=last_warn,
        )
        assert last_warn == 100.0
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=3,
            worker_id="w-1",
            now=159.9,
            last_warn_at=last_warn,
        )
        assert last_warn == 100.0
        # Past 60s window: emits a second bounded warning.
        last_warn = worker_main._write_liveness_stamp_with_warning(
            progress=4,
            worker_id="w-1",
            now=160.0,
            last_warn_at=last_warn,
        )
        assert last_warn == 160.0

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "OSError" in warnings[0].getMessage()


def test_watchdog_does_not_trigger_while_mark_progress_advances(caplog):
    stalls: list[float] = []
    clock = [0.0]

    loop = WorkerHeartbeatLoop(
        "w-watchdog-ok",
        _noop_session_factory,
        interval_s=15.0,
        watchdog_timeout_s=1.0,
        on_watchdog_stall=stalls.append,
        monotonic=lambda: clock[0],
    )
    with caplog.at_level(logging.CRITICAL, logger="mail_core.worker.heartbeat"):
        for step in range(1, 10):
            clock[0] = step * 0.5
            loop._tick()
            loop.mark_progress()
            clock[0] += 0.4
            loop._tick()

    assert stalls == []
    assert [r for r in caplog.records if r.levelno == logging.CRITICAL] == []


def test_watchdog_triggers_callback_once_per_stall_and_logs_critical(caplog):
    stalls: list[float] = []
    clock = [0.0]

    loop = WorkerHeartbeatLoop(
        "w-watchdog-stall",
        _noop_session_factory,
        interval_s=15.0,
        watchdog_timeout_s=10.0,
        on_watchdog_stall=stalls.append,
        monotonic=lambda: clock[0],
    )
    with caplog.at_level(logging.CRITICAL, logger="mail_core.worker.heartbeat"):
        clock[0] = 5.0
        loop._tick()
        assert stalls == []

        clock[0] = 10.0
        loop._tick()
        assert stalls == []

        # First tick past watchdog_timeout_s -> triggers exactly once.
        clock[0] = 10.5
        loop._tick()
        assert len(stalls) == 1
        assert stalls[0] == pytest.approx(10.5)

        # Repeated ticks during the same stall do not spam callback or CRITICAL logs.
        clock[0] = 25.0
        loop._tick()
        clock[0] = 40.0
        loop._tick()
        assert len(stalls) == 1

        # Recovery via mark_progress resets latch so a later stall can fire again.
        loop.mark_progress()
        clock[0] = 55.0
        loop._tick()
        assert len(stalls) == 2

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 2


def test_watchdog_disabled_when_timeout_non_positive(monkeypatch):
    stalls: list[float] = []
    clock = [0.0]

    for disabled in (None, 0.0, -5.0):
        loop = WorkerHeartbeatLoop(
            "w-disabled",
            _noop_session_factory,
            interval_s=15.0,
            watchdog_timeout_s=disabled,
            on_watchdog_stall=stalls.append,
            monotonic=lambda: clock[0],
        )
        assert loop.watchdog_timeout_s is None
        clock[0] += 10000.0
        loop._tick()
    assert stalls == []

    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "0")
    assert worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0) is None
    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "-10")
    assert worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0) is None

    monkeypatch.delenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", raising=False)
    monkeypatch.delenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raising=False)
    default_timeout = worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=10.0)
    assert default_timeout is not None and default_timeout >= 180.0

    # Large max_idle_s (e.g. 60s) must push watchdog timeout well past idle sleep so
    # an idle worker never false-triggers.
    idle_timeout = worker_main._resolve_watchdog_timeout_s(poll_interval_s=2.0, max_idle_s=60.0)
    assert idle_timeout is not None and idle_timeout >= 240.0


def test_worker_run_wires_watchdog_and_calls_mark_progress(monkeypatch):
    created: list[dict] = []
    progressed = threading.Event()
    progress_calls = 0

    class _SpyHeartbeatLoop:
        def __init__(self, worker_id, session_factory, *, interval_s=15.0, watchdog_timeout_s=None, on_watchdog_stall=None):
            created.append(
                {
                    "worker_id": worker_id,
                    "interval_s": interval_s,
                    "watchdog_timeout_s": watchdog_timeout_s,
                    "on_watchdog_stall": on_watchdog_stall,
                }
            )

        def start(self):
            pass

        def stop(self, timeout=None):
            pass

        def mark_progress(self):
            nonlocal progress_calls
            progress_calls += 1
            if progress_calls >= 2:
                progressed.set()

    class _NoopInfra:
        def start(self):
            pass

        def stop(self, timeout=None):
            pass

    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: _noop_session_factory)
    monkeypatch.setattr("mail_core.worker.heartbeat.WorkerHeartbeatLoop", _SpyHeartbeatLoop)
    monkeypatch.setattr(worker_main, "UnifiedClaimHeartbeatLoop", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr(worker_main, "_schedule_periodic_sync_once", lambda: 0)
    monkeypatch.setattr(worker_main, "_reclaim_once", lambda: 0)
    monkeypatch.setattr(worker_main, "_tick", lambda *_a, **_k: worker_main.TickResult(claimed=0, handled=0))
    monkeypatch.setattr("mail_core.worker.wake.JobWakeListener", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr("mail_core.sync.idle_watcher.get_idle_manager", lambda *_a, **_k: _NoopInfra())
    monkeypatch.setattr("mail_core.liveness.write_liveness_stamp", lambda **_k: None)
    monkeypatch.setenv("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT", "123")

    t = threading.Thread(target=lambda: worker_main.run(poll_interval_s=0.01), daemon=True)
    t.start()
    try:
        assert progressed.wait(timeout=3.0)
    finally:
        worker_main.request_stop()
        t.join(timeout=3.0)
    assert not t.is_alive()
    assert len(created) == 1
    assert created[0]["watchdog_timeout_s"] == 123.0
    assert created[0]["on_watchdog_stall"] is worker_main._exit_on_watchdog_stall
    assert progress_calls >= 2


def test_watchdog_background_thread_fires_on_real_stall():
    triggered = threading.Event()
    calls: list[float] = []

    def on_stall(elapsed: float) -> None:
        calls.append(elapsed)
        triggered.set()

    loop = WorkerHeartbeatLoop(
        "w-thread-stall",
        _noop_session_factory,
        interval_s=0.02,
        watchdog_timeout_s=0.05,
        on_watchdog_stall=on_stall,
    )
    loop.start()
    try:
        assert triggered.wait(timeout=2.0)
        time.sleep(0.08)
        assert len(calls) == 1
    finally:
        loop.stop(timeout=2.0)

