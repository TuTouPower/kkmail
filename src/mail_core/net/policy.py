"""Unified outbound network security policy and SSRF primitives."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Mapping, Sequence

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class NetworkSecurityError(ValueError):
    """Raised when an outbound target or resolved peer violates SSRF policy."""


# Extra reserved or special-purpose networks explicitly blocked for SSRF defense
# alongside CPython's ``is_global`` and semantic address-property checks.
_EXTRA_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),      # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmark tests
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("169.254.169.254/32"), # Cloud metadata IP
)


def private_hosts_allowed(env: Mapping[str, str] | None = None) -> bool:
    """Return True when local/private targets are explicitly permitted."""
    source = os.environ if env is None else env
    return source.get("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def parse_allowed_cidrs(raw: str | None) -> tuple[IPNetwork, ...]:
    """Parse comma-separated CIDR allowlist entries, skipping blanks/invalid items."""
    text = (raw or "").strip()
    if not text:
        return ()
    cidrs: list[IPNetwork] = []
    for item in text.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            cidrs.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            pass
    return tuple(cidrs)


def allowed_cidrs_from_env(env: Mapping[str, str] | None = None) -> tuple[IPNetwork, ...]:
    """Load operator-approved CIDR exceptions from MAIL_CORE_PROXY_ALLOW_CIDRS."""
    source = os.environ if env is None else env
    return parse_allowed_cidrs(source.get("MAIL_CORE_PROXY_ALLOW_CIDRS"))


def _unwrap_ip_and_check_cidrs(
    address: str | IPAddress,
    allow_cidrs: Sequence[IPNetwork],
) -> tuple[IPAddress, bool]:
    ip_obj = ipaddress.ip_address(address) if isinstance(address, str) else address
    if any(ip_obj.version == cidr.version and ip_obj in cidr for cidr in allow_cidrs):
        return ip_obj, True
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        mapped = ip_obj.ipv4_mapped
        if any(mapped.version == cidr.version and mapped in cidr for cidr in allow_cidrs):
            return mapped, True
        return mapped, False
    return ip_obj, False


def is_restricted_ip(
    address: str | IPAddress,
    *,
    allow_cidrs: Sequence[IPNetwork] = (),
) -> bool:
    """Return True when ``address`` is non-public/loopback/reserved and not allowlisted."""
    ip_obj, allowlisted = _unwrap_ip_and_check_cidrs(address, allow_cidrs)
    if allowlisted:
        return False

    # CPython keeps some special blocks (e.g., multicast / deprecated IPv6
    # site-local fec0::/10) with ``is_global == True``, so combine checks.
    is_special = (
        not ip_obj.is_global
        or ip_obj.is_multicast
        or getattr(ip_obj, "is_site_local", False)
        or ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )
    if is_special:
        return True
    return any(ip_obj.version == net.version and ip_obj in net for net in _EXTRA_BLOCKED_NETWORKS)


def is_safe_ip(
    address: str | IPAddress,
    *,
    allow_cidrs: Sequence[IPNetwork] = (),
) -> bool:
    """Return True when ``address`` is safe to connect directly."""
    return not is_restricted_ip(address, allow_cidrs=allow_cidrs)


def is_loopback_host(host: str) -> bool:
    """Return True for ``localhost`` or loopback IP literals."""
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_syntactic_private_host(
    host: str,
    *,
    allow_cidrs: Sequence[IPNetwork] = (),
) -> bool:
    """Syntactic private/local check for host strings without performing DNS."""
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if not normalized:
        return True
    if (
        normalized in ("localhost", "localhost.localdomain")
        or normalized.endswith(".local")
        or normalized.endswith(".localhost")
    ):
        return True
    try:
        return is_restricted_ip(normalized, allow_cidrs=allow_cidrs)
    except ValueError:
        return False


def validate_hostname_syntax(host: str) -> str:
    """Validate host has no whitespace, control characters, or path delimiters."""
    if not isinstance(host, str):
        raise NetworkSecurityError("target host must be a string")
    cleaned = host.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise NetworkSecurityError("target host is empty")
    if any(ch.isspace() or ord(ch) < 32 or ch in ("/", "\\", "@") for ch in cleaned):
        raise NetworkSecurityError(f"target host contains invalid characters: {host!r}")
    return cleaned


@dataclass(frozen=True, slots=True)
class OutboundSecurityPolicy:
    """Immutable outbound target validation policy shared by direct & proxy paths."""

    allow_private_hosts: bool = False
    allow_cidrs: tuple[IPNetwork, ...] = ()

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        allow_private_hosts: bool | None = None,
        allow_cidrs: Sequence[IPNetwork] | None = None,
    ) -> OutboundSecurityPolicy:
        resolved_private = (
            private_hosts_allowed(env) if allow_private_hosts is None else bool(allow_private_hosts)
        )
        resolved_cidrs = (
            allowed_cidrs_from_env(env) if allow_cidrs is None else tuple(allow_cidrs)
        )
        return cls(allow_private_hosts=resolved_private, allow_cidrs=resolved_cidrs)

    def validate_resolved_ips(self, ips: Sequence[str], *, host: str) -> list[str]:
        """Validate every resolved IP before dialing any socket (prevents mixed-DNS SSRF)."""
        if not ips:
            raise NetworkSecurityError(f"no IP addresses resolved for host {host!r}")
        deduped: list[str] = []
        seen: set[str] = set()
        for ip_str in ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise NetworkSecurityError(f"invalid resolved IP {ip_str!r} for host {host!r}") from exc
            if not self.allow_private_hosts and is_restricted_ip(ip_obj, allow_cidrs=self.allow_cidrs):
                raise NetworkSecurityError(
                    f"target host {host!r} resolved to private or loopback address: {ip_str} (SSRF protection)"
                )
            if ip_str not in seen:
                seen.add(ip_str)
                deduped.append(ip_str)
        return deduped

    def validate_target_for_proxy(self, host: str) -> str:
        """Validate target hostname for proxy CONNECT/SOCKS5h without local DNS lookup.

        Trusted private/loopback *proxy* endpoints remain allowed; only private/loopback
        *target* hosts are blocked unless ``allow_private_hosts`` is enabled.
        """
        cleaned = validate_hostname_syntax(host)
        if not self.allow_private_hosts and is_syntactic_private_host(
            cleaned, allow_cidrs=self.allow_cidrs
        ):
            raise NetworkSecurityError(
                f"proxy target host {host!r} is a private or loopback address (SSRF protection)"
            )
        return cleaned
