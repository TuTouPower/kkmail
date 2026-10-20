"""Public settings never echo secrets."""

from __future__ import annotations

from mail_core.accounts.settings_store import PUBLIC_SETTING_KEYS, _is_secret_key


def test_secret_keys_detected():
    assert _is_secret_key("login_password")
    assert _is_secret_key("openai_api_key")
    assert _is_secret_key("refresh_token")
    assert not _is_secret_key("app_timezone")


def test_public_allowlist():
    assert "app_timezone" in PUBLIC_SETTING_KEYS
    assert "mail_fetch_timeout_seconds" in PUBLIC_SETTING_KEYS
