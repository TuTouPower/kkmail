"""Error redaction for persisted job errors and logs.

Provider HTTP bodies, bearer tokens, OAuth secrets and passwords must never be
written to ``worker_jobs.last_error`` or logs. Callers persist ``safe_error(exc)``.
"""

from __future__ import annotations

import re

MAX_ERROR_CHARS = 500

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # A120: an Authorization header value is secret regardless of scheme
    # (Bearer/Basic/Digest/Token/MAC/Negotiate/raw) — drop the whole value.
    (re.compile(r"(?i)\b(authorization\s*:\s*).+"), r"\1[REDACTED]"),
    # A120: Cookie / Set-Cookie header values are session material — drop
    # the entire header value, not just the first pair.
    (re.compile(r"(?i)\b((?:set-)?cookie\s*:\s*).+"), r"\1[REDACTED]"),
    # A120: JWTs (header.payload.signature, header always base64url "eyJ…").
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[REDACTED]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)([\"']?(?:access_token|refresh_token|id_token|token|client_secret|code_verifier|device_code|state|password|passwd|secret|api_key|apikey|code)[\"']?\s*[:=]\s*)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,&}]+)"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)([?&](?:access_token|refresh_token|id_token|token|client_secret|code|password|secret)=)[^&\s\"'#]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)(/api/accounts/oauth/callback/[^\s?\"']*\?)[^\s\"']+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?i)((?:https?|socks[45]?h?|postgres(?:ql)?(?:\+\w+)?|ftp)://[^:/@\s]+:)[^@\s]+@"),
        r"\1[REDACTED]@",
    ),
)


def redact(text: str | None, *, limit: int | None = MAX_ERROR_CHARS) -> str:
    out = str(text or "")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    if limit is not None and len(out) > limit:
        out = out[: limit - 1] + "…"
    return out


def safe_error(exc: BaseException | str | None) -> str:
    """Short, redacted description. Provider HTTP bodies are dropped, not stored."""
    if exc is None:
        return ""
    if isinstance(exc, str):
        return redact(exc)
    from mail_core.providers.http import ProviderHttpError

    if isinstance(exc, ProviderHttpError):
        status = f" status={exc.status}" if exc.status is not None else ""
        first = (str(exc).splitlines() or [""])[0].strip()
        is_raw_body = False
        if exc.body is not None:
            if isinstance(exc.body, str) and exc.body.strip() and (exc.body.strip() == first or exc.body.strip() in str(exc)):
                is_raw_body = True
            elif str(exc).strip() == str(exc.body).strip():
                is_raw_body = True
        if first.startswith(("{", "[", "<")) or ('{"' in first) or ("<html" in first.lower()):
            is_raw_body = True

        if is_raw_body or not first:
            return f"{type(exc).__name__}{status}"
        return redact(f"{type(exc).__name__}{status}: {first[:120]}")
    # A325: non-provider exceptions converge to type + controlled fields
    # only. Their raw messages routinely embed SQL text, file paths and
    # other internal details that must never be persisted (e.g. into
    # worker_jobs.last_error); the full message remains available to
    # debug logs through the redacting formatter, not through this value.
    return safe_provider_summary(exc)


def safe_provider_summary(exc: BaseException | str | None) -> str:
    """Controlled, safe summary for provider errors and job details.

    Retains only exception type, controlled status/error code, and retry fields.
    Provider HTTP response bodies, error messages, and raw payloads are dropped.
    """
    if exc is None:
        return ""
    if isinstance(exc, str):
        value = exc.strip()
        if not value:
            return "ProviderError"
        http_status = re.match(
            r"^HTTP(?:Error)?(?:/\d+(?:\.\d+)?)?\s+(?:ERROR\s+)?(?P<status>\d{3})\b",
            value,
            re.IGNORECASE,
        )
        if http_status:
            return f"HTTP {http_status.group('status')}"
        bare_status = re.match(
            r"^(?P<status>429|5\d{2})\s+(?:too many requests|server error|internal server error|"
            r"bad gateway|service unavailable|gateway timeout|temporarily unavailable)\b",
            value,
            re.IGNORECASE,
        )
        if bare_status:
            return f"HTTP {bare_status.group('status')}"
        error_type = re.match(
            r"^([A-Za-z][A-Za-z0-9_.]{0,79}(?:Error|Exception))(?:\s+status=(\d{3}))?(?=\s|:|$)",
            value,
        )
        if error_type:
            summary = error_type.group(1)
            status = error_type.group(2)
            return f"{summary} status={status}" if status else summary

        safe_prefixes = (
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
        lowered = value.lower()
        for prefix in safe_prefixes:
            if lowered.startswith(prefix):
                return prefix
        if lowered in {"remote_id_missing", "missing dest_folder_remote_id", "message not found"}:
            return lowered
        return "ProviderError"

    parts = [type(exc).__name__]
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is not None and isinstance(status, (int, str)):
        parts.append(f"status={status}")
    code = getattr(exc, "code", None) or getattr(exc, "error_code", None) or getattr(exc, "errno", None)
    if code is not None and isinstance(code, (int, str)):
        parts.append(f"code={code}")
    retry_after = getattr(exc, "retry_after_seconds", None)
    if retry_after is not None:
        parts.append(f"retry_after={retry_after}")
    return " ".join(parts)


class RedactingFilter:
    """Standard logging.Filter that automatically redacts credentials from LogRecords.

    A326: the filter is self-sufficient — it also redacts exception
    tracebacks. ``record.exc_text`` is pre-generated from ``exc_info``
    (or redacted in place when already built) so that even a plain
    ``logging.Formatter`` — without RedactingTraceFormatter — cannot emit
    a plaintext traceback. Stack info is redacted the same way.
    """

    def filter(self, record: object) -> bool:
        import logging
        import traceback

        if not isinstance(record, logging.LogRecord):
            return True
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, limit=2000)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(str(v), limit=500) if isinstance(v, (str, BaseException)) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(str(arg), limit=500) if isinstance(arg, (str, BaseException)) else arg
                    for arg in record.args
                )
        if isinstance(record.exc_text, str) and record.exc_text:
            record.exc_text = redact(record.exc_text, limit=None)
        elif record.exc_info and record.exc_info[0] is not None:
            try:
                record.exc_text = redact(
                    "".join(traceback.format_exception(*record.exc_info)),
                    limit=None,
                )
            except Exception:
                record.exc_text = f"{record.exc_info[0].__name__}: [REDACTED]"
        if isinstance(record.stack_info, str) and record.stack_info:
            record.stack_info = redact(record.stack_info, limit=None)
        return True

