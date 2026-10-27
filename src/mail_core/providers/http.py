"""Injectable HTTP transport contract for the Graph provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Protocol


class ProviderHttpError(Exception):
    """Non-2xx (or transport-level) failure from a provider HTTP call."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


class AmbiguousOutcomeError(ProviderHttpError):
    """A non-idempotent request may have reached the provider; do not replay automatically."""


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header: delay-seconds or HTTP-date (RFC 9110).

    Returns remaining seconds (clamped at 0 for past dates), or None
    when the value is neither form.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


class RateLimitedError(ProviderHttpError):
    """HTTP 429 — caller should back off using retry_after_seconds."""

    def __init__(
        self,
        message: str = "rate limited",
        *,
        retry_after_seconds: float | None = None,
        status: int = 429,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message, status=status, body=body, headers=headers)
        if retry_after_seconds is None and self.headers.get("retry-after"):
            retry_after_seconds = _parse_retry_after(self.headers["retry-after"])
        self.retry_after_seconds = retry_after_seconds


class CursorInvalidError(ProviderHttpError):
    """Opaque sync cursor expired / unknown — fall back to controlled rebuild."""

    def __init__(
        self,
        message: str = "sync cursor invalid",
        *,
        status: int | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message, status=status, body=body, headers=headers)


TransportFn = Callable[..., Any]


class HttpTransport(Protocol):
    """method, path, params → JSON dict (or raise ProviderHttpError)."""

    def __call__(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any: ...


@dataclass
class FixtureTransport:
    """Queue / map based transport for contract tests.

    ``routes`` maps ``(METHOD, path_prefix_or_exact)`` → response dict, or a
    callable(method, path, params) → dict. Raising RateLimitedError /
    CursorInvalidError simulates 429 / invalid cursor.
    """

    routes: dict[tuple[str, str], Any] = field(default_factory=dict)
    calls: list[tuple[str, str, dict]] = field(default_factory=list)

    def add(self, method: str, path: str, response: Any) -> None:
        self.routes[(method.upper(), path)] = response

    def __call__(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        self.calls.append((method.upper(), path, params))
        key = (method.upper(), path)
        if key in self.routes:
            resp = self.routes[key]
        else:
            resp = None
            # Longest matching prefix wins, regardless of insertion order.
            candidates = [
                (prefix, candidate)
                for (m, prefix), candidate in self.routes.items()
                if m == method.upper() and (path == prefix or path.startswith(prefix))
            ]
            if candidates:
                resp = max(candidates, key=lambda item: len(item[0]))[1]
        if resp is None:
            raise ProviderHttpError(f"no fixture for {method} {path}", status=404)
        if callable(resp) and not isinstance(resp, type):
            return resp(method, path, params)
        if isinstance(resp, BaseException):
            raise resp
        return resp


class PermanentAuthError(Exception):
    """Provider rejected credentials permanently (e.g. Basic auth disabled, account closed)."""

