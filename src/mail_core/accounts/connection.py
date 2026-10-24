"""Provider-specific account connection validation (no network login)."""
from urllib.parse import urlsplit

MICROSOFT_DOMAINS = frozenset(('outlook.com', 'outlook.cn', 'hotmail.com', 'live.com', 'msn.com', 'hotmail.co.uk', 'live.co.uk', 'hotmail.fr', 'live.fr', 'hotmail.de', 'live.de', 'outlook.de'))
MICROSOFT_IMAP_HOSTS = frozenset(('outlook.office365.com', 'imap-mail.outlook.com', 'imap.outlook.com', 'imap.hotmail.com', 'outlook.office.com'))
PROFILES = {'other': {'imap'}, 'google': {'imap', 'gmail'}, 'microsoft': {'graph'}, 'qq': {'imap'}, 'netease_163': {'imap'}, 'netease_126': {'imap'}, 'netease_yeah': {'imap'}, 'icloud': {'imap'}, 'yahoo': {'imap'}, 'zoho': {'imap'}}
CREDENTIAL_FIELDS = {'imap': {'password', 'secret'}, 'gmail': {'client_id', 'client_secret', 'refresh_token', 'token_uri', 'scope'}, 'graph': {'client_id', 'client_secret', 'refresh_token', 'token_uri', 'scope'}}


def reject_microsoft_imap(email: str, config: dict) -> None:
    host = str(config.get('imap_host') or config.get('host') or '').strip().lower().rstrip('.')
    if (email.strip().lower().rsplit('@', 1)[-1] in MICROSOFT_DOMAINS or host in MICROSOFT_IMAP_HOSTS
            or config.get('provider_profile') == 'microsoft'):
        raise ValueError('Microsoft IMAP is not supported; use Microsoft Graph OAuth')


def merge_credentials(provider: str, old: dict, patch: dict) -> dict:
    result = dict(old)
    allowed = CREDENTIAL_FIELDS.get(provider, set(patch))
    for key, value in patch.items():
        if key not in allowed:
            raise ValueError(f'credentials.{key}: unsupported field')
        if not isinstance(value, str):
            raise ValueError(f'credentials.{key}: must be a string')
        if value:
            result[key] = value
    if provider in ('gmail', 'graph') and result != old:
        result.pop('access_token', None)
        result.pop('expires_at', None)
    return result


def validate_connection(email: str, provider: str, config: dict, credentials: dict | None, *, require_credentials: bool = True) -> None:
    if not isinstance(config, dict):
        raise ValueError('config: must be an object')
    profile = config.get('provider_profile')
    if profile is not None and (not isinstance(profile, str) or profile not in PROFILES or provider not in PROFILES[profile]):
        raise ValueError('config.provider_profile: incompatible provider')
    client_type = config.get('oauth_client_type', 'public')
    if not isinstance(client_type, str) or client_type not in ('public', 'confidential'):
        raise ValueError('config.oauth_client_type: unsupported client type')
    for key in ('imap_user', 'username'):
        if config.get(key) is not None and not isinstance(config.get(key), str):
            raise ValueError(f'config.{key}: must be a string')
    if provider == 'imap':
        for key in ('imap_host', 'host'):
            if config.get(key) is not None and not isinstance(config.get(key), str):
                raise ValueError(f'config.{key}: must be a string')
        reject_microsoft_imap(email, config)
        host = config.get('imap_host') or config.get('host')
        if not isinstance(host, str) or not host.strip():
            raise ValueError('config.imap_host: required')
        from mail_core.providers.factory import validate_imap_host
        validate_imap_host(host)
        for key in ('imap_port', 'port'):
            if key in config and config[key] is not None:
                port = config[key]
                if isinstance(port, bool) or not isinstance(port, (int, str)) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
                    raise ValueError('config.imap_port: must be 1–65535')
        if 'use_ssl' in config and not isinstance(config['use_ssl'], bool):
            raise ValueError('config.use_ssl: must be boolean')
    if not require_credentials or provider not in CREDENTIAL_FIELDS:
        return
    values = credentials or {}
    if not isinstance(values, dict):
        raise ValueError('credentials: must be an object')
    for key, val in values.items():
        if val is None:
            continue
        if key == 'expires_at':
            if isinstance(val, bool) or not isinstance(val, (int, float, str)):
                raise ValueError('credentials.expires_at: must be a number')
        elif key in CREDENTIAL_FIELDS.get(provider, set()) and not isinstance(val, str):
            raise ValueError(f'credentials.{key}: must be a string')
    if provider == "imap" and "refresh_token" in values:
        raise ValueError("credentials.refresh_token: unsupported field")
    required = ['password'] if provider == 'imap' else ['client_id', 'refresh_token']
    if provider in ('graph', 'gmail') and client_type == 'confidential':
        required.append('client_secret')
    for key in required:
        value = values.get(key) or (values.get('secret') if key == 'password' else None)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'credentials.{key}: required')
    if values.get('token_uri'):
        uri = urlsplit(str(values['token_uri']))
        hosts = {'oauth2.googleapis.com', 'www.googleapis.com'} if provider == 'gmail' else {'login.microsoftonline.com', 'login.live.com', 'login.microsoft.com'}
        if uri.scheme != 'https' or uri.hostname not in hosts or uri.username or uri.password or uri.port not in (None, 443):
            raise ValueError('credentials.token_uri: must use the provider HTTPS endpoint')
