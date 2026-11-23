"""Account health state machine.

Account health is modelled as three orthogonal states, stored directly on
``accounts``:

* ``credential_state``  — whether the stored credential can authenticate.
* ``connectivity_state`` — transport reachability, driven by a circuit breaker.
* ``sync_activity``      — whether a sync job is currently executing.

This module is the single authority for writing those states.  Transport
failures (network blips, proxy drops, timeouts) never touch the credential
state; only a confirmed provider authentication rejection invalidates it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    OutboxEventType,
    SyncActivity,
)
from mail_core.mail.storage.models import Account, OutboxEvent
from mail_core.security.redact import safe_provider_summary

CONNECTIVITY_FAILURE_THRESHOLD = 5
CONNECTIVITY_WINDOW = timedelta(seconds=300)
UNREACHABLE_RECHECK_INTERVAL = timedelta(minutes=15)

CFG_FAILURE_TIMESTAMPS = "connectivity_failure_timestamps"
CFG_LAST_CONNECTIVITY_ERROR = "last_connectivity_error"
CFG_LAST_SYNCED_AT = "last_synced_at"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _config(acc: Account) -> dict[str, Any]:
    return dict(acc.config or {})


def _publish_connectivity_change(
    session: Session, acc: Account, previous: str
) -> None:
    """Broadcast a real transition so every client invalidates cached health."""

    if previous != acc.connectivity_state:
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.ACCOUNT_UPDATED.value,
                account_id=acc.id,
                payload={"connectivity_state": acc.connectivity_state},
            )
        )


def _stored_failure_timestamps(cfg: dict[str, Any]) -> list[datetime]:
    raw = cfg.get(CFG_FAILURE_TIMESTAMPS)
    if not isinstance(raw, list):
        return []
    stamps: list[datetime] = []
    for item in raw:
        try:
            stamp = datetime.fromisoformat(str(item))
        except (ValueError, TypeError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamps.append(stamp)
    return stamps


def _failure_streak(cfg: dict[str, Any], now: datetime) -> list[datetime]:
    """Consecutive failures: a gap larger than the window starts a new streak."""

    stamps = _stored_failure_timestamps(cfg)
    if stamps and now - max(stamps) > CONNECTIVITY_WINDOW:
        return []
    return stamps


def mark_credential_invalid(session: Session, account_id: uuid.UUID) -> Account | None:
    """A confirmed authentication rejection: invalidate credential and stop sync."""

    acc = session.get(Account, account_id)
    if acc is None:
        return None
    acc.credential_state = CredentialState.INVALID.value
    acc.sync_enabled = False
    acc.sync_activity = SyncActivity.IDLE.value
    cfg = _config(acc)
    cfg[CFG_LAST_SYNCED_AT] = _now().isoformat()
    acc.config = cfg
    session.flush()
    return acc


def reset_credential(session: Session, account_id: uuid.UUID) -> Account | None:
    """After a successful re-authorization: restore credential and re-enable sync."""

    acc = session.get(Account, account_id)
    if acc is None:
        return None
    acc.credential_state = CredentialState.VALID.value
    acc.sync_enabled = True
    session.flush()
    return acc


def set_sync_activity(session: Session, account_id: uuid.UUID, *, active: bool) -> Account | None:
    acc = session.get(Account, account_id)
    if acc is None:
        return None
    acc.sync_activity = SyncActivity.SYNCING.value if active else SyncActivity.IDLE.value
    session.flush()
    return acc


def record_connectivity_success(
    session: Session, account_id: uuid.UUID, *, now: datetime | None = None
) -> Account | None:
    """Any successful provider round-trip deterministically closes the breaker."""

    acc = session.get(Account, account_id)
    if acc is None:
        return None
    now = now or _now()
    previous = acc.connectivity_state
    acc.connectivity_state = ConnectivityState.CONNECTED.value
    cfg = _config(acc)
    cfg.pop(CFG_FAILURE_TIMESTAMPS, None)
    cfg.pop(CFG_LAST_CONNECTIVITY_ERROR, None)
    cfg.pop("last_sync_error", None)
    cfg[CFG_LAST_SYNCED_AT] = now.isoformat()
    acc.config = cfg
    _publish_connectivity_change(session, acc, previous)
    session.flush()
    return acc


def record_connectivity_failure(
    session: Session,
    account_id: uuid.UUID,
    *,
    error: str,
    now: datetime | None = None,
) -> ConnectivityState | None:
    """Advance the breaker on a transport failure; return the resulting state.

    ``degraded`` after a single failure. ``unreachable`` once a streak has
    ``CONNECTIVITY_FAILURE_THRESHOLD`` failures with no adjacent gap larger
    than ``CONNECTIVITY_WINDOW`` and a first-failure-to-now span at least that
    window. A gap larger than the window starts a fresh streak, so intermittent
    failures days apart never escalate.
    """

    acc = session.get(Account, account_id)
    if acc is None:
        return None
    now = now or _now()
    previous = acc.connectivity_state
    cfg = _config(acc)

    stamps = _failure_streak(cfg, now)
    stamps.append(now)
    if len(stamps) >= CONNECTIVITY_FAILURE_THRESHOLD and now - min(stamps) >= CONNECTIVITY_WINDOW:
        state = ConnectivityState.UNREACHABLE
    else:
        state = ConnectivityState.DEGRADED

    acc.connectivity_state = state.value
    cfg[CFG_FAILURE_TIMESTAMPS] = [stamp.isoformat() for stamp in stamps]
    cfg[CFG_LAST_CONNECTIVITY_ERROR] = safe_provider_summary(error)
    cfg[CFG_LAST_SYNCED_AT] = now.isoformat()
    acc.config = cfg
    _publish_connectivity_change(session, acc, previous)
    session.flush()
    return state


def recheck_unreachable(
    session: Session, account_id: uuid.UUID, *, now: datetime | None = None
) -> ConnectivityState | None:
    """Bounded half-open re-check: demote a stale open breaker to degraded.

    Normal periodic sync then supplies the success event that closes the
    breaker.  Without this, an account with no foreground activity (paused or
    IDLE-held) keeps an open breaker forever, and any retry text is a lie.
    """

    acc = session.get(Account, account_id)
    if acc is None or acc.connectivity_state != ConnectivityState.UNREACHABLE.value:
        return None
    now = now or _now()
    stamps = _stored_failure_timestamps(_config(acc))
    if not stamps or now - max(stamps) < UNREACHABLE_RECHECK_INTERVAL:
        return None
    previous = acc.connectivity_state
    acc.connectivity_state = ConnectivityState.DEGRADED.value
    cfg = _config(acc)
    cfg[CFG_FAILURE_TIMESTAMPS] = [
        stamp.isoformat() for stamp in stamps if stamp >= now - CONNECTIVITY_WINDOW
    ]
    acc.config = cfg
    _publish_connectivity_change(session, acc, previous)
    session.flush()
    return ConnectivityState.DEGRADED


def health_fields(acc: Account) -> dict[str, Any]:
    """Structured health projection for API DTOs."""

    cfg = _config(acc)
    return {
        "credential_state": acc.credential_state,
        "connectivity_state": acc.connectivity_state,
        "sync_activity": acc.sync_activity,
        "last_connectivity_error": cfg.get(CFG_LAST_CONNECTIVITY_ERROR),
    }
