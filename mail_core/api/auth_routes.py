"""Login / logout / me for mail-core."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from mail_core.api.deps import require_auth
from mail_core.security.ratelimit import login_limiter
from mail_core.security.auth import (
    SESSION_COOKIE_NAME,
    AuthConfigError,
    AuthPrincipal,
    change_login_password,
    cookie_samesite,
    cookie_secure,
    issue_session,
    session_max_age,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(min_length=1)


class LoginOut(BaseModel):
    ok: bool = True
    csrf_token: str


class MeOut(BaseModel):
    authenticated: bool = True
    via: str
    csrf_token: str | None = None


def _set_session_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=value,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),  # type: ignore[arg-type]
        path="/",
        max_age=session_max_age(),
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response) -> LoginOut:
    client = request.client.host if request.client else "unknown"
    wait = login_limiter.retry_after(client)
    if wait:
        raise HTTPException(status_code=429, detail="too many failed logins", headers={"Retry-After": str(wait)})
    if not verify_password(body.password):
        login_limiter.record_failure(client)
        raise HTTPException(status_code=401, detail="invalid credentials")
    login_limiter.reset(client)
    cookie_val, csrf = issue_session()
    _set_session_cookie(response, cookie_val)
    return LoginOut(csrf_token=csrf)


@router.post("/logout")
def logout(response: Response, _principal: AuthPrincipal = Depends(require_auth)) -> dict[str, bool]:
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(principal: AuthPrincipal = Depends(require_auth)) -> MeOut:
    return MeOut(via=principal.via, csrf_token=principal.csrf_token)



class PasswordChangeIn(BaseModel):
    current_login_password: str = Field(min_length=1)
    login_password: str = Field(min_length=8)


@router.post("/password")
def change_password(body: PasswordChangeIn, _principal: AuthPrincipal = Depends(require_auth)) -> dict[str, bool]:
    try:
        change_login_password(current=body.current_login_password, new=body.login_password)
    except AuthConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "success": True}
