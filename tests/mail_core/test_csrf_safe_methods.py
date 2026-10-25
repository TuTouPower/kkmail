import pytest
from fastapi import HTTPException
from starlette.requests import Request

from mail_core.api.deps import enforce_csrf
from mail_core.security.auth import AuthPrincipal


def _request(method: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/test",
            "headers": headers or [],
            "query_string": b"",
        }
    )


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_read_only_methods_remain_csrf_safe(method):
    assert enforce_csrf(_request(method), AuthPrincipal(via="session", csrf_token="csrf")) is None


def test_trace_requires_csrf_token():
    with pytest.raises(HTTPException) as exc_info:
        enforce_csrf(_request("TRACE"), AuthPrincipal(via="session", csrf_token="csrf"))

    assert exc_info.value.status_code == 403


def test_trace_accepts_matching_csrf_token():
    request = _request("TRACE", [(b"x-csrf-token", b"csrf")])

    assert enforce_csrf(request, AuthPrincipal(via="session", csrf_token="csrf")) is None
