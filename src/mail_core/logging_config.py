"""Structured logging with contextual trace_id and automatic sensitive-data redaction."""

from __future__ import annotations

import contextvars
import logging
import os
import sys
import traceback
from collections.abc import Generator
from contextlib import contextmanager

from mail_core.security.redact import RedactingFilter, redact, safe_provider_summary

_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    """Return the current trace/request identifier or empty string."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """Set the trace/request identifier for the current context."""
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """Reset the trace/request identifier to a previous context state."""
    _trace_id_var.reset(token)


@contextmanager
def trace_scope(trace_id: str) -> Generator[str, None, None]:
    """Context manager for scoping trace_id across sync/async blocks."""
    token = set_trace_id(trace_id)
    try:
        yield trace_id
    finally:
        reset_trace_id(token)


def _format_safe_exception_chain(ei: tuple[type[BaseException], BaseException, Any]) -> str:
    typ, exc, tb = ei
    if exc is None:
        return ""

    curr: BaseException | None = exc
    chain: list[tuple[BaseException, str | None]] = []
    seen: set[int] = set()
    while curr is not None and id(curr) not in seen:
        seen.add(id(curr))
        cause = curr.__cause__
        context = curr.__context__
        suppress_context = curr.__suppress_context__
        relation = None
        nxt: BaseException | None = None
        if cause is not None:
            relation = "The above exception was the direct cause of the following exception:"
            nxt = cause
        elif context is not None and not suppress_context:
            relation = "During handling of the above exception, another exception occurred:"
            nxt = context
        chain.append((curr, relation))
        curr = nxt

    from mail_core.providers.http import ProviderHttpError

    has_provider_error = False
    for e, _ in chain:
        if (
            isinstance(e, ProviderHttpError)
            or "provider" in type(e).__module__.lower()
            or "provider" in type(e).__name__.lower()
        ):
            has_provider_error = True
            break

    if not has_provider_error:
        raw = "".join(traceback.format_exception(typ, exc, tb))
        return redact(raw, limit=None)

    lines: list[str] = []
    reversed_chain = list(reversed(chain))
    for i, (e, rel) in enumerate(reversed_chain):
        lines.append("Traceback (most recent call last):\n")
        e_tb = e.__traceback__
        if e_tb is not None:
            lines.extend(traceback.format_tb(e_tb))
        safe_msg = safe_provider_summary(e)
        lines.append(f"{type(e).__module__}.{type(e).__qualname__}: {safe_msg}\n")
        if rel and i < len(reversed_chain) - 1:
            lines.append(f"\n{rel}\n\n")

    return redact("".join(lines), limit=None)


class RedactingTraceFormatter(logging.Formatter):
    """Logging formatter that injects trace_id and redacts sensitive credentials."""

    def formatException(self, ei: tuple[type[BaseException], BaseException, Any] | tuple[None, None, None]) -> str:
        if not ei or ei[0] is None:
            return ""
        return _format_safe_exception_chain(ei)  # type: ignore[arg-type]

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "trace_id") or not record.trace_id:
            tid = get_trace_id()
            record.trace_id = tid if tid else "-"
        formatted = super().format(record)
        return redact(formatted, limit=None)


def configure_logging(
    service_name: str = "mail-core",
    level: int | str | None = None,
) -> None:
    """Configure root logger with RedactingTraceFormatter and stdout streaming."""
    requested_level = level if level is not None else os.environ.get("MAIL_CORE_LOG_LEVEL", "INFO")
    if isinstance(requested_level, int):
        resolved_level = requested_level
    else:
        resolved_level = logging.getLevelName(str(requested_level).strip().upper())
    invalid_level = not isinstance(resolved_level, int)
    if invalid_level:
        resolved_level = logging.INFO

    root = logging.getLogger()
    root.setLevel(resolved_level)

    # A164: only remove handlers this function installed previously (they
    # carry the marker attribute); foreign handlers owned by the host
    # process or other libraries must survive reconfiguration. Removed
    # handlers are closed so file/socket handler resources are released.
    for handler in list(root.handlers):
        if getattr(handler, "_mail_core_installed", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    fmt = f"%(asctime)s %(levelname)s [{service_name}] [%(name)s] [trace:%(trace_id)s] %(message)s"
    formatter = RedactingTraceFormatter(fmt)

    handler = logging.StreamHandler(sys.stdout)
    handler._mail_core_installed = True  # type: ignore[attr-defined]
    handler.setFormatter(formatter)
    root.addHandler(handler)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactingFilter) for f in access_logger.filters):
        access_logger.addFilter(RedactingFilter())
    if invalid_level:
        logging.getLogger(__name__).warning("invalid logging level %r; using INFO", requested_level)
