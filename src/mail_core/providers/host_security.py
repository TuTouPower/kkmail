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


def private_hosts_allowed() -> bool:
    return os.environ.get("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_restricted_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


def validate_imap_peer_address(address: str) -> None:
    if private_hosts_allowed():
        return
    if is_restricted_ip(address):
        raise ValueError("IMAP peer is a private or loopback address (SSRF protection)")
