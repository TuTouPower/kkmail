from __future__ import annotations

import time

from mail_core.accounts import google_oauth, oauth_flow


def test_google_callback_expires_after_network_calls_before_authorizing(monkeypatch):
    flow = {
        "client_id": "test-client",
        "client_secret": "temporary-secret",
        "redirect_uri": "https://example.test/callback",
        "code_verifier": "temporary-verifier",
        "intent": "create",
        "expires_at": time.time() + 600,
        "code_consumed": True,
    }
    monkeypatch.setattr(
        oauth_flow,
        "_call_token_endpoint",
        lambda *_args, **_kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": oauth_flow.GOOGLE_REQUIRED_SCOPE,
            "expires_in": 3600,
        },
    )

    def profile_after_expiry(*_args, **_kwargs):
        flow["expires_at"] = 0
        return {"emailAddress": "user@gmail.com"}

    monkeypatch.setattr(oauth_flow, "_call_profile_endpoint", profile_after_expiry)
    monkeypatch.setattr(oauth_flow, "_email_exists", lambda _email: False)

    success, status_code, message = google_oauth._exchange_and_verify_google(
        flow,
        "authorization-code",
        time.time(),
    )

    assert not success
    assert status_code == 400
    assert message == oauth_flow.EXPIRED_FLOW_MESSAGE
    assert flow["status"] == "expired"
    assert flow["code_consumed"] is True
    assert "staged_credentials" not in flow
    assert "client_secret" not in flow
    assert "code_verifier" not in flow
