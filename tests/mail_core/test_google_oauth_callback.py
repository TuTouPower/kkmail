"""Google OAuth authorization-code + PKCE callback and reauthorization tests (t054)."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import hashlib
import os
from urllib.parse import parse_qs, urlsplit
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from mail_core.accounts.credentials import get_credential_store, load_json_secret
from mail_core.accounts.oauth_flow import set_oauth_http_hooks
from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account
from mail_core.providers.oauth import OAuthTokenClient
from mail_core.security.redact import redact
from tests.mail_core.conftest import TEST_LOGIN_PASSWORD


def _login_session_client() -> tuple[TestClient, str]:
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert res.status_code == 200, res.text
    csrf = res.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf})
    return client, csrf


def test_oauth_metadata_distinguishes_web_and_desktop_without_trusting_headers_or_query(
    api_client, monkeypatch
):
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.delenv("MAIL_CORE_PUBLIC_ORIGIN", raising=False)

    res = api_client.get(
        "/api/accounts/oauth/metadata?provider=google&desktop=1",
        headers={"Host": "evil.example.com", "X-Forwarded-Host": "evil.example.com"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["runtime_mode"] == "web"
    assert body["default_client_type"] == "confidential"
    assert body["origin_configured"] is False
    assert body["redirect_uri"] is None
    assert body["callback_path"] == "/api/accounts/oauth/callback/google"

    # Untrusted HTTP loopback origin on web mode without explicit allow flag is rejected
    monkeypatch.setenv("MAIL_CORE_PUBLIC_ORIGIN", "http://127.0.0.1:9999")
    res_http = api_client.get("/api/accounts/oauth/metadata?provider=google")
    assert res_http.json()["origin_configured"] is False
    assert res_http.json()["redirect_uri"] is None

    # Trusted HTTPS origin on web mode
    monkeypatch.setenv("MAIL_CORE_PUBLIC_ORIGIN", "https://mail.example.com")
    res_https = api_client.get(
        "/api/accounts/oauth/metadata?provider=google",
        headers={"Host": "attacker.invalid"},
    )
    assert res_https.status_code == 200
    assert res_https.json()["origin_configured"] is True
    assert res_https.json()["redirect_uri"] == "https://mail.example.com/api/accounts/oauth/callback/google"

    # Desktop sidecar mode uses 127.0.0.1 with dynamic local port
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "29876")
    res_desktop = api_client.get("/api/accounts/oauth/metadata?provider=google")
    assert res_desktop.status_code == 200
    dbody = res_desktop.json()
    assert dbody["runtime_mode"] == "desktop"
    assert dbody["default_client_type"] == "public"
    assert dbody["redirect_uri"] == "http://127.0.0.1:29876/api/accounts/oauth/callback/google"


def test_oauth_start_reports_missing_fields_and_generates_pkce_s256(api_client, monkeypatch):
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.delenv("MAIL_CORE_PUBLIC_ORIGIN", raising=False)

    missing = api_client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_type": "confidential"},
    )
    assert missing.status_code == 400
    detail = missing.json()["detail"]
    assert "Client ID" in detail
    assert "Client Secret" in detail
    assert "MAIL_CORE_PUBLIC_ORIGIN" in detail

    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "18765")
    started = api_client.post(
        "/api/accounts/oauth/start",
        json={
            "provider": "google",
            "intent": "create",
            "client_type": "public",
            "client_id": "desktop-client-id",
            "email_hint": "User@Gmail.com",
        },
    )
    assert started.status_code == 200, started.text
    payload = started.json()
    parsed = urlsplit(payload["auth_url"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert qs["response_type"] == "code"
    assert qs["client_id"] == "desktop-client-id"
    assert qs["redirect_uri"] == "http://127.0.0.1:18765/api/accounts/oauth/callback/google"
    assert qs["scope"] == "https://www.googleapis.com/auth/gmail.modify"
    assert "gmail.send" not in qs["scope"]
    assert "mail.google.com" not in qs["scope"]
    assert qs["code_challenge_method"] == "S256"
    assert qs["access_type"] == "offline"
    assert qs["prompt"] == "consent"
    assert qs["login_hint"] == "user@gmail.com"
    assert len(qs["state"]) >= 32
    assert len(qs["code_challenge"]) >= 40


def test_callback_rejects_invalid_provider_state_missing_code_replay_and_wrong_scope(
    api_client, monkeypatch
):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "18765")

    started = api_client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-1"},
    ).json()
    state = parse_qs(urlsplit(started["auth_url"]).query)["state"][0]

    unauth_browser = TestClient(app)
    # Wrong provider
    assert unauth_browser.get(f"/api/accounts/oauth/callback/microsoft?state={state}&code=c1").status_code == 400
    # Missing state / tampered state
    assert unauth_browser.get("/api/accounts/oauth/callback/google?code=c1").status_code == 400
    assert unauth_browser.get("/api/accounts/oauth/callback/google?state=tampered_state_value_123456&code=c1").status_code == 400

    # Missing code consumes state and fails closed
    no_code = unauth_browser.get(f"/api/accounts/oauth/callback/google?state={state}")
    assert no_code.status_code == 400
    status_after = api_client.get(f"/api/accounts/oauth/flows/{started['flow_id']}").json()
    assert status_after["status"] == "failed"

    # Replay of same state fails closed
    assert unauth_browser.get(f"/api/accounts/oauth/callback/google?state={state}&code=c1").status_code == 400

    # Missing required gmail.modify scope or missing refresh_token on create fails closed
    for token_payload, expected_err in [
        ({"access_token": "at", "refresh_token": "rt", "scope": "https://www.googleapis.com/auth/userinfo.email"}, "gmail.modify"),
        ({"access_token": "at", "scope": "https://www.googleapis.com/auth/gmail.modify"}, "Refresh Token"),
    ]:
        s2 = api_client.post(
            "/api/accounts/oauth/start",
            json={"provider": "google", "intent": "create", "client_id": "cid-1"},
        ).json()
        st2 = parse_qs(urlsplit(s2["auth_url"]).query)["state"][0]
        set_oauth_http_hooks(
            token_post=lambda _url, _form, tp=token_payload: tp,
            profile_get=lambda _url, _at: {"emailAddress": "newuser@gmail.com"},
        )
        cb = unauth_browser.get(f"/api/accounts/oauth/callback/google?state={st2}&code=code-{ uuid.uuid4().hex }")
        assert cb.status_code == 400
        flow_view = api_client.get(f"/api/accounts/oauth/flows/{s2['flow_id']}").json()
        assert flow_view["status"] == "failed"
        assert expected_err in flow_view["error"]


def test_callback_headers_url_scrubbing_and_log_redaction(api_client, monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    started = api_client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-sec"},
    ).json()
    state = parse_qs(urlsplit(started["auth_url"]).query)["state"][0]
    set_oauth_http_hooks(
        token_post=lambda _url, _form: {
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
            "expires_in": 3600,
        },
        profile_get=lambda _url, _at: {"emailAddress": "verified@gmail.com"},
    )
    unauth_browser = TestClient(app)
    cb = unauth_browser.get(f"/api/accounts/oauth/callback/google?state={state}&code=secret-auth-code")
    assert cb.status_code == 200
    assert "no-store" in cb.headers.get("cache-control", "")
    assert cb.headers.get("referrer-policy") == "no-referrer"
    assert "default-src 'none'" in cb.headers.get("content-security-policy", "")
    assert "window.history.replaceState" in cb.text
    assert 'href="/#oauth-return"' in cb.text
    for secret in ("secret-access-token", "secret-refresh-token", "secret-auth-code", state):
        assert secret not in cb.text

    status_res = api_client.get(f"/api/accounts/oauth/flows/{started['flow_id']}")
    assert status_res.status_code == 200
    for secret in ("secret-access-token", "secret-refresh-token", "secret-auth-code", state):
        assert secret not in status_res.text

    log_line = f'GET /api/accounts/oauth/callback/google?code=secret-auth-code&state={state} HTTP/1.1'
    redacted = redact(log_line)
    assert "secret-auth-code" not in redacted
    assert state not in redacted


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_full_google_oauth_create_reauthorize_session_isolation_and_concurrency_pg(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_PUBLIC_ORIGIN", "https://mail.example.com")

    session_a, _ = _login_session_client()
    session_b, _ = _login_session_client()
    system_browser = TestClient(app)

    # 1. Start create flow in session A
    started = session_a.post(
        "/api/accounts/oauth/start",
        json={
            "provider": "google",
            "intent": "create",
            "client_type": "confidential",
            "client_id": "web-client-id",
            "client_secret": "web-client-secret",
            "email_hint": "wrong-hint@gmail.com",
        },
    )
    assert started.status_code == 200, started.text
    flow_id = started.json()["flow_id"]
    query = parse_qs(urlsplit(started.json()["auth_url"]).query)
    state = query["state"][0]
    challenge = query["code_challenge"][0]

    token_calls: list[dict[str, str]] = []

    def fake_token_post(url: str, form: dict[str, str]):
        assert url == "https://oauth2.googleapis.com/token"
        token_calls.append(dict(form))
        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert expected_challenge == challenge
        return {
            "access_token": "google-access-1",
            "refresh_token": "google-refresh-1",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
            "expires_in": 3600,
        }

    real_email = f"real-{uuid.uuid4().hex[:8]}@gmail.com"
    set_oauth_http_hooks(
        token_post=fake_token_post,
        profile_get=lambda _url, at: {"emailAddress": real_email} if at == "google-access-1" else {},
    )

    # 2. Unauthenticated system browser completes callback; replay is rejected without 2nd token call
    cb1 = system_browser.get(f"/api/accounts/oauth/callback/google?state={state}&code=auth-code-1")
    assert cb1.status_code == 200
    cb2 = system_browser.get(f"/api/accounts/oauth/callback/google?state={state}&code=auth-code-1")
    assert cb2.status_code == 400
    assert len(token_calls) == 1

    # Callback alone must NOT have created the account yet
    with get_session_factory()() as db:
        assert db.scalar(select(Account).where(Account.email == real_email)) is None

    # 3. Cross-session access from session B is denied (status, cancel, and save)
    assert session_b.get(f"/api/accounts/oauth/flows/{flow_id}").status_code == 403
    assert session_b.post(f"/api/accounts/oauth/flows/{flow_id}/cancel").status_code == 403
    hijack = session_b.post("/api/accounts", json={"provider": "gmail", "oauth_flow_id": flow_id})
    assert hijack.status_code == 403

    # 4. Failed save (non-existent group_id) rolls back without losing the authorized flow
    bad_group = session_a.post(
        "/api/accounts",
        json={"provider": "gmail", "group_id": str(uuid.uuid4()), "oauth_flow_id": flow_id},
    )
    assert bad_group.status_code == 404

    # 5. Session A confirms save; verified_email from users.getProfile wins over mismatched input
    created = session_a.post(
        "/api/accounts",
        json={"email": "ignored@gmail.com", "provider": "gmail", "oauth_flow_id": flow_id},
    )
    assert created.status_code == 200, created.text
    acc_out = created.json()
    account_id = acc_out["id"]
    assert acc_out["email"] == real_email
    assert acc_out["provider_profile"] == "google"
    assert acc_out["oauth_client_type"] == "confidential"
    assert "web-client-secret" not in created.text
    assert "google-refresh-1" not in created.text

    # Re-submitting the consumed flow_id fails closed
    dup_save = session_a.post("/api/accounts", json={"provider": "gmail", "oauth_flow_id": flow_id})
    assert dup_save.status_code in (400, 404)

    # 6. Reauthorize existing Gmail account reuses saved client_id/client_secret when left blank
    reauth_start = session_a.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "reauthorize", "account_id": account_id},
    )
    assert reauth_start.status_code == 200, reauth_start.text
    reauth_flow_id = reauth_start.json()["flow_id"]
    reauth_state = parse_qs(urlsplit(reauth_start.json()["auth_url"]).query)["state"][0]

    # Wrong account email during reauthorize is rejected
    set_oauth_http_hooks(
        token_post=lambda _url, _form: {
            "access_token": "wrong-at",
            "refresh_token": "wrong-rt",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
        },
        profile_get=lambda _url, _at: {"emailAddress": "another-person@gmail.com"},
    )
    assert system_browser.get(f"/api/accounts/oauth/callback/google?state={reauth_state}&code=code-wrong").status_code == 400
    assert session_a.get(f"/api/accounts/oauth/flows/{reauth_flow_id}").json()["status"] == "failed"

    # Start a new reauthorize flow where Google omits refresh_token (allowed to keep existing rotated RT for same client+email)
    reauth2 = session_a.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "reauthorize", "account_id": account_id},
    ).json()
    state2 = parse_qs(urlsplit(reauth2["auth_url"]).query)["state"][0]

    # Simulate background token rotation happening while reauthorization is in flight
    with get_session_factory()() as db:
        ref = db.get(Account, uuid.UUID(account_id)).credential_ref
    token_client = OAuthTokenClient(
        credential_ref=ref,
        store=get_credential_store(),
        provider="gmail",
        http_post=lambda *_a: {"access_token": "bg-access", "refresh_token": "bg-rotated-refresh", "expires_in": 3600},
    )
    assert token_client.get_access_token(force_refresh=True) == "bg-access"

    set_oauth_http_hooks(
        token_post=lambda _url, form: (
            assert_secret := form.get("client_secret") == "web-client-secret",
            {
                "access_token": "reauth-access-2",
                "scope": "https://www.googleapis.com/auth/gmail.modify",
                "expires_in": 3600,
            } if assert_secret else {},
        )[1],
        profile_get=lambda _url, _at: {"emailAddress": real_email},
    )
    assert system_browser.get(f"/api/accounts/oauth/callback/google?state={state2}&code=code-reauth-2").status_code == 200
    patched = session_a.patch(f"/api/accounts/{account_id}", json={"oauth_flow_id": reauth2["flow_id"]})
    assert patched.status_code == 200, patched.text

    stored = load_json_secret(get_credential_store(), ref)
    assert stored["access_token"] == "reauth-access-2"
    assert stored["refresh_token"] == "bg-rotated-refresh"
    assert stored["client_secret"] == "web-client-secret"

    # 7. Logout invalidates any pending OAuth flow via session_epoch increment
    s_logout = session_a.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "reauthorize", "account_id": account_id},
    ).json()
    assert session_a.post("/api/auth/logout").status_code == 200
    session_c, _ = _login_session_client()
    assert session_c.get(f"/api/accounts/oauth/flows/{s_logout['flow_id']}").status_code == 403


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_concurrent_callbacks_code_reuse_multi_flow_isolation_and_error_recovery_pg(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from mail_core.accounts.oauth_flow import _flow_store, save_json_secret

    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "18765")
    client, _ = _login_session_client()
    browser = TestClient(app)

    # 1. Two concurrent callbacks for the same state: exactly one succeeds, one fails closed, 1 token exchange
    s_conc = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-conc"},
    ).json()
    state_conc = parse_qs(urlsplit(s_conc["auth_url"]).query)["state"][0]
    conc_email = f"conc-{uuid.uuid4().hex[:8]}@gmail.com"
    exchange_calls: list[str] = []

    def conc_token_post(_url: str, form: dict[str, str]):
        exchange_calls.append(form["code"])
        return {
            "access_token": "at-conc",
            "refresh_token": "rt-conc",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
            "expires_in": 3600,
        }

    set_oauth_http_hooks(
        token_post=conc_token_post,
        profile_get=lambda _url, _at: {"emailAddress": conc_email},
    )
    barrier = Barrier(2)

    def hit_callback(_i: int) -> int:
        c = TestClient(app)
        barrier.wait(timeout=5)
        return c.get(f"/api/accounts/oauth/callback/google?state={state_conc}&code=once-only-code").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(hit_callback, range(2)))
    assert statuses == [200, 400]
    assert exchange_calls == ["once-only-code"]

    # Reusing the same authorization code on a different flow fails closed
    s_reuse = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-conc"},
    ).json()
    state_reuse = parse_qs(urlsplit(s_reuse["auth_url"]).query)["state"][0]
    assert browser.get(f"/api/accounts/oauth/callback/google?state={state_reuse}&code=once-only-code").status_code == 400
    assert client.get(f"/api/accounts/oauth/flows/{s_reuse['flow_id']}").json()["status"] == "failed"

    # First concurrent flow is still intact and can be saved
    acc1 = client.post("/api/accounts", json={"provider": "gmail", "oauth_flow_id": s_conc["flow_id"]})
    assert acc1.status_code == 200, acc1.text
    acc1_id = acc1.json()["id"]

    # 2. Duplicate email on create flow is rejected without overwriting existing account
    s_dup = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-conc"},
    ).json()
    state_dup = parse_qs(urlsplit(s_dup["auth_url"]).query)["state"][0]
    assert browser.get(f"/api/accounts/oauth/callback/google?state={state_dup}&code=dup-code").status_code == 400
    dup_status = client.get(f"/api/accounts/oauth/flows/{s_dup['flow_id']}").json()
    assert dup_status["status"] == "failed"
    assert conc_email in dup_status["error"]

    # 3. Multiple simultaneous flows: error in flow A does not affect valid flow B; cannot save flow B onto account A
    email_b = f"second-{uuid.uuid4().hex[:8]}@gmail.com"
    acc2 = client.post(
        "/api/accounts",
        json={
            "email": email_b,
            "provider": "gmail",
            "config": {"oauth_client_type": "confidential"},
            "credentials": {
                "client_id": "cid-b",
                "client_secret": "old-secret-b",
                "refresh_token": "orig-rt-b",
            },
        },
    )
    assert acc2.status_code == 200, acc2.text
    acc2 = acc2.json()
    acc2_id = acc2["id"]
    with get_session_factory()() as db:
        acc2_row = db.get(Account, uuid.UUID(acc2_id))
        acc2_row.sync_status = "auth_failed"
        acc2_ref = acc2_row.credential_ref
        db.commit()
    from mail_core.accounts.credentials import credential_edit
    with credential_edit(get_credential_store(), acc2_ref) as saved:
        saved["expires_at"] = 123456789.0

    flow_a = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "reauthorize", "account_id": acc1_id},
    ).json()
    flow_b = client.post(
        "/api/accounts/oauth/start",
        json={
            "provider": "google",
            "intent": "reauthorize",
            "account_id": acc2_id,
            "client_type": "public",
            "client_id": "cid-b-public",
        },
    ).json()
    state_a = parse_qs(urlsplit(flow_a["auth_url"]).query)["state"][0]
    state_b = parse_qs(urlsplit(flow_b["auth_url"]).query)["state"][0]

    # Active flow pointer currently points to flow_b
    active_before = client.get("/api/accounts/oauth/active").json()["flow"]
    assert active_before["flow_id"] == flow_b["flow_id"]

    # User denies flow A
    assert browser.get(f"/api/accounts/oauth/callback/google?state={state_a}&error=access_denied").status_code == 400
    assert client.get(f"/api/accounts/oauth/flows/{flow_a['flow_id']}").json()["status"] == "failed"
    assert client.get(f"/api/accounts/oauth/flows/{flow_b['flow_id']}").json()["status"] == "pending"

    # Cancelling flow A must NOT delete the active pointer that belongs to flow B
    assert client.post(f"/api/accounts/oauth/flows/{flow_a['flow_id']}/cancel").status_code == 200
    assert client.get("/api/accounts/oauth/active").json()["flow"]["flow_id"] == flow_b["flow_id"]

    # Reauthorize with changed client_id ("cid-b-public" != "cid-b") and missing refresh_token must fail closed
    flow_no_rt = client.post(
        "/api/accounts/oauth/start",
        json={
            "provider": "google",
            "intent": "reauthorize",
            "account_id": acc2_id,
            "client_type": "public",
            "client_id": "different-client-id",
        },
    ).json()
    state_no_rt = parse_qs(urlsplit(flow_no_rt["auth_url"]).query)["state"][0]
    set_oauth_http_hooks(
        token_post=lambda _url, _form: {
            "access_token": "at-no-rt",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
        },
        profile_get=lambda _url, _at: {"emailAddress": email_b},
    )
    assert browser.get(f"/api/accounts/oauth/callback/google?state={state_no_rt}&code=code-no-rt").status_code == 400
    assert client.get(f"/api/accounts/oauth/flows/{flow_no_rt['flow_id']}").json()["status"] == "failed"

    # Flow B succeeds for email_b as public client without sending old client_secret and without expires_in
    sent_forms: list[dict[str, str]] = []
    set_oauth_http_hooks(
        token_post=lambda _url, form: (
            sent_forms.append(dict(form)),
            {
                "access_token": "at-b-new",
                "refresh_token": "rt-b-new",
                "scope": "https://www.googleapis.com/auth/gmail.modify",
            },
        )[1],
        profile_get=lambda _url, _at: {"emailAddress": email_b},
    )
    assert browser.get(f"/api/accounts/oauth/callback/google?state={state_b}&code=code-b-ok").status_code == 200
    assert "client_secret" not in sent_forms[-1]

    # Attempting to save flow B onto account 1 is rejected and does not consume flow B
    wrong_target = client.patch(f"/api/accounts/{acc1_id}", json={"oauth_flow_id": flow_b["flow_id"]})
    assert wrong_target.status_code == 400

    # Saving flow B clears stale credential fields and resumes enabled-account synchronization.
    ok_target = client.patch(f"/api/accounts/{acc2_id}", json={"oauth_flow_id": flow_b["flow_id"]})
    assert ok_target.status_code == 200
    assert ok_target.json()["sync_status"] == "running"
    # Enabled accounts immediately enqueue sync with the newly authorized credentials.
    from mail_core.mail.storage.models import WorkerJob
    with get_session_factory()() as db:
        assert db.scalar(select(WorkerJob.id).where(WorkerJob.account_id == uuid.UUID(acc2_id))) is not None
    assert ok_target.json()["oauth_client_type"] == "public"
    saved_b = load_json_secret(get_credential_store(), acc2_ref)
    assert saved_b["refresh_token"] == "rt-b-new"
    assert "client_secret" not in saved_b
    assert "expires_at" not in saved_b

    # 4. IMAP account cannot start Google OAuth reauthorize
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    imap_acc = client.post(
        "/api/accounts",
        json={
            "email": f"imap-{uuid.uuid4().hex[:8]}@gmail.com",
            "provider": "imap",
            "config": {"imap_host": "imap.gmail.com"},
            "credentials": {"password": "app-password"},
        },
    ).json()
    imap_reauth = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "reauthorize", "account_id": imap_acc["id"]},
    )
    assert imap_reauth.status_code == 400

    # 5. Cancelled and expired flows (both pending and authorized) cannot be used or recovered
    s_cancel = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-cancel"},
    ).json()
    assert client.post(f"/api/accounts/oauth/flows/{s_cancel['flow_id']}/cancel").status_code == 200
    assert client.post("/api/accounts", json={"provider": "gmail", "oauth_flow_id": s_cancel["flow_id"]}).status_code == 404

    s_exp = client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-exp"},
    ).json()
    exp_state = parse_qs(urlsplit(s_exp["auth_url"]).query)["state"][0]
    exp_ref = f"oauth_flow:{s_exp['flow_id']}"
    exp_data = load_json_secret(_flow_store(), exp_ref)
    exp_data["status"] = "authorized"
    exp_data["verified_email"] = f"exp-{uuid.uuid4().hex[:6]}@gmail.com"
    exp_data["staged_credentials"] = {"client_id": "cid-exp", "refresh_token": "rt-exp", "access_token": "at-exp"}
    exp_data["expires_at"] = 1.0
    save_json_secret(_flow_store(), exp_ref, exp_data)

    # Expired authorized flow reports expired on status, returns null on active, and fails closed on callback/save
    assert browser.get(f"/api/accounts/oauth/callback/google?state={exp_state}&code=late-code").status_code == 400
    assert client.get(f"/api/accounts/oauth/flows/{s_exp['flow_id']}").json()["status"] == "expired"
    assert client.get("/api/accounts/oauth/active").json()["flow"] is None
    assert client.post("/api/accounts", json={"provider": "gmail", "oauth_flow_id": s_exp["flow_id"]}).status_code == 400


def test_unauthenticated_and_missing_csrf_are_rejected_and_real_urllib_transport_redacts_errors(monkeypatch):
    import io
    import json
    import urllib.error
    import urllib.request

    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "18765")

    unauth = TestClient(app)
    assert unauth.get("/api/accounts/oauth/metadata").status_code == 401
    assert unauth.get("/api/accounts/oauth/active").status_code == 401
    assert unauth.post("/api/accounts/oauth/start", json={"provider": "google"}).status_code == 401
    assert unauth.get("/api/accounts/oauth/flows/f1").status_code == 401
    assert unauth.post("/api/accounts/oauth/flows/f1/cancel").status_code == 401

    session_client, _csrf = _login_session_client()
    no_csrf_headers = {"X-CSRF-Token": ""}
    assert session_client.post("/api/accounts/oauth/start", json={"provider": "google"}, headers=no_csrf_headers).status_code == 403
    assert session_client.post("/api/accounts/oauth/flows/f1/cancel", headers=no_csrf_headers).status_code == 403

    # Exercise production default_urllib_token_post and urllib_json_request without set_oauth_http_hooks
    class _FakeResp:
        def __init__(self, payload: dict):
            self._raw = json.dumps(payload).encode("utf-8")
            self.headers = {"Content-Type": "application/json"}

        def read(self) -> bytes:
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    # 1) HTTPError redirect_uri_mismatch & invalid_client & URLError transport failure
    for mode, expected_snippet in [
        ("redirect_uri_mismatch", "redirect_uri_mismatch"),
        ("invalid_client", "invalid_client"),
        ("network_error", "令牌交换网络或服务错误"),
    ]:
        started = session_client.post(
            "/api/accounts/oauth/start",
            json={
                "provider": "google",
                "intent": "create",
                "client_type": "confidential",
                "client_id": "cid-urllib",
                "client_secret": "top-secret-client-value",
            },
        ).json()
        st = parse_qs(urlsplit(started["auth_url"]).query)["state"][0]

        def fake_urlopen(req, timeout=30, m=mode):
            if m in ("redirect_uri_mismatch", "invalid_client"):
                body = json.dumps({"error": m, "client_secret": "top-secret-client-value"}).encode("utf-8")
                raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))
            raise urllib.error.URLError("connection refused; client_secret=top-secret-client-value")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        cb = unauth.get(f"/api/accounts/oauth/callback/google?state={st}&code=urllib-code-{mode}")
        assert cb.status_code == 400
        assert "top-secret-client-value" not in cb.text
        fstatus = session_client.get(f"/api/accounts/oauth/flows/{started['flow_id']}").json()
        assert fstatus["status"] == "failed"
        assert expected_snippet in fstatus["error"]
        assert "top-secret-client-value" not in fstatus["error"]

    # 2) Full production urllib path success (token POST + users.getProfile GET)
    s_ok = session_client.post(
        "/api/accounts/oauth/start",
        json={"provider": "google", "intent": "create", "client_id": "cid-urllib-ok"},
    ).json()
    st_ok = parse_qs(urlsplit(s_ok["auth_url"]).query)["state"][0]

    def fake_urlopen_ok(req, timeout=30):
        if "oauth2.googleapis.com/token" in req.full_url:
            return _FakeResp({
                "access_token": "urllib-access-ok",
                "refresh_token": "urllib-refresh-ok",
                "scope": "https://www.googleapis.com/auth/gmail.modify",
                "expires_in": 3600,
            })
        assert req.get_header("Authorization") == "Bearer urllib-access-ok"
        return _FakeResp({"emailAddress": "urllib-verified@gmail.com"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen_ok)
    cb_ok = unauth.get(f"/api/accounts/oauth/callback/google?state={st_ok}&code=urllib-code-ok")
    assert cb_ok.status_code == 200
    view_ok = session_client.get(f"/api/accounts/oauth/flows/{s_ok['flow_id']}").json()
    assert view_ok["status"] == "authorized"
    assert view_ok["verified_email"] == "urllib-verified@gmail.com"


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL") or os.environ.get("KKMAIL_TEST_ELECTRON") != "1",
    reason="requires owned PG runtime, compiled SPA and explicit Electron integration mode",
)
def test_electron_real_spa_cookie_free_loopback_callback_and_save(monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    import socket
    import subprocess
    import threading
    import urllib.request

    import uvicorn

    class Supplier(BaseHTTPRequestHandler):
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            assert form["grant_type"] == ["authorization_code"]
            assert form["code"] == ["electron-code"]
            assert form["code_verifier"]
            assert "client_secret" not in form
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({
                "access_token": "electron-access", "refresh_token": "electron-refresh",
                "scope": "https://www.googleapis.com/auth/gmail.modify", "expires_in": 3600,
            }).encode())

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer electron-access"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"emailAddress":"electron@gmail.com"}')

        def log_message(self, *_args):
            pass

    supplier = ThreadingHTTPServer(("127.0.0.1", 0), Supplier)
    supplier_thread = threading.Thread(target=supplier.serve_forever, daemon=True)
    supplier_thread.start()
    real_urlopen = urllib.request.urlopen

    def routed_urlopen(req, *args, **kwargs):
        if urlsplit(req.full_url).hostname in ("oauth2.googleapis.com", "gmail.googleapis.com"):
            req = urllib.request.Request(
                f"http://127.0.0.1:{supplier.server_port}/", data=req.data,
                headers=dict(req.header_items()), method=req.method,
            )
        return real_urlopen(req, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", routed_urlopen)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", str(port))
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="warning"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        env = {**os.environ, "KKMAIL_OAUTH_TEST_ORIGIN": f"http://127.0.0.1:{port}",
               "KKMAIL_OAUTH_TEST_PASSWORD": TEST_LOGIN_PASSWORD}
        result = subprocess.run(
            ["node", "src/desktop/oauth_integration.test.js"],
            cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with get_session_factory()() as db:
            account = db.scalar(select(Account).where(Account.email == "electron@gmail.com"))
            assert account is not None
            saved = load_json_secret(get_credential_store(), account.credential_ref)
            assert saved["refresh_token"] == "electron-refresh"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        supplier.shutdown()
        supplier.server_close()
        supplier_thread.join(timeout=5)

@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_same_code_concurrently_submitted_to_distinct_flows_is_claimed_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    client, _ = _login_session_client()
    calls = []
    set_oauth_http_hooks(
        token_post=lambda _url, form: (calls.append(form["code"]), {
            "access_token": "at", "refresh_token": "rt",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
        })[1],
        profile_get=lambda _url, _at: {"emailAddress": "race@gmail.com"},
    )
    for attempt in range(5):
        states = []
        for _ in range(2):
            started = client.post("/api/accounts/oauth/start", json={"client_id": "race-client"})
            assert started.status_code == 200
            states.append(parse_qs(urlsplit(started.json()["auth_url"]).query)["state"][0])
        barrier = Barrier(2)
        def callback(state):
            barrier.wait(timeout=5)
            return TestClient(app, raise_server_exceptions=False).get(
                f"/api/accounts/oauth/callback/google?state={state}&code=race-code-{attempt}"
            ).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(callback, states)) == [200, 400]
        assert calls.count(f"race-code-{attempt}") == 1


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_reauthorization_and_normal_group_move_share_lock_order_pg(monkeypatch):
    from mail_core.accounts import oauth_flow, service
    from mail_core.accounts.credentials import get_credential_store
    from mail_core.mail.application.accounts import create_account_app, update_account_app, create_group_app
    from mail_core.security.auth import AuthPrincipal

    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    principal = AuthPrincipal(via='api_key')
    a = create_account_app(email='review-lock@gmail.com', provider='gmail',
                           config={'oauth_client_type': 'public'}, credentials={'client_id':'cid','refresh_token':'rt'})
    group = create_group_app(name='review-group')
    started = oauth_flow.start_oauth_flow(principal, intent='reauthorize', account_id=uuid.UUID(a.id))
    state = parse_qs(urlsplit(started['auth_url']).query)['state'][0]
    oauth_flow.set_oauth_http_hooks(token_post=lambda *_a: {'access_token':'new-at','refresh_token':'new-rt',
        'scope':oauth_flow.GOOGLE_REQUIRED_SCOPE}, profile_get=lambda *_a:{'emailAddress':a.email})
    assert oauth_flow.complete_oauth_callback('google',state=state,code='review-lock-code')[0]
    account_locked = Event()
    sidebar_locked = Event()
    original_consume = oauth_flow.consume_oauth_flow_for_reauthorize
    original_lock = service._lock_sidebar_layout

    def wrapped_consume(*args, **kwargs):
        account_locked.set()
        assert sidebar_locked.wait(5)
        return original_consume(*args, **kwargs)

    def wrapped_lock(session):
        original_lock(session)
        sidebar_locked.set()

    monkeypatch.setattr(oauth_flow, 'consume_oauth_flow_for_reauthorize', wrapped_consume)
    monkeypatch.setattr(service, '_lock_sidebar_layout', wrapped_lock)

    def authorize():
        try:
            update_account_app(uuid.UUID(a.id), group_id=uuid.UUID(group.id),
                               oauth_flow_id=started['flow_id'], principal=principal)
            return 'ok'
        except Exception as exc:
            return type(exc).__name__ + ': ' + str(exc).splitlines()[0]

    def move():
        assert account_locked.wait(5)
        try:
            update_account_app(uuid.UUID(a.id), group_id=uuid.UUID(group.id))
            return 'ok'
        except Exception as exc:
            return type(exc).__name__ + ': ' + str(exc).splitlines()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(authorize)
        two = pool.submit(move)
        results = [one.result(10),two.result(10)]
    assert results == ['ok', 'ok'], results
    with get_session_factory()() as db:
        row = db.get(Account, uuid.UUID(a.id))
        assert row.group_id == uuid.UUID(group.id)
        assert load_json_secret(get_credential_store(), row.credential_ref)['refresh_token'] == 'new-rt'



@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_clearing_old_active_pointer_cannot_erase_concurrent_start_pg(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from mail_core.accounts import oauth_flow
    from mail_core.security.auth import AuthPrincipal

    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    principal = AuthPrincipal(via="api_key")
    old = oauth_flow.start_oauth_flow(principal, client_id="pointer-client")
    snapshot_read, new_started, cleaner_started = Event(), Event(), Event()
    original_load = oauth_flow.load_json_secret
    sess_key = oauth_flow.session_binding_key(principal)

    def observed_load(store, ref):
        data = original_load(store, ref)
        if current_thread().name.startswith("old-cleaner") and ref == f"oauth_active:{sess_key}":
            snapshot_read.set()
            assert new_started.wait(5)
        return data

    monkeypatch.setattr(oauth_flow, "load_json_secret", observed_load)
    def clear_old():
        cleaner_started.set()
        oauth_flow._clear_matching_active_pointer(oauth_flow._flow_store(), sess_key, old["flow_id"])

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="old-cleaner") as pool:
        future = pool.submit(clear_old)
        assert cleaner_started.wait(5)
        # If cleanup uses a separate read, force the new start into its read/delete gap.
        # Atomic cleanup has no unlocked snapshot and may finish before the new start.
        snapshot_read.wait(0.2)
        new = oauth_flow.start_oauth_flow(principal, client_id="pointer-client")
        new_started.set()
        future.result(5)
    assert oauth_flow.get_active_oauth_flow(principal)["flow_id"] == new["flow_id"]


def test_non_object_token_response_becomes_actionable_failure(api_client, monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    started = api_client.post("/api/accounts/oauth/start", json={"client_id": "bad-json-client"}).json()
    state = parse_qs(urlsplit(started["auth_url"]).query)["state"][0]
    set_oauth_http_hooks(token_post=lambda *_args: ["unexpected-array"])
    callback = TestClient(app, raise_server_exceptions=False).get(
        f"/api/accounts/oauth/callback/google?state={state}&code=bad-json-code"
    )
    assert callback.status_code == 400
    status = api_client.get(f"/api/accounts/oauth/flows/{started['flow_id']}").json()
    assert status["status"] == "failed"
    assert "响应格式" in status["error"]


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_oauth_create_and_group_reauthorization_share_lock_order_pg(monkeypatch):
    from mail_core.accounts import oauth_flow, service
    from mail_core.accounts.credentials import get_credential_store
    from mail_core.mail.application import accounts as application
    from mail_core.security.auth import AuthPrincipal

    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    principal = AuthPrincipal(via='api_key')
    account = application.create_account_app(email='old-lock@gmail.com',provider='gmail',
        config={'oauth_client_type':'public'},credentials={'client_id':'cid','refresh_token':'old-rt'})
    group = application.create_group_app(name='new-group')
    oauth_flow.set_oauth_http_hooks(token_post=lambda _url, form:{'access_token':form['code'],
        'refresh_token':'new-rt','scope':oauth_flow.GOOGLE_REQUIRED_SCOPE},
        profile_get=lambda _url, at:{'emailAddress':'new-lock@gmail.com' if at=='create-code' else account.email})
    create_flow = oauth_flow.start_oauth_flow(principal,client_id='cid')
    state = parse_qs(urlsplit(create_flow['auth_url']).query)['state'][0]
    assert oauth_flow.complete_oauth_callback('google',state=state,code='create-code')[0]
    edit_flow = oauth_flow.start_oauth_flow(principal,intent='reauthorize',account_id=uuid.UUID(account.id))
    state = parse_qs(urlsplit(edit_flow['auth_url']).query)['state'][0]
    assert oauth_flow.complete_oauth_callback('google',state=state,code='edit-code')[0]

    pointer_locked = Event()
    sidebar_locked = Event()
    original_create = application.create_account
    original_sidebar = service._lock_sidebar_layout

    def create_after_consume(*args, **kwargs):
        pointer_locked.set()
        assert sidebar_locked.wait(5)
        return original_create(*args, **kwargs)

    def sidebar(session):
        original_sidebar(session)
        sidebar_locked.set()

    monkeypatch.setattr(application,'create_account',create_after_consume)
    monkeypatch.setattr(service,'_lock_sidebar_layout',sidebar)

    def create():
        try:
            application.create_account_app(email='',provider='gmail',oauth_flow_id=create_flow['flow_id'],principal=principal)
            return 'ok'
        except Exception as exc:
            return type(exc).__name__+': '+str(exc).splitlines()[0]

    def reauthorize():
        assert pointer_locked.wait(5)
        try:
            application.update_account_app(uuid.UUID(account.id),group_id=uuid.UUID(group.id),
                oauth_flow_id=edit_flow['flow_id'],principal=principal)
            return 'ok'
        except Exception as exc:
            return type(exc).__name__+': '+str(exc).splitlines()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(create)
        b=pool.submit(reauthorize)
        results=[a.result(10),b.result(10)]
    assert results == ['ok', 'ok'], results
    with get_session_factory()() as db:
        original = db.get(Account, uuid.UUID(account.id))
        created = db.scalar(select(Account).where(Account.email == 'new-lock@gmail.com'))
        assert created is not None and created.id != original.id
        assert original.group_id == uuid.UUID(group.id)
        assert load_json_secret(get_credential_store(), original.credential_ref)['refresh_token'] == 'new-rt'
        assert load_json_secret(get_credential_store(), created.credential_ref)['refresh_token'] == 'new-rt'
