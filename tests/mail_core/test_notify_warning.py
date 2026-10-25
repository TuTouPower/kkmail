from __future__ import annotations

from unittest.mock import Mock

from mail_core.realtime import notify as notify_module


def test_try_notify_outbox_warns_once_then_summarizes_hourly_failures(monkeypatch, caplog):
    monkeypatch.setattr(notify_module, "_notify_first_failure_logged", False)
    monkeypatch.setattr(notify_module, "_notify_failures_since_warning", 0)
    monkeypatch.setattr(notify_module, "_notify_last_warning_at", None)
    times = iter((100.0, 110.0, 3701.0))
    monkeypatch.setattr(notify_module, "_monotonic", lambda: next(times))
    session = Mock()
    session.execute.side_effect = RuntimeError("password=private-value")

    with caplog.at_level("WARNING", logger="mail_core.realtime.notify"):
        notify_module.try_notify_outbox(session)
        notify_module.try_notify_outbox(session)
        notify_module.try_notify_outbox(session)

    assert len(caplog.records) == 2
    assert "error type=RuntimeError" in caplog.records[0].message
    assert "2 failures since last warning" in caplog.records[1].message
    assert "private-value" not in caplog.text
