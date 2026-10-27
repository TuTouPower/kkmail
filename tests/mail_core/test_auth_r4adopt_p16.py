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
