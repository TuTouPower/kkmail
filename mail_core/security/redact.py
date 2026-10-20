"""Error redaction for persisted job errors and logs.

Provider HTTP bodies, bearer tokens, OAuth secrets and passwords must never be
written to ``worker_jobs.last_error`` or logs. Callers persist ``safe_error(exc)``.
"""

from __future__ import annotations

import re

MAX_ERROR_CHARS = 500

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/]+=*"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)([\"']?(?:access_token|refresh_token|id_token|client_secret|password|passwd|secret|api_key|apikey|code)[\"']?\s*[:=]\s*)"
            r"(\"[^\"]*\"|'[^']*'|[^\s,&}]+)"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
)


def redact(text: str | None, *, limit: int = MAX_ERROR_CHARS) -> str:
    out = str(text or "")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    if len(out) > limit:
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
