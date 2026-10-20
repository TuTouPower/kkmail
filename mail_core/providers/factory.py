"""Build a MailProvider from an Account row + credential store."""

from __future__ import annotations

import json

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.storage.models import Account
from mail_core.providers.base import MailProvider
from mail_core.providers.gmail import GmailProvider
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import (
    BearerTransport,
    OAuthTokenClient,
    default_urllib_token_post,
    urllib_json_request,
)
from mail_core.providers.stub_memory import MemoryProvider


def _oauth_transport(
    *,
    credential_ref: str,
    store: CredentialStore,
    provider: str,
    token_http=None,
    api_http=None,
) -> BearerTransport:
    client = OAuthTokenClient(
        credential_ref=credential_ref,
        store=store,
        provider=provider,
        http_post=token_http or default_urllib_token_post,
    )
    base = "https://gmail.googleapis.com" if provider == "gmail" else "https://graph.microsoft.com/v1.0"
    api = api_http or urllib_json_request
    return BearerTransport(token_client=client, inner=api, base_url=base)


def build_provider(
    account: Account,
    store: CredentialStore | None = None,
    *,
    token_http=None,
    api_http=None,
) -> MailProvider:
    store = store or get_credential_store()
    provider = (account.provider or "").lower()
    cfg = dict(account.config or {})

    if provider == "stub" or provider == "memory":
        return MemoryProvider.from_config(cfg)

    if provider == "imap":
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
        return ImapProvider(host=host, port=port, username=user, password=password, use_ssl=use_ssl)

    if provider == "gmail":
        ref = account.credential_ref or ""
        if not ref:
            return GmailProvider(credential_ref="")
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="gmail",
            token_http=token_http,
            api_http=api_http,
        )
        return GmailProvider(credential_ref=ref, transport=transport)

    if provider == "graph":
        ref = account.credential_ref or ""
        if not ref:
            return GraphProvider(credential_ref="")
        transport = _oauth_transport(
            credential_ref=ref,
            store=store,
            provider="graph",
            token_http=token_http,
            api_http=api_http,
        )
        return GraphProvider(credential_ref=ref, transport=transport)

    raise ValueError(f"unknown provider type {account.provider!r}")
