"""Shared IP checks for outbound IMAP host validation.

Known residual risk — DNS TOCTOU window (A350, accepted): the host is
resolved and checked at build time in ``factory.validate_imap_host``, but
``imaplib`` resolves the name again independently when connecting, and
:func:`validate_imap_peer_address` re-checks the connected peer only
after the TCP connection (and, for SSL, the TLS handshake) has already
been established. A DNS rebinding attacker can therefore make the
build-time check see a public address while the actual connection lands
on a restricted address: the connection itself (port probing / protocol
interaction with an internal service) can happen before the peer check
aborts the session. Credentials are still protected — the peer check
runs before login, so no password is ever sent to a restricted peer —
but the connection-level exposure is a residual risk accepted in place
of pinning the connection to the pre-resolved IP (which would require
replacing imaplib's transport and re-validating the TLS certificate
against the original hostname/SAN).
"""

from __future__ import annotations

import ipaddress
import os
import socket

MICROSOFT_DOMAINS = frozenset((
    "outlook.com",
    "outlook.cn",
    "hotmail.com",
    "live.com",
    "msn.com",
    "hotmail.co.uk",
    "live.co.uk",
    "hotmail.fr",
    "live.fr",
    "hotmail.de",
    "live.de",
    "outlook.de",
))
MICROSOFT_IMAP_HOSTS = frozenset((
    "outlook.office365.com",
    "imap-mail.outlook.com",
    "imap.outlook.com",
    "imap.hotmail.com",
    "outlook.office.com",
))


def private_hosts_allowed() -> bool:
    return os.environ.get("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_restricted_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # A171: anything that is not globally routable is restricted. The old
    # OR of is_private/is_loopback/is_link_local/is_reserved/is_unspecified
    # missed CGNAT 100.64.0.0/10 (is_private is False for it), multicast
    # 224.0.0.0/4 and IPv6 site-local fec0::/10. `not is_global` covers
    # CGNAT, but CPython reports multicast and fec0::/10 as is_global, so
    # those two ranges are added explicitly.
    return not ip.is_global or ip.is_multicast or getattr(ip, "is_site_local", False)


def validate_imap_peer_address(address: str) -> None:
    if private_hosts_allowed():
        return
    if is_restricted_ip(address):
        raise ValueError("IMAP peer is a private or loopback address (SSRF protection)")


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


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_imap_host(host: str) -> None:
    # Build-time check only: a DNS TOCTOU window remains until the
    # connect-time peer re-check in imap.py — see the residual-risk note
    # in providers/host_security.py (A350).
    if private_hosts_allowed():
        return
    if is_private_host(host):
        raise ValueError(f"imap host {host!r} is a private or loopback address (SSRF protection)")


def reject_microsoft_imap(email: str, config: dict) -> None:
    host = str(config.get("imap_host") or config.get("host") or "").strip().lower().rstrip(".")
    if (
        email.strip().lower().rsplit("@", 1)[-1] in MICROSOFT_DOMAINS
        or host in MICROSOFT_IMAP_HOSTS
        or config.get("provider_profile") == "microsoft"
    ):
        raise ValueError("Microsoft IMAP is not supported; use Microsoft Graph OAuth")
