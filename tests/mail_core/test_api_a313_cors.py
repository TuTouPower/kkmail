"""A313: with allow_credentials=True, CORS methods/headers must not be
wildcards; converge to the methods and headers the app actually uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mail_core.api.app import app

_ORIGIN = "http://localhost:5173"


def _preflight(method: str, headers: str):
    return TestClient(app).options(
        "/health",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_a313_preflight_allows_used_methods_and_headers():
    for method in ["GET", "POST", "PATCH", "PUT", "DELETE"]:
        res = _preflight(method, "authorization,content-type,x-csrf-token,x-request-id")
        assert res.status_code == 200, method
        allowed_methods = res.headers.get("access-control-allow-methods", "")
        assert method in allowed_methods
        allowed_headers = res.headers.get("access-control-allow-headers", "").lower()
        for header in ["authorization", "content-type", "x-csrf-token", "x-request-id"]:
            assert header in allowed_headers


def test_a313_preflight_rejects_unused_method():
    res = _preflight("TRACE", "authorization")
    assert res.status_code == 400


def test_a313_preflight_rejects_unused_header():
    res = _preflight("GET", "x-not-a-real-header")
    assert res.status_code == 400
