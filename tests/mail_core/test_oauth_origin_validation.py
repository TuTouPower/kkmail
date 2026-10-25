import pytest

from mail_core.accounts.oauth_flow import _validate_public_origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8080",
        "https://api.localhost",
        "https://127.0.0.1:8080",
        "https://[::1]:8080",
        "https://169.254.1.5",
        "https://mail.local",
        "https://192.168.1.10",
    ],
)
def test_rejects_local_and_private_oauth_origins_by_default(monkeypatch, origin):
    monkeypatch.delenv("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN", raising=False)
    assert _validate_public_origin(origin) is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:8080",
        "http://localhost:8080",
        "https://127.0.0.1:8080",
        "http://[::1]:8080",
        "https://169.254.1.5",
    ],
)
def test_loopback_and_link_local_oauth_origins_require_explicit_opt_in(monkeypatch, origin):
    monkeypatch.setenv("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN", "1")
    assert _validate_public_origin(origin) == origin


def test_private_oauth_origin_remains_rejected_with_loopback_opt_in(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN", "1")
    assert _validate_public_origin("https://192.168.1.10") is None


def test_public_oauth_origin_remains_accepted(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN", raising=False)
    assert _validate_public_origin("https://mail.example.com") == "https://mail.example.com"
