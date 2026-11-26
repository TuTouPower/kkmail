"""Error classification and retry-resolution helpers for remote push."""

from __future__ import annotations

import re

from mail_core.mail.domain.failures import FailureDomain, FailurePhase, StructuredFailure

DEFAULT_MAX_REMOTE_OP_ATTEMPTS = 5

_HTTP_STATUS_PREFIXES = (
    re.compile(
        r"^HTTP(?:Error)?(?:/\d+(?:\.\d+)?)?\s+(?:ERROR\s+)?(?P<status>\d{3})\b",
        re.IGNORECASE,
    ),
    re.compile(r"^[A-Za-z][A-Za-z0-9_.]*\s+status=(?P<status>\d{3})(?:\s|$)", re.IGNORECASE),
    re.compile(
        r"^(?P<status>429|5\d{2})\s+"
        r"(?:too many requests|server error|internal server error|bad gateway|"
        r"service unavailable|gateway timeout|temporarily unavailable)\b",
        re.IGNORECASE,
    ),
)
_TRANSIENT_ERROR_PREFIXES = (
    re.compile(
        r"^(?:TimeoutError|TimeoutException|ConnectTimeout|ReadTimeout|WriteTimeout|PoolTimeout|"
        r"NetworkError|SocketError)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:request|operation|connection|connect|read|write)\s+"
        r"(?:timed out|timeout|reset|refused|closed|failed|error)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:server error|internal server error|service unavailable|temporarily unavailable|"
        r"gateway timeout|bad gateway)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:temporary|transient)\s+(?:server|provider)\s+(?:failure|error)\b",
        re.IGNORECASE,
    ),
)
_RATE_LIMIT_ERROR_PREFIXES = (
    re.compile(
        r"^(?:rate[- ]limited(?:error)?|ratelimited(?:error)?|rate limit(?:ed)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^too many requests\b", re.IGNORECASE),
)
_STRUCTURED_DETAIL_ATTRS = (
    "safe_reason",
    "phase",
    "http_status",
    "errno",
    "symbolic_code",
)


def _error_text_status_code(err_msg: str) -> int | None:
    for pattern in _HTTP_STATUS_PREFIXES:
        match = pattern.match(err_msg.strip())
        if match:
            return int(match.group("status"))
    return None


def _is_transient_status(status_code: int | None) -> bool:
    return status_code == 429 or (status_code is not None and 500 <= status_code < 600)


def _is_transient_failure(parsed: StructuredFailure) -> bool:
    if parsed.error_type == "AmbiguousOutcomeError":
        return False
    if _is_transient_status(parsed.http_status):
        return True
    if parsed.domain in (FailureDomain.TRANSPORT, FailureDomain.CONTROL):
        return True
    return parsed.phase in (
        FailurePhase.DNS,
        FailurePhase.PROXY_CONNECT,
        FailurePhase.TCP_CONNECT,
        FailurePhase.TLS,
    )


def _is_transient_text(err_msg: str) -> bool:
    parsed = StructuredFailure.from_text(err_msg)
    if _is_transient_failure(parsed):
        return True
    if _is_transient_status(_error_text_status_code(err_msg)):
        return True
    return any(pattern.match(err_msg.strip()) for pattern in _TRANSIENT_ERROR_PREFIXES)


def is_transient_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    """Return True when the error represents a transient or retryable failure."""
    if exc is not None:
        return _is_transient_failure(StructuredFailure.from_exception(exc))
    if err_msg:
        return _is_transient_text(err_msg)
    return False


def _classify_rate_limit_exception(exc: Exception) -> bool | None:
    parsed_exc = StructuredFailure.from_exception(exc)
    if parsed_exc.error_type == "RateLimitedError" or parsed_exc.domain is FailureDomain.CONTROL:
        return True
    if parsed_exc.http_status is not None:
        return parsed_exc.http_status == 429
    return None


def _is_rate_limit_text(err_msg: str) -> bool:
    parsed = StructuredFailure.from_text(err_msg)
    if parsed.http_status == 429 or parsed.error_type == "RateLimitedError":
        return True
    if _error_text_status_code(err_msg) == 429:
        return True
    return any(pattern.match(err_msg.strip()) for pattern in _RATE_LIMIT_ERROR_PREFIXES)


def is_rate_limited_error(exc: Exception | None = None, err_msg: str | None = None) -> bool:
    """Return True when the exception or message indicates provider rate limiting."""
    if exc is not None:
        verdict = _classify_rate_limit_exception(exc)
        if verdict is not None:
            return verdict
    if err_msg:
        return _is_rate_limit_text(err_msg)
    return False


def get_retry_after_seconds(exc: Exception | None, fallback: float = 60.0) -> float:
    """Extract bounded retry-after seconds from an exception, falling back cleanly."""
    if exc is not None:
        sec = getattr(exc, "retry_after_seconds", None)
        if sec is not None:
            try:
                val = float(sec)
                if val > 0:
                    return max(1.0, min(val, 86400.0))
            except (ValueError, TypeError):
                pass
    return max(1.0, min(fallback, 86400.0))


def _has_structured_detail(parsed: StructuredFailure) -> bool:
    if parsed.error_type != "ProviderError" or parsed.domain is not FailureDomain.UNKNOWN:
        return True
    return any(getattr(parsed, attr) is not None for attr in _STRUCTURED_DETAIL_ATTRS)


def resolve_push_op_failure(
    caught_batch_exc: Exception | None,
    result: object,
) -> StructuredFailure | str | None:
    """Resolve failure for persistence/retry without wiping non-structured business errors."""
    if caught_batch_exc is not None:
        return StructuredFailure.from_exception(caught_batch_exc)
    embedded = getattr(result, "failure", None)
    if isinstance(embedded, StructuredFailure):
        return embedded
    raw_err = getattr(result, "error", None)
    if not raw_err:
        return None
    text = str(raw_err)
    parsed = StructuredFailure.from_text(text)
    return parsed if _has_structured_detail(parsed) else text
