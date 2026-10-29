from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.security.redact import redact, safe_error
from mail_core.worker.main import next_poll_delay


def test_redacts_tokens_secrets_and_dsn():
    raw = (
        'Authorization: Bearer ya29.AAAbbb-ccc refresh_token=1//xyz '
        '{"client_secret": "s3cr3t", "password":"pw"} '
        "postgresql+psycopg://kkmail:hunter2@db:5432/x"
    )
    out = redact(raw)
    for secret in ("ya29.AAAbbb-ccc", "1//xyz", "s3cr3t", '"pw"', "hunter2"):
        assert secret not in out, secret
    assert "[REDACTED]" in out


def test_provider_body_is_not_persisted():
    exc = ProviderHttpError("bad request", status=400, body={"error": "invalid_grant", "refresh_token": "LEAK"})
    out = safe_error(exc)
    assert out == "ProviderHttpError status=400: bad request"
    assert "LEAK" not in out


def test_provider_raw_body_in_message_is_sanitized():
    raw_json = '{"error": "invalid_grant", "sensitive_info": "CONFIDENTIAL"}'
    exc = ProviderHttpError(raw_json, status=400, body=raw_json)
    out = safe_error(exc)
    assert out == "ProviderHttpError status=400"
    assert "CONFIDENTIAL" not in out


def test_rate_limited_error_summary_and_truncation():
    assert safe_error(RateLimitedError("slow down")).startswith("RateLimitedError status=429")
    assert len(safe_error("x" * 5000)) == 500


def test_poll_delay_backoff():
    # t063: claim_batch removed; poll delay is based on handled or claimed count
    assert next_poll_delay(5, 2.0, base=2.0, max_idle=10.0, claimed=5) == 2.0
    assert next_poll_delay(1, 8.0, base=2.0, max_idle=10.0) == 2.0
    assert next_poll_delay(0, 8.0, base=2.0, max_idle=10.0, claimed=3) == 2.0
    d = 2.0
    seen = []
    for _ in range(5):
        d = next_poll_delay(0, d, base=2.0, max_idle=10.0)
        seen.append(d)
    assert seen == [4.0, 8.0, 10.0, 10.0, 10.0]


def test_application_layer_exports_resolve():
    import mail_core.mail.application as app_layer

    for name in app_layer.__all__:
        obj = getattr(app_layer, name)
        assert callable(obj) or isinstance(obj, type), name
