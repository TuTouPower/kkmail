"""OAuth2 authorization-code + PKCE flow management for Google Gmail API (t054)."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import (
    CompositeCredentialStore,
    CredentialStore,
    DbCredentialStore,
    DictCredentialStore,
    credential_edit,
    get_credential_store,
    load_json_secret,
    save_json_secret,
)
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, AccountGroup
from mail_core.providers.http import ProviderHttpError
from mail_core.providers.oauth import default_urllib_token_post, urllib_json_request
from mail_core.security.auth import AuthPrincipal, get_session_epoch
from mail_core.security.redact import safe_error

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_PROFILE_URI = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GOOGLE_REQUIRED_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
FLOW_TTL_SECONDS = 600.0
EXPIRED_FLOW_MESSAGE = "授权流程已超过 10 分钟有效期，请重新发起授权。"

_STATE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_unit_memory_store = DictCredentialStore()

TokenPostFn = Callable[[str, dict[str, str]], dict[str, Any]]
ProfileGetFn = Callable[[str, str], dict[str, Any]]

_token_http_post: TokenPostFn | None = None
_profile_http_get: ProfileGetFn | None = None


def set_oauth_http_hooks(*, token_post: TokenPostFn | None = None, profile_get: ProfileGetFn | None = None) -> None:
    global _token_http_post, _profile_http_get
    _token_http_post = token_post
    _profile_http_get = profile_get


def reset_oauth_flow_state() -> None:
    global _token_http_post, _profile_http_get
    _token_http_post = None
    _profile_http_get = None
    _unit_memory_store._mapping.clear()


def _flow_store() -> CredentialStore:
    store = get_credential_store()
    if (
        isinstance(store, CompositeCredentialStore)
        and isinstance(store.db, DbCredentialStore)
        and not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip()
    ):
        return _unit_memory_store
    return store


def _delete_ref(store: CredentialStore, ref: str, *, session: Session | None = None) -> None:
    try:
        store.delete_secret(ref, session=session)
    except TypeError:
        store.delete_secret(ref)
    except KeyError:
        pass


def _clear_matching_active_pointer(
    store: CredentialStore,
    sess_key: str,
    flow_id: str,
    *,
    session: Session | None = None,
) -> None:
    with credential_edit(store, f"oauth_active:{sess_key}", session=session) as active:
        if active.get("flow_id") == flow_id:
            active.clear()


def session_binding_key(principal: AuthPrincipal | None) -> str:
    if principal is None:
        raise PermissionError("authentication required")
    if principal.via == "session" and principal.csrf_token:
        digest = hashlib.sha256(principal.csrf_token.encode("utf-8")).hexdigest()
        return f"session:{digest}"
    if principal.via == "api_key":
        return "api_key:default"
    raise PermissionError("authentication required")


def _verify_flow_owner(flow: dict[str, Any], principal: AuthPrincipal | None) -> None:
    if not flow:
        raise LookupError("OAuth 授权流程不存在或已失效")
    if flow.get("session_key") != session_binding_key(principal):
        raise PermissionError("无权访问其他会话发起的 OAuth 授权流程")
    if int(flow.get("session_epoch") or 0) != get_session_epoch():
        raise PermissionError("当前登录会话已失效，请重新登录后再发起授权")


def _validate_public_origin(raw_origin: str) -> str | None:
    parts = urlsplit(raw_origin)
    allow_loopback = os.environ.get("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    host = (parts.hostname or "").lower()
    valid_scheme = parts.scheme == "https" or (parts.scheme == "http" and allow_loopback and host in ("127.0.0.1", "localhost"))
    if not host or not valid_scheme or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        return None
    return f"{parts.scheme}://{parts.netloc}"


def get_oauth_metadata(provider: str = "google") -> dict[str, Any]:
    norm = (provider or "").strip().lower()
    if norm != "google":
        raise ValueError(f"不支持的 OAuth 供应商: {provider}")
    callback_path = f"/api/accounts/oauth/callback/{norm}"
    if os.environ.get("KKMAIL_SIDECAR", "").strip() == "1":
        port_raw = (os.environ.get("MAIL_CORE_PORT") or "18765").strip()
        if not port_raw.isdigit() or not (1 <= int(port_raw) <= 65535):
            raise ValueError("桌面端本地服务端口无效")
        return {
            "provider": norm,
            "runtime_mode": "desktop",
            "default_client_type": "public",
            "redirect_uri": f"http://127.0.0.1:{int(port_raw)}{callback_path}",
            "callback_path": callback_path,
            "origin_configured": True,
            "notice": None,
        }

    raw_origin = (os.environ.get("MAIL_CORE_PUBLIC_ORIGIN") or "").strip()
    if not raw_origin:
        return {
            "provider": norm,
            "runtime_mode": "web",
            "default_client_type": "confidential",
            "redirect_uri": None,
            "callback_path": callback_path,
            "origin_configured": False,
            "notice": f"自托管网页部署需配置可信 HTTPS 公网 Origin（MAIL_CORE_PUBLIC_ORIGIN），固定回调路径为 {callback_path}",
        }
    clean_origin = _validate_public_origin(raw_origin)
    if not clean_origin:
        return {
            "provider": norm,
            "runtime_mode": "web",
            "default_client_type": "confidential",
            "redirect_uri": None,
            "callback_path": callback_path,
            "origin_configured": False,
            "notice": "MAIL_CORE_PUBLIC_ORIGIN 必须为可信 HTTPS 公网 Origin（不得包含路径或指向未授权 loopback）",
        }
    return {
        "provider": norm,
        "runtime_mode": "web",
        "default_client_type": "confidential",
        "redirect_uri": f"{clean_origin}{callback_path}",
        "callback_path": callback_path,
        "origin_configured": True,
        "notice": None,
    }


def _load_account_for_reauthorize(account_id: uuid.UUID) -> tuple[str, str | None, dict[str, Any], dict[str, Any]]:
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        raise LookupError("account not found")
    with get_session_factory()() as session:
        acc = session.get(Account, account_id)
        if acc is None:
            raise LookupError("account not found")
        if (acc.provider or "").lower() != "gmail":
            raise ValueError("仅已有 Gmail API 账户支持 Google OAuth 重新授权，不能将 IMAP 账户直接切换为 Gmail API")
        saved: dict[str, Any] = {}
        if acc.credential_ref:
            try:
                saved = load_json_secret(get_credential_store(), acc.credential_ref)
            except KeyError:
                saved = {}
        return acc.email.strip().lower(), str(acc.group_id) if acc.group_id else None, dict(acc.config or {}), saved


def _email_exists(email: str) -> bool:
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return False
    with get_session_factory()() as session:
        return session.scalar(select(Account.id).where(Account.email == email.strip().lower())) is not None


def start_oauth_flow(
    principal: AuthPrincipal,
    *,
    provider: str = "google",
    intent: str = "create",
    account_id: uuid.UUID | None = None,
    email_hint: str | None = None,
    group_id: uuid.UUID | None = None,
    client_type: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    norm_provider = (provider or "").strip().lower()
    if norm_provider != "google":
        raise ValueError(f"不支持的 OAuth 供应商: {provider}")
    if intent not in ("create", "reauthorize"):
        raise ValueError("无效的 OAuth 授权用途")

    meta = get_oauth_metadata(norm_provider)
    saved_config: dict[str, Any] = {}
    saved_creds: dict[str, Any] = {}
    target_email = (email_hint or "").strip().lower() or None
    effective_group_id = str(group_id) if group_id else None

    if intent == "reauthorize":
        if account_id is None:
            raise ValueError("重新授权必须指定目标账户 ID")
        target_email, existing_group, saved_config, saved_creds = _load_account_for_reauthorize(account_id)
        effective_group_id = effective_group_id or existing_group
    elif account_id is not None:
        raise ValueError("新增账户流程不能指定已有账户 ID")

    effective_client_type = (
        (client_type or "").strip()
        or str(saved_config.get("oauth_client_type") or "").strip()
        or str(meta["default_client_type"])
    )
    if effective_client_type not in ("public", "confidential"):
        raise ValueError("config.oauth_client_type: unsupported client type")

    cid = (client_id or "").strip() or str(saved_creds.get("client_id") or "").strip()
    if client_secret is not None and client_secret.strip():
        csecret = client_secret.strip()
    elif effective_client_type == "confidential":
        csecret = str(saved_creds.get("client_secret") or "").strip()
    else:
        csecret = ""

    missing = [
        name
        for cond, name in (
            (not cid, "Client ID"),
            ((effective_client_type == "confidential" or meta["runtime_mode"] == "web") and not csecret, "Client Secret"),
            (not meta["redirect_uri"], "可信回调地址 (MAIL_CORE_PUBLIC_ORIGIN)"),
        )
        if cond
    ]
    if missing:
        raise ValueError(f"缺少 OAuth 配置项：{'、'.join(missing)}。请补齐配置或打开凭据帮助查看步骤。")

    flow_id = secrets.token_urlsafe(24)
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    now = time.time()
    expires_at = now + FLOW_TTL_SECONDS
    sess_key = session_binding_key(principal)

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": str(meta["redirect_uri"]),
        "scope": GOOGLE_REQUIRED_SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        **({"login_hint": target_email} if target_email else {}),
    }

    store = _flow_store()
    save_json_secret(
        store,
        f"oauth_flow:{flow_id}",
        {
            "flow_id": flow_id,
            "provider": norm_provider,
            "account_provider": "gmail",
            "intent": intent,
            "account_id": str(account_id) if account_id else None,
            "target_email": target_email,
            "group_id": effective_group_id,
            "client_type": effective_client_type,
            "client_id": cid,
            "client_secret": csecret,
            "redirect_uri": str(meta["redirect_uri"]),
            "state": state,
            "code_verifier": code_verifier,
            "session_key": sess_key,
            "session_epoch": get_session_epoch(),
            "status": "pending",
            "code_consumed": False,
            "consumed": False,
            "verified_email": None,
            "error": None,
            "created_at": now,
            "expires_at": expires_at,
        },
    )
    save_json_secret(store, f"oauth_state:{state}", {"flow_id": flow_id, "provider": norm_provider, "expires_at": expires_at})
    with credential_edit(store, f"oauth_active:{sess_key}") as active:
        active.clear()
        active.update({"flow_id": flow_id, "updated_at": now})
    return {
        "flow_id": flow_id,
        "provider": norm_provider,
        "intent": intent,
        "status": "pending",
        "auth_url": f"{GOOGLE_AUTH_URI}?{urlencode(params)}",
        "redirect_uri": str(meta["redirect_uri"]),
        "client_type": effective_client_type,
        "expires_at": expires_at,
    }


def _call_token_endpoint(url: str, form: dict[str, str]) -> dict[str, Any]:
    if _token_http_post is not None:
        return _token_http_post(url, form)
    return default_urllib_token_post("POST", url, form, {"Content-Type": "application/x-www-form-urlencoded"})


def _call_profile_endpoint(url: str, access_token: str) -> dict[str, Any]:
    if _profile_http_get is not None:
        return _profile_http_get(url, access_token)
    res = urllib_json_request("GET", url, None, {"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    return res if isinstance(res, dict) else {}


def _friendly_oauth_error(err_code: str, err_desc: str | None = None) -> str:
    code = (err_code or "").strip().lower()
    desc = (err_desc or "").strip().lower()
    if code == "access_denied":
        return "您已拒绝或取消 Google 授权；原账户与凭据未受影响，可随时重新发起。"
    if "redirect_uri_mismatch" in code or "redirect_uri_mismatch" in desc:
        return "回调地址不匹配（redirect_uri_mismatch）：请在 Google Cloud Console 将已授权重定向 URI 配置为表单显示的回调地址。"
    if code == "invalid_client":
        return "OAuth 客户端无效（invalid_client）：请核对 Client ID、客户端类型与 Client Secret 是否匹配。"
    if code == "invalid_grant":
        return "授权码已过期或已被使用（invalid_grant）：请重新点击 Google 登录发起授权。"
    if code == "org_internal":
        return "Google OAuth 同意屏幕受组织策略限制，或当前账号未加入测试用户名单。"
    return f"Google OAuth 授权失败（{code or 'unknown_error'}），请核对客户端配置后重试。"


def _fail_flow(flow: dict[str, Any], message: str) -> tuple[bool, int, str]:
    flow["status"] = "failed"
    flow["error"] = message
    flow.pop("staged_credentials", None)
    return False, 400, message


def _exchange_and_verify_google(flow: dict[str, Any], clean_code: str, now: float) -> tuple[bool, int, str]:
    token_form = {
        "grant_type": "authorization_code",
        "code": clean_code,
        "client_id": str(flow["client_id"]),
        "redirect_uri": str(flow["redirect_uri"]),
        "code_verifier": str(flow["code_verifier"]),
        **({"client_secret": str(flow["client_secret"])} if flow.get("client_secret") else {}),
    }
    try:
        token_resp = _call_token_endpoint(GOOGLE_TOKEN_URI, token_form)
    except ProviderHttpError as exc:
        body_text = str(getattr(exc, "body", "") or "").lower()
        for code_key in ("redirect_uri_mismatch", "invalid_client", "invalid_grant"):
            if code_key in body_text:
                return _fail_flow(flow, _friendly_oauth_error(code_key))
        return _fail_flow(flow, f"Google 令牌交换网络或服务错误（{safe_error(exc)}），请检查配置与网络后重试。")
    except Exception as exc:
        return _fail_flow(flow, f"Google 令牌交换失败（{safe_error(exc)}），请稍后重试。")

    if not isinstance(token_resp, dict):
        return _fail_flow(flow, "Google 令牌端点响应格式无效，请检查服务或代理后重新授权。")
    if token_resp.get("error"):
        return _fail_flow(flow, _friendly_oauth_error(str(token_resp["error"]), str(token_resp.get("error_description") or "")))

    access_token = str(token_resp.get("access_token") or "").strip()
    if not access_token:
        return _fail_flow(flow, "Google 令牌端点未返回有效 Access Token。")

    granted_scope = str(token_resp.get("scope") or "").strip()
    tokens = {item.strip() for item in granted_scope.split() if item.strip()}
    if GOOGLE_REQUIRED_SCOPE not in tokens and "gmail.modify" not in tokens:
        return _fail_flow(flow, "Google 授权缺少必需的 gmail.modify 权限范围，请重新发起授权并勾选邮件访问权限。")

    try:
        profile = _call_profile_endpoint(GOOGLE_PROFILE_URI, access_token)
    except Exception as exc:
        return _fail_flow(flow, f"无法核实 Gmail 账户邮箱身份（{safe_error(exc)}），请确认已在 Google Cloud 启用 Gmail API。")

    verified_email = str((profile or {}).get("emailAddress") or "").strip().lower()
    if not verified_email or "@" not in verified_email:
        return _fail_flow(flow, "Gmail users.getProfile 未返回有效的邮箱地址。")

    refresh_token = str(token_resp.get("refresh_token") or "").strip()
    keep_existing_refresh = False

    if flow.get("intent") == "create":
        if _email_exists(verified_email):
            return _fail_flow(flow, f"邮箱账户 {verified_email} 已存在，不能重复添加或覆盖现有账户。")
        if not refresh_token:
            return _fail_flow(flow, "Google 未返回离线刷新令牌（Refresh Token），无法用于后台持续同步；请重新授权并确认同意离线访问。")
    else:
        try:
            expected_email, _, _, saved_creds = _load_account_for_reauthorize(uuid.UUID(str(flow["account_id"])))
        except Exception as exc:
            return _fail_flow(flow, str(exc))
        if verified_email != expected_email:
            return _fail_flow(flow, f"当前授权的 Google 邮箱（{verified_email}）与原账户邮箱（{expected_email}）不一致，请使用 {expected_email} 重新授权。")
        if not refresh_token:
            if str(saved_creds.get("client_id") or "").strip() == str(flow["client_id"]).strip() and str(saved_creds.get("refresh_token") or "").strip():
                keep_existing_refresh = True
            else:
                return _fail_flow(flow, "重新授权未返回新的 Refresh Token，且无相同客户端的既有有效 Refresh Token 可保留，请重新授权。")

    staged: dict[str, Any] = {
        "client_id": str(flow["client_id"]),
        "token_uri": GOOGLE_TOKEN_URI,
        "scope": granted_scope,
        "access_token": access_token,
        **({"client_secret": str(flow["client_secret"])} if flow.get("client_secret") else {}),
        **({"refresh_token": refresh_token} if refresh_token else {}),
    }
    if token_resp.get("expires_in") is not None:
        try:
            staged["expires_at"] = now + float(token_resp["expires_in"])
        except (TypeError, ValueError):
            pass

    flow["status"] = "authorized"
    flow["verified_email"] = verified_email
    flow["staged_credentials"] = staged
    flow["keep_existing_refresh_token"] = keep_existing_refresh
    flow["error"] = None
    flow.pop("code_verifier", None)
    flow.pop("client_secret", None)
    return True, 200, f"已完成 Google 账号 {verified_email} 授权，请返回 kkmail 点击保存完成确认。"


def complete_oauth_callback(
    provider: str,
    *,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> tuple[bool, int, str]:
    norm_provider = (provider or "").strip().lower()
    if norm_provider != "google":
        return False, 400, "不支持的 OAuth 供应商回调。"
    clean_state = (state or "").strip()
    if not clean_state or not _STATE_RE.match(clean_state):
        return False, 400, "授权回调缺少有效的 state 参数，已拒绝处理。"

    store = _flow_store()
    try:
        state_record = load_json_secret(store, f"oauth_state:{clean_state}")
    except KeyError:
        return False, 400, "授权状态无效、已过期或已被使用，请返回 kkmail 重新发起授权。"

    flow_id = str(state_record.get("flow_id") or "").strip()
    if not flow_id or state_record.get("provider") != norm_provider:
        _delete_ref(store, f"oauth_state:{clean_state}")
        return False, 400, "授权状态与当前供应商不匹配，已拒绝处理。"

    with credential_edit(store, f"oauth_flow:{flow_id}") as flow:
        _delete_ref(store, f"oauth_state:{clean_state}")
        if not flow or flow.get("provider") != norm_provider or not secrets.compare_digest(str(flow.get("state") or ""), clean_state):
            return False, 400, "授权状态校验失败，已拒绝处理。"
        now = time.time()
        if flow.get("status") == "cancelled":
            return False, 400, "该授权流程已取消，请返回 kkmail 重新发起。"
        if now > float(flow.get("expires_at") or 0):
            flow["status"] = "expired"
            flow["error"] = EXPIRED_FLOW_MESSAGE
            flow["code_consumed"] = True
            flow.pop("staged_credentials", None)
            return False, 400, EXPIRED_FLOW_MESSAGE
        if flow.get("code_consumed") or flow.get("status") != "pending":
            return False, 400, "授权回调已被处理，拒绝重复请求。"

        flow["code_consumed"] = True
        if error:
            return _fail_flow(flow, _friendly_oauth_error(error, error_description))
        clean_code = (code or "").strip()
        if not clean_code:
            return _fail_flow(flow, "授权回调缺少授权码（code），请返回 kkmail 重新发起授权。")

        code_ref = f"oauth_code:{hashlib.sha256(f'{norm_provider}:{clean_code}'.encode('utf-8')).hexdigest()}"
        with credential_edit(store, code_ref) as claim:
            if claim:
                return _fail_flow(flow, "该授权码已被使用，拒绝重放。")
            claim.update({"flow_id": flow_id, "used_at": now})
        return _exchange_and_verify_google(flow, clean_code, now)


def _public_flow_view(flow: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    status = str(flow.get("status") or "pending")
    error = flow.get("error")
    expires_at = float(flow.get("expires_at") or 0)
    if status in ("pending", "authorized") and now > expires_at:
        status = "expired"
        error = error or EXPIRED_FLOW_MESSAGE
    return {
        "flow_id": str(flow["flow_id"]),
        "provider": str(flow.get("provider") or "google"),
        "intent": str(flow.get("intent") or "create"),
        "account_id": flow.get("account_id"),
        "group_id": flow.get("group_id"),
        "client_type": str(flow.get("client_type") or "public"),
        "client_id": str(flow.get("client_id") or ""),
        "status": status,
        "verified_email": flow.get("verified_email") if status != "expired" else None,
        "error": error,
        "redirect_uri": str(flow.get("redirect_uri") or ""),
        "expires_at": expires_at,
    }


def _expire_flow_if_needed(store: CredentialStore, flow_id: str, flow: dict[str, Any], sess_key: str) -> None:
    if str(flow.get("status") or "pending") in ("pending", "authorized") and time.time() > float(flow.get("expires_at") or 0):
        state = str(flow.get("state") or "").strip()
        if state:
            _delete_ref(store, f"oauth_state:{state}")
        with credential_edit(store, f"oauth_flow:{flow_id}") as current:
            if current:
                current["status"] = "expired"
                current["error"] = current.get("error") or EXPIRED_FLOW_MESSAGE
                current.pop("staged_credentials", None)
                current.pop("code_verifier", None)
                current.pop("client_secret", None)
        _clear_matching_active_pointer(store, sess_key, flow_id)


def get_oauth_flow_status(flow_id: str, principal: AuthPrincipal) -> dict[str, Any]:
    clean_id = (flow_id or "").strip()
    if not clean_id:
        raise LookupError("OAuth 授权流程不存在")
    store = _flow_store()
    try:
        flow = load_json_secret(store, f"oauth_flow:{clean_id}")
    except KeyError as exc:
        raise LookupError("OAuth 授权流程不存在或已取消") from exc
    _verify_flow_owner(flow, principal)
    view = _public_flow_view(flow)
    if view["status"] == "expired" and flow.get("status") != "expired":
        _expire_flow_if_needed(store, clean_id, flow, session_binding_key(principal))
    return view


def get_active_oauth_flow(principal: AuthPrincipal) -> dict[str, Any] | None:
    sess_key = session_binding_key(principal)
    store = _flow_store()
    try:
        pointer = load_json_secret(store, f"oauth_active:{sess_key}")
    except KeyError:
        return None
    flow_id = str(pointer.get("flow_id") or "").strip()
    if not flow_id:
        return None
    try:
        flow = load_json_secret(store, f"oauth_flow:{flow_id}")
        _verify_flow_owner(flow, principal)
    except (KeyError, PermissionError, LookupError):
        return None
    view = _public_flow_view(flow)
    if view["status"] == "expired":
        _expire_flow_if_needed(store, flow_id, flow, sess_key)
        return None
    if view["status"] in ("cancelled", "consumed"):
        return None
    return view


def cancel_oauth_flow(flow_id: str, principal: AuthPrincipal) -> dict[str, Any]:
    clean_id = (flow_id or "").strip()
    if not clean_id:
        raise LookupError("OAuth 授权流程不存在")
    store = _flow_store()
    try:
        flow = load_json_secret(store, f"oauth_flow:{clean_id}")
    except KeyError:
        return {"ok": True, "status": "cancelled"}
    _verify_flow_owner(flow, principal)
    state = str(flow.get("state") or "").strip()
    if state:
        _delete_ref(store, f"oauth_state:{state}")
    _delete_ref(store, f"oauth_flow:{clean_id}")
    _clear_matching_active_pointer(store, session_binding_key(principal), clean_id)
    return {"ok": True, "status": "cancelled"}


def consume_oauth_flow_for_create(
    session: Session,
    *,
    flow_id: str,
    principal: AuthPrincipal | None,
    provider: str,
    config: dict[str, Any] | None,
    group_id: uuid.UUID | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    clean_id = (flow_id or "").strip()
    store = _flow_store()
    ref = f"oauth_flow:{clean_id}"
    sess_arg = session if isinstance(store, (DbCredentialStore, CompositeCredentialStore)) else None
    with credential_edit(store, ref, session=sess_arg) as flow:
        _verify_flow_owner(flow, principal)
        if time.time() > float(flow.get("expires_at") or 0):
            if principal is not None:
                _clear_matching_active_pointer(store, session_binding_key(principal), clean_id)
            raise ValueError("OAuth 授权结果已过期，请重新发起授权")
        if flow.get("consumed") or flow.get("status") != "authorized":
            raise ValueError("OAuth 授权尚未完成或授权结果已被使用，请重新发起授权")
        if flow.get("intent") != "create":
            raise ValueError("该 OAuth 授权流程仅用于重新授权既有账户，不能用于新建账户")
        if flow.get("account_provider") != (provider or "").lower():
            raise ValueError("OAuth 授权协议与当前账户协议不匹配")
        if group_id is not None and session.get(AccountGroup, group_id) is None:
            raise LookupError("group not found")
        verified_email = str(flow.get("verified_email") or "").strip().lower()
        staged = dict(flow.get("staged_credentials") or {})
        if not verified_email or not staged.get("refresh_token") or not staged.get("client_id"):
            raise ValueError("OAuth 授权结果缺少已核实的邮箱或离线凭据")
        merged_config = {
            **(config or {}),
            "provider_profile": str(flow.get("provider") or "google"),
            "oauth_client_type": str(flow.get("client_type") or "public"),
        }
        from mail_core.accounts.connection import validate_connection

        validate_connection(verified_email, (provider or "").lower(), merged_config, staged)
        if session.scalar(select(Account.id).where(Account.email == verified_email)) is not None:
            raise ValueError(f"邮箱账户 {verified_email} 已存在，不能重复添加或覆盖现有账户")
        flow["consumed"] = True
        flow["status"] = "consumed"
        flow.pop("staged_credentials", None)

    _delete_ref(store, ref, session=session)
    if principal is not None:
        _clear_matching_active_pointer(store, session_binding_key(principal), clean_id, session=session)
    return verified_email, merged_config, staged


def consume_oauth_flow_for_reauthorize(
    session: Session,
    *,
    account: Account,
    flow_id: str,
    principal: AuthPrincipal | None,
    config_patch: dict[str, Any] | None,
    group_id: uuid.UUID | None | object = ...,
) -> dict[str, Any]:
    clean_id = (flow_id or "").strip()
    store = _flow_store()
    ref = f"oauth_flow:{clean_id}"
    sess_arg = session if isinstance(store, (DbCredentialStore, CompositeCredentialStore)) else None
    with credential_edit(store, ref, session=sess_arg) as flow:
        _verify_flow_owner(flow, principal)
        if time.time() > float(flow.get("expires_at") or 0):
            if principal is not None:
                _clear_matching_active_pointer(store, session_binding_key(principal), clean_id)
            raise ValueError("OAuth 授权结果已过期，请重新发起授权")
        if flow.get("consumed") or flow.get("status") != "authorized":
            raise ValueError("OAuth 授权尚未完成或授权结果已被使用，请重新发起授权")
        if flow.get("intent") != "reauthorize" or str(flow.get("account_id") or "") != str(account.id):
            raise ValueError("OAuth 授权流程与目标编辑账户不匹配")
        if (account.provider or "").lower() != str(flow.get("account_provider") or "").lower():
            raise ValueError("不能通过 OAuth 重新授权切换账户协议")
        if group_id is not ... and group_id is not None and session.get(AccountGroup, group_id) is None:
            raise LookupError("group not found")
        verified_email = str(flow.get("verified_email") or "").strip().lower()
        if verified_email != account.email.strip().lower():
            raise ValueError(f"授权邮箱（{verified_email}）与当前账户（{account.email}）不一致")

        staged = dict(flow.get("staged_credentials") or {})
        keep_existing_refresh = bool(flow.get("keep_existing_refresh_token"))
        client_type = str(flow.get("client_type") or "public")
        provider_profile = str(flow.get("provider") or "google")
        merged_config = {
            **(account.config or {}),
            **(config_patch or {}),
            "provider_profile": provider_profile,
            "oauth_client_type": client_type,
        }
        from mail_core.accounts.connection import validate_connection

        validate_connection(account.email, account.provider, merged_config, None, require_credentials=False)
        cred_ref = account.credential_ref or f"account:{account.id}"
        with credential_edit(get_credential_store(), cred_ref, session=session) as saved:
            if keep_existing_refresh and not staged.get("refresh_token"):
                if str(saved.get("client_id") or "").strip() == str(staged.get("client_id") or "").strip() and str(saved.get("refresh_token") or "").strip():
                    staged["refresh_token"] = str(saved["refresh_token"])
                else:
                    raise ValueError("缺少可复用的有效 Refresh Token，请重新发起授权")
            if not staged.get("refresh_token") or not staged.get("client_id"):
                raise ValueError("OAuth 授权结果缺少必需的凭据字段")
            merged = {**saved, **staged}
            if client_type == "public" and "client_secret" not in staged:
                merged.pop("client_secret", None)
            if "expires_at" not in staged:
                merged.pop("expires_at", None)
            validate_connection(account.email, account.provider, merged_config, merged)
            saved.clear()
            saved.update(merged)

        flow["consumed"] = True
        flow["status"] = "consumed"
        flow.pop("staged_credentials", None)

    account.credential_ref = cred_ref
    account.config = merged_config
    if account.sync_status in ("failed", "auth_failed"):
        account.sync_status = "idle"
    _delete_ref(store, ref, session=session)
    if principal is not None:
        _clear_matching_active_pointer(store, session_binding_key(principal), clean_id, session=session)
    return merged_config
