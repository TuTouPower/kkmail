"""Server-controlled Microsoft device polling, shared durable flow and final save."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

from mail_core.accounts.credentials import credential_edit
from mail_core.accounts.microsoft_oauth import (
    MICROSOFT_SCOPE, authority, friendly_error, http_error, response_error, stage_verified_response,
)
from mail_core.providers.http import ProviderHttpError


class DevicePollTooSoon(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("device-code poll interval has not elapsed")


def begin_device_authorization(flow: dict) -> None:
    from mail_core.accounts import oauth_flow as lifecycle
    try:
        response = lifecycle._call_token_endpoint(authority(flow['tenant']) + '/devicecode',
            {'client_id': flow['client_id'], 'scope': MICROSOFT_SCOPE})
    except ProviderHttpError as exc:
        raise ValueError(friendly_error(*http_error(exc))) from None
    except Exception:
        raise ValueError('无法申请微软设备验证码，请检查网络与公共客户端配置后重试。') from None
    if not isinstance(response, dict) or response.get('error'):
        raise ValueError(friendly_error(*response_error(response)))
    try:
        lifetime, interval = float(response['expires_in']), float(response.get('interval', 5))
        uri = urlsplit(str(response['verification_uri']))
        official = ((uri.hostname in ('microsoft.com', 'www.microsoft.com') and uri.path == '/devicelogin')
                    or (uri.hostname == 'login.microsoftonline.com' and uri.path == '/common/oauth2/deviceauth'))
        if (not official or uri.scheme != 'https' or uri.port not in (None, 443)
                or uri.username or uri.password or uri.query or uri.fragment):
            raise ValueError('untrusted URI')
        if not all(math.isfinite(v) and v > 0 for v in (lifetime, interval)):
            raise ValueError('invalid lifetime')
        if not isinstance(response.get('device_code'), str) or not response['device_code']:
            raise ValueError('missing device code')
        if not isinstance(response.get('user_code'), str) or not response['user_code']:
            raise ValueError('missing user code')
    except (ValueError, TypeError, KeyError):
        raise ValueError('微软设备验证码响应无效或验证地址不受信，请核对应用配置后重试。') from None
    now = lifecycle.time.time()
    interval = max(5.0, interval)
    flow.update(device_code=response['device_code'], user_code=response['user_code'],
                verification_uri=response['verification_uri'], interval=interval,
                expires_at=min(flow['expires_at'], now + lifetime), next_poll_at=now + interval)
    flow.pop('client_secret', None)


def poll_device_flow(flow_id, principal):
    from mail_core.accounts import oauth_flow as lifecycle
    store = lifecycle._flow_store()
    with credential_edit(store, f'oauth_flow:{flow_id}') as flow:
        if not flow:
            raise LookupError('OAuth 授权流程不存在或已取消')
        lifecycle._verify_flow_owner(flow, principal)
        if flow.get('provider') != 'microsoft' or flow.get('method') != 'device_code':
            raise ValueError('当前流程不是 Microsoft 设备码登录')
        now = lifecycle.time.time()
        if flow['status'] != 'pending':
            return lifecycle._public_flow_view(flow)
        if now >= flow['expires_at']:
            flow.update(status='expired', error=lifecycle.EXPIRED_FLOW_MESSAGE)
            flow.pop('device_code', None)
            return lifecycle._public_flow_view(flow)
        if now < flow['next_poll_at']:
            raise DevicePollTooSoon(max(1, math.ceil(flow['next_poll_at'] - now)))
        # The durable flow lock covers due check + HTTP exchange, including across API processes.
        interval = float(flow['interval'])
        flow['next_poll_at'] = now + interval
        retry_after = 0.0
        try:
            response = lifecycle._call_token_endpoint(authority(flow['tenant']) + '/token', {
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'client_id': flow['client_id'], 'device_code': flow['device_code'],
            })
        except ProviderHttpError as exc:
            code, description = http_error(exc)
            if exc.status == 429:
                code = 'slow_down'
                try:
                    retry_after = float((exc.headers or {}).get('retry-after', 0))
                except (TypeError, ValueError):
                    pass
            response = {'error': code or 'network_error', 'error_description': description}
        except Exception:
            response = {'error': 'network_error'}
        lifecycle._verify_flow_owner(flow, principal)
        now = lifecycle.time.time()
        if now >= flow['expires_at']:
            flow.update(status='expired', error=lifecycle.EXPIRED_FLOW_MESSAGE)
            flow.pop('device_code', None)
        else:
            code, description = response_error(response)
            if code == 'authorization_pending':
                flow['next_poll_at'] = now + interval
            elif code == 'slow_down':
                interval = max(interval + 5, retry_after if math.isfinite(retry_after) else 0)
                flow.update(interval=interval, next_poll_at=now + interval)
            elif code:
                message = ('微软设备码轮询网络异常，请取消后重试；原凭据未变。'
                           if code == 'network_error' else friendly_error(code, description))
                lifecycle._fail_flow(flow, message)
            else:
                stage_verified_response(flow, response, now)
        return lifecycle._public_flow_view(flow)
