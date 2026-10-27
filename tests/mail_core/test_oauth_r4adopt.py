"""R4 adoption spec tests for src/mail_core/providers/oauth.py (A116+)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from mail_core.accounts import DictCredentialStore
from mail_core.accounts.credentials import credential_edit
from mail_core.providers.oauth import OAuthTokenClient

_TOKEN_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _store(refresh="rt-1"):
    return DictCredentialStore(
        {
            "oauth:graph": json.dumps(
                {
                    "refresh_token": refresh,
                    "client_id": "cid",
                    "client_secret": "sec",
                    "token_uri": _TOKEN_URI,
                }
            )
        }
    )


# --- A116: network refresh must not run under credential_edit -------------


def test_a116_refresh_network_call_runs_outside_credential_edit_lock():
    store = _store()
    entered = []

    def token_post(method, url, form, headers):
        def probe():
            with credential_edit(store, "oauth:graph") as _data:
                entered.append(True)

        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        thread.join(2.0)
        return {"access_token": "at-1", "expires_in": 3600}

    client = OAuthTokenClient(
        credential_ref="oauth:graph", store=store, provider="graph", http_post=token_post
    )
    assert client.get_access_token() == "at-1"
    assert entered == [True]


def test_a116_refresh_cas_adopts_persisted_token_on_refresh_token_conflict():
    store = _store()

    def token_post(method, url, form, headers):
        # Another process rotated the credential while our POST was in flight.
        store.put_secret(
            "oauth:graph",
            json.dumps(
                {
                    "refresh_token": "rt-2",
                    "client_id": "cid",
                    "client_secret": "sec",
                    "token_uri": _TOKEN_URI,
                    "access_token": "at-persisted",
                    "expires_at": time.time() + 3600,
                }
            ),
        )
        return {"access_token": "at-from-old-refresh", "refresh_token": "rt-3", "expires_in": 3600}

    client = OAuthTokenClient(
        credential_ref="oauth:graph", store=store, provider="graph", http_post=token_post
    )
    assert client.get_access_token() == "at-persisted"
    saved = json.loads(store.get_secret("oauth:graph"))
    assert saved["refresh_token"] == "rt-2"
    assert saved["access_token"] == "at-persisted"


# --- A169: malformed expires_in must not roll back the whole refresh ------


@pytest.mark.parametrize("bad_expires_in", ["not-a-number", {"seconds": 3600}, ["3600"], float("nan")])
def test_a169_bad_expires_in_still_persists_rotated_refresh_token(bad_expires_in):
    store = _store()

    def token_post(method, url, form, headers):
        return {
            "access_token": "at-new",
            "refresh_token": "rt-rotated",
            "expires_in": bad_expires_in,
        }

    client = OAuthTokenClient(
        credential_ref="oauth:graph", store=store, provider="graph", http_post=token_post
    )
    assert client.get_access_token() == "at-new"
    saved = json.loads(store.get_secret("oauth:graph"))
    assert saved["access_token"] == "at-new"
    assert saved["refresh_token"] == "rt-rotated"


# --- A186: missing expires_in must still set expires_at (default 3600s) ---


def test_a186_missing_expires_in_defaults_expires_at_to_3600_and_caches():
    store = _store()
    calls = []

    def token_post(method, url, form, headers):
        calls.append(form)
        return {"access_token": "at-no-expiry", "refresh_token": "rt-2"}  # no expires_in

    client = OAuthTokenClient(
        credential_ref="oauth:graph", store=store, provider="graph", http_post=token_post
    )
    before = time.time()
    assert client.get_access_token() == "at-no-expiry"
    after = time.time()
    saved = json.loads(store.get_secret("oauth:graph"))
    assert saved["expires_at"] >= before + 3600 - 5
    assert saved["expires_at"] <= after + 3600 + 5
    # With expires_at set, the next call is served from cache, not a refresh.
    assert client.get_access_token() == "at-no-expiry"
    assert len(calls) == 1


# --- A187: provider / MIME responses must have an explicit size cap -------


class _FakeHttpResponse:
    def __init__(self, body: bytes, content_type="application/json"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self, size=-1):
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_a187_json_response_over_limit_raises_provider_error(monkeypatch):
    import urllib.request

    import mail_core.providers.oauth as oauth_mod
    from mail_core.providers.http import ProviderHttpError
    from mail_core.providers.oauth import urllib_json_request

    monkeypatch.setattr(oauth_mod, "MAX_JSON_RESPONSE_BYTES", 8)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=60: _FakeHttpResponse(b'{"value": "0123456789abcdef"}'),
    )
    with pytest.raises(ProviderHttpError):
        urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=lambda _s: None)


def test_a187_mime_value_response_over_limit_raises_provider_error(monkeypatch):
    import urllib.request

    import mail_core.providers.oauth as oauth_mod
    from mail_core.providers.http import ProviderHttpError
    from mail_core.providers.oauth import urllib_json_request

    monkeypatch.setattr(oauth_mod, "MAX_MIME_RESPONSE_BYTES", 8)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=60: _FakeHttpResponse(b"x" * 64, content_type="message/rfc822"),
    )
    with pytest.raises(ProviderHttpError):
        urllib_json_request(
            "GET", "https://graph.microsoft.com/v1.0/me/messages/m1/$value", _sleep_fn=lambda _s: None
        )


def test_a187_responses_under_limit_still_parse(monkeypatch):
    import urllib.request

    from mail_core.providers.oauth import urllib_json_request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=60: _FakeHttpResponse(b'{"ok": true}'),
    )
    assert urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=lambda _s: None) == {
        "ok": True
    }
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=60: _FakeHttpResponse(b"mime-body", content_type="message/rfc822"),
    )
    result = urllib_json_request(
        "GET", "https://graph.microsoft.com/v1.0/me/messages/m1/$value", _sleep_fn=lambda _s: None
    )
    assert result == {"raw_bytes": b"mime-body"}
