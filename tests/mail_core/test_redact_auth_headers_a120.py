"""A120: redact() must cover JWTs, Cookie headers and every Authorization scheme."""

from __future__ import annotations

from mail_core.security.redact import redact

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c"
)


def test_jwt_is_redacted_wherever_it_appears():
    out = redact(f"provider replied with token {JWT} in body")
    assert JWT not in out
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c" not in out
    assert "[REDACTED]" in out


def test_cookie_and_set_cookie_headers_are_fully_redacted():
    out = redact("Cookie: session=abc123secret; theme=dark; uid=42")
    assert "abc123secret" not in out
    assert "theme=dark" not in out
    assert "uid=42" not in out
    assert "[REDACTED]" in out

    out2 = redact("Set-Cookie: sid=zzz999; Path=/; HttpOnly")
    assert "zzz999" not in out2
    assert "[REDACTED]" in out2


def test_authorization_any_scheme_is_redacted():
    for header in (
        "Authorization: Digest username='u', response='deadbeefcafe'",
        "Authorization: Token abcdef123456",
        "Authorization: MAC id='x', ts='1', nonce='n', mac='c2VjcmV0'",
        "Authorization: Negotiate YIIF...\u2026".replace("\u2026", "TlRMTVNTUAABAAA"),
        "Authorization: rawtokenvalue123",
    ):
        out = redact(header)
        for secret in ("deadbeefcafe", "abcdef123456", "c2VjcmV0", "TlRMTVNTUAABAAA", "rawtokenvalue123"):
            assert secret not in out, (header, out)
        assert "[REDACTED]" in out, header


def test_existing_bearer_and_basic_still_redacted():
    out = redact("Authorization: Bearer ya29.AAAbbb-ccc and Basic dXNlcjpwYXNz")
    assert "ya29.AAAbbb-ccc" not in out
    assert "dXNlcjpwYXNz" not in out
