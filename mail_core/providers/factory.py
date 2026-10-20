"""Build a MailProvider from an Account row + credential store."""

from __future__ import annotations

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.storage.models import Account
from mail_core.providers.base import MailProvider
from mail_core.providers.gmail import GmailProvider
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider
from mail_core.providers.stub_memory import MemoryProvider


def build_provider(account: Account, store: CredentialStore | None = None) -> MailProvider:
    store = store or get_credential_store()
    provider = (account.provider or "").lower()
    cfg = dict(account.config or {})

    if provider == "stub" or provider == "memory":
        return MemoryProvider.from_config(cfg)

    if provider == "imap":
        if not account.credential_ref:
            raise ValueError("imap account missing credential_ref")
        password = store.get_secret(account.credential_ref)
        host = cfg.get("imap_host") or cfg.get("host")
        port = int(cfg.get("imap_port") or cfg.get("port") or 143)
        user = cfg.get("imap_user") or cfg.get("username") or account.email
        use_ssl = bool(cfg.get("use_ssl") or cfg.get("imap_ssl") or False)
        if not host:
            raise ValueError("imap account config missing imap_host")
        return ImapProvider(host=host, port=port, username=user, password=password, use_ssl=use_ssl)

    if provider == "gmail":
        return GmailProvider(credential_ref=account.credential_ref or "")

    if provider == "graph":
        return GraphProvider(credential_ref=account.credential_ref or "")

    raise ValueError(f"unknown provider type {account.provider!r}")
