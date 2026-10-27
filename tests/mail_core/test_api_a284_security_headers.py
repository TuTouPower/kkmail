"""A284: HSTS only on HTTPS requests; HTML (SPA) responses get a CSP.

HSTS over plain HTTP is meaningless and was sent unconditionally; with
the trusted ProxyHeadersMiddleware installed, request.url.scheme
already reflects X-Forwarded-Proto from trusted proxies only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_a284_no_hsts_on_plain_http():
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert "Strict-Transport-Security" not in res.headers


def test_a284_hsts_on_https():
    client = TestClient(app, base_url="https://testserver")
    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_a284_html_responses_get_default_src_self_csp():
    # /docs is an HTML response through the same middleware stack the
    # SPA FileResponses use; JSON API responses must stay CSP-free.
    res = TestClient(app).get("/docs")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    csp = res.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp


def test_a284_json_responses_have_no_csp():
    res = TestClient(app).get("/health")
    assert "Content-Security-Policy" not in res.headers
