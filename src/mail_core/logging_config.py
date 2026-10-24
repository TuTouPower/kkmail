"""Structured logging with contextual trace_id and automatic sensitive-data redaction."""

from __future__ import annotations

import contextvars
import logging
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager

from mail_core.security.redact import RedactingFilter, redact

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


class RedactingTraceFormatter(logging.Formatter):
    """Logging formatter that injects trace_id and redacts sensitive credentials."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "trace_id") or not record.trace_id:
            tid = get_trace_id()
            record.trace_id = tid if tid else "-"
        formatted = super().format(record)
        return redact(formatted, limit=4000)


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

    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = f"%(asctime)s %(levelname)s [{service_name}] [%(name)s] [trace:%(trace_id)s] %(message)s"
    formatter = RedactingTraceFormatter(fmt)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactingFilter) for f in access_logger.filters):
        access_logger.addFilter(RedactingFilter())
    if invalid_level:
        logging.getLogger(__name__).warning("invalid logging level %r; using INFO", requested_level)
