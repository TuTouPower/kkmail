"""Public settings never echo secrets."""

from __future__ import annotations

from mail_core.accounts.settings_store import (
    PUBLIC_SETTING_KEYS,
    _is_secret_key,
    get_app_setting,
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

    # Invalid timezone
    with pytest.raises(ValueError, match="invalid IANA timezone"):
        update_public_settings(session, {"app_timezone": "Invalid/Timezone_Name"})


def test_get_fetch_timeout_seconds():
    session = MagicMock()
    session.get.return_value = AppSetting(key="mail_fetch_timeout_seconds", value="45.5")
    assert get_fetch_timeout_seconds(session) == 45.5

    session.get.return_value = None
    assert get_fetch_timeout_seconds(session, default=30.0) == 30.0
