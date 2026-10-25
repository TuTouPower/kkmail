import json
import time
from contextlib import contextmanager

from mail_core.accounts import oauth_flow
from mail_core.accounts.credentials import DictCredentialStore, load_json_secret


def _flow_store_with_pending_flow():
    store = DictCredentialStore()
    store.put_secret(
        "oauth_flow:flow-1",
        json.dumps(
            {
                "flow_id": "flow-1",
                "status": "pending",
                "expires_at": time.time() + 600,
                "state": "oauth-state",
            }
        ),
    )
    return store


def _track_credential_edits(monkeypatch):
    refs = []
    real_credential_edit = oauth_flow.credential_edit

    @contextmanager
    def tracked(store, ref, **kwargs):
        refs.append(ref)
        with real_credential_edit(store, ref, **kwargs) as data:
            yield data

    monkeypatch.setattr(oauth_flow, "credential_edit", tracked)
    return refs


def test_get_oauth_flow_status_reads_flow_under_credential_edit(monkeypatch):
    store = _flow_store_with_pending_flow()
    monkeypatch.setattr(oauth_flow, "_flow_store", lambda: store)
    monkeypatch.setattr(oauth_flow, "_verify_flow_owner", lambda _flow, _principal: None)
    refs = _track_credential_edits(monkeypatch)

    view = oauth_flow.get_oauth_flow_status("flow-1", object())

    assert view["status"] == "pending"
    assert refs == ["oauth_flow:flow-1"]


def test_cancel_oauth_flow_reads_and_clears_flow_under_credential_edit(monkeypatch):
    store = _flow_store_with_pending_flow()
    monkeypatch.setattr(oauth_flow, "_flow_store", lambda: store)
    monkeypatch.setattr(oauth_flow, "_verify_flow_owner", lambda _flow, _principal: None)
    monkeypatch.setattr(oauth_flow, "session_binding_key", lambda _principal: "session-key")
    refs = _track_credential_edits(monkeypatch)

    result = oauth_flow.cancel_oauth_flow("flow-1", object())

    assert result == {"ok": True, "status": "cancelled"}
    assert refs == ["oauth_flow:flow-1", "oauth_active:session-key"]


def test_expired_oauth_flow_is_rechecked_and_cleaned_under_credential_edit(monkeypatch):
    store = DictCredentialStore()
    store.put_secret(
        "oauth_flow:flow-1",
        json.dumps(
            {
                "flow_id": "flow-1",
                "status": "pending",
                "expires_at": 0,
                "state": "oauth-state",
                "staged_credentials": {"refresh_token": "temporary"},
                "client_secret": "temporary-secret",
            }
        ),
    )
    store.put_secret("oauth_state:oauth-state", json.dumps({"flow_id": "flow-1"}))
    store.put_secret("oauth_active:session-key", json.dumps({"flow_id": "flow-1"}))
    monkeypatch.setattr(oauth_flow, "_flow_store", lambda: store)
    monkeypatch.setattr(oauth_flow, "_verify_flow_owner", lambda _flow, _principal: None)
    monkeypatch.setattr(oauth_flow, "session_binding_key", lambda _principal: "session-key")
    refs = _track_credential_edits(monkeypatch)

    view = oauth_flow.get_oauth_flow_status("flow-1", object())

    assert view["status"] == "expired"
    assert refs == ["oauth_flow:flow-1", "oauth_flow:flow-1", "oauth_active:session-key"]
    persisted = load_json_secret(store, "oauth_flow:flow-1")
    assert persisted["status"] == "expired"
    assert "staged_credentials" not in persisted
    assert "client_secret" not in persisted
    assert load_json_secret(store, "oauth_active:session-key") == {}
