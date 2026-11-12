"""Sync-layer context lineage and failure classification shared by sync/worker.

Account health is no longer a single enum: failures are classified into
orthogonal kinds so that a transient transport blip can never be mistaken for
an invalid credential (and vice versa).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.storage.models import SyncRequest

_TRANSIENT_MARKERS = (
    "oserror",
    "timeout",
    "timed out",
    "connection",
    "network",
    "unreachable",
    "ssl",
    "eof",
    "socket",
    "reset by peer",
    "temporarily",
    "broken pipe",
)


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def sync_context_payload(request_id: uuid.UUID | str | None = None, **extra: Any) -> dict[str, Any]:
    payload = {key: value for key, value in extra.items() if value is not None}
    if request_id is not None:
        payload["request_id"] = str(request_id)
    return payload


def resolve_sync_context(session: Session, job: Any) -> tuple[bool, uuid.UUID | None]:
    """Resolve whether a job belongs to a background (silent) sync.

    Background lineage is expressed either by an explicit top-level
    ``background`` marker (periodic/silent jobs) or by a ``SyncRequest`` whose
    scope carries ``background: True``.  A job with neither is foreground.
    """

    payload = getattr(job, "payload", None)
    if not isinstance(payload, dict):
        return False, None
    if bool(payload.get("background")):
        return True, None
    request_id = _coerce_uuid(payload.get("request_id") or payload.get("parent_request_id"))
    if request_id is None:
        return False, None
    req = session.get(SyncRequest, request_id)
    if req is None:
        return False, request_id
    scope = req.scope if isinstance(req.scope, dict) else {}
    return bool(scope.get("background")), request_id


_AUTH_MARKERS = (
    "auth_failed",
    "authenticationfailed",
    "invalid_grant",
    "invalid credentials",
    "basic auth disabled",
    "unauthorized",
    "permanentautherror",
    "status=401",
    "401 unauthorized",
    "invalidauthenticationtoken",
)


def is_permanent_auth_error(result: Any) -> bool:
    """A confirmed, non-refreshable provider credential rejection.

    Transport blips never carry these markers, so an auth failure can never
    be confused with a network failure (and vice versa).  Authentication
    signals are carried structurally (``PermanentAuthError``, HTTP 401, or an
    ``auth_failed`` error code) because ``safe_error`` deliberately strips the
    free-text provider message.
    """

    if isinstance(result, BaseException):
        from mail_core.providers.http import PermanentAuthError

        if isinstance(result, PermanentAuthError):
            return True
        if getattr(result, "status", None) == 401:
            return True
        text = f"{type(result).__name__} {result}".lower()
    elif isinstance(result, dict):
        if str(result.get("error_code") or "").lower() == "auth_failed":
            return True
        text = " ".join(
            str(result.get(key) or "")
            for key in ("status", "error_code", "error", "detail")
        ).lower()
    else:
        text = str(result).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def is_transient_network_error(result: Any) -> bool:
    """Whether a failure is a transport-level blip (never a credential issue)."""

    if isinstance(result, BaseException):
        if isinstance(result, (TimeoutError, ConnectionError, OSError)):
            return True
        name = type(result).__name__.lower()
        if any(token in name for token in ("ssl", "eof", "timeout", "socket", "connection")):
            return True
        text = str(result).lower()
    elif isinstance(result, dict):
        text = " ".join(
            str(result.get(key) or "")
            for key in ("status", "error", "error_code", "detail", "reason")
        ).lower()
    else:
        text = str(result).lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


class AccountFailureKind(StrEnum):
    AUTH = "auth"
    TRANSPORT = "transport"
    NONE = "none"


def account_failure_kind(*, result: Any, is_background: bool) -> AccountFailureKind:
    """Classify a sync failure into the account-health action it warrants.

    * A confirmed auth rejection invalidates the credential (foreground or
      background alike — a dead credential must be surfaced everywhere).
    * A transient transport blip only degrades connectivity for *foreground*
      work; silent background polling must never pollute account state.
    * Control-flow outcomes (rate limiting, capacity, lease/fencing) and
      permanent non-auth errors leave account health untouched.
    """

    if is_permanent_auth_error(result):
        return AccountFailureKind.AUTH
    if is_transient_network_error(result):
        return AccountFailureKind.NONE if is_background else AccountFailureKind.TRANSPORT
    return AccountFailureKind.NONE
