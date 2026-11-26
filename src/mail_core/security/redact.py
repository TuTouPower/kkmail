"""Error redaction for persisted job errors and logs.

Provider HTTP bodies, bearer tokens, OAuth secrets and passwords must never be
written to ``worker_jobs.last_error`` or logs. Callers persist ``safe_error(exc)``.
"""

from __future__ import annotations

import logging
import re
import traceback
import urllib.error
from collections.abc import Mapping
from typing import Any

from mail_core.mail.domain.failures import (
    StructuredFailure,
    coerce_structured_failure,
    failure_phase_of,
)

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
        re.compile(r"(?i)(/api/mail/messages/[^/\s]+/remote-images\?[^#\s]*\burl=)[^&\s\"'#]+"),
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


def _is_raw_http_body(body: Any, first: str, raw_exc_text: str) -> bool:
    if not first or first.startswith(("{", "[", "<")) or ('{"' in first) or ("<html" in first.lower()):
        return True
    if body is None:
        return False
    if isinstance(body, str):
        stripped = body.strip()
        if stripped and (stripped == first or stripped in raw_exc_text):
            return True
    return raw_exc_text.strip() == str(body).strip()


def _format_provider_http_error(exc: BaseException) -> str:
    phase = failure_phase_of(exc)
    phase_part = f" phase={phase.value}" if phase is not None else ""
    status_val = getattr(exc, "status", None)
    status = f" status={status_val}" if status_val is not None else ""
    raw_text = str(exc)
    first = (raw_text.splitlines() or [""])[0].strip()
    if _is_raw_http_body(getattr(exc, "body", None), first, raw_text):
        return StructuredFailure.from_exception(exc).format()
    return redact(f"{type(exc).__name__}{phase_part}{status}: {first[:120]}")


def safe_error(exc: StructuredFailure | BaseException | str | None) -> str:
    """Short, allowlisted or redacted description. Provider HTTP bodies are dropped."""
    if exc is None:
        return ""
    if isinstance(exc, StructuredFailure):
        return exc.format()
    if isinstance(exc, str):
        return redact(exc)
    from mail_core.providers.http import ProviderHttpError

    if isinstance(exc, ProviderHttpError):
        return _format_provider_http_error(exc)
    # A325 + t091: non-provider exceptions converge deterministically via the
    # StructuredFailure allowlist (phase/status/errno/symbolic code only, never
    # raw messages or double-redacted regex stripping).
    return StructuredFailure.from_exception(exc).format()


def safe_provider_summary(
    exc: StructuredFailure | Mapping[str, Any] | BaseException | str | None,
) -> str:
    """Controlled allowlist projection for provider errors, health state, and job details."""
    if exc is None:
        return ""
    return coerce_structured_failure(exc).format()


_SAFE_EXC_ATTR = "_mail_core_safe_exc_text"


def _sanitize_log_arg(value: object) -> object:
    if isinstance(value, StructuredFailure):
        return value
    if isinstance(value, (str, BaseException)):
        return redact(str(value), limit=500)
    return value


def _collect_exception_chain(exc: BaseException) -> list[tuple[BaseException, str | None]]:
    curr: BaseException | None = exc
    chain: list[tuple[BaseException, str | None]] = []
    seen: set[int] = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        relation = None
        nxt: BaseException | None = None
        if curr.__cause__ is not None:
            relation = "The above exception was the direct cause of the following exception:"
            nxt = curr.__cause__
        elif curr.__context__ is not None and not curr.__suppress_context__:
            relation = "During handling of the above exception, another exception occurred:"
            nxt = curr.__context__
        chain.append((curr, relation))
        curr = nxt
    return chain


def _chain_requires_allowlist(chain: list[tuple[BaseException, str | None]]) -> bool:
    from mail_core.providers.http import ProviderHttpError

    for e, _ in chain:
        mod_lower = type(e).__module__.lower()
        if (
            isinstance(e, (ProviderHttpError, urllib.error.HTTPError))
            or "provider" in mod_lower
            or "provider" in type(e).__name__.lower()
            or "mail_core.net" in mod_lower
            or "imap4" in type(e).__qualname__.lower()
            or failure_phase_of(e) is not None
        ):
            return True
    return False


def format_safe_exception_chain(ei: tuple[type[BaseException], BaseException, Any]) -> str:
    """Format an exception traceback safely; provider/network chains use allowlist projection."""
    typ, exc, tb = ei
    if exc is None:
        return ""
    chain = _collect_exception_chain(exc)
    if not _chain_requires_allowlist(chain):
        raw = "".join(traceback.format_exception(typ, exc, tb))
        return redact(raw, limit=None)

    lines: list[str] = []
    reversed_chain = list(reversed(chain))
    for i, (e, rel) in enumerate(reversed_chain):
        lines.append("Traceback (most recent call last):\n")
        if e.__traceback__ is not None:
            tb_text = "".join(traceback.format_tb(e.__traceback__))
            lines.append(redact(tb_text, limit=None))
        safe_msg = StructuredFailure.from_exception(e).format()
        lines.append(f"{type(e).__module__}.{type(e).__qualname__}: {safe_msg}\n")
        if rel and i < len(reversed_chain) - 1:
            lines.append(f"\n{rel}\n\n")
    return "".join(lines)


def _redact_record_exceptions(record: logging.LogRecord) -> None:
    if isinstance(record.exc_text, str) and record.exc_text:
        if getattr(record, _SAFE_EXC_ATTR, None) != record.exc_text:
            record.exc_text = redact(record.exc_text, limit=None)
    elif record.exc_info and record.exc_info[0] is not None:
        try:
            record.exc_text = format_safe_exception_chain(record.exc_info)  # type: ignore[arg-type]
            setattr(record, _SAFE_EXC_ATTR, record.exc_text)
        except Exception:
            record.exc_text = f"{record.exc_info[0].__name__}: [REDACTED]"
    if isinstance(record.stack_info, str) and record.stack_info:
        record.stack_info = redact(record.stack_info, limit=None)


def _protect_structured_args(record: logging.LogRecord) -> tuple[Any, list[tuple[str, str]]]:
    args = record.args
    replacements: list[tuple[str, str]] = []
    if not args:
        return args, replacements
    if isinstance(args, Mapping):
        if not any(isinstance(v, StructuredFailure) for v in args.values()):
            return args, replacements
        protected_map: dict[Any, Any] = {}
        for k, v in args.items():
            if isinstance(v, StructuredFailure):
                marker = f"\x1f__KKMAIL_SF_{len(replacements)}__\x1f"
                replacements.append((marker, v.format()))
                protected_map[k] = marker
            else:
                protected_map[k] = v
        record.args = protected_map
        return args, replacements
    if isinstance(args, tuple) and any(isinstance(item, StructuredFailure) for item in args):
        protected_items: list[Any] = []
        for item in args:
            if isinstance(item, StructuredFailure):
                marker = f"\x1f__KKMAIL_SF_{len(replacements)}__\x1f"
                replacements.append((marker, item.format()))
                protected_items.append(marker)
            else:
                protected_items.append(item)
        record.args = tuple(protected_items)
    return args, replacements


def format_redacted_log_record(formatter: logging.Formatter, record: logging.LogRecord) -> str:
    """Format and redact a log record while preserving allowlisted StructuredFailure args/chains."""
    orig_args, replacements = _protect_structured_args(record)
    try:
        record.message = record.getMessage()
    finally:
        record.args = orig_args
    if formatter.usesTime():
        record.asctime = formatter.formatTime(record, formatter.datefmt)
    out = redact(formatter.formatMessage(record), limit=None)
    for marker, safe_val in replacements:
        out = out.replace(marker, safe_val)
    if record.exc_info and not record.exc_text:
        record.exc_text = formatter.formatException(record.exc_info)
        setattr(record, _SAFE_EXC_ATTR, record.exc_text)
    if record.exc_text:
        exc_out = (
            record.exc_text
            if getattr(record, _SAFE_EXC_ATTR, None) == record.exc_text
            else redact(record.exc_text, limit=None)
        )
        out = f"{out}{exc_out}" if out.endswith("\n") else f"{out}\n{exc_out}"
    if record.stack_info:
        stack_out = redact(formatter.formatStack(record.stack_info), limit=None)
        out = f"{out}{stack_out}" if out.endswith("\n") else f"{out}\n{stack_out}"
    return out


class RedactingFilter:
    """Standard logging.Filter that automatically redacts credentials from LogRecords.

    A326: the filter is self-sufficient — it also redacts exception
    tracebacks. ``record.exc_text`` is pre-generated from ``exc_info``
    (or redacted in place when already built) so that even a plain
    ``logging.Formatter`` — without RedactingTraceFormatter — cannot emit
    a plaintext traceback. Stack info is redacted the same way.
    """

    def filter(self, record: object) -> bool:
        if not isinstance(record, logging.LogRecord):
            return True
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, limit=2000)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _sanitize_log_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_sanitize_log_arg(arg) for arg in record.args)
        _redact_record_exceptions(record)
        return True

