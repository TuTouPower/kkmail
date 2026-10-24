"""Error redaction for persisted job errors and logs.

Provider HTTP bodies, bearer tokens, OAuth secrets and passwords must never be
written to ``worker_jobs.last_error`` or logs. Callers persist ``safe_error(exc)``.
"""

from __future__ import annotations

import re

MAX_ERROR_CHARS = 500

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)([\"']?(?:access_token|refresh_token|id_token|client_secret|code_verifier|device_code|state|password|passwd|secret|api_key|apikey|code)[\"']?\s*[:=]\s*)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,&}]+)"
        ),
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
    return redact(f"{type(exc).__name__}: {exc}")


def safe_provider_summary(exc: BaseException | str | None) -> str:
    """Controlled, safe summary for provider errors and job details.

    Retains only exception type, controlled status/error code, and retry fields.
    Provider HTTP response bodies, error messages, and raw payloads are dropped.
    """
    if exc is None:
        return ""
    if isinstance(exc, str):
        cleaned = redact(exc)
        if ":" in cleaned:
            prefix, _, _ = cleaned.partition(":")
            if any(term in prefix.lower() for term in ("error", "exception", "status", "failed", "http")):
                return prefix.strip()
        return cleaned

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
    """Standard logging.Filter that automatically redacts credentials from LogRecords."""

    def filter(self, record: object) -> bool:
        import logging

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
        return True

