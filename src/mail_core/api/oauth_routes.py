"""OAuth2 authorization flow & callback HTTP routes for mail-core (t054)."""

from __future__ import annotations

import html
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from mail_core.accounts.oauth_flow import (
    cancel_oauth_flow,
    complete_oauth_callback,
    get_active_oauth_flow,
    get_oauth_flow_status,
    get_oauth_metadata,
    start_oauth_flow,
)
from mail_core.api.deps import require_auth
from mail_core.security.auth import AuthPrincipal

def prevent_oauth_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(tags=["accounts-oauth"], dependencies=[Depends(prevent_oauth_cache)])


class OAuthMetadataOut(BaseModel):
    provider: str
    runtime_mode: Literal["desktop", "web"]
    default_client_type: Literal["public", "confidential"]
    redirect_uri: str | None = None
    callback_path: str
    origin_configured: bool
    notice: str | None = None


class OAuthStartIn(BaseModel):
    provider: str = Field(default="google", max_length=32)
    intent: Literal["create", "reauthorize"] = "create"
    account_id: UUID | None = None
    email_hint: str | None = Field(default=None, max_length=320)
    group_id: UUID | None = None
    client_type: Literal["public", "confidential"] | None = None
    client_id: str | None = Field(default=None, max_length=512)
    client_secret: str | None = Field(default=None, max_length=512)
    method: Literal["authorization_code", "device_code"] = "authorization_code"
    tenant: str | None = Field(default=None, max_length=253)


class OAuthStartOut(BaseModel):
    flow_id: str
    provider: str
    intent: Literal["create", "reauthorize"]
    status: str
    auth_url: str
    redirect_uri: str
    client_type: Literal["public", "confidential"]
    expires_at: float
    method: Literal["authorization_code", "device_code"] = "authorization_code"
    tenant: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None


class OAuthFlowStatusOut(BaseModel):
    flow_id: str
    provider: str
    intent: Literal["create", "reauthorize"]
    account_id: str | None = None
    group_id: str | None = None
    client_type: Literal["public", "confidential"]
    client_id: str
    status: Literal["pending", "authorized", "failed", "expired", "cancelled", "consumed"]
    verified_email: str | None = None
    error: str | None = None
    redirect_uri: str
    expires_at: float
    method: Literal["authorization_code", "device_code"] = "authorization_code"
    tenant: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None


class OAuthActiveOut(BaseModel):
    flow: OAuthFlowStatusOut | None = None


class OAuthCancelOut(BaseModel):
    ok: bool = True
    status: str = "cancelled"


def _callback_html(ok: bool, message: str, provider: str = "google") -> str:
    safe_msg = html.escape(message)
    label = "Microsoft" if provider == "microsoft" else "Google"
    title = f"{label} 授权已完成" if ok else f"{label} 授权未完成"
    badge = "授权已核实并暂存" if ok else "授权未完成"
    color = "#10b981" if ok else "#ef4444"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="referrer" content="no-referrer" />
  <title>{title} - kkmail</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; box-sizing: border-box; }}
    main {{ max-width: 460px; width: 100%; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; box-sizing: border-box; }}
    .badge {{ display: inline-block; font-size: 12px; font-weight: 600; color: {color}; border: 1px solid {color}; border-radius: 999px; padding: 2px 10px; margin-bottom: 12px; }}
    h1 {{ font-size: 18px; margin: 0 0 10px; }}
    p {{ font-size: 14px; line-height: 1.6; color: #cbd5e1; margin: 0 0 16px; word-break: break-word; }}
    a.btn {{ display: inline-block; background: #3b82f6; color: #fff; text-decoration: none; padding: 8px 16px; border-radius: 6px; font-size: 14px; }}
  </style>
</head>
<body>
  <main>
    <span class="badge">{badge}</span>
    <h1>{title}</h1>
    <p id="oauth-callback-message">{safe_msg}</p>
    <p>若此窗口来自桌面端或弹窗，您可以直接关闭此标签页返回 kkmail 账户设置窗口点击「保存」完成确认。</p>
    <a class="btn" id="oauth-return-link" href="/#oauth-return">返回 kkmail</a>
  </main>
  <script>
    if (window.history && window.history.replaceState) {{
      window.history.replaceState(null, "", window.location.pathname);
    }}
  </script>
</body>
</html>"""


@router.get("/api/accounts/oauth/metadata", response_model=OAuthMetadataOut)
def api_oauth_metadata(
    provider: str = Query("google", max_length=32),
    _principal: AuthPrincipal = Depends(require_auth),
) -> OAuthMetadataOut:
    try:
        data = get_oauth_metadata(provider)
        return OAuthMetadataOut(**data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/accounts/oauth/active", response_model=OAuthActiveOut)
def api_oauth_active(
    principal: AuthPrincipal = Depends(require_auth),
) -> OAuthActiveOut:
    try:
        view = get_active_oauth_flow(principal)
        return OAuthActiveOut(flow=OAuthFlowStatusOut(**view) if view else None)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/accounts/oauth/start", response_model=OAuthStartOut)
def api_oauth_start(
    body: OAuthStartIn,
    principal: AuthPrincipal = Depends(require_auth),
) -> OAuthStartOut:
    try:
        res = start_oauth_flow(
            principal,
            provider=body.provider,
            intent=body.intent,
            account_id=body.account_id,
            email_hint=body.email_hint,
            group_id=body.group_id,
            client_type=body.client_type,
            client_id=body.client_id,
            client_secret=body.client_secret,
            method=body.method,
            tenant=body.tenant,
        )
        return OAuthStartOut(**res)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/accounts/oauth/flows/{flow_id}", response_model=OAuthFlowStatusOut)
def api_oauth_flow_status(
    flow_id: str,
    principal: AuthPrincipal = Depends(require_auth),
) -> OAuthFlowStatusOut:
    try:
        view = get_oauth_flow_status(flow_id, principal)
        return OAuthFlowStatusOut(**view)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/accounts/oauth/flows/{flow_id}/poll", response_model=OAuthFlowStatusOut)
def api_oauth_device_poll(flow_id: str, principal: AuthPrincipal = Depends(require_auth)) -> OAuthFlowStatusOut:
    from mail_core.accounts.device_oauth import poll_device_flow
    try:
        return OAuthFlowStatusOut(**poll_device_flow(flow_id, principal))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/accounts/oauth/flows/{flow_id}/cancel", response_model=OAuthCancelOut)
def api_oauth_flow_cancel(
    flow_id: str,
    principal: AuthPrincipal = Depends(require_auth),
) -> OAuthCancelOut:
    try:
        res = cancel_oauth_flow(flow_id, principal)
        return OAuthCancelOut(**res)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/api/accounts/oauth/callback/{provider}", response_class=HTMLResponse)
def api_oauth_callback(
    provider: str,
    state: str | None = Query(default=None, max_length=256),
    code: str | None = Query(default=None, max_length=2048),
    error: str | None = Query(default=None, max_length=256),
    error_description: str | None = Query(default=None, max_length=1024),
) -> HTMLResponse:
    ok, status_code, message = complete_oauth_callback(
        provider,
        state=state,
        code=code,
        error=error,
        error_description=error_description,
    )
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    }
    return HTMLResponse(
        content=_callback_html(ok, message, provider),
        status_code=status_code,
        headers=headers,
    )
