"""PostgreSQL LISTEN/NOTIFY wake helpers for the outbox dispatcher."""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

CHANNEL = "mail_core_outbox"
SESSION_REVOCATION_CHANNEL = "mail_core_session_revoked"
JOB_CHANNEL = "mail_core_jobs"
JOB_WAKE_CHANNEL = JOB_CHANNEL
log = logging.getLogger("mail_core.realtime.notify")
_monotonic = time.monotonic
_NOTIFY_WARNING_INTERVAL_S = 3600.0
_notify_failure_lock = threading.Lock()
_notify_first_failure_logged = False
_notify_failures_since_warning = 0
_notify_last_warning_at: float | None = None


def notify_outbox(session: Session) -> None:
    """Emit NOTIFY after outbox inserts (delivered when the transaction commits)."""
    session.execute(text(f"SELECT pg_notify('{CHANNEL}', 'wake')"))


def notify_jobs(session: Session) -> None:
    """Emit NOTIFY after runnable job inserts or accelerated merges (delivered when transaction commits)."""
    session.execute(text(f"SELECT pg_notify('{JOB_CHANNEL}', 'wake')"))


def notify_session_revocation(session: Session, session_epoch: int) -> None:
    """Publish a committed session-epoch change to every API process listener."""
    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": SESSION_REVOCATION_CHANNEL, "payload": str(session_epoch)},
    )


def try_notify_session_revocation(session: Session, session_epoch: int) -> None:
    try:
        with session.begin_nested():
            notify_session_revocation(session, session_epoch)
    except Exception as exc:
        _warn_notify_failure(exc)


def _warn_notify_failure(exc: Exception) -> None:
    global _notify_first_failure_logged, _notify_failures_since_warning, _notify_last_warning_at
    now = _monotonic()
    first_failure = False
    summary_count = 0
    with _notify_failure_lock:
        if not _notify_first_failure_logged:
            _notify_first_failure_logged = True
            _notify_last_warning_at = now
            first_failure = True
        else:
            _notify_failures_since_warning += 1
            if (
                _notify_last_warning_at is not None
                and now - _notify_last_warning_at >= _NOTIFY_WARNING_INTERVAL_S
            ):
                summary_count = _notify_failures_since_warning
                _notify_failures_since_warning = 0
                _notify_last_warning_at = now
    if first_failure:
        log.warning("pg_notify failed (non-fatal; error type=%s)", type(exc).__name__)
    elif summary_count:
        log.warning("pg_notify continues failing (non-fatal; %s failures since last warning)", summary_count)


def try_notify_outbox(session: Session) -> None:
    try:
        notify_outbox(session)
    except Exception as exc:
        _warn_notify_failure(exc)
