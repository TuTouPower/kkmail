"""A179: in-memory OAuth flow fallback must warn it is plaintext/non-durable."""
from __future__ import annotations
import logging
from mail_core.accounts import oauth_flow

def test_memory_fallback_warns_plaintext_non_durable(monkeypatch, caplog):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    oauth_flow.reset_oauth_flow_state()
    with caplog.at_level(logging.WARNING, logger="mail_core.accounts.oauth_flow"):
        store = oauth_flow._flow_store()
    assert store is oauth_flow._unit_memory_store
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "expected a warning when OAuth flows fall back to in-memory plaintext store"
    text = " ".join(r.getMessage() for r in warnings).lower()
    assert "plaintext" in text or "明文" in text
    assert "database_url" in text or "non-durable" in text or "not durable" in text

def test_memory_fallback_warning_not_spammed_per_call(monkeypatch, caplog):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    oauth_flow.reset_oauth_flow_state()
    with caplog.at_level(logging.WARNING, logger="mail_core.accounts.oauth_flow"):
        oauth_flow._flow_store()
        oauth_flow._flow_store()
        oauth_flow._flow_store()
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "oauth" in r.getMessage().lower()]
    assert len(warnings) == 1
