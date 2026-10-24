"""FastAPI auth dependencies for mail-core."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from mail_core.security.auth import (
    SESSION_COOKIE_NAME,
    AuthPrincipal,
    api_key_matches,
    csrf_header_value,
    digest_api_key,
    extract_bearer,
    read_session,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

bearer_scheme = HTTPBearer(auto_error=False)
cookie_scheme = APIKeyCookie(name=SESSION_COOKIE_NAME, auto_error=False)


def authenticate_request(
    request: Request,
    bearer_creds: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    cookie_token: str | None = Security(cookie_scheme),
) -> AuthPrincipal:
    bearer = (
        bearer_creds.credentials
        if isinstance(bearer_creds, HTTPAuthorizationCredentials)
        else extract_bearer(request.headers.get("Authorization"))
    )
    if bearer is not None:
        if api_key_matches(bearer):
            return AuthPrincipal(via="api_key", api_key_digest=digest_api_key(bearer))
        raise HTTPException(status_code=401, detail="invalid api key")

    raw = cookie_token if isinstance(cookie_token, str) else request.cookies.get(SESSION_COOKIE_NAME)
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


def require_auth(
    request: Request,
    bearer_creds: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    cookie_token: str | None = Security(cookie_scheme),
) -> AuthPrincipal:
    principal = authenticate_request(request, bearer_creds=bearer_creds, cookie_token=cookie_token)
    enforce_csrf(request, principal)
    return principal
