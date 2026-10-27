"""A325: safe_error() must not persist raw non-provider exception messages.

worker_jobs.last_error stores safe_error(exc); for non-ProviderHttpError
exceptions the raw message (SQL text, file paths, internal details) must
converge to exception type plus controlled fields only.
"""

from __future__ import annotations

from mail_core.providers.http import ProviderHttpError
from mail_core.security.redact import safe_error


def test_sql_exception_message_is_not_persisted():
    exc = RuntimeError(
        "SELECT id, password_hash FROM accounts WHERE email='a@b.c' "
        "failed at /srv/kkmail/db.py:42 password=hunter2"
    )
    out = safe_error(exc)
    assert out == "RuntimeError"
    for leak in ("SELECT", "password_hash", "hunter2", "/srv/kkmail", "a@b.c"):
        assert leak not in out


def test_value_error_message_is_not_persisted():
    out = safe_error(ValueError("credential JSON missing password for account 7"))
    assert out == "ValueError"
    assert "credential" not in out
    assert "account 7" not in out


def test_controlled_fields_are_retained():
    class DbError(Exception):
        status = 503
        code = "57P03"

    out = safe_error(DbError("cannot connect now, server says no"))
    assert out == "DbError status=503 code=57P03"
    assert "cannot connect" not in out


def test_string_input_still_redacted_and_truncated():
    assert safe_error("boom") == "boom"
    assert safe_error("token=abc123") == "token=[REDACTED]"
    assert len(safe_error("x" * 5000)) == 500
    assert safe_error(None) == ""


def test_provider_http_error_branch_unchanged():
    exc = ProviderHttpError("bad request", status=400, body={"error": "invalid_grant"})
    assert safe_error(exc) == "ProviderHttpError status=400: bad request"
