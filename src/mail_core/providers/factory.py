"""Build a MailProvider from an Account row + credential store."""

from __future__ import annotations

import ipaddress
import json
import logging
import socket

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.storage.models import Account
from mail_core.providers.base import MailProvider
from mail_core.providers.connection_slots import (
    TrafficClass,
    default_permit_factory,
)
from mail_core.providers.gmail import GmailNotConfiguredError, GmailProvider
from mail_core.providers.graph import GraphNotConfiguredError, GraphProvider
from mail_core.providers.host_security import is_restricted_ip, private_hosts_allowed
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import (
    BearerTransport,
    OAuthTokenClient,
    default_urllib_token_post,
    urllib_json_request,
)
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.security.redact import safe_error

logger = logging.getLogger(__name__)


def _oauth_transport(
    *,
    credential_ref: str,
    store: CredentialStore,
    provider: str,
    token_http=None,
    api_http=None,
    timeout: float = 30.0,
    traffic_class: TrafficClass = TrafficClass.FOREGROUND,
    permit_factory=None,
) -> BearerTransport:
    # The token client scopes its own refresh permit (acquire → refresh →
    # release) before the API transport opens any mail connection.
    client = OAuthTokenClient(
        credential_ref=credential_ref,
        store=store,
        provider=provider,
        http_post=token_http,
        timeout=timeout,
        permit_factory=permit_factory,
        traffic_class=traffic_class,
    )
    base = "https://gmail.googleapis.com" if provider == "gmail" else "https://graph.microsoft.com/v1.0"
    if api_http is not None:
        api = api_http
    else:
        # The real urllib transport acquires one permit per urlopen
        # attempt and releases it during retry waits.
        api = lambda m, u, p=None, h=None: urllib_json_request(
            m, u, p, h, timeout=timeout,
            permit_factory=permit_factory, traffic_class=traffic_class,
        )
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
    traffic_class: TrafficClass | str = TrafficClass.FOREGROUND,
    permit_factory=None,
) -> MailProvider:
    """Build a provider wired into the global connection budget (§7).

    ``traffic_class`` is derived by the caller from the actual job type
    (see ``connection_slots.traffic_class_for_job``) and propagated
    explicitly into the provider/transport instances built here.
    ``permit_factory`` defaults to the shared production factory
    (dedicated control connections when a DB URL is configured).
    """
    store = store or get_credential_store()
    if permit_factory is None:
        permit_factory = default_permit_factory()
    if not isinstance(traffic_class, TrafficClass):
        traffic_class = TrafficClass(str(traffic_class))
    provider = (account.provider or "").lower()
    cfg = dict(account.config or {})

    if timeout is None and session is not None:
        try:
            from mail_core.accounts.settings_store import get_fetch_timeout_seconds
            timeout = get_fetch_timeout_seconds(session)
        except Exception as exc:
            logger.warning(
                "fetch timeout lookup failed for account id=%s; using default 30s: %s",
                account.id,
                safe_error(exc),
            )
            timeout = 30.0
    elif timeout is None:
        try:
            from mail_core.accounts.settings_store import get_fetch_timeout_seconds
            from mail_core.db.session import get_session_factory
            SessionFactory = get_session_factory()
            with SessionFactory() as s:
                timeout = get_fetch_timeout_seconds(s)
        except Exception as exc:
            logger.warning(
                "fetch timeout lookup failed for account id=%s; using default 30s: %s",
                account.id,
                safe_error(exc),
            )
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
            except json.JSONDecodeError:
                password = secret
            else:
                if isinstance(data, dict):
                    password_value = data.get("password") or data.get("secret")
                    if password_value is None:
                        raise ValueError("credential JSON missing password")
                    password = str(password_value)
                else:
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
        return ImapProvider(host=host, port=port, username=user, password=password, use_ssl=use_ssl, timeout=effective_timeout, traffic_class=traffic_class, permit_factory=permit_factory)

    if provider == "gmail":
        ref = account.credential_ref or ""
        if not ref:
            raise GmailNotConfiguredError("Gmail account missing credential_ref")
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="gmail",
            token_http=token_http,
            api_http=api_http,
            timeout=effective_timeout,
            traffic_class=traffic_class,
            permit_factory=permit_factory,
        )
        # Provider-level permit_factory stays None: the transport stack
        # already acquires per-request permits (no double counting).
        return GmailProvider(credential_ref=ref, transport=transport, timeout=effective_timeout, traffic_class=traffic_class)

    if provider == "graph":
        ref = account.credential_ref or ""
        if not ref:
            raise GraphNotConfiguredError("Graph account missing credential_ref")
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="graph",
            token_http=token_http,
            api_http=api_http,
            timeout=effective_timeout,
            traffic_class=traffic_class,
            permit_factory=permit_factory,
        )
        return GraphProvider(credential_ref=ref, transport=transport, timeout=effective_timeout, traffic_class=traffic_class)

    raise ValueError(f"unknown provider type {account.provider!r}")
