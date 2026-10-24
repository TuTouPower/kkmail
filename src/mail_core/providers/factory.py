"""Build a MailProvider from an Account row + credential store."""

from __future__ import annotations

import ipaddress
import json
import logging
import socket

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.storage.models import Account
from mail_core.providers.base import MailProvider
from mail_core.providers.gmail import GmailProvider
from mail_core.providers.graph import GraphProvider
from mail_core.providers.host_security import is_restricted_ip, private_hosts_allowed
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import (
    BearerTransport,
    OAuthTokenClient,
    default_urllib_token_post,
    urllib_json_request,
)
from mail_core.providers.stub_memory import MemoryProvider

logger = logging.getLogger(__name__)


def _oauth_transport(
    *,
    credential_ref: str,
    store: CredentialStore,
    provider: str,
    token_http=None,
    api_http=None,
    timeout: float = 30.0,
) -> BearerTransport:
    client = OAuthTokenClient(
        credential_ref=credential_ref,
        store=store,
        provider=provider,
        http_post=token_http,
        timeout=timeout,
    )
    base = "https://gmail.googleapis.com" if provider == "gmail" else "https://graph.microsoft.com/v1.0"
    if api_http is not None:
        api = api_http
    else:
        api = lambda m, u, p=None, h=None: urllib_json_request(m, u, p, h, timeout=timeout)
    return BearerTransport(token_client=client, inner=api, base_url=base)


def is_private_host(host: str) -> bool:
    h = host.strip().lower()
    if h in ("localhost", "localhost.localdomain") or h.endswith(".local") or h.endswith(".localhost"):
        return True
    try:
        return is_restricted_ip(h)
    except ValueError:
        pass
    try:
        for res in socket.getaddrinfo(h, None):
            if is_restricted_ip(res[4][0]):
                return True
    except (socket.gaierror, socket.herror, OSError):
        pass
    return False


def validate_imap_host(host: str) -> None:
    if private_hosts_allowed():
        return
    if is_private_host(host):
        raise ValueError(f"imap host {host!r} is a private or loopback address (SSRF protection)")


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def build_provider(
    account: Account,
    store: CredentialStore | None = None,
    *,
    token_http=None,
    api_http=None,
    timeout: float | None = None,
    session: Any = None,
) -> MailProvider:
    store = store or get_credential_store()
    provider = (account.provider or "").lower()
    cfg = dict(account.config or {})

    if timeout is None and session is not None:
        try:
            from mail_core.accounts.settings_store import get_fetch_timeout_seconds
            timeout = get_fetch_timeout_seconds(session)
        except Exception:
            timeout = 30.0
    elif timeout is None:
        try:
            from mail_core.accounts.settings_store import get_fetch_timeout_seconds
            from mail_core.db.session import get_session_factory
            SessionFactory = get_session_factory()
            with SessionFactory() as s:
                timeout = get_fetch_timeout_seconds(s)
        except Exception:
            timeout = 30.0

    effective_timeout = float(timeout) if timeout is not None else 30.0

    if provider == "stub" or provider == "memory":
        return MemoryProvider.from_config(cfg)

    if provider == "imap":
        from mail_core.accounts.connection import reject_microsoft_imap
        reject_microsoft_imap(account.email, cfg)
        if not account.credential_ref:
            raise ValueError("imap account missing credential_ref")
        secret = store.get_secret(account.credential_ref)
        if isinstance(secret, dict):
            password = str(secret.get("password") or secret.get("secret") or "")
        elif isinstance(secret, str) and secret.strip().startswith("{"):
            try:
                data = json.loads(secret)
                if isinstance(data, dict):
                    password = str(data.get("password") or data.get("secret") or secret)
                else:
                    password = secret
            except Exception:
                password = secret
        else:
            password = str(secret or "")
        host = cfg.get("imap_host") or cfg.get("host")
        user = cfg.get("imap_user") or cfg.get("username") or account.email
        raw_ssl = cfg.get("use_ssl", True)
        # TLS by default; plaintext IMAP only when explicitly configured (e.g. loopback test fixture).
        use_ssl = raw_ssl if isinstance(raw_ssl, bool) else str(raw_ssl).strip().lower() not in ("0", "false", "no", "off")
        port = int(cfg.get("imap_port") or cfg.get("port") or (993 if use_ssl else 143))
        if not host:
            raise ValueError("imap account config missing imap_host")
        if not use_ssl:
            logger.warning("plaintext IMAP is configured; credentials and messages are unencrypted")
            if not _is_loopback_host(host):
                raise ValueError("plaintext IMAP is only allowed for loopback hosts")
        validate_imap_host(host)
        return ImapProvider(host=host, port=port, username=user, password=password, use_ssl=use_ssl, timeout=effective_timeout)

    if provider == "gmail":
        ref = account.credential_ref or ""
        if not ref:
            return GmailProvider(credential_ref="", timeout=effective_timeout)
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="gmail",
            token_http=token_http,
            api_http=api_http,
            timeout=effective_timeout,
        )
        return GmailProvider(credential_ref=ref, transport=transport, timeout=effective_timeout)

    if provider == "graph":
        ref = account.credential_ref or ""
        if not ref:
            return GraphProvider(credential_ref="", timeout=effective_timeout)
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="graph",
            token_http=token_http,
            api_http=api_http,
            timeout=effective_timeout,
        )
        return GraphProvider(credential_ref=ref, transport=transport, timeout=effective_timeout)

    raise ValueError(f"unknown provider type {account.provider!r}")
