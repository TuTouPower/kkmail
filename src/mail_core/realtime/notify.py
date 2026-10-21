"""PostgreSQL LISTEN/NOTIFY wake helpers for the outbox dispatcher."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

CHANNEL = "mail_core_outbox"
log = logging.getLogger("mail_core.realtime.notify")


def notify_outbox(session: Session) -> None:
    """Emit NOTIFY after outbox inserts (delivered when the transaction commits)."""
    session.execute(text(f"SELECT pg_notify('{CHANNEL}', 'wake')"))


def try_notify_outbox(session: Session) -> None:
    try:
        notify_outbox(session)
    except Exception:
        log.debug("pg_notify failed (non-fatal)", exc_info=True)
