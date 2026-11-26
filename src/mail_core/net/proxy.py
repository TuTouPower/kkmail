"""Unified outbound proxy URL parsing, NO_PROXY matching, and resolution."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from typing import Literal, Mapping
from urllib.parse import SplitResult, unquote, urlsplit

ProxyScheme = Literal["http", "https", "socks5", "socks5h"]
ProxyMode = Literal["auto", "direct"]

SUPPORTED_PROXY_SCHEMES: frozenset[str] = frozenset({"http", "https", "socks5", "socks5h"})
_DEFAULT_PROXY_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "socks5": 1080,
    "socks5h": 1080,
}


class ProxyParseError(ValueError):
    """Raised when an outbound proxy configuration URL or mode is invalid."""


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """Validated outbound proxy endpoint; never discloses credentials in repr/keys."""

    scheme: ProxyScheme
    host: str
    port: int
    username: str | None = None
    password: str | None = field(default=None, repr=False)

    def safe_key(self) -> str:
        """Return ``scheme://host:port`` without username/password."""
        formatted_host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{formatted_host}:{self.port}"

    def __repr__(self) -> str:
        has_auth = self.username is not None or self.password is not None
        return f"ProxyConfig({self.safe_key()!r}, authenticated={has_auth})"

    def __str__(self) -> str:
        return self.safe_key()


def _resolve_proxy_port(parts: SplitResult, scheme: str) -> int:
    try:
        port = parts.port
    except ValueError as exc:
        raise ProxyParseError(f"invalid proxy port: {exc}") from exc
    resolved_port = port if port is not None else _DEFAULT_PROXY_PORTS[scheme]
    if not (1 <= resolved_port <= 65535):
        raise ProxyParseError(f"proxy port out of range: {resolved_port}")
    return resolved_port


def parse_proxy_url(raw_url: str) -> ProxyConfig:
    """Parse and validate an explicit proxy URL (http, https, socks5, socks5h)."""
    if not isinstance(raw_url, str):
        raise ProxyParseError("proxy URL must be a string")
    stripped = raw_url.strip()
    if not stripped or any(ch.isspace() or ord(ch) < 32 for ch in stripped):
        raise ProxyParseError("proxy URL must be non-empty without whitespace or control characters")

    parts = urlsplit(stripped)
    scheme = parts.scheme.lower()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ProxyParseError(
            f"unsupported proxy scheme {parts.scheme!r}; expected http, https, socks5, or socks5h"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ProxyParseError("proxy URL must not contain a path, query, or fragment")

    hostname = (parts.hostname or "").strip()
    if not hostname:
        raise ProxyParseError("proxy URL is missing a host")

    resolved_port = _resolve_proxy_port(parts, scheme)
    username = unquote(parts.username) if parts.username is not None else None
    password = unquote(parts.password) if parts.password is not None else None
    return ProxyConfig(
        scheme=scheme,  # type: ignore[arg-type]
        host=hostname,
        port=resolved_port,
        username=username,
        password=password,
    )


def validate_proxy_mode(raw_mode: str | None) -> ProxyMode | None:
    """Validate optional proxy_mode ('auto' | 'direct')."""
    if raw_mode is None:
        return None
    if not isinstance(raw_mode, str):
        raise ProxyParseError("proxy_mode must be a string")
    normalized = raw_mode.strip().lower()
    if normalized in ("auto", "direct"):
        return normalized  # type: ignore[return-value]
    raise ProxyParseError(f"unsupported proxy_mode {raw_mode!r}; expected 'auto' or 'direct'")


def parse_no_proxy(no_proxy: str | None) -> tuple[str, ...]:
    """Split NO_PROXY string into normalized non-empty tokens."""
    if not no_proxy:
        return ()
    return tuple(item.strip() for item in no_proxy.split(",") if item.strip())


def _split_no_proxy_rule(rule: str) -> tuple[str, int | None]:
    """Split a NO_PROXY rule into (host_or_cidr, optional_port)."""
    token = rule.strip().lower()
    if token.startswith("["):
        end_bracket = token.find("]")
        if end_bracket != -1:
            inner = token[1:end_bracket]
            rest = token[end_bracket + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return inner, int(rest[1:])
            return inner, None
    # Distinguish host:port from bare IPv6 address (contains >=2 colons) or CIDR.
    if token.count(":") == 1 and "/" not in token:
        host_part, port_part = token.rsplit(":", 1)
        if port_part.isdigit():
            return host_part, int(port_part)
    return token, None


def _match_ip_or_cidr_rule(
    rule_pattern: str,
    target_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
) -> bool:
    if target_ip is None:
        return False
    if "/" in rule_pattern:
        try:
            net = ipaddress.ip_network(rule_pattern, strict=False)
        except ValueError:
            return False
        return target_ip.version == net.version and target_ip in net
    try:
        rule_ip = ipaddress.ip_address(rule_pattern.lstrip("."))
    except ValueError:
        return False
    return target_ip == rule_ip


def _match_single_no_proxy_rule(
    rule: str,
    norm_host: str,
    target_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    target_port: int | None,
) -> bool:
    if rule == "*":
        return True
    rule_pattern, rule_port = _split_no_proxy_rule(rule)
    if rule_port is not None and target_port is not None and rule_port != int(target_port):
        return False
    rule_pattern = rule_pattern.rstrip(".")
    if not rule_pattern:
        return False
    if "/" in rule_pattern:
        return _match_ip_or_cidr_rule(rule_pattern, target_ip)
    if _match_ip_or_cidr_rule(rule_pattern, target_ip):
        return True
    domain = rule_pattern.lstrip(".")
    return norm_host == domain or norm_host.endswith("." + domain)


def matches_no_proxy(
    target_host: str,
    target_port: int | None = None,
    no_proxy: str | None = None,
) -> bool:
    """Return True if ``target_host[:target_port]`` matches ``NO_PROXY`` rules."""
    rules = parse_no_proxy(no_proxy)
    if not rules:
        return False
    norm_host = target_host.strip().lower().strip("[]").rstrip(".")
    try:
        target_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(norm_host)
    except ValueError:
        target_ip = None
    return any(_match_single_no_proxy_rule(rule, norm_host, target_ip, target_port) for rule in rules)


def _first_non_empty(source: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        val = source.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def resolve_outbound_proxy(
    target_host: str,
    target_port: int,
    *,
    explicit_proxy: str | None = None,
    explicit_no_proxy: str | None = None,
    proxy_mode: str | None = None,
    protocol: str = "imap",
    env: Mapping[str, str] | None = None,
) -> ProxyConfig | None:
    """Resolve effective outbound proxy for a target host/port.

    Precedence:
    1. ``proxy_mode == "direct"`` -> ``None`` (direct only).
    2. Explicit non-empty ``explicit_proxy`` -> subject only to ``explicit_no_proxy``.
    3. Environment configuration:
       - ``NO_PROXY`` match (``MAIL_CORE_NO_PROXY``, ``NO_PROXY``, ``no_proxy``) -> ``None``
       - ``MAIL_CORE_OUTBOUND_PROXY``
       - ``HTTPS_PROXY`` / ``https_proxy`` (for ``imap`` / ``https``)
       - ``HTTP_PROXY`` / ``http_proxy``
       - ``ALL_PROXY`` / ``all_proxy``
    """
    mode = validate_proxy_mode(proxy_mode)
    if mode == "direct":
        return None

    source = os.environ if env is None else env

    if explicit_proxy is not None and explicit_proxy.strip():
        if matches_no_proxy(target_host, target_port, explicit_no_proxy):
            return None
        return parse_proxy_url(explicit_proxy)

    no_proxy_raw = (
        explicit_no_proxy
        if explicit_no_proxy is not None
        else _first_non_empty(source, ("MAIL_CORE_NO_PROXY", "NO_PROXY", "no_proxy"))
    )
    if matches_no_proxy(target_host, target_port, no_proxy_raw):
        return None

    proto = protocol.strip().lower()
    if proto == "http":
        candidate_keys = (
            "MAIL_CORE_OUTBOUND_PROXY",
            "HTTP_PROXY",
            "http_proxy",
            "ALL_PROXY",
            "all_proxy",
        )
    else:
        candidate_keys = (
            "MAIL_CORE_OUTBOUND_PROXY",
            "HTTPS_PROXY",
            "https_proxy",
            "HTTP_PROXY",
            "http_proxy",
            "ALL_PROXY",
            "all_proxy",
        )
    raw = _first_non_empty(source, candidate_keys)
    if not raw:
        return None
    return parse_proxy_url(raw)


def env_would_proxy_url(
    target_host: str,
    target_port: int,
    *,
    protocol: str = "https",
    env: Mapping[str, str] | None = None,
) -> bool:
    """True when standard env proxy vars alone would proxy this URL (used for direct override)."""
    source = os.environ if env is None else env
    raw_no_proxy = _first_non_empty(source, ("NO_PROXY", "no_proxy"))
    if matches_no_proxy(target_host, target_port, raw_no_proxy):
        return False
    proto = protocol.strip().lower()
    keys = (
        ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
        if proto == "http"
        else ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
    )
    return _first_non_empty(source, keys) is not None
