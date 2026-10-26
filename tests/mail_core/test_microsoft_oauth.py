"""Microsoft code/device grants through real account APIs and owned PostgreSQL."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.accounts import oauth_flow
from mail_core.accounts.credentials import get_credential_store, load_json_secret
from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account
from mail_core.providers.http import ProviderHttpError
from tests.mail_core.conftest import TEST_LOGIN_PASSWORD

SCOPE = 'https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read'


def login():
    client = TestClient(app)
    response = client.post('/api/auth/login', json={'password': TEST_LOGIN_PASSWORD})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return client


def start(client, **extra):
    response = client.post('/api/accounts/oauth/start', json={
        'provider': 'microsoft', 'client_id': 'own-microsoft-client', **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def authorize(started, code='ms-code'):
    state = parse_qs(urlsplit(started['auth_url']).query)['state'][0]
    return TestClient(app).get(f'/api/accounts/oauth/callback/microsoft?state={state}&code={code}')


def successful_hooks(email, user_id='ms-user-1', **token_extra):
    oauth_flow.set_oauth_http_hooks(
        token_post=lambda _url, _form: {'access_token': 'opaque-ms-access',
            'refresh_token': 'ms-refresh', 'scope': SCOPE, 'expires_in': 3600, **token_extra},
        profile_get=lambda url, _at: {'id': user_id, 'mail': email} if '/me?' in url else {'id': 'inbox-id'},
    )


def test_microsoft_metadata_reports_effective_client_id(api_client, monkeypatch):
    # The simplified frontend flow authorizes with the client id the
    # metadata reports, so the authorize step and the backend exchange
    # step (which resolves MICROSOFT_CLIENT_ID env overrides) always use
    # the same id.
    from mail_core.accounts.microsoft_oauth import DEFAULT_MICROSOFT_CLIENT_ID

    monkeypatch.delenv('MICROSOFT_CLIENT_ID', raising=False)
    metadata = api_client.get('/api/accounts/oauth/metadata?provider=microsoft')
    assert metadata.status_code == 200
    assert metadata.json()['microsoft_client_id'] == DEFAULT_MICROSOFT_CLIENT_ID

    monkeypatch.setenv('MICROSOFT_CLIENT_ID', 'env-override-client')
    metadata = api_client.get('/api/accounts/oauth/metadata?provider=microsoft')
    assert metadata.status_code == 200
    assert metadata.json()['microsoft_client_id'] == 'env-override-client'


def test_microsoft_metadata_code_request_and_device_without_callback(api_client, monkeypatch):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    monkeypatch.setenv('MAIL_CORE_PORT', '29654')
    metadata = api_client.get('/api/accounts/oauth/metadata?provider=microsoft')
    assert metadata.status_code == 200
    assert metadata.json()['redirect_uri'] == 'http://localhost:29654/api/accounts/oauth/callback/microsoft'
    flow = start(api_client, tenant='consumers')
    params = parse_qs(urlsplit(flow['auth_url']).query)
    assert urlsplit(flow['auth_url']).hostname == 'login.microsoftonline.com'
    assert urlsplit(flow['auth_url']).path == '/consumers/oauth2/v2.0/authorize'
    assert params['response_type'] == ['code'] and params['code_challenge_method'] == ['S256']
    assert set(params['scope'][0].split()) == {'https://graph.microsoft.com/Mail.ReadWrite',
        'https://graph.microsoft.com/User.Read', 'offline_access'}
    monkeypatch.delenv('KKMAIL_SIDECAR')
    monkeypatch.delenv('MAIL_CORE_PUBLIC_ORIGIN', raising=False)
    forms = []
    oauth_flow.set_oauth_http_hooks(token_post=lambda url, form: (forms.append((url, form)), {
        'device_code': 'private-long-device', 'user_code': 'ABCD-EFGH',
        'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 900, 'interval': 5,
    })[1])
    device = start(api_client, method='device_code', client_type='public', tenant='organizations')
    assert device['user_code'] == 'ABCD-EFGH'
    assert device['verification_uri'] == 'https://microsoft.com/devicelogin'
    assert device['redirect_uri'] == ''
    assert 'private-long-device' not in str(device)
    assert forms[0][0].endswith('/organizations/oauth2/v2.0/devicecode')
    assert set(forms[0][1]) == {'client_id', 'scope'}
    assert not {'state', 'code_verifier', 'client_secret'} & set(forms[0][1])


@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
def test_microsoft_create_identity_duplicate_reauthorize_and_legacy_graph_pg(monkeypatch):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    client = login()
    email = f'ms-{uuid.uuid4().hex[:8]}@outlook.com'
    successful_hooks(email)
    created_flow = start(client, tenant='consumers')
    callback = authorize(created_flow)
    assert callback.status_code == 200 and 'Microsoft' in callback.text
    # Callback stages only; no account before explicit confirmation.
    with get_session_factory()() as db:
        assert db.scalar(select(Account.id).where(Account.email == email)) is None
    saved = client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': created_flow['flow_id']})
    assert saved.status_code == 200, saved.text
    account_id = saved.json()['id']
    with get_session_factory()() as db:
        row = db.get(Account, uuid.UUID(account_id))
        assert row.email == email and row.config['microsoft_user_id'] == 'ms-user-1'
        assert row.config['oauth_tenant'] == 'consumers'
        ref = row.credential_ref
    creds = load_json_secret(get_credential_store(), ref)
    assert creds['token_uri'].endswith('/consumers/oauth2/v2.0/token')
    assert creds['refresh_token'] == 'ms-refresh'
    assert client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': created_flow['flow_id']}).status_code in (400, 404)
    duplicate = start(client, tenant='consumers')
    assert authorize(duplicate, 'duplicate-ms-code').status_code == 400

    # Same email with a different Microsoft user ID cannot replace the original.
    successful_hooks(email, user_id='someone-else')
    edit = start(client, intent='reauthorize', account_id=account_id)
    assert authorize(edit, 'wrong-id-code').status_code == 400
    assert load_json_secret(get_credential_store(), ref) == creds
    for patch in ({'tenant': 'organizations'}, {'client_id': 'another-client'}):
        rejected = client.post('/api/accounts/oauth/start', json={'provider': 'microsoft',
            'intent': 'reauthorize', 'account_id': account_id, **patch})
        assert rejected.status_code == 400

    # Legacy Graph account without remote ID can reauthorize even with revoked old tokens.
    legacy_email = f'legacy-{uuid.uuid4().hex[:8]}@example.com'
    legacy = client.post('/api/accounts', json={'provider': 'graph', 'email': legacy_email,
        'credentials': {'client_id': 'own-microsoft-client', 'refresh_token': 'revoked-old-token',
            'token_uri': 'https://login.microsoftonline.com/organizations/oauth2/v2.0/token'}})
    assert legacy.status_code == 200
    legacy_id = legacy.json()['id']
    group = client.post('/api/groups', json={'name': 'preserved-ms-group'}).json()
    client.patch(f'/api/accounts/{legacy_id}', json={'group_id': group['id'], 'sync_enabled': False})
    successful_hooks(legacy_email, user_id='legacy-real-id')
    legacy_flow = start(client, intent='reauthorize', account_id=legacy_id)
    assert '/organizations/' in legacy_flow['auth_url']
    assert authorize(legacy_flow, 'legacy-code').status_code == 200
    updated = client.patch(f'/api/accounts/{legacy_id}', json={'oauth_flow_id': legacy_flow['flow_id']})
    assert updated.status_code == 200, updated.text
    assert updated.json()['group_id'] == group['id'] and updated.json()['sync_enabled'] is False
    with get_session_factory()() as db:
        assert db.get(Account, uuid.UUID(legacy_id)).config['microsoft_user_id'] == 'legacy-real-id'


@pytest.mark.parametrize('profile,token,expected', [
    ({'id': 'u', 'mail': None, 'userPrincipalName': 'unverified@example.com'}, {}, '邮箱'),
    ({'mail': 'real@outlook.com'}, {}, '身份'),
    ({'id': 'u', 'mail': 'real@outlook.com'}, {'refresh_token': ''}, 'Refresh Token'),
    ({'id': 'u', 'mail': 'real@outlook.com'}, {'scope': 'User.Read'}, 'Mail.ReadWrite'),
])
def test_microsoft_identity_and_offline_permission_fail_closed(api_client, monkeypatch, profile, token, expected):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    oauth_flow.set_oauth_http_hooks(
        token_post=lambda *_args: {'access_token': 'opaque-token', 'refresh_token': 'rt', 'scope': SCOPE, **token},
        profile_get=lambda *_args: profile,
    )
    flow = start(api_client)
    assert authorize(flow).status_code == 400
    status = api_client.get(f"/api/accounts/oauth/flows/{flow['flow_id']}").json()
    assert status['status'] == 'failed' and expected in status['error']


def test_device_poll_interval_slowdown_owner_csrf_cancel_and_expiry(monkeypatch):
    clock = [10000.0]
    monkeypatch.setattr(oauth_flow, 'time', SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.delenv('KKMAIL_SIDECAR', raising=False)
    monkeypatch.delenv('MAIL_CORE_PUBLIC_ORIGIN', raising=False)
    client, other = login(), login()
    calls = []
    responses = ['authorization_pending', 'slow_down', 'authorization_pending']
    def post(url, form):
        calls.append((url, dict(form)))
        if url.endswith('/devicecode'):
            return {'device_code': 'long-secret-never-return', 'user_code': 'WXYZ-1234',
                'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 40, 'interval': 5}
        return {'error': responses.pop(0)}
    oauth_flow.set_oauth_http_hooks(token_post=post)
    flow = start(client, method='device_code')
    endpoint = f"/api/accounts/oauth/flows/{flow['flow_id']}"
    assert flow['expires_at'] == 10040
    assert other.post(endpoint + '/poll').status_code == 403
    assert client.post(endpoint + '/poll', headers={'X-CSRF-Token': ''}).status_code == 403
    assert client.get(endpoint).status_code == 200
    assert len(calls) == 1
    early = client.post(endpoint + '/poll')
    assert early.status_code == 429
    assert early.headers['Retry-After'] == '5'
    assert len(calls) == 1
    clock[0] += 5
    assert client.post(endpoint + '/poll').json()['status'] == 'pending'
    assert len(calls) == 2 and calls[-1][1]['grant_type'] == 'urn:ietf:params:oauth:grant-type:device_code'
    clock[0] += 5
    assert client.post(endpoint + '/poll').json()['status'] == 'pending'
    assert len(calls) == 3
    clock[0] += 5
    early = client.post(endpoint + '/poll')
    assert early.status_code == 429
    assert early.headers['Retry-After'] == '5'
    assert len(calls) == 3  # slow_down extended interval to ten seconds
    clock[0] += 5
    client.post(endpoint + '/poll')
    assert len(calls) == 4
    assert 'long-secret-never-return' not in client.get(endpoint).text
    assert client.post(endpoint + '/cancel').status_code == 200
    clock[0] += 10
    assert client.post(endpoint + '/poll').status_code == 404
    assert len(calls) == 4
    # Expiry is capped locally, no late request or result may authorize.
    flow2 = start(client, method='device_code')
    clock[0] += 41
    assert client.post(f"/api/accounts/oauth/flows/{flow2['flow_id']}/poll").json()['status'] == 'expired'
    assert len(calls) == 5


@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
def test_device_concurrent_poll_and_save_use_same_identity_guards_pg(monkeypatch):
    clock = [20000.0]
    monkeypatch.setattr(oauth_flow, 'time', SimpleNamespace(time=lambda: clock[0]))
    client = login()
    exchanges = []
    email = f'device-{uuid.uuid4().hex[:8]}@outlook.com'
    def post(url, form):
        if url.endswith('/devicecode'):
            return {'device_code': 'private-device-code', 'user_code': 'GOOD-CODE',
                'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 900, 'interval': 5}
        exchanges.append(dict(form))
        return {'access_token': 'opaque-success', 'refresh_token': 'device-refresh', 'scope': SCOPE}
    oauth_flow.set_oauth_http_hooks(token_post=post,
        profile_get=lambda url, _at: {'id': 'device-user', 'mail': email} if '/me?' in url else {'id': 'inbox'})
    flow = start(client, method='device_code', tenant='consumers')
    assert flow['expires_at'] == 20600
    clock[0] += 5
    barrier = Barrier(2)
    def poll(_index):
        sibling = TestClient(app)
        sibling.cookies.update(client.cookies)
        sibling.headers.update(client.headers)
        barrier.wait(5)
        return sibling.post(f"/api/accounts/oauth/flows/{flow['flow_id']}/poll")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(poll, range(2)))
    assert all(r.status_code == 200 and r.json()['status'] == 'authorized' for r in results)
    assert len(exchanges) == 1
    saved = client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': flow['flow_id']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['email'] == email
    assert client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': flow['flow_id']}).status_code in (400, 404)


@pytest.mark.parametrize('verification_uri', ['https://evil.example/devicelogin',
    'http://microsoft.com/devicelogin', 'https://microsoft.com/devicelogin?code=hidden'])
def test_device_untrusted_verification_url_is_rejected(api_client, monkeypatch, verification_uri):
    monkeypatch.delenv('KKMAIL_SIDECAR', raising=False)
    oauth_flow.set_oauth_http_hooks(token_post=lambda *_args: {'device_code': 'secret',
        'user_code': 'ABCD', 'verification_uri': verification_uri, 'expires_in': 60, 'interval': 5})
    result = api_client.post('/api/accounts/oauth/start', json={'provider': 'microsoft',
        'method': 'device_code', 'client_id': 'own-client'})
    assert result.status_code == 400
    assert 'evil.example' not in result.text

@pytest.mark.skipif(
    not os.environ.get('MAIL_CORE_DATABASE_URL') or os.environ.get('KKMAIL_TEST_ELECTRON') != '1',
    reason='requires owned PG, production SPA and explicit Electron integration mode',
)
def test_microsoft_electron_dynamic_localhost_and_cookie_free_callback_pg(monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    import socket
    import subprocess
    import threading
    import urllib.request
    import uvicorn

    forms = []
    class Supplier(BaseHTTPRequestHandler):
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            forms.append(form)
            assert form['code_verifier'] and form['grant_type'] == ['authorization_code']
            assert urlsplit(form['redirect_uri'][0]).hostname == 'localhost'
            assert 'client_secret' not in form
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'access_token': 'opaque-electron-ms', 'refresh_token': 'electron-ms-refresh',
                'scope': SCOPE, 'expires_in': 3600}).encode())
        def do_GET(self):
            assert self.headers['Authorization'] == 'Bearer opaque-electron-ms'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'id': 'electron-ms-user', 'mail': 'electron@outlook.com'}
                if '/me?' in self.path else {'id': 'mailbox-inbox'}).encode())
        def log_message(self, *_args):
            pass

    supplier = ThreadingHTTPServer(('127.0.0.1', 0), Supplier)
    supplier_thread = threading.Thread(target=supplier.serve_forever, daemon=True)
    supplier_thread.start()
    original_open = urllib.request.urlopen
    def route(req, *args, **kwargs):
        if urlsplit(req.full_url).hostname in ('login.microsoftonline.com', 'graph.microsoft.com'):
            parsed = urlsplit(req.full_url)
            target = f'http://127.0.0.1:{supplier.server_port}{parsed.path}' + (f'?{parsed.query}' if parsed.query else '')
            req = urllib.request.Request(target, data=req.data, headers=dict(req.header_items()), method=req.method)
        return original_open(req, *args, **kwargs)
    monkeypatch.setattr(urllib.request, 'urlopen', route)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    monkeypatch.setenv('MAIL_CORE_PORT', str(port))
    server = uvicorn.Server(uvicorn.Config(app, lifespan='off', access_log=False, log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        result = subprocess.run(['node', 'src/desktop/oauth_integration.test.js'],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
            env={**os.environ, 'KKMAIL_OAUTH_TEST_ORIGIN': f'http://127.0.0.1:{port}',
                 'KKMAIL_OAUTH_TEST_PASSWORD': TEST_LOGIN_PASSWORD, 'KKMAIL_OAUTH_TEST_PROVIDER': 'microsoft'})
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(forms) == 1
        with get_session_factory()() as db:
            row = db.scalar(select(Account).where(Account.email == 'electron@outlook.com'))
            assert row is not None and row.config['microsoft_user_id'] == 'electron-ms-user'
            assert load_json_secret(get_credential_store(), row.credential_ref)['refresh_token'] == 'electron-ms-refresh'
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        supplier.shutdown()
        supplier.server_close()
        supplier_thread.join(5)

@pytest.mark.parametrize('error,description,expected', [
    ('authorization_declined', '', '拒绝'), ('expired_token', '', '失效'),
    ('invalid_client', 'AADSTS7000218 secret missing; client_secret=do-not-echo', '公共客户端'),
    ('access_denied', 'AADSTS65001 admin consent required', '管理员'),
    ('invalid_request', 'AADSTS50011', '回调地址'),
    ('unauthorized_client', 'AADSTS700016', '租户'),
])
def test_microsoft_errors_are_actionable_and_never_echo_secrets(api_client, monkeypatch, error, description, expected):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    flow = start(api_client)
    oauth_flow.set_oauth_http_hooks(token_post=lambda *_args: {
        'error': error, 'error_description': description + ' access_token=do-not-echo',
    })
    assert authorize(flow).status_code == 400
    status = api_client.get(f"/api/accounts/oauth/flows/{flow['flow_id']}")
    assert expected in status.json()['error'] and 'do-not-echo' not in status.text
    assert status.headers['Cache-Control'] == 'no-store'


def test_device_http_429_retry_after_late_success_and_session_epoch(monkeypatch):
    clock = [30000.0]
    monkeypatch.setattr(oauth_flow, 'time', SimpleNamespace(time=lambda: clock[0]))
    client = login()
    requests = []
    mode = ['rate-limit']
    def post(url, form):
        requests.append(dict(form))
        if url.endswith('/devicecode'):
            return {'device_code': 'private-code', 'user_code': 'ABCD-EFGH',
                'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 60, 'interval': 5}
        if mode[0] == 'rate-limit':
            raise ProviderHttpError('provider body secret', status=429, body='secret body', headers={'Retry-After': '30'})
        clock[0] += 61  # Provider responds after the local/remote deadline.
        return {'access_token': 'late-token', 'refresh_token': 'late-refresh', 'scope': SCOPE}
    oauth_flow.set_oauth_http_hooks(token_post=post,
        profile_get=lambda *_args: {'id': 'never-accepted', 'mail': 'late@outlook.com'})
    flow = start(client, method='device_code')
    endpoint = f"/api/accounts/oauth/flows/{flow['flow_id']}/poll"
    clock[0] += 5
    assert client.post(endpoint).json()['status'] == 'pending'
    clock[0] += 29
    client.post(endpoint)
    assert len(requests) == 2
    mode[0] = 'late-success'
    clock[0] += 1
    result = client.post(endpoint)
    assert result.json()['status'] == 'expired'
    assert 'late-token' not in result.text and 'private-code' not in result.text
    fresh = start(client, method='device_code')
    assert client.post('/api/auth/logout').status_code == 200
    logged_again = login()
    assert logged_again.post(f"/api/accounts/oauth/flows/{fresh['flow_id']}/poll").status_code == 403
    assert len(requests) == 4


def test_device_registration_failure_has_configuration_help(api_client, monkeypatch):
    oauth_flow.set_oauth_http_hooks(token_post=lambda *_args: (_ for _ in ()).throw(
        ProviderHttpError('raw secret', status=400, body='{"error":"unauthorized_client","error_description":"AADSTS7000218 client_secret=hidden"}')))
    result = api_client.post('/api/accounts/oauth/start', json={
        'provider': 'microsoft', 'method': 'device_code', 'client_id': 'own-id'})
    assert result.status_code == 400
    assert '公共客户端' in result.text and 'hidden' not in result.text

@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
@pytest.mark.parametrize('field', ['oauth_tenant', 'microsoft_user_id'])
def test_malformed_new_graph_config_is_rejected_before_commit(api_client, field):
    response = api_client.post('/api/accounts', json={'provider': 'graph', 'email': 'typed@outlook.com',
        'config': {field: ['not-a-string']}, 'credentials': {'client_id': 'cid', 'refresh_token': 'rt'}})
    assert response.status_code == 400
    assert api_client.get('/api/accounts').json()['accounts'] == []


def test_production_token_transport_preserves_rate_limit_headers(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from mail_core.providers.oauth import default_urllib_token_post
    def limited(req, **kwargs):
        raise urllib.error.HTTPError(req.full_url, 429, 'limited', {'Retry-After': '30'}, io.BytesIO(b'{}'))
    monkeypatch.setattr(urllib.request, 'urlopen', limited)
    with pytest.raises(ProviderHttpError) as caught:
        default_urllib_token_post('POST', 'https://login.microsoftonline.com/common/oauth2/v2.0/token', {})
    assert caught.value.status == 429 and caught.value.headers['retry-after'] == '30'

@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
def test_device_reauthorization_checks_identity_and_preserves_original_on_failure_pg(monkeypatch):
    clock = [40000.0]
    monkeypatch.setattr(oauth_flow, 'time', SimpleNamespace(time=lambda: clock[0]))
    client = login()
    created = client.post('/api/accounts', json={'provider': 'graph', 'email': 'device-edit@outlook.com',
        'config': {'microsoft_user_id': 'expected-user', 'oauth_tenant': 'common'},
        'credentials': {'client_id': 'own-microsoft-client', 'refresh_token': 'original-refresh'}})
    assert created.status_code == 200
    account_id = created.json()['id']
    with get_session_factory()() as db:
        ref = db.get(Account, uuid.UUID(account_id)).credential_ref
    identity = ['unexpected-user']
    def post(url, _form):
        if url.endswith('/devicecode'):
            return {'device_code': 'private', 'user_code': 'SHOW-CODE',
                'verification_uri': 'https://microsoft.com/devicelogin', 'expires_in': 600, 'interval': 5}
        return {'access_token': 'opaque-reauthorized', 'refresh_token': 'new-device-refresh', 'scope': SCOPE}
    oauth_flow.set_oauth_http_hooks(token_post=post,
        profile_get=lambda url, _at: {'id': identity[0], 'mail': 'device-edit@outlook.com'} if '/me?' in url else {'id': 'inbox'})
    wrong = start(client, method='device_code', intent='reauthorize', account_id=account_id)
    clock[0] += 5
    assert client.post(f"/api/accounts/oauth/flows/{wrong['flow_id']}/poll").json()['status'] == 'failed'
    assert load_json_secret(get_credential_store(), ref)['refresh_token'] == 'original-refresh'
    identity[0] = 'expected-user'
    good = start(client, method='device_code', intent='reauthorize', account_id=account_id)
    clock[0] += 5
    assert client.post(f"/api/accounts/oauth/flows/{good['flow_id']}/poll").json()['status'] == 'authorized'
    assert load_json_secret(get_credential_store(), ref)['refresh_token'] == 'original-refresh'
    saved = client.patch(f'/api/accounts/{account_id}', json={'oauth_flow_id': good['flow_id']})
    assert saved.status_code == 200
    assert load_json_secret(get_credential_store(), ref)['refresh_token'] == 'new-device-refresh'


def test_microsoft_callback_cross_provider_replay_and_missing_mailbox_fail_closed(api_client, monkeypatch):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    browser = TestClient(app)
    flow = start(api_client)
    state = parse_qs(urlsplit(flow['auth_url']).query)['state'][0]
    assert browser.post(f"/api/accounts/oauth/flows/{flow['flow_id']}/poll").status_code == 401
    successful_hooks('cross-provider@outlook.com')
    assert authorize(flow).status_code == 200
    assert authorize(flow).status_code == 400
    missing = start(api_client)
    oauth_flow.set_oauth_http_hooks(token_post=lambda *_args: {
        'access_token': 'opaque', 'refresh_token': 'rt', 'scope': SCOPE},
        profile_get=lambda url, _at: {'id': 'no-mailbox', 'mail': 'profile-only@example.com'} if '/me?' in url else {})
    assert authorize(missing, code='no-mailbox-code').status_code == 400
    assert '邮箱' in api_client.get(f"/api/accounts/oauth/flows/{missing['flow_id']}").json()['error']

@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
def test_verified_oauth_save_rejects_mixed_manual_credentials_without_consuming_result_pg(api_client, monkeypatch):
    monkeypatch.setenv('KKMAIL_SIDECAR', '1')
    successful_hooks('verified-only@outlook.com')
    flow = start(api_client)
    assert authorize(flow).status_code == 200
    mixed = api_client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': flow['flow_id'],
        'credentials': {'refresh_token': 'unverified-manual-token'}})
    assert mixed.status_code == 400
    saved = api_client.post('/api/accounts', json={'provider': 'graph', 'oauth_flow_id': flow['flow_id']})
    assert saved.status_code == 200
    edit = start(api_client, intent='reauthorize', account_id=saved.json()['id'])
    assert authorize(edit, code='edit-mixed-code').status_code == 200
    mixed_edit = api_client.patch('/api/accounts/' + saved.json()['id'], json={'oauth_flow_id': edit['flow_id'],
        'credentials': {'refresh_token': 'unverified-manual-token'}})
    assert mixed_edit.status_code == 400
    assert api_client.patch('/api/accounts/' + saved.json()['id'], json={'oauth_flow_id': edit['flow_id']}).status_code == 200

@pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')
@pytest.mark.parametrize('provider', ['graph'])
def test_legacy_oauth_ordinary_save_and_group_move_do_not_require_new_secret_pg(api_client, provider):
    created = api_client.post('/api/accounts', json={'provider': provider, 'email': f'legacy-{provider}@example.com',
        'credentials': {'client_id': 'original-client', 'refresh_token': 'original-refresh'}})
    assert created.status_code == 200
    account_id = created.json()['id']
    group = api_client.post('/api/groups', json={'name': 'legacy-move'}).json()['id']
    with get_session_factory()() as db:
        ref = db.get(Account, uuid.UUID(account_id)).credential_ref
    original = load_json_secret(get_credential_store(), ref)
    for patch in ({}, {'group_id': group}):
        saved = api_client.patch('/api/accounts/' + account_id, json=patch)
        assert saved.status_code == 200
        assert saved.json()['oauth_client_type'] is None
        assert load_json_secret(get_credential_store(), ref) == original
    assert saved.json()['group_id'] == group
    # Explicit invalid upgrades still fail; the server validation was not weakened.
    rejected = api_client.patch('/api/accounts/' + account_id, json={'config': {'oauth_client_type': 'confidential'}})
    assert rejected.status_code == 400
    assert load_json_secret(get_credential_store(), ref) == original
