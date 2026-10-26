"""B2: device-code polling must not hold the credential lock over HTTP.

Pre-fix, ``poll_device_flow`` ran the blocking token-endpoint exchange
inside ``credential_edit`` — i.e. inside a DB transaction holding the
advisory lock and the flow row lock — starving the connection pool for
the duration of every poll. The fix splits the poll into a short locked
claim (due check + ``next_poll_at`` pushed forward, which is what keeps
concurrent pollers from duplicating the exchange), the HTTP call with
no lock held, and a short locked persist that discards the outcome if
the flow was cancelled/replaced in the meantime.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

import pytest

from mail_core.accounts import device_oauth, oauth_flow
from mail_core.accounts.credentials import DictCredentialStore, load_json_secret
from mail_core.accounts.device_oauth import DevicePollTooSoon, poll_device_flow


def _store_with_device_flow(**overrides):
    store = DictCredentialStore()
    flow = {
        "flow_id": "flow-1",
        "provider": "microsoft",
        "method": "device_code",
        "tenant": "common",
        "client_id": "client-1",
        "device_code": "device-code-1",
        "user_code": "USER-CODE",
        "verification_uri": "https://microsoft.com/devicelogin",
        "status": "pending",
        "interval": 5,
        "next_poll_at": time.time() - 1,
        "expires_at": time.time() + 600,
    }
    flow.update(overrides)
    store.put_secret("oauth_flow:flow-1", json.dumps(flow))
    return store


class _LockTracker:
    def __init__(self, monkeypatch):
        self.depth = 0
        real = device_oauth.credential_edit

        @contextmanager
        def tracked(store, ref, **kwargs):
            self.depth += 1
            try:
                with real(store, ref, **kwargs) as data:
                    yield data
            finally:
                self.depth -= 1

        monkeypatch.setattr(device_oauth, "credential_edit", tracked)


def _patch_lifecycle(monkeypatch, store):
    monkeypatch.setattr(oauth_flow, "_flow_store", lambda: store)
    monkeypatch.setattr(oauth_flow, "_verify_flow_owner", lambda _flow, _principal: None)


def test_token_http_runs_outside_the_credential_lock(monkeypatch):
    store = _store_with_device_flow()
    _patch_lifecycle(monkeypatch, store)
    tracker = _LockTracker(monkeypatch)
    calls = []

    def fake_token_endpoint(url, form):
        calls.append((url, form, tracker.depth))
        return {"error": "authorization_pending", "error_description": "waiting"}

    monkeypatch.setattr(oauth_flow, "_call_token_endpoint", fake_token_endpoint)

    view = poll_device_flow("flow-1", object())

    assert view["status"] == "pending"
    assert len(calls) == 1
    assert calls[0][2] == 0, "token HTTP ran while credential_edit was held"
    persisted = load_json_secret(store, "oauth_flow:flow-1")
    assert persisted["next_poll_at"] > time.time(), "claim/next poll time was not persisted"


def test_claim_prevents_duplicate_polling(monkeypatch):
    store = _store_with_device_flow()
    _patch_lifecycle(monkeypatch, store)
    calls = []

    def fake_token_endpoint(url, form):
        calls.append(url)
        return {"error": "authorization_pending"}

    monkeypatch.setattr(oauth_flow, "_call_token_endpoint", fake_token_endpoint)

    poll_device_flow("flow-1", object())
    with pytest.raises(DevicePollTooSoon):
        poll_device_flow("flow-1", object())
    assert len(calls) == 1, "second poll duplicated the token exchange"


def test_outcome_discarded_when_flow_cancelled_during_http(monkeypatch):
    store = _store_with_device_flow()
    _patch_lifecycle(monkeypatch, store)

    def cancelling_token_endpoint(url, form):
        flow = load_json_secret(store, "oauth_flow:flow-1")
        flow["status"] = "cancelled"
        flow.pop("device_code", None)
        store.put_secret("oauth_flow:flow-1", json.dumps(flow))
        return {"error": "authorization_pending"}

    monkeypatch.setattr(oauth_flow, "_call_token_endpoint", cancelling_token_endpoint)

    view = poll_device_flow("flow-1", object())

    assert view["status"] == "cancelled"
    persisted = load_json_secret(store, "oauth_flow:flow-1")
    assert persisted["status"] == "cancelled", "poll outcome resurrected a cancelled flow"
