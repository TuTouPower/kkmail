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

from mail_core.mail.domain.enums import ConnectivityState, CredentialState, SyncActivity
from mail_core.mail.storage.models import Account
from mail_core.security.redact import safe_provider_summary

CONNECTIVITY_FAILURE_THRESHOLD = 5
CONNECTIVITY_WINDOW = timedelta(seconds=300)

CFG_FAILURE_COUNT = "connectivity_failure_count"
CFG_FIRST_FAILURE_AT = "connectivity_first_failure_at"
CFG_LAST_CONNECTIVITY_ERROR = "last_connectivity_error"
CFG_LAST_SYNCED_AT = "last_synced_at"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _config(acc: Account) -> dict[str, Any]:
    return dict(acc.config or {})


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
    acc.connectivity_state = ConnectivityState.CONNECTED.value
    cfg = _config(acc)
    cfg.pop(CFG_FAILURE_COUNT, None)
    cfg.pop(CFG_FIRST_FAILURE_AT, None)
    cfg.pop(CFG_LAST_CONNECTIVITY_ERROR, None)
    cfg.pop("last_sync_error", None)
    cfg[CFG_LAST_SYNCED_AT] = now.isoformat()
    acc.config = cfg
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

    A single failure marks the account ``degraded`` (retry in progress).  Only
    after ``CONNECTIVITY_FAILURE_THRESHOLD`` consecutive failures spanning at
    least ``CONNECTIVITY_WINDOW`` does it escalate to ``unreachable``.
    """

    acc = session.get(Account, account_id)
    if acc is None:
        return None
    now = now or _now()
    cfg = _config(acc)

    first: datetime | None = None
    raw_first = cfg.get(CFG_FIRST_FAILURE_AT)
    if raw_first:
        try:
            first = datetime.fromisoformat(str(raw_first))
        except (ValueError, TypeError):
            first = None

    # The consecutive-failure counter is monotonic: a long pause between
    # failures (e.g. a 20-minute periodic poll) must not reset it, otherwise
    # the breaker could never reach its threshold within a realistic backoff
    # sequence.  Only a successful round trip clears it.
    if first is None:
        first = now
    count = int(cfg.get(CFG_FAILURE_COUNT, 0)) + 1

    elapsed = now - first
    if count >= CONNECTIVITY_FAILURE_THRESHOLD and elapsed >= CONNECTIVITY_WINDOW:
        state = ConnectivityState.UNREACHABLE
    else:
        state = ConnectivityState.DEGRADED

    acc.connectivity_state = state.value
    cfg[CFG_FAILURE_COUNT] = count
    cfg[CFG_FIRST_FAILURE_AT] = first.isoformat()
    cfg[CFG_LAST_CONNECTIVITY_ERROR] = safe_provider_summary(error)
    cfg[CFG_LAST_SYNCED_AT] = now.isoformat()
    acc.config = cfg
    session.flush()
    return state


def health_fields(acc: Account) -> dict[str, Any]:
    """Structured health projection for API DTOs."""

    cfg = _config(acc)
    return {
        "credential_state": acc.credential_state,
        "connectivity_state": acc.connectivity_state,
        "sync_activity": acc.sync_activity,
        "last_connectivity_error": cfg.get(CFG_LAST_CONNECTIVITY_ERROR),
    }
