"""Microsoft Graph authorization protocol and verified account identity."""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from mail_core.providers.http import ProviderHttpError

MICROSOFT_SCOPE = 'https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access'
PROFILE_URI = 'https://graph.microsoft.com/v1.0/me?$select=id,mail'
MAILBOX_URI = 'https://graph.microsoft.com/v1.0/me/mailFolders/inbox?$select=id'
# p056: built-in public client (no Client Secret, RFC 6749 public-client
# flow) so self-hosted users can onboard without registering an Azure app.
DEFAULT_MICROSOFT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
DEFAULT_MICROSOFT_REDIRECT_URI = "http://localhost:8080"
MICROSOFT_TOKEN_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_ME_URI = "https://graph.microsoft.com/v1.0/me"

TokenPostFn = Callable[[str, dict[str, str]], dict[str, Any]]
ProfileGetFn = Callable[[str, str], dict[str, Any]]


def default_microsoft_client_id() -> str:
    """Effective public Client ID: MICROSOFT_CLIENT_ID env overrides the built-in."""
    return (os.environ.get("MICROSOFT_CLIENT_ID") or "").strip() or DEFAULT_MICROSOFT_CLIENT_ID


def parse_redirect_code(redirected_url: str) -> str:
    """Extract the authorization code from a pasted post-consent redirect URL."""
    params = parse_qs(urlsplit((redirected_url or "").strip()).query)
    errors = params.get("error")
    if errors:
        description = (params.get("error_description") or [""])[0].strip()
        raise ValueError(f"微软授权失败：{description or errors[0]}")
    codes = params.get("code")
    if not codes or not codes[0].strip():
        raise ValueError("链接中未找到授权码 (code)，请确保复制的是授权完成后的完整地址")
    return codes[0]


def exchange_redirect_url_for_tokens(
    redirected_url: str,
    client_id: str | None = None,
    *,
    token_post: TokenPostFn | None = None,
    profile_get: ProfileGetFn | None = None,
) -> dict[str, Any]:
    """Exchange a pasted redirect URL for tokens and the verified account email.

    Public-client flow: no client_secret is sent. Transports default to the
    shared OAuth flow hooks (``oauth_flow._call_token_endpoint`` /
    ``_call_profile_endpoint``), so tests can inject fakes either here or via
    ``oauth_flow.set_oauth_http_hooks``. Provider error descriptions are
    mapped through :func:`friendly_error` and never echoed (they may carry
    tokens or tenant details).
    """
    from mail_core.accounts import oauth_flow as lifecycle

    code = parse_redirect_code(redirected_url)
    effective_client_id = (client_id or "").strip() or default_microsoft_client_id()
    post = token_post or lifecycle._call_token_endpoint
    get = profile_get or lifecycle._call_profile_endpoint
    form = {
        "client_id": effective_client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DEFAULT_MICROSOFT_REDIRECT_URI,
        "scope": MICROSOFT_SCOPE,
    }
    try:
        result = post(MICROSOFT_TOKEN_URI, form)
    except ProviderHttpError as exc:
        err, desc = http_error(exc)
        raise ValueError(
            friendly_error(err, desc) if err else "Microsoft 令牌交换网络或服务错误，请检查网络后重试。"
        ) from exc
    except Exception as exc:
        raise ValueError("Microsoft 令牌交换失败，请检查网络后重试。") from exc
    if not isinstance(result, dict):
        raise ValueError("Microsoft 令牌端点响应格式无效，请重试。")
    if result.get("error"):
        raise ValueError(friendly_error(*response_error(result)))
    access = result.get("access_token")
    refresh = result.get("refresh_token")
    if not isinstance(access, str) or not access.strip():
        raise ValueError("Microsoft 未返回有效 Access Token，请重新授权。")
    if not isinstance(refresh, str) or not refresh.strip():
        raise ValueError("Microsoft 未返回 Refresh Token，无法后台继续同步；请重新授权并允许持续访问。")
    try:
        profile = get(MICROSOFT_ME_URI, access)
    except Exception as exc:
        raise ValueError("无法核实 Microsoft 账号邮箱，请确认授权后重试。") from exc
    email = profile.get("mail") or profile.get("userPrincipalName") if isinstance(profile, dict) else None
    if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
        raise ValueError("Graph /me 未返回已核实的邮箱地址；账号可能没有可用邮箱，请确认 Microsoft 邮箱服务已启用。")
    return {
        "client_id": effective_client_id,
        "access_token": access,
        "refresh_token": refresh,
        "email": email.strip().lower(),
    }
_TENANT = re.compile(r'^(common|consumers|organizations|[a-zA-Z0-9][a-zA-Z0-9.-]{0,252})$')


def authority(tenant: str) -> str:
    if not _TENANT.fullmatch(tenant):
        raise ValueError('微软租户格式无效，请选择账号类型或填写租户 ID/域名')
    return f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0'


def resolve_tenant(tenant: str | None, config: dict, credentials: dict) -> str:
    existing = config.get('oauth_tenant')
    if not existing and credentials.get('token_uri'):
        parts = urlsplit(str(credentials['token_uri']))
        if parts.hostname == 'login.microsoftonline.com':
            existing = parts.path.strip('/').split('/')[0]
    selected = (tenant or existing or 'common').strip().lower()
    authority(selected)
    if existing and selected != str(existing).lower():
        raise ValueError('重新授权的租户/账号类型与原账户不一致，请使用原配置')
    return selected


def friendly_error(code: str, description: str | None = None) -> str:
    # Never echo provider descriptions: they may include tokens or tenant details.
    text = f'{code} {description or ""}'.lower()
    if any(part in text for part in ('65001', '65004', '90094', 'consent_required', 'interaction_required')):
        return '微软尚未同意所需权限；请完成同意或联系组织管理员批准 Graph 委托权限。'
    if code in ('access_denied', 'authorization_declined'):
        return 'Microsoft 授权已拒绝或取消；原凭据未变，可重新登录。'
    if code in ('expired_token', 'bad_verification_code', 'invalid_grant'):
        return '微软验证码或授权码已失效，请重新发起登录。'
    if '50011' in text or 'redirect_uri_mismatch' in text:
        return '微软回调地址不匹配：按表单地址登记 Web 或移动和桌面应用回调，核对路径与端口规则。'
    if any(part in text for part in ('7000215', '7000218', '7000222', 'invalid_client')):
        return 'Microsoft 客户端配置无效或 Secret 过期：核对 Client ID、应用类型和 Secret value（不是 secret ID）。设备码需在 Authentication 启用公共客户端流程。'
    if any(part in text for part in ('50020', '50194', '700016', 'unauthorized_client', 'invalid_tenant')):
        return '微软账号类型、租户或应用注册不匹配；核对 App registrations 的账号类型及 Authentication 公共客户端设置，或切换浏览器登录。'
    return 'Microsoft 登录失败；请核对应用注册、租户、权限及组织策略后重试。'


def response_error(response: Any) -> tuple[str, str]:
    if isinstance(response, dict):
        return str(response.get('error') or ''), str(response.get('error_description') or '')
    return '', ''


def http_error(exc: ProviderHttpError) -> tuple[str, str]:
    if isinstance(exc.body, dict):
        return response_error(exc.body)
    try:
        return response_error(json.loads(exc.body or '{}'))
    except (TypeError, ValueError):
        return '', ''


def exchange_code(flow: dict, code: str, now: float) -> tuple[bool, int, str]:
    from mail_core.accounts import oauth_flow as lifecycle
    form = {'grant_type': 'authorization_code', 'client_id': flow['client_id'],
            'code': code, 'redirect_uri': flow['redirect_uri'], 'code_verifier': flow['code_verifier'],
            **({'client_secret': flow['client_secret']} if flow.get('client_secret') else {})}
    try:
        result = lifecycle._call_token_endpoint(authority(flow['tenant']) + '/token', form)
    except ProviderHttpError as exc:
        err, desc = http_error(exc)
        return lifecycle._fail_flow(flow, friendly_error(err, desc) if err else 'Microsoft 令牌交换网络或服务错误，请检查网络后重试。')
    except Exception:
        return lifecycle._fail_flow(flow, 'Microsoft 令牌交换失败，请检查网络与应用配置后重试。')
    return stage_verified_response(flow, result, now)


def stage_verified_response(flow: dict, response: Any, now: float) -> tuple[bool, int, str]:
    from mail_core.accounts import oauth_flow as lifecycle
    if not isinstance(response, dict):
        return lifecycle._fail_flow(flow, 'Microsoft 令牌端点响应格式无效，请重试。')
    if response.get('error'):
        return lifecycle._fail_flow(flow, friendly_error(*response_error(response)))
    access, refresh = response.get('access_token'), response.get('refresh_token')
    if not isinstance(access, str) or not access.strip():
        return lifecycle._fail_flow(flow, 'Microsoft 未返回有效 Access Token，请重新登录。')
    scopes = {s.lower().removeprefix('https://graph.microsoft.com/') for s in str(response.get('scope') or '').split()}
    if not {'mail.readwrite', 'user.read'} <= scopes:
        return lifecycle._fail_flow(flow, 'Microsoft 缺少 Mail.ReadWrite 或 User.Read 委托权限；请完成同意或联系管理员。')
    if not isinstance(refresh, str) or not refresh.strip():
        return lifecycle._fail_flow(flow, 'Microsoft 未返回 Refresh Token，无法后台继续同步；请重新登录并允许持续访问。')
    try:
        profile = lifecycle._call_profile_endpoint(PROFILE_URI, access)
        user_id, email = profile.get('id'), profile.get('mail')
        if not isinstance(user_id, str) or not user_id.strip():
            return lifecycle._fail_flow(flow, 'Graph /me 未返回可核对的微软用户身份。')
        if not isinstance(email, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            return lifecycle._fail_flow(flow, 'Graph /me 未返回已核实的邮箱地址；账号可能没有可用邮箱，请确认 Microsoft 邮箱服务已启用。')
        email = email.strip().lower()
        mailbox = lifecycle._call_profile_endpoint(MAILBOX_URI, access)
        if not isinstance(mailbox, dict) or not mailbox.get('id'):
            return lifecycle._fail_flow(flow, '当前 Microsoft 用户没有可访问的邮箱，请确认邮箱许可及管理员策略。')
    except Exception:
        return lifecycle._fail_flow(flow, '无法核实 Microsoft 身份或访问邮箱；请确认 User.Read/Mail.ReadWrite 权限、邮箱许可及网络。')
    if flow['intent'] == 'reauthorize':
        try:
            original_email, _, config, saved = lifecycle._load_account_for_reauthorize(uuid.UUID(flow['account_id']), 'microsoft')
        except (LookupError, ValueError):
            return lifecycle._fail_flow(flow, '原 Graph 账户已删除或不再可重新授权。')
        if email != original_email or (config.get('microsoft_user_id') and config['microsoft_user_id'] != user_id):
            return lifecycle._fail_flow(flow, '微软用户身份或邮箱与原账户不一致，请使用原账号登录；旧凭据未变。')
        if saved.get('client_id') and saved['client_id'] != flow['client_id']:
            return lifecycle._fail_flow(flow, '原账户客户端配置已变化，请重新发起授权。')
        try:
            resolve_tenant(flow['tenant'], config, saved)
        except ValueError:
            return lifecycle._fail_flow(flow, '原账户租户配置已变化，请重新发起授权。')
    elif lifecycle._email_exists(email):
        return lifecycle._fail_flow(flow, f'邮箱账户 {email} 已存在，不能重复添加或覆盖。')
    if lifecycle.time.time() >= float(flow['expires_at']):
        flow['status'] = 'expired'
        flow['error'] = lifecycle.EXPIRED_FLOW_MESSAGE
        return False, 400, lifecycle.EXPIRED_FLOW_MESSAGE
    staged = {'client_id': flow['client_id'], 'access_token': access, 'refresh_token': refresh,
              'token_uri': authority(flow['tenant']) + '/token', 'scope': str(response['scope']),
              **({'client_secret': flow['client_secret']} if flow.get('client_secret') else {})}
    try:
        lifetime = float(response.get('expires_in', 0))
        if math.isfinite(lifetime) and lifetime > 0:
            staged['expires_at'] = now + lifetime
    except (TypeError, ValueError):
        pass
    flow.update(status='authorized', verified_email=email, microsoft_user_id=user_id,
                staged_credentials=staged, error=None)
    for key in ('client_secret', 'code_verifier', 'device_code', 'user_code'):
        flow.pop(key, None)
    return True, 200, f'已完成 Microsoft 账号 {email} 授权，请返回 kkmail 点击保存完成确认。'
