"""Google authorization-code response and Gmail identity validation."""
import time
import uuid
from typing import Any

from mail_core.providers.http import ProviderHttpError
from mail_core.security.redact import safe_error

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

def _exchange_and_verify_google(flow: dict[str, Any], clean_code: str, now: float) -> tuple[bool, int, str]:
    from mail_core.accounts.oauth_flow import (
        EXPIRED_FLOW_MESSAGE, GOOGLE_TOKEN_URI, GOOGLE_PROFILE_URI, GOOGLE_REQUIRED_SCOPE,
        _call_token_endpoint, _call_profile_endpoint, _fail_flow,
        _email_exists, _load_account_for_reauthorize,
    )
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

    if time.time() >= float(flow.get("expires_at") or 0):
        return _fail_flow(flow, EXPIRED_FLOW_MESSAGE, status="expired")

    flow["status"] = "authorized"
    flow["verified_email"] = verified_email
    flow["staged_credentials"] = staged
    flow["keep_existing_refresh_token"] = keep_existing_refresh
    flow["error"] = None
    flow.pop("code_verifier", None)
    flow.pop("client_secret", None)
    return True, 200, f"已完成 Google 账号 {verified_email} 授权，请返回 kkmail 点击保存完成确认。"
