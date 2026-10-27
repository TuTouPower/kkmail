"""A162: starting a new OAuth flow must invalidate the session's old pending flow."""
from __future__ import annotations
from urllib.parse import parse_qs, urlsplit
import pytest
from mail_core.accounts import oauth_flow
from mail_core.accounts.credentials import load_json_secret, save_json_secret
from mail_core.security.auth import AuthPrincipal

def _principal():
    return AuthPrincipal(via="session", csrf_token="csrf-a162")

def _start(monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "18765")
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    return oauth_flow.start_oauth_flow(_principal(), provider="microsoft", client_id="cid-a162")

def _state_of(flow):
    return parse_qs(urlsplit(flow["auth_url"]).query)["state"][0]

def test_new_flow_cancels_old_pending_flow_and_state(monkeypatch):
    first = _start(monkeypatch)
    old_state = _state_of(first)
    second = _start(monkeypatch)
    assert second["flow_id"] != first["flow_id"]
    # Old flow record is gone.
    with pytest.raises(LookupError):
        oauth_flow.get_oauth_flow_status(first["flow_id"], _principal())
    store = oauth_flow._flow_store()
    with pytest.raises(KeyError):
        load_json_secret(store, f"oauth_state:{old_state}")
    # Old callback state is rejected.
    ok, status, _msg = oauth_flow.complete_oauth_callback("microsoft", state=old_state, code="code-x")
    assert ok is False and status == 400
    # New flow is the active one.
    active = oauth_flow.get_active_oauth_flow(_principal())
    assert active is not None and active["flow_id"] == second["flow_id"]

def test_new_flow_preserves_authorized_old_flow(monkeypatch):
    first = _start(monkeypatch)
    store = oauth_flow._flow_store()
    flow = load_json_secret(store, f"oauth_flow:{first['flow_id']}")
    flow["status"] = "authorized"
    save_json_secret(store, f"oauth_flow:{first['flow_id']}", flow)
    second = _start(monkeypatch)
    assert second["flow_id"] != first["flow_id"]
    status = oauth_flow.get_oauth_flow_status(first["flow_id"], _principal())
    assert status["flow_id"] == first["flow_id"]
    assert status["status"] == "authorized"
