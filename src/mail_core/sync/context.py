"""Sync-layer context lineage and failure classification shared by sync/worker."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import SyncRequest


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
    payload = getattr(job, "payload", None)
    if not isinstance(payload, dict):
        return False, None
    request_id = _coerce_uuid(payload.get("request_id") or payload.get("parent_request_id"))
    if request_id is None:
        return False, None
    req = session.get(SyncRequest, request_id)
    if req is None:
        return False, request_id
    scope = req.scope if isinstance(req.scope, dict) else {}
    return bool(scope.get("background")), request_id


def is_permanent_auth_error(result: Any) -> bool:
    if isinstance(result, BaseException):
        from mail_core.providers.http import PermanentAuthError

        return isinstance(result, PermanentAuthError)
    if isinstance(result, dict):
        return any(
            str(result.get(key) or "") == SyncStatus.AUTH_FAILED.value
            for key in ("status", "error_code", "error")
        )
    return False


def account_sync_failure_status(*, result: Any, is_background: bool) -> SyncStatus | None:
    if is_permanent_auth_error(result):
        return SyncStatus.AUTH_FAILED
    if is_background:
        return None
    return SyncStatus.FAILED
