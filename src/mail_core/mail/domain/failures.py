"""Structured allowlist failure model and single-source classification (t091).

Cross-layer failure reporting must never round-trip through lossy prose
summaries or trigger generic secret-key regexes (e.g. OS ``errno=101`` turned
into ``code=[REDACTED]``). Producers attach a controlled :class:`FailurePhase`
at socket/protocol boundaries and project failures into :class:`StructuredFailure`,
emitting strictly allowlisted tokens (``phase=``, ``status=``, ``errno=``,
``code=`` for symbolic non-errno identifiers, ``socks_reply=``, ``retry_after=``).
"""

from __future__ import annotations

import errno
import http.client
import imaplib
import math
import re
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar
from weakref import WeakKeyDictionary

ExcT = TypeVar("ExcT", bound=BaseException)


class FailureDomain(StrEnum):
    AUTH = "auth"
    TRANSPORT = "transport"
    CONTROL = "control"
    UNKNOWN = "unknown"


class FailurePhase(StrEnum):
    DNS = "dns"
    PROXY_CONNECT = "proxy_connect"
    TCP_CONNECT = "tcp_connect"
    TLS = "tls"
    AUTH = "auth"
    HTTP = "http"
    IMAP = "imap"


NETWORK_ERRNOS: frozenset[int] = frozenset(
    value
    for value in (
        getattr(errno, name, None)
        for name in (
            "ECONNRESET",
            "ECONNREFUSED",
            "ECONNABORTED",
            "ETIMEDOUT",
            "EHOSTUNREACH",
            "ENETUNREACH",
            "ENETRESET",
            "ENETDOWN",
            "EPIPE",
            "ESHUTDOWN",
            "ENOTCONN",
            "EAGAIN",
        )
    )
    if value is not None
)
_NON_NETWORK_ERRNOS: frozenset[int] = frozenset(
    value
    for value in (
        getattr(errno, name, None)
        for name in (
            "ENOSPC",
            "EMFILE",
            "ENFILE",
            "EACCES",
            "EPERM",
            "ENOENT",
            "EISDIR",
            "ENOTDIR",
            "EROFS",
        )
    )
    if value is not None
)

_SAFE_ERROR_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,79}$")
_SAFE_SYMBOLIC_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_SAFE_TEXT_TYPE_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_.]{0,79})(?=\s|:|$)(.*)$"
)
_SAFE_HTTP_REASON_RE = re.compile(r"^HTTP [1-5]\d{2}$")
_HTTP_BANNER_RE = re.compile(
    r"^HTTP(?:Error)?(?:/\d+(?:\.\d+)?)?\s+(?:ERROR\s+)?(?P<status>\d{3})\b",
    re.IGNORECASE,
)
_BARE_HTTP_STATUS_RE = re.compile(
    r"^(?P<status>429|5\d{2})\s+(?:too many requests|server error|internal server error|"
    r"bad gateway|service unavailable|gateway timeout|temporarily unavailable)\b",
    re.IGNORECASE,
)
_SAFE_PROSE_PREFIXES: tuple[str, ...] = (
    "rate-limited",
    "rate limited",
    "rate limit",
    "too many requests",
    "request timed out",
    "request timeout",
    "operation timed out",
    "operation timeout",
    "connection timed out",
    "connection timeout",
    "connection reset",
    "connection refused",
    "connection closed",
    "connect timeout",
    "read timeout",
    "write timeout",
    "network error",
    "socket error",
    "server error",
    "internal server error",
    "service unavailable",
    "temporarily unavailable",
    "gateway timeout",
    "bad gateway",
    "temporary server failure",
    "transient provider error",
    "transient provider failure",
)
_SAFE_EXACT_MESSAGES: frozenset[str] = frozenset(
    {
        "remote_id_missing",
        "missing dest_folder_remote_id",
        "message not found",
    }
)
_KNOWN_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "IdleSessionDisconnected",
        "IMAP4Abort",
        "IMAP4Readonly",
        "gaierror",
        "herror",
        "RemoteDisconnected",
        "IncompleteRead",
        "BadStatusLine",
    }
)
_PHASE_BY_EXC: WeakKeyDictionary[BaseException, FailurePhase] = WeakKeyDictionary()


def _coerce_phase(value: Any) -> FailurePhase | None:
    if isinstance(value, FailurePhase):
        return value
    if isinstance(value, str):
        try:
            return FailurePhase(value.strip().lower())
        except ValueError:
            return None
    return None


def attach_failure_phase(
    exc: ExcT,
    phase: FailurePhase | str,
    *,
    overwrite: bool = False,
) -> ExcT:
    """Attach a controlled :class:`FailurePhase` to an exception without altering its type."""
    resolved = _coerce_phase(phase)
    if resolved is None:
        return exc
    if not overwrite and failure_phase_of(exc) is not None:
        return exc
    try:
        setattr(exc, "failure_phase", resolved.value)
    except Exception:
        pass
    try:
        _PHASE_BY_EXC[exc] = resolved
    except TypeError:
        pass
    return exc


def failure_phase_of(exc: BaseException) -> FailurePhase | None:
    """Read any controlled :class:`FailurePhase` attached to an exception."""
    direct = _coerce_phase(getattr(exc, "failure_phase", None))
    if direct is not None:
        return direct
    try:
        attached = _PHASE_BY_EXC.get(exc)
    except TypeError:
        attached = None
    if attached is not None:
        return attached
    if isinstance(exc, imaplib.IMAP4.error):
        return FailurePhase.IMAP
    return None


def _sanitize_error_type(name: Any) -> str:
    if isinstance(name, str) and _SAFE_ERROR_TYPE_RE.match(name):
        return name
    return "Error"


def _coerce_http_status(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    return num if 100 <= num <= 599 else None


def _coerce_int_field(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_retry_after(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num) or num < 0.0:
        return None
    return num


def _coerce_symbolic_code(
    value: Any,
    *,
    errno_val: int | None,
    http_status: int | None = None,
) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if errno_val is not None and text == str(errno_val):
        return None
    if http_status is not None and text == str(http_status):
        return None
    if _SAFE_SYMBOLIC_CODE_RE.match(text):
        return text
    return None


def _unwrap_cause(exc: BaseException) -> BaseException | None:
    """Follow transport wrapper causes (`URLError.reason` or `__cause__`)."""
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        return reason
    if isinstance(exc.__cause__, BaseException):
        return exc.__cause__
    return None


def _is_network_exception(exc: BaseException, *, phase: FailurePhase | None = None) -> bool:
    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            ssl.SSLError,
            socket.gaierror,
            socket.herror,
            imaplib.IMAP4.abort,
            http.client.IncompleteRead,
            http.client.BadStatusLine,
        ),
    ):
        return True
    if isinstance(exc, OSError):
        if exc.errno in NETWORK_ERRNOS:
            return True
        if phase is FailurePhase.DNS and exc.errno not in _NON_NETWORK_ERRNOS:
            return True
    return False


def _exception_error_type(exc: BaseException) -> str:
    raw_name = type(exc).__name__
    if "IMAP4" in getattr(type(exc), "__qualname__", ""):
        mapped = {
            "error": "IMAP4Error",
            "abort": "IMAP4Abort",
            "readonly": "IMAP4Readonly",
        }.get(raw_name)
        if mapped is not None:
            return mapped
    return _sanitize_error_type(raw_name)


def _extract_wrapped_transport(
    exc: BaseException,
) -> tuple[FailurePhase | None, int | None, int | None, FailureDomain | None]:
    """Walk at most 3 wrapper hops for URL/HTTP/OAuth transport causes."""
    phase = failure_phase_of(exc)
    errno_val = _coerce_int_field(getattr(exc, "errno", None))
    socks_reply = _coerce_int_field(getattr(exc, "socks_reply", None))
    domain: FailureDomain | None = None

    curr: BaseException | None = _unwrap_cause(exc)
    for _ in range(3):
        if curr is None:
            break
        if phase is None:
            phase = failure_phase_of(curr)
        if errno_val is None:
            errno_val = _coerce_int_field(getattr(curr, "errno", None))
        if socks_reply is None:
            socks_reply = _coerce_int_field(getattr(curr, "socks_reply", None))
        if domain is None:
            domain = _wrapped_cause_domain(curr, phase=phase)
        curr = _unwrap_cause(curr)
    return phase, errno_val, socks_reply, domain


def _wrapped_cause_domain(curr: BaseException, *, phase: FailurePhase | None) -> FailureDomain | None:
    marker = _coerce_domain_marker(curr)
    if marker is not None:
        return marker
    if _is_network_exception(curr, phase=phase):
        return FailureDomain.TRANSPORT
    if type(curr).__name__ in ("ProviderHttpError", "CursorInvalidError"):
        curr_status = _coerce_http_status(getattr(curr, "status", None))
        if curr_status == 401:
            return FailureDomain.AUTH
        if curr_status == 429:
            return FailureDomain.CONTROL
        if curr_status is not None and 500 <= curr_status <= 599:
            return FailureDomain.TRANSPORT
    return None


def _coerce_domain_marker(exc: BaseException) -> FailureDomain | None:
    marker = getattr(exc, "_failure_domain", None)
    if isinstance(marker, str):
        try:
            return FailureDomain(marker)
        except ValueError:
            return None
    if type(exc).__name__ == "PermanentAuthError":
        return FailureDomain.AUTH
    if type(exc).__name__ == "RateLimitedError":
        return FailureDomain.CONTROL
    return None


def _classify_exception_domain(
    exc: BaseException,
    *,
    phase: FailurePhase | None,
    http_status: int | None,
    wrapped_domain: FailureDomain | None,
) -> FailureDomain:
    marker = _coerce_domain_marker(exc)
    if marker is not None:
        return marker
    if http_status == 401:
        return FailureDomain.AUTH
    if type(exc).__name__ == "AmbiguousOutcomeError":
        return FailureDomain.UNKNOWN
    if _is_network_exception(exc, phase=phase):
        return FailureDomain.TRANSPORT
    if type(exc).__name__ in ("ProviderHttpError", "CursorInvalidError", "OAuthError"):
        if http_status == 429:
            return FailureDomain.CONTROL
        if http_status is not None and 500 <= http_status <= 599:
            return FailureDomain.TRANSPORT
        if http_status is None and wrapped_domain is not None:
            return wrapped_domain
        return FailureDomain.UNKNOWN
    if wrapped_domain is not None and isinstance(exc, urllib_urlerror_tuple()):
        return wrapped_domain
    return FailureDomain.UNKNOWN


def urllib_urlerror_tuple() -> tuple[type[BaseException], ...]:
    import urllib.error

    return (urllib.error.URLError,)


_TRANSPORT_ERROR_SUBSTRINGS: tuple[str, ...] = (
    "Timeout",
    "Connection",
    "ProxyTunnel",
    "SSLError",
    "SSL",
    "CircuitOpen",
    "IMAP4Abort",
)
_TRANSPORT_EXACT_NAMES: frozenset[str] = frozenset(
    {"gaierror", "herror", "RemoteDisconnected", "IncompleteRead", "BadStatusLine"}
)


def _is_transport_error_type(error_type: str) -> bool:
    return error_type in _TRANSPORT_EXACT_NAMES or any(
        term in error_type for term in _TRANSPORT_ERROR_SUBSTRINGS
    )


def _is_transport_phase(phase: FailurePhase | None, errno_val: int | None) -> bool:
    if phase is FailurePhase.DNS:
        return errno_val is None or errno_val not in _NON_NETWORK_ERRNOS
    return (
        phase in (FailurePhase.PROXY_CONNECT, FailurePhase.TCP_CONNECT, FailurePhase.TLS)
        and errno_val is None
    )


def _classify_text_domain(
    error_type: str,
    *,
    http_status: int | None,
    errno_val: int | None,
    phase: FailurePhase | None,
) -> FailureDomain:
    if error_type == "PermanentAuthError" or http_status == 401 or phase is FailurePhase.AUTH:
        return FailureDomain.AUTH
    if error_type == "RateLimitedError" or http_status == 429:
        return FailureDomain.CONTROL
    if http_status is not None and 500 <= http_status <= 599:
        return FailureDomain.TRANSPORT
    if errno_val is not None and errno_val in NETWORK_ERRNOS:
        return FailureDomain.TRANSPORT
    if _is_transport_error_type(error_type) or _is_transport_phase(phase, errno_val):
        return FailureDomain.TRANSPORT
    return FailureDomain.UNKNOWN


def _parse_kv_fields(head: str) -> tuple[FailurePhase | None, int | None, int | None, int | None, float | None, str | None] | None:
    """Parse strict allowlisted ``key=value`` pairs in structured failure strings."""
    phase: FailurePhase | None = None
    http_status: int | None = None
    errno_val: int | None = None
    socks_reply: int | None = None
    retry_after_s: float | None = None
    symbolic_code: str | None = None
    for token in head.split():
        if "=" not in token:
            return None
        key, val = token.split("=", 1)
        if key == "phase":
            phase = _coerce_phase(val)
        elif key == "status":
            http_status = _coerce_http_status(val)
        elif key == "errno":
            errno_val = _coerce_int_field(val)
        elif key == "socks_reply":
            socks_reply = _coerce_int_field(val)
        elif key == "retry_after":
            retry_after_s = _coerce_retry_after(val)
        elif key == "code":
            symbolic_code = val if _SAFE_SYMBOLIC_CODE_RE.match(val) else None
    return phase, http_status, errno_val, socks_reply, retry_after_s, symbolic_code


@dataclass(frozen=True, slots=True)
class StructuredFailure:
    """Controlled, allowlisted failure representation safe for logs, DB, and API."""

    domain: FailureDomain
    error_type: str
    phase: FailurePhase | None = None
    http_status: int | None = None
    errno: int | None = None
    socks_reply: int | None = None
    retry_after_s: float | None = None
    symbolic_code: str | None = None
    safe_reason: str | None = None

    def format(self) -> str:
        """Project strictly allowlisted diagnostic fields without free-text leakage."""
        if self.safe_reason is not None:
            return self.safe_reason
        parts = [self.error_type]
        if self.phase is not None:
            parts.append(f"phase={self.phase.value}")
        if self.http_status is not None:
            parts.append(f"status={self.http_status}")
        if self.errno is not None:
            parts.append(f"errno={self.errno}")
        if self.symbolic_code is not None:
            parts.append(f"code={self.symbolic_code}")
        if self.socks_reply is not None:
            parts.append(f"socks_reply={self.socks_reply}")
        if self.retry_after_s is not None:
            parts.append(f"retry_after={self.retry_after_s}")
        return " ".join(parts)

    def __str__(self) -> str:
        return self.format()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": self.domain.value,
            "error_type": self.error_type,
        }
        if self.phase is not None:
            payload["phase"] = self.phase.value
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.errno is not None:
            payload["errno"] = self.errno
        if self.socks_reply is not None:
            payload["socks_reply"] = self.socks_reply
        if self.retry_after_s is not None:
            payload["retry_after_s"] = self.retry_after_s
        if self.symbolic_code is not None:
            payload["symbolic_code"] = self.symbolic_code
        if self.safe_reason is not None:
            payload["safe_reason"] = self.safe_reason
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StructuredFailure | None:
        if not isinstance(data, Mapping):
            return None
        try:
            domain = FailureDomain(str(data.get("domain")))
        except ValueError:
            return None
        error_type = _sanitize_error_type(data.get("error_type"))
        http_status = _coerce_http_status(data.get("http_status"))
        errno_val = _coerce_int_field(data.get("errno"))
        safe_reason = data.get("safe_reason")
        if safe_reason is not None and not (
            isinstance(safe_reason, str)
            and (
                safe_reason in _SAFE_EXACT_MESSAGES
                or safe_reason in _SAFE_PROSE_PREFIXES
                or _SAFE_HTTP_REASON_RE.fullmatch(safe_reason) is not None
            )
        ):
            safe_reason = None
        return cls(
            domain=domain,
            error_type=error_type,
            phase=_coerce_phase(data.get("phase")),
            http_status=http_status,
            errno=errno_val,
            socks_reply=_coerce_int_field(data.get("socks_reply")),
            retry_after_s=_coerce_retry_after(data.get("retry_after_s")),
            symbolic_code=_coerce_symbolic_code(
                data.get("symbolic_code"),
                errno_val=errno_val,
                http_status=http_status,
            ),
            safe_reason=safe_reason,
        )

    @classmethod
    def from_exception(cls, exc: BaseException) -> StructuredFailure:
        """Build a typed :class:`StructuredFailure` directly from an exception object."""
        wrapped_phase, wrapped_errno, wrapped_socks, wrapped_domain = _extract_wrapped_transport(exc)
        phase = failure_phase_of(exc) or wrapped_phase
        http_status = _coerce_http_status(getattr(exc, "status", None))
        if http_status is None:
            http_status = _coerce_http_status(getattr(exc, "status_code", None))
        errno_val = _coerce_int_field(getattr(exc, "errno", None))
        if errno_val is None and (http_status is None or _unwrap_cause(exc) is not None):
            errno_val = wrapped_errno
        socks_reply = _coerce_int_field(getattr(exc, "socks_reply", None))
        if socks_reply is None:
            socks_reply = wrapped_socks
        raw_retry = getattr(exc, "retry_after_seconds", None)
        if raw_retry is None:
            raw_retry = getattr(exc, "retry_after_s", None)
        retry_after_s = _coerce_retry_after(raw_retry)
        raw_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
        symbolic_code = _coerce_symbolic_code(
            raw_code,
            errno_val=errno_val,
            http_status=http_status,
        )
        domain = _classify_exception_domain(
            exc,
            phase=phase,
            http_status=http_status,
            wrapped_domain=wrapped_domain,
        )
        return cls(
            domain=domain,
            error_type=_exception_error_type(exc),
            phase=phase,
            http_status=http_status,
            errno=errno_val,
            socks_reply=socks_reply,
            retry_after_s=retry_after_s,
            symbolic_code=symbolic_code,
        )

    @classmethod
    def from_text(cls, value: str | None) -> StructuredFailure:
        """Parse an existing allowlisted failure projection or safe prefix; drop raw prose."""
        text = str(value or "").strip()
        if not text:
            return cls(domain=FailureDomain.UNKNOWN, error_type="ProviderError")
        return (
            _from_http_banner_text(text)
            or _from_structured_type_text(text)
            or _from_safe_prose_text(text)
            or cls(domain=FailureDomain.UNKNOWN, error_type="ProviderError")
        )


def _classify_http_status_domain(status: int) -> FailureDomain:
    if status == 401:
        return FailureDomain.AUTH
    if status == 429:
        return FailureDomain.CONTROL
    if 500 <= status <= 599:
        return FailureDomain.TRANSPORT
    return FailureDomain.UNKNOWN


def _from_http_banner_text(text: str) -> StructuredFailure | None:
    match = _HTTP_BANNER_RE.match(text) or _BARE_HTTP_STATUS_RE.match(text)
    if not match:
        return None
    status = int(match.group("status"))
    return StructuredFailure(
        domain=_classify_http_status_domain(status),
        error_type="ProviderHttpError",
        http_status=status,
        safe_reason=f"HTTP {status}",
    )


def _from_structured_type_text(text: str) -> StructuredFailure | None:
    m_type = _SAFE_TEXT_TYPE_RE.match(text)
    if not m_type:
        return None
    err_type, rest = m_type.group(1), m_type.group(2)
    if not (err_type.endswith(("Error", "Exception")) or err_type in _KNOWN_ERROR_NAMES):
        return None
    kv_part = rest.split(":", 1)[0].strip()
    parsed = _parse_kv_fields(kv_part) if kv_part else (None, None, None, None, None, None)
    if parsed is None:
        return None
    phase, http_status, errno_val, socks_reply, retry_after_s, symbolic_code = parsed
    symbolic_code = _coerce_symbolic_code(symbolic_code, errno_val=errno_val, http_status=http_status)
    domain = _classify_text_domain(
        err_type,
        http_status=http_status,
        errno_val=errno_val,
        phase=phase,
    )
    return StructuredFailure(
        domain=domain,
        error_type=err_type,
        phase=phase,
        http_status=http_status,
        errno=errno_val,
        socks_reply=socks_reply,
        retry_after_s=retry_after_s,
        symbolic_code=symbolic_code,
    )


_TRANSPORT_PROSE_WORDS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "connection",
    "connect",
    "read",
    "write",
    "network",
    "socket",
    "server error",
    "unavailable",
    "gateway",
)


def _from_safe_prose_text(text: str) -> StructuredFailure | None:
    lowered = text.lower()
    for prefix in _SAFE_PROSE_PREFIXES:
        if lowered.startswith(prefix):
            if "rate" in prefix or "429" in prefix or "many requests" in prefix:
                domain = FailureDomain.CONTROL
            elif any(w in prefix for w in _TRANSPORT_PROSE_WORDS):
                domain = FailureDomain.TRANSPORT
            else:
                domain = FailureDomain.UNKNOWN
            return StructuredFailure(domain=domain, error_type="ProviderError", safe_reason=prefix)
    if lowered in _SAFE_EXACT_MESSAGES:
        return StructuredFailure(domain=FailureDomain.UNKNOWN, error_type="ProviderError", safe_reason=lowered)
    return None


def coerce_structured_failure(
    value: StructuredFailure | Mapping[str, Any] | BaseException | str | None,
) -> StructuredFailure:
    """Convert an exception, dict projection, StructuredFailure, or string to allowlisted failure."""
    if isinstance(value, StructuredFailure):
        return value
    if isinstance(value, Mapping):
        parsed = StructuredFailure.from_dict(value)
        if parsed is not None:
            return parsed
        return StructuredFailure(domain=FailureDomain.UNKNOWN, error_type="ProviderError")
    if isinstance(value, BaseException):
        return StructuredFailure.from_exception(value)
    return StructuredFailure.from_text(None if value is None else str(value))
