"""Public settings never echo secrets."""

from __future__ import annotations

from mail_core.accounts.settings_store import (
    PUBLIC_SETTING_KEYS,
    _is_secret_key,
    get_fetch_timeout_seconds,
    update_public_settings,
)
import pytest
from unittest.mock import MagicMock
from mail_core.mail.storage.models import AppSetting


def test_secret_keys_detected():
    assert _is_secret_key("login_password")
    assert _is_secret_key("openai_api_key")
    assert _is_secret_key("refresh_token")
    assert not _is_secret_key("app_timezone")


def test_public_allowlist():
    assert "app_timezone" in PUBLIC_SETTING_KEYS
    assert "mail_fetch_timeout_seconds" in PUBLIC_SETTING_KEYS


def test_update_public_settings_rejects_unknown_or_secret():
    session = MagicMock()
    with pytest.raises(ValueError, match="unsupported setting keys"):
        update_public_settings(session, {"unknown_key": "val"})

    with pytest.raises(ValueError, match="unsupported setting keys"):
        update_public_settings(session, {"password_reset": "secret"})


def test_update_public_settings_validates_values():
    session = MagicMock()
    # Invalid timeout values
    with pytest.raises(ValueError, match="positive number"):
        update_public_settings(session, {"mail_fetch_timeout_seconds": "not-a-number"})

    with pytest.raises(ValueError, match="positive"):
        update_public_settings(session, {"mail_fetch_timeout_seconds": "-5"})

    for value in ("nan", "inf", "-inf", "600.1", "0"):
        with pytest.raises(ValueError):
            update_public_settings(session, {"mail_fetch_timeout_seconds": value})

    # Invalid timezone
    with pytest.raises(ValueError, match="invalid IANA timezone"):
        update_public_settings(session, {"app_timezone": "Invalid/Timezone_Name"})


def test_get_fetch_timeout_seconds():
    session = MagicMock()
    session.get.return_value = AppSetting(key="mail_fetch_timeout_seconds", value="45.5")
    assert get_fetch_timeout_seconds(session) == 45.5

    session.get.return_value = None
    assert get_fetch_timeout_seconds(session, default=30.0) == 30.0


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "600.1", "0", "-5", "invalid"])
def test_get_fetch_timeout_seconds_rejects_invalid_persisted_values(value):
    session = MagicMock()
    session.get.return_value = AppSetting(key="mail_fetch_timeout_seconds", value=value)
    assert get_fetch_timeout_seconds(session, default=30.0) == 30.0


def test_build_provider_wires_fetch_timeout_from_session():
    from unittest.mock import patch
    from mail_core.mail.storage.models import Account
    from mail_core.providers.factory import build_provider

    session = MagicMock()
    session.get.return_value = AppSetting(key="mail_fetch_timeout_seconds", value="120")

    account = Account(
        email="user@example.com",
        provider="imap",
        credential_ref="cred-1",
        config={"imap_host": "imap.example.com"},
    )
    store = MagicMock()
    store.get_secret.return_value = "secret"

    with patch("mail_core.providers.factory.validate_imap_host"):
        provider = build_provider(account, store, session=session)
    assert provider.timeout == 120.0

    # Default 30.0 when unset
    empty_session = MagicMock()
    empty_session.get.return_value = None
    with patch("mail_core.providers.factory.validate_imap_host"):
        default_provider = build_provider(account, store, session=empty_session)
    assert default_provider.timeout == 30.0

    # Explicit timeout override takes precedence
    with patch("mail_core.providers.factory.validate_imap_host"):
        explicit_provider = build_provider(account, store, timeout=45.0, session=session)
    assert explicit_provider.timeout == 45.0


def test_build_provider_wires_fetch_timeout_to_oauth_providers():
    from mail_core.mail.storage.models import Account
    from mail_core.providers.factory import build_provider

    session = MagicMock()
    session.get.return_value = AppSetting(key="mail_fetch_timeout_seconds", value="75")

    store = MagicMock()
    store.get_secret.return_value = "{}"

    gmail_acc = Account(email="g@example.com", provider="gmail", credential_ref="oauth:g")
    gmail_p = build_provider(gmail_acc, store, session=session, token_http=lambda *a, **k: {}, api_http=lambda *a, **k: {})
    assert gmail_p.timeout == 75.0

    graph_acc = Account(email="m@example.com", provider="graph", credential_ref="oauth:m")
    graph_p = build_provider(graph_acc, store, session=session, token_http=lambda *a, **k: {}, api_http=lambda *a, **k: {})
    assert graph_p.timeout == 75.0

@pytest.mark.parametrize('provider_name', ['imap', 'gmail', 'graph'])
def test_runtime_timeout_uses_persisted_setting_without_injected_session(provider_name, monkeypatch):
    import os
    if not os.environ.get('MAIL_CORE_DATABASE_URL'):
        pytest.skip('PG required')
    from mail_core.accounts.credentials import DictCredentialStore
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import Account
    from mail_core.providers.factory import build_provider

    with get_session_factory()() as session:
        update_public_settings(session, {'mail_fetch_timeout_seconds': '75'})
        session.commit()
    monkeypatch.setattr('mail_core.providers.factory.validate_imap_host', lambda _host: None)
    account = Account(email='timeout@example.com', provider=provider_name, credential_ref='test-timeout',
                      config={'imap_host': 'imap.example.com'})
    store = DictCredentialStore({'test-timeout': '{"password":"test-only","client_id":"cid","refresh_token":"rt"}'})
    provider = build_provider(account, store)
    assert provider.timeout == 75.0
    if provider_name in ('gmail', 'graph'):
        assert provider.transport.token_client.timeout == 75.0
