"""Application services for scoped delta/full synchronization requests (D10)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.accounts import enabled_account_ids
from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import (
    Account,
    AccountGroup,
    AccountSyncActivity,
    Folder,
    SyncCheckpoint,
    SyncRequest,
    SyncRequestTarget,
    WorkerJob,
)
from mail_core.sync.jobs import enqueue_job


class SyncTargetErrorOut(BaseModel):
    target_id: str
    code: str
    safe_message: str | None = None


class SyncRequestOut(BaseModel):
    id: str
    mode: Literal["delta", "full"]
    trigger: Literal["manual", "focus", "navigation", "initialization"]
    state: Literal["queued", "running", "complete", "failed"]
    target_count: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    created_at: str
    finished_at: str | None = None
    errors: list[SyncTargetErrorOut] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    account_id: uuid.UUID
    folder_id: uuid.UUID | None
    folder_role: str | None
    target_key: str


def resolve_sync_targets(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    folder_role: str | None = None,
    limit_accounts: int | None = None,
) -> list[TargetCandidate]:
    """Resolve targets while enforcing enabled status and selectable folders."""
    acc_ids = enabled_account_ids(session, group_id=group_id)
    if account_id is not None:
        if account_id not in acc_ids:
            acc = session.get(Account, account_id)
            if acc is not None and not acc.sync_enabled:
                raise ValueError("account_disabled")
            raise LookupError("account not found or not enabled in scope")
        acc_ids = [account_id]

    if limit_accounts is not None and len(acc_ids) > limit_accounts:
        # Pick top active accounts by recent foreground activity
        activity_rows = list(
            session.scalars(
                select(AccountSyncActivity.account_id)
                .where(AccountSyncActivity.account_id.in_(acc_ids))
                .order_by(AccountSyncActivity.last_foreground_at.desc())
                .limit(limit_accounts)
            ).all()
        )
        remaining = [aid for aid in acc_ids if aid not in activity_rows]
        acc_ids = (activity_rows + remaining)[:limit_accounts]

    targets: list[TargetCandidate] = []
    for aid in acc_ids:
        if folder_id is not None:
            folder = session.get(Folder, folder_id)
            if folder is None or folder.account_id != aid:
                raise LookupError("folder not found in account scope")
            if folder.sync_status == SyncStatus.PAUSED.value:
                raise ValueError("folder_not_selectable")
            key = f"account:{aid}:folder:{folder_id}:role:{folder.role or 'all'}"
            targets.append(TargetCandidate(account_id=aid, folder_id=folder_id, folder_role=folder.role, target_key=key))
        elif folder_role is not None:
            # All selectable folders matching this role
            role_folders = list(
                session.scalars(
                    select(Folder)
                    .where(Folder.account_id == aid)
                    .where(Folder.role == folder_role)
                    .where(Folder.sync_status != SyncStatus.PAUSED.value)
                ).all()
            )
            for f in role_folders:
                key = f"account:{aid}:folder:{f.id}:role:{folder_role}"
                targets.append(TargetCandidate(account_id=aid, folder_id=f.id, folder_role=folder_role, target_key=key))
        else:
            # Entire account
            key = f"account:{aid}:folder:all:role:all"
            targets.append(TargetCandidate(account_id=aid, folder_id=None, folder_role=None, target_key=key))

    return targets


def create_sync_request(
    session: Session,
    *,
    client_request_id: str,
    mode: Literal["delta", "full"],
    trigger: Literal["manual", "focus", "navigation", "initialization"],
    scope: dict[str, Any],
    account_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    folder_role: str | None = None,
    limit_accounts: int | None = None,
) -> tuple[SyncRequest, bool]:
    """Create or retrieve idempotent SyncRequest, enqueuing actual worker jobs."""
    existing = session.scalar(
        select(SyncRequest).where(SyncRequest.client_request_id == client_request_id)
    )
    if existing is not None:
        return existing, False

    candidates = resolve_sync_targets(
        session,
        account_id=account_id,
        group_id=group_id,
        folder_id=folder_id,
        folder_role=folder_role,
        limit_accounts=limit_accounts,
    )

    request_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    initial_state = "complete" if not candidates else "queued"
    req = SyncRequest(
        id=request_id,
        client_request_id=client_request_id,
        mode=mode,
        trigger=trigger,
        state=initial_state,
        scope=scope,
        created_at=now,
        finished_at=now if not candidates else None,
    )
    session.add(req)
    session.flush()

    generation = uuid.uuid4()
    for cand in candidates:
        target = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=request_id,
            account_id=cand.account_id,
            folder_id=cand.folder_id,
            target_key=cand.target_key,
            requested_generation=generation,
            state="queued",
            created_at=now,
        )
        session.add(target)
        session.flush()

        # Enqueue corresponding worker job
        if mode == "delta":
            if cand.folder_id is not None:
                job = enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    account_id=cand.account_id,
                    payload={"folder_id": str(cand.folder_id), "request_id": str(request_id)},
                    priority=20,
                    dedupe_key=f"delta:{cand.account_id}:{cand.folder_id}",
                )
            else:
                job = enqueue_job(
                    session,
                    job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                    account_id=cand.account_id,
                    payload={"request_id": str(request_id)},
                    priority=20,
                    dedupe_key=f"sync:{cand.account_id}",
                )
        else:
            job = enqueue_job(
                session,
                job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                account_id=cand.account_id,
                payload={"request_id": str(request_id), "full": True},
                priority=50,
                dedupe_key=f"sync:{cand.account_id}",
            )
        target.current_job_id = job.id

    session.flush()
    return req, True


def get_sync_request_report(session: Session, request_id: uuid.UUID) -> SyncRequestOut | None:
    req = session.get(SyncRequest, request_id)
    if req is None:
        return None

    targets = list(
        session.scalars(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
        ).all()
    )

    queued = sum(1 for t in targets if t.state == "queued")
    running = sum(1 for t in targets if t.state == "running")
    completed = sum(1 for t in targets if t.state == "complete")
    failed = sum(1 for t in targets if t.state == "failed")
    total = len(targets)

    # Re-evaluate overall state if all targets finished
    current_state = req.state
    if total > 0 and (completed + failed == total):
        current_state = "failed" if failed > 0 else "complete"
        if req.state != current_state:
            req.state = current_state
            req.finished_at = req.finished_at or datetime.now(timezone.utc)
            session.flush()
    elif total == 0:
        current_state = "complete"

    errors = [
        SyncTargetErrorOut(target_id=str(t.id), code=t.error_code or "error", safe_message=t.safe_error)
        for t in targets
        if t.state == "failed"
    ]

    return SyncRequestOut(
        id=str(req.id),
        mode=req.mode,  # type: ignore[arg-type]
        trigger=req.trigger,  # type: ignore[arg-type]
        state=current_state,  # type: ignore[arg-type]
        target_count=total,
        queued_count=queued,
        running_count=running,
        completed_count=completed,
        failed_count=failed,
        created_at=req.created_at.isoformat(),
        finished_at=req.finished_at.isoformat() if req.finished_at else None,
        errors=errors,
    )


def record_account_activity(session: Session, account_ids: list[uuid.UUID], ttl_seconds: int = 45) -> None:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    for aid in account_ids:
        act = session.get(AccountSyncActivity, aid)
        if act is None:
            act = AccountSyncActivity(account_id=aid, last_foreground_at=now, expires_at=expires)
            session.add(act)
        else:
            act.last_foreground_at = now
            act.expires_at = expires
    session.flush()
