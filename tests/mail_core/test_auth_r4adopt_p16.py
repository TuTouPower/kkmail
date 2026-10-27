"""R4 adoption P16: auth hardening regressions (A87/A88/A119/A188/A250/A251/A324)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mail_core.security.auth import reset_auth_caches

_AUTH_PY = Path(__file__).resolve().parent.parent.parent / "src" / "mail_core" / "security" / "auth.py"


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_caches()
    yield
    reset_auth_caches()


def test_a188_session_epoch_declared_once():
    source = _AUTH_PY.read_text(encoding="utf-8")
    declarations = re.findall(r"^_session_epoch: int = 1$", source, flags=re.MULTILINE)
    assert len(declarations) == 1


@pytest.mark.parametrize("raw", ["0", "-1", "-86400", str(60 * 60 * 24 * 365 + 1), str(10**15)])
def test_a88_session_max_age_out_of_range_rejected(monkeypatch, raw):
    from mail_core.security.auth import AuthConfigError, session_max_age

    monkeypatch.setenv("MAIL_CORE_SESSION_MAX_AGE", raw)
    reset_auth_caches()
    with pytest.raises(AuthConfigError, match="MAIL_CORE_SESSION_MAX_AGE"):
        session_max_age()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1", 1), ("120", 120), (str(60 * 60 * 24 * 365), 60 * 60 * 24 * 365)],
)
def test_a88_session_max_age_boundaries_accepted(monkeypatch, raw, expected):
    from mail_core.security.auth import session_max_age

    monkeypatch.setenv("MAIL_CORE_SESSION_MAX_AGE", raw)
    reset_auth_caches()
    assert session_max_age() == expected


@pytest.mark.parametrize("raw", ['[123]', '[null]', '[true]', '["valid-key", 123]', '[""]', '["   "]'])
def test_a251_api_keys_json_rejects_non_string_or_empty_elements(monkeypatch, raw):
    from mail_core.security.auth import AuthConfigError, load_api_keys

    monkeypatch.setenv("MAIL_CORE_API_KEYS", raw)
    reset_auth_caches()
    with pytest.raises(AuthConfigError, match="MAIL_CORE_API_KEYS"):
        load_api_keys()


def test_a251_api_keys_json_syntax_error_wrapped_as_auth_config_error(monkeypatch):
    import json as json_module

    from mail_core.security.auth import AuthConfigError, load_api_keys

    monkeypatch.setenv("MAIL_CORE_API_KEYS", "[not-json")
    reset_auth_caches()
    with pytest.raises(AuthConfigError, match="MAIL_CORE_API_KEYS") as excinfo:
        load_api_keys()
    assert isinstance(excinfo.value.__cause__, json_module.JSONDecodeError)


def test_a251_api_keys_valid_forms_still_load(monkeypatch):
    from mail_core.security.auth import load_api_keys

    monkeypatch.setenv("MAIL_CORE_API_KEYS", '["key-one", "key-two"]')
    reset_auth_caches()
    assert load_api_keys() == frozenset({"key-one", "key-two"})

    monkeypatch.setenv("MAIL_CORE_API_KEYS", "alpha, beta")
    reset_auth_caches()
    assert load_api_keys() == frozenset({"alpha", "beta"})


def _fake_request(scheme: str):
    from types import SimpleNamespace

    return SimpleNamespace(scope={"scheme": scheme}, url=SimpleNamespace(scheme=scheme))


def test_a324_samesite_none_without_secure_falls_back_to_lax_with_warning(monkeypatch, caplog):
    import logging

    from mail_core.security.auth import cookie_samesite

    monkeypatch.setenv("MAIL_CORE_COOKIE_SAMESITE", "none")
    monkeypatch.delenv("MAIL_CORE_COOKIE_SECURE", raising=False)
    with caplog.at_level(logging.WARNING, logger="mail_core.security.auth"):
        assert cookie_samesite() == "lax"
        assert cookie_samesite(_fake_request("http")) == "lax"
    assert any("samesite" in r.message.lower() for r in caplog.records)


def test_a324_samesite_none_with_secure_is_kept(monkeypatch):
    from mail_core.security.auth import cookie_samesite

    monkeypatch.setenv("MAIL_CORE_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "1")
    assert cookie_samesite() == "none"

    monkeypatch.delenv("MAIL_CORE_COOKIE_SECURE", raising=False)
    assert cookie_samesite(_fake_request("https")) == "none"


@pytest.mark.parametrize("value", ["lax", "strict"])
def test_a324_other_samesite_values_unaffected_without_secure(monkeypatch, value):
    from mail_core.security.auth import cookie_samesite

    monkeypatch.setenv("MAIL_CORE_COOKIE_SAMESITE", value)
    monkeypatch.delenv("MAIL_CORE_COOKIE_SECURE", raising=False)
    assert cookie_samesite() == value


_A250_SECRET_DETAIL = "could not connect to postgres://operator:s3cr3t-pw@db-internal-host:5432/proddb"


def _a250_broken_factory():
    class BrokenSession:
        def __enter__(self):
            raise RuntimeError(_A250_SECRET_DETAIL)

        def __exit__(self, *args):
            return False

    return lambda: BrokenSession()


def test_a250_fetch_db_credentials_logs_only_type_and_fixed_error_message(monkeypatch, caplog):
    import logging
    from unittest.mock import patch

    from mail_core.security.auth import AuthConfigError, get_login_password_hash

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://test/db")
    reset_auth_caches()
    with patch("mail_core.db.session.get_session_factory", return_value=_a250_broken_factory()):
        with caplog.at_level(logging.DEBUG, logger="mail_core.security.auth"):
            with pytest.raises(AuthConfigError) as excinfo:
                get_login_password_hash()
    assert "s3cr3t-pw" not in str(excinfo.value)
    assert "db-internal-host" not in str(excinfo.value)
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records
    assert all("RuntimeError" in r.getMessage() for r in error_records)
    assert all("s3cr3t-pw" not in r.getMessage() for r in error_records)
    assert all("db-internal-host" not in r.getMessage() for r in error_records)
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert debug_records
    assert all("s3cr3t-pw" not in r.getMessage() for r in debug_records)


def test_a87_verify_password_returns_false_only_when_no_credentials_configured(monkeypatch):
    from mail_core.security.auth import verify_password

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD", raising=False)
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()
    assert verify_password("any-password") is False


def test_a87_verify_password_propagates_db_failure(monkeypatch):
    from unittest.mock import patch

    from mail_core.security.auth import AuthConfigError, verify_password

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://test/db")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "fallback-password")
    reset_auth_caches()
    with patch("mail_core.db.session.get_session_factory", return_value=_a250_broken_factory()):
        with pytest.raises(AuthConfigError, match="failed to query authentication credentials"):
            verify_password("fallback-password")


def test_a87_login_route_returns_500_without_recording_rate_limit_failure(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import mail_core.api.auth_routes as auth_routes
    from mail_core.security.auth import AuthConfigError

    recorded: list[str] = []

    def _broken_verify(_password: str) -> bool:
        raise AuthConfigError("failed to query authentication credentials from database")

    monkeypatch.setattr(auth_routes, "verify_password", _broken_verify)
    monkeypatch.setattr(auth_routes.login_limiter, "retry_after", lambda _client: 0)
    monkeypatch.setattr(auth_routes.login_limiter, "record_failure", recorded.append)

    test_app = FastAPI()
    test_app.include_router(auth_routes.router)
    response = TestClient(test_app, raise_server_exceptions=False).post(
        "/api/auth/login", json={"password": "any-password"}
    )
    assert response.status_code == 500
    assert recorded == []


def test_a250_get_session_epoch_logs_only_type_and_fixed_error_message(monkeypatch, caplog):
    import logging
    from unittest.mock import patch

    from mail_core.security.auth import AuthConfigError, get_session_epoch

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://test/db")
    reset_auth_caches()
    with patch("mail_core.db.session.get_session_factory", return_value=_a250_broken_factory()):
        with caplog.at_level(logging.DEBUG, logger="mail_core.security.auth"):
            with pytest.raises(AuthConfigError) as excinfo:
                get_session_epoch()
    assert "s3cr3t-pw" not in str(excinfo.value)
    assert "db-internal-host" not in str(excinfo.value)
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records
    assert all("RuntimeError" in r.getMessage() for r in error_records)
    assert all("s3cr3t-pw" not in r.getMessage() for r in error_records)
    assert all("db-internal-host" not in r.getMessage() for r in error_records)
