"""A274: (1) build_provider without a session must not open a fresh DB
session per call just to read the fetch-timeout setting — successful lookups
are cached process-wide for a short TTL (failures are not cached).
(2) GraphProvider.timeout must actually reach transports that accept a
timeout, instead of being stored and ignored."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mail_core.accounts.credentials import DictCredentialStore
from mail_core.mail.storage.models import Account
from mail_core.providers import factory
from mail_core.providers.factory import build_provider
from mail_core.providers.graph import GraphProvider


class _FakeSettingSession:
    def __init__(self):
        self.get_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _model, key):
        self.get_calls += 1
        return SimpleNamespace(key=key, value="42")


def test_no_session_timeout_lookup_is_cached(monkeypatch):
    factory._clear_fetch_timeout_cache()
    sessions: list[_FakeSettingSession] = []

    def counting_factory():
        session = _FakeSettingSession()
        sessions.append(session)
        return session

    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: counting_factory)
    account = Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref",
        config={"imap_host": "imap.example.test", "imap_port": 993},
    )
    store = DictCredentialStore({"ref": {"password": "pw"}})
    with patch("mail_core.providers.factory.validate_imap_host", lambda _h: None):
        first = build_provider(account, store)
        second = build_provider(account, store)
    assert first.timeout == 42.0
    assert second.timeout == 42.0
    assert len(sessions) == 1, "second build within TTL must reuse the cached timeout"
    factory._clear_fetch_timeout_cache()


def test_graph_provider_passes_timeout_to_capable_transport():
    seen: dict = {}

    def transport(method, path, params, timeout=None):
        seen["timeout"] = timeout
        return {"value": []}

    provider = GraphProvider(credential_ref="x", transport=transport, timeout=17.5)
    provider._call("GET", "/me/mailFolders", {})
    assert seen["timeout"] == 17.5


def test_graph_provider_keeps_three_arg_transports_working():
    def transport(method, path, params):
        return {"ok": True, "method": method}

    provider = GraphProvider(credential_ref="x", transport=transport, timeout=9.0)
    assert provider._call("GET", "/me", {}) == {"ok": True, "method": "GET"}
