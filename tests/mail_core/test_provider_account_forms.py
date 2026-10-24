"""Provider-aware connection contracts exercise account/provider production paths."""
import json
from types import SimpleNamespace

import pytest

from mail_core.accounts.connection import validate_connection, merge_credentials
from mail_core.accounts.credentials import DictCredentialStore
from mail_core.providers.factory import build_provider


@pytest.mark.parametrize('email,host', [
    ('x@outlook.com', 'imap.example.test'),
    ('x@HOTMAIL.com', 'imap.example.test'),
    ('x@company.test', 'Outlook.Office365.com.'),
    ('x@company.test', 'imap-mail.outlook.com'),
])
def test_microsoft_imap_is_rejected_before_connecting(email, host):
    with pytest.raises(ValueError, match='Microsoft'):
        validate_connection(email, 'imap', {'imap_host': host}, {'password': 'test-password'})
    account = SimpleNamespace(email=email, provider='imap', config={'imap_host': host}, credential_ref='test')
    with pytest.raises(ValueError, match='Microsoft'):
        build_provider(account, DictCredentialStore({'test': json.dumps({'password': 'test-password'})}))


def test_domain_suffix_does_not_block_unrelated_imap(monkeypatch):
    monkeypatch.setenv('MAIL_CORE_ALLOW_PRIVATE_HOSTS', '1')
    validate_connection('x@outlook.com.evil.test', 'imap', {'imap_host': 'imap.example.test'}, {'password': 'test-password'})


@pytest.mark.parametrize('credentials,field', [({}, 'password'), ({'password': 'ok', 'refresh_token': 'secret'}, 'refresh_token')])
def test_imap_rejects_missing_or_wrong_credentials(monkeypatch, credentials, field):
    monkeypatch.setenv('MAIL_CORE_ALLOW_PRIVATE_HOSTS', '1')
    with pytest.raises(ValueError, match=field):
        validate_connection('x@example.test', 'imap', {'imap_host': 'imap.example.test'}, credentials)


def test_partial_oauth_update_preserves_secrets_but_invalidates_access_cache():
    old = {'client_id': 'client', 'client_secret': 'saved-secret', 'refresh_token': 'old', 'access_token': 'cached', 'expires_at': 9999999999, 'legacy': 'preserved'}
    merged = merge_credentials('graph', old, {'refresh_token': 'replacement', 'client_secret': ''})
    assert merged == {'client_id': 'client', 'client_secret': 'saved-secret', 'refresh_token': 'replacement', 'legacy': 'preserved'}
    assert old['access_token'] == 'cached'


def test_provider_profile_and_client_type_are_validated(monkeypatch):
    monkeypatch.setenv('MAIL_CORE_ALLOW_PRIVATE_HOSTS', '1')
    with pytest.raises(ValueError, match='provider_profile'):
        validate_connection('x@example.test', 'imap', {'imap_host': 'mail.example.test', 'provider_profile': 'microsoft'}, {'password': 'p'})
    with pytest.raises(ValueError, match='client_secret'):
        validate_connection('x@example.test', 'graph', {'oauth_client_type': 'confidential'}, {'client_id': 'id', 'refresh_token': 'r'})
    with pytest.raises(ValueError, match='imap_port'):
        validate_connection('x@example.test', 'imap', {'imap_host': 'mail.example.test', 'imap_port': 65536}, {'password': 'p'})


def test_invalid_profile_and_imap_user_types_are_validation_errors(monkeypatch):
    monkeypatch.setenv('MAIL_CORE_ALLOW_PRIVATE_HOSTS', '1')
    with pytest.raises(ValueError, match='provider_profile'):
        validate_connection('a@example.test', 'graph', {'provider_profile': []}, {'client_id': 'id', 'refresh_token': 'r'})
    for key in ('imap_user', 'username'):
        with pytest.raises(ValueError, match=key):
            validate_connection(
                'a@example.test',
                'imap',
                {'imap_host': 'imap.example.test', key: ['invalid']},
                {'password': 'p'},
                require_credentials=False,
            )


def test_operator_managed_environment_refresh_caches_access_and_rotated_refresh_token(monkeypatch):
    from mail_core.accounts.credentials import EnvCredentialStore
    from mail_core.providers.oauth import OAuthTokenClient
    monkeypatch.setenv('TEST_PROVIDER_ENV', json.dumps({'client_id': 'id', 'refresh_token': 'r'}))
    calls = []

    def token_post(method, uri, form, headers):
        calls.append(dict(form))
        idx = len(calls)
        return {'access_token': f'renewed-{idx}', 'refresh_token': f'rotated-{idx}', 'expires_in': 3600}

    client = OAuthTokenClient('env:TEST_PROVIDER_ENV', EnvCredentialStore(), provider='graph', http_post=token_post)
    assert client.get_access_token() == 'renewed-1'
    assert client.get_access_token() == 'renewed-1'
    assert len(calls) == 1
    assert calls[0]['refresh_token'] == 'r'
    assert client.get_access_token(force_refresh=True) == 'renewed-2'
    assert len(calls) == 2
    assert calls[1]['refresh_token'] == 'rotated-1'
    assert json.loads(EnvCredentialStore().get_secret('env:TEST_PROVIDER_ENV')) == {'client_id': 'id', 'refresh_token': 'r'}


@pytest.mark.parametrize('email,host', [('legacy@outlook.com', 'imap.example.test'), ('legacy@example.test', 'outlook.office365.com'), ('legacy@example.test', '')])
def test_legacy_import_does_not_create_microsoft_imap_defaults(email, host):
    from scripts.migrate_from_legacy_db import legacy_account_connection
    row = {'id': 7, 'email': email, 'authorization_type': 'imap', 'refresh_token': '', 'imap_host': host, 'imap_port': 993}
    with pytest.raises(ValueError):
        legacy_account_connection(row)
