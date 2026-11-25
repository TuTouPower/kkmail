"""IMAP target host validation helpers backed by ``mail_core.net.policy``.

Pin-IP SSRF enforcement (eliminating DNS rebinding TOCTOU) and proxy
tunneling run at dial time inside :mod:`mail_core.net.dialer`. This module
provides synchronous config-time syntactic validation and provider policy
helpers without build-time DNS lookups or post-connect ``getpeername()`` checks.
"""

from __future__ import annotations

from mail_core.net.policy import (
    OutboundSecurityPolicy,
    is_loopback_host,
    is_restricted_ip,
    is_syntactic_private_host,
    private_hosts_allowed,
)

MICROSOFT_DOMAINS = frozenset((
    "outlook.com",
    "outlook.cn",
    "outlook.de",
    "hotmail.com",
    "hotmail.co.uk",
    "hotmail.fr",
    "hotmail.de",
    "hotmail.it",
    "hotmail.es",
    "hotmail.co.jp",
    "live.com",
    "live.cn",
    "live.co.uk",
    "live.fr",
    "live.de",
    "msn.com",
))

MICROSOFT_IMAP_HOSTS = frozenset((
    "outlook.office365.com",
    "outlook.office.com",
    "imap-mail.outlook.com",
    "imap.outlook.com",
    "imap.hotmail.com",
    "partner.outlook.cn",
))


def is_private_host(host: str) -> bool:
    """Syntactic private/local/restricted-IP check without DNS side effects."""
    return is_syntactic_private_host(host)


def validate_imap_host(host: str) -> None:
    """Validate IMAP host syntax and reject private/loopback literals unless allowed."""
    OutboundSecurityPolicy.from_env().validate_target_for_proxy(host)


def reject_microsoft_imap(email: str, config: dict) -> None:
    host = str(config.get("imap_host") or config.get("host") or "").strip().lower().rstrip(".")
    if (
        email.strip().lower().rsplit("@", 1)[-1] in MICROSOFT_DOMAINS
        or host in MICROSOFT_IMAP_HOSTS
        or config.get("provider_profile") == "microsoft"
    ):
        raise ValueError("Microsoft IMAP is not supported; use Microsoft Graph OAuth")
