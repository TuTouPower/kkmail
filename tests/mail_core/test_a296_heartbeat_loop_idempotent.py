"""A296: WorkerHeartbeatLoop.start() must be idempotent (no leaked thread
on repeat start) and stop() must keep the thread reference until join
actually completes."""
import time
from unittest.mock import MagicMock, patch

from mail_core.worker.heartbeat import WorkerHeartbeatLoop


def _fake_factory():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def test_double_start_keeps_single_thread():
    with patch("mail_core.worker.heartbeat.record_heartbeat"):
        loop = WorkerHeartbeatLoop("w-dup", _fake_factory, interval_s=0.05)
        loop.start()
        first = loop._thread
        assert first is not None and first.is_alive()
        loop.start()
        assert loop._thread is first
        loop.stop(timeout=1.0)
        assert loop._thread is None
        assert not first.is_alive()


def test_stop_retains_reference_when_join_times_out():
    class FakeThread:
        def __init__(self):
            self.join_timeouts = []

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.join_timeouts.append(timeout)

    loop = WorkerHeartbeatLoop("w-stuck", _fake_factory, interval_s=0.05)
    fake = FakeThread()
    loop._thread = fake  # type: ignore[assignment]
    loop.stop(timeout=0.01)
    # Join did not complete (thread still alive): reference must be kept
    # so a later stop() can retry instead of leaking the thread.
    assert loop._thread is fake
    assert fake.join_timeouts == [0.01]


def test_restart_after_stop_works():
    with patch("mail_core.worker.heartbeat.record_heartbeat") as mock_record:
        loop = WorkerHeartbeatLoop("w-restart", _fake_factory, interval_s=0.05)
        loop.start()
        loop.stop(timeout=1.0)
        assert loop._thread is None
        loop.start()
        try:
            time.sleep(0.12)
            assert loop._thread is not None and loop._thread.is_alive()
            assert mock_record.call_count >= 3
        finally:
            loop.stop(timeout=1.0)
