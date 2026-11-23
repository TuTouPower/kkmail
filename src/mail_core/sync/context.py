"""Sync-layer context lineage and structured failure classification.

Failure domain is a typed property of the failure, never inferred from prose:
producers attach ``failure_code`` to result dicts at the point where a provider
exception is redacted, and exceptions are classified by type/status/errno.
Account health is derived only from that structure.
"""

from __future__ import annotations

import errno
import ssl
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.storage.models import SyncRequest

_NETWORK_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, name, None)
        for name in (
            "ECONNRESET",
            "ECONNREFUSED",
            "ETIMEDOUT",
            "EHOSTUNREACH",
            "ENETUNREACH",
            "ENETRESET",
            "ENETDOWN",
            "EPIPE",
            "ESHUTDOWN",
            "ENOTCONN",
            "EAGAIN",
            "EAI_AGAIN",
        )
    )
    if value is not None
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


class FailureDomain(StrEnum):
    AUTH = "auth"
    TRANSPORT = "transport"
    CONTROL = "control"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    domain: FailureDomain

    @property
    def code(self) -> str:
        return self.domain.value


_UNKNOWN = FailureClassification(FailureDomain.UNKNOWN)
_AUTH = FailureClassification(FailureDomain.AUTH)
_TRANSPORT = FailureClassification(FailureDomain.TRANSPORT)
_CONTROL = FailureClassification(FailureDomain.CONTROL)


def _classify_exception(result: BaseException) -> FailureClassification:
    from mail_core.providers.http import (
        PermanentAuthError,
        ProviderHttpError,
        RateLimitedError,
    )

    if isinstance(result, PermanentAuthError):
        return _AUTH
    status = getattr(result, "status", None)
    if status == 401 or getattr(result, "status_code", None) == 401:
        return _AUTH
    if isinstance(result, RateLimitedError):
        return _CONTROL
    if isinstance(result, (ConnectionError, TimeoutError, ssl.SSLError)):
        return _TRANSPORT
    if isinstance(result, OSError) and result.errno in _NETWORK_ERRNOS:
        return _TRANSPORT
    if isinstance(result, ProviderHttpError) and isinstance(status, int) and 500 <= status <= 599:
        return _TRANSPORT
    return _UNKNOWN


def _classify_result_dict(result: dict[str, Any]) -> FailureClassification:
    code = result.get("failure_code")
    if isinstance(code, str):
        try:
            return FailureClassification(FailureDomain(code))
        except ValueError:
            return _UNKNOWN
    status = result.get("status")
    if status == 401 or status == "auth_failed":
        return _AUTH
    if isinstance(status, int) and 500 <= status <= 599:
        return _TRANSPORT
    return _UNKNOWN


def classify_failure(result: Any) -> FailureClassification:
    """Classify a failure by type, HTTP status, errno or producer-attached code.

    Free-text provider messages are deliberately ignored: they are redacted,
    localized and reused for unrelated errors, so substring matching cannot be
    a classification contract.
    """

    if isinstance(result, BaseException):
        return _classify_exception(result)
    if isinstance(result, dict):
        return _classify_result_dict(result)
    if result == 401:
        return _AUTH
    return _UNKNOWN


class AccountFailureKind(StrEnum):
    AUTH = "auth"
    TRANSPORT = "transport"
    NONE = "none"


def account_failure_kind(*, result: Any, is_background: bool) -> AccountFailureKind:
    """Map a failure domain to the account-health action it warrants.

    Auth rejection is global. A transport blip is account-health relevant only
    for foreground work; silent background polling never pollutes state.
    Control-flow and unknown failures leave account health untouched.
    """

    domain = classify_failure(result).domain
    if domain is FailureDomain.AUTH:
        return AccountFailureKind.AUTH
    if domain is FailureDomain.TRANSPORT and not is_background:
        return AccountFailureKind.TRANSPORT
    return AccountFailureKind.NONE
