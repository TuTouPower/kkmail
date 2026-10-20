"""FastAPI auth dependencies for mail-core."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from mail_core.security.auth import (
    SESSION_COOKIE_NAME,
    AuthPrincipal,
    api_key_matches,
    csrf_header_value,
    extract_bearer,
    read_session,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def authenticate_request(request: Request) -> AuthPrincipal:
    bearer = extract_bearer(request.headers.get("Authorization"))
    if bearer is not None:
        if api_key_matches(bearer):
            return AuthPrincipal(via="api_key")
        raise HTTPException(status_code=401, detail="invalid api key")

    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if raw:
        data = read_session(raw)
        if data:
            return AuthPrincipal(via="session", csrf_token=str(data["csrf"]))

    raise HTTPException(status_code=401, detail="authentication required")


def enforce_csrf(request: Request, principal: AuthPrincipal) -> None:
    if principal.via == "api_key":
        return
    if request.method.upper() in _SAFE_METHODS:
        return
    header = csrf_header_value(request.headers)
    expected = principal.csrf_token
    if (
        not header
        or not expected
        or not secrets.compare_digest(header, expected)
    ):
        raise HTTPException(
            status_code=403,
            detail={"error": "CSRF validation failed", "csrf_error": True},
        )


def require_auth(request: Request) -> AuthPrincipal:
    principal = authenticate_request(request)
    enforce_csrf(request, principal)
    return principal


def require_auth_no_csrf(request: Request) -> AuthPrincipal:
    """Authenticate without CSRF (SSE / safe reads already covered by require_auth)."""
    return authenticate_request(request)
