"""Real API/PG coverage for credential patch atomicity and redaction."""
import os
import uuid

import pytest
from sqlalchemy import select

from mail_core.accounts.credentials import DbCredentialStore, load_json_secret
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account

pytestmark = pytest.mark.skipif(not os.environ.get('MAIL_CORE_DATABASE_URL'), reason='PG required')


def test_named_credentials_patch_is_atomic_and_never_echoed(api_client):
    email = f'forms-{uuid.uuid4().hex}@example.test'
    response = api_client.post('/api/accounts', json={
        'email': email, 'provider': 'graph', 'config': {'provider_profile': 'microsoft'},
        'credentials': {'client_id': 'app', 'client_secret': 'saved-secret', 'refresh_token': 'saved-refresh'},
    })
    assert response.status_code == 200, response.text
    account_id = response.json()['id']
    for secret in ('saved-secret', 'saved-refresh'):
        assert secret not in response.text
    with get_session_factory()() as session:
        ref = session.scalar(select(Account.credential_ref).where(Account.email == email))
    patch = api_client.patch(f'/api/accounts/{account_id}', json={'credentials': {'refresh_token': 'new-refresh', 'client_secret': ''}})
    assert patch.status_code == 200, patch.text
    assert load_json_secret(DbCredentialStore(), ref) == {'client_id': 'app', 'client_secret': 'saved-secret', 'refresh_token': 'new-refresh'}
    failed = api_client.patch(f'/api/accounts/{account_id}', json={'config': {'oauth_client_type': 'confidential'}, 'credentials': {'refresh_token': 123}, 'display_name': 'must rollback'})
    assert failed.status_code == 400
    with get_session_factory()() as session:
        account = session.get(Account, uuid.UUID(account_id))
        assert account.display_name is None
    assert load_json_secret(DbCredentialStore(), ref)['refresh_token'] == 'new-refresh'


def test_api_rejects_microsoft_imap_and_invalid_new_credentials(api_client):
    response = api_client.post('/api/accounts', json={'email': 'new@outlook.com', 'provider': 'imap', 'config': {'imap_host': 'outlook.office365.com'}, 'credentials': {'password': 'private-password'}})
    assert response.status_code == 400
    assert 'private-password' not in response.text
    assert api_client.post('/api/accounts', json={'email': 'new@example.test', 'provider': 'graph', 'credentials': {}}).status_code == 400


def test_config_only_confidential_change_requires_stored_secret(api_client):
    email = f'public-{uuid.uuid4().hex}@example.test'
    created = api_client.post('/api/accounts', json={'email': email, 'provider': 'graph', 'credentials': {'client_id': 'app', 'refresh_token': 'r'}})
    assert created.status_code == 200
    aid = created.json()['id']
    result = api_client.patch(f'/api/accounts/{aid}', json={'config': {'oauth_client_type': 'confidential'}})
    assert result.status_code == 400
    with get_session_factory()() as session:
        assert not session.get(Account, uuid.UUID(aid)).config.get('oauth_client_type')


def test_two_token_clients_serialize_rotation_and_observe_credential_edit(api_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from mail_core.providers.oauth import OAuthTokenClient

    created = api_client.post('/api/accounts', json={'email': f'rotate-{uuid.uuid4().hex}@example.test', 'provider': 'graph', 'credentials': {'client_id': 'app', 'refresh_token': 'r'}})
    assert created.status_code == 200
    aid = created.json()['id']
    with get_session_factory()() as session:
        ref = session.get(Account, uuid.UUID(aid)).credential_ref
    calls = []
    def token_post(method, uri, form, headers):
        calls.append(dict(form))
        return {'access_token': 'new-access', 'refresh_token': 'rotated', 'expires_in': 3600}
    clients = [OAuthTokenClient(credential_ref=ref, store=DbCredentialStore(), provider='graph', http_post=token_post) for _ in range(2)]
    barrier = Barrier(2)
    def run(client):
        barrier.wait(timeout=5)
        return client.get_access_token()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, clients)) == ['new-access', 'new-access']
    assert len(calls) == 1
    assert api_client.patch(f'/api/accounts/{aid}', json={'credentials': {'refresh_token': 'edited'}}).status_code == 200
    assert clients[0].get_access_token() == 'new-access'
    assert calls[-1]['refresh_token'] == 'edited'


def test_invalid_imap_user_rejected_before_commit_and_accounts_list_remains_readable(api_client, monkeypatch):
    monkeypatch.setenv('MAIL_CORE_ALLOW_PRIVATE_HOSTS', '1')
    bad_create = api_client.post('/api/accounts', json={
        'email': f'bad-user-{uuid.uuid4().hex}@example.test',
        'provider': 'imap',
        'config': {'imap_host': 'imap.example.test', 'imap_user': ['invalid']},
        'credentials': {'password': 'secret-password'},
    })
    assert bad_create.status_code == 400
    assert 'secret-password' not in bad_create.text

    email = f'valid-imap-{uuid.uuid4().hex}@example.test'
    created = api_client.post('/api/accounts', json={
        'email': email,
        'provider': 'imap',
        'config': {'imap_host': 'imap.example.test', 'imap_user': 'custom-login'},
        'credentials': {'password': 'secret-password'},
    })
    assert created.status_code == 200, created.text
    aid = created.json()['id']
    assert created.json()['imap_config']['imap_user'] == 'custom-login'

    bad_patch = api_client.patch(f'/api/accounts/{aid}', json={
        'display_name': 'should-not-persist',
        'config': {'imap_host': 'imap.example.test', 'imap_user': ['invalid']},
    })
    assert bad_patch.status_code == 400
    with get_session_factory()() as session:
        acc = session.get(Account, uuid.UUID(aid))
        assert acc.display_name is None
        assert acc.config.get('imap_user') == 'custom-login'

    cleared = api_client.patch(f'/api/accounts/{aid}', json={
        'config': {'imap_host': 'imap.example.test', 'imap_user': ''},
    })
    assert cleared.status_code == 200, cleared.text
    assert 'imap_user' not in (cleared.json()['imap_config'] or {})

    listed = api_client.get('/api/accounts')
    assert listed.status_code == 200, listed.text
    assert any(item['id'] == aid for item in listed.json()['accounts'])
