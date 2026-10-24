"""Shared IP checks for outbound IMAP host validation."""

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
