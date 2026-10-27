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
from mail_core.sync.execution import bind_target, binding_generation_for
from mail_core.sync.jobs import enqueue_job


def _payload_root_generation(payload: dict | None) -> uuid.UUID | None:
    """Root scan generation carried by a job payload, if it is a full scan."""
    payload = payload or {}
    if not payload.get("full"):
        # A claimed job may carry the full request only in its successor.
        queue_next = payload.get("_queue_next") or {}
        payload = queue_next.get("payload") or {}
        if not payload.get("full"):
            return None
    raw = payload.get("scan_generation")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _inflight_full_root_generation(session: Session, account_id: uuid.UUID) -> uuid.UUID | None:
    """Root scan generation of an in-flight full scan for this account, if any.

    The scan is in flight not only while its folder-discovery job
    (``sync:{account_id}``) is active: after discovery completes, the
    scan continues in per-folder metadata jobs
    (``metadata:{account_id}:{folder_id}``) whose payloads carry the
    same root generation. Both phases count -- otherwise a full request
    issued during the metadata phase allocates a second root generation
    and forces a redundant rescan with a cursor reset.
    """
    job = session.scalar(
        select(WorkerJob)
        .where(WorkerJob.dedupe_key == f"sync:{account_id}")
        .where(WorkerJob.status.in_(["pending", "claimed"]))
        .limit(1)
    )
    if job is not None:
        generation = _payload_root_generation(job.payload)
        if generation is not None:
            return generation
        # Root job is not a full scan (e.g. a delta): the in-flight full
        # scan, if any, may still be in its metadata phase -- fall through
        # and check the metadata jobs instead of giving up (A84).
    metadata_jobs = session.scalars(
        select(WorkerJob)
        .where(WorkerJob.dedupe_key.like(f"metadata:{account_id}:%"))
        .where(WorkerJob.status.in_(["pending", "claimed"]))
        .order_by(WorkerJob.created_at)
    ).all()
    for metadata_job in metadata_jobs:
        generation = _payload_root_generation(metadata_job.payload)
        if generation is not None:
            return generation
    return None


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


_SCOPE_KEYS = ("account_id", "group_id", "folder_id", "folder_role", "all")


def _canonical_scope(
    scope: dict[str, Any] | None,
    *,
    account_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    folder_role: str | None = None,
) -> dict[str, Any]:
    """Normalize a sync scope so idempotency compares intent, not serialization.

    Only scope-defining fields survive: trigger / client_request_id stored in a
    raw request dump, ordering, and UUID-vs-string spellings must not make the
    same intent look different. Explicit arguments win over the scope dict.
    """
    canonical: dict[str, Any] = {}
    raw = scope or {}
    for key in _SCOPE_KEYS:
        value = raw.get(key)
        if value is not None:
            canonical[key] = str(value) if key != "all" else bool(value)
    for key, value in (
        ("account_id", account_id),
        ("group_id", group_id),
        ("folder_id", folder_id),
        ("folder_role", folder_role),
    ):
        if value is not None:
            canonical[key] = str(value)
    return canonical


def _intent_matches(existing: SyncRequest, *, mode: str, trigger: str, canonical_scope: dict[str, Any]) -> bool:
    return (
        existing.mode == mode
        and existing.trigger == trigger
        and _canonical_scope(existing.scope) == canonical_scope
    )


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

    if folder_id is not None:
        # An exact folder target resolves against its owning account only;
        # ownership is validated against the requested scope (enabled accounts,
        # or the requested group/account), never degraded to a broader sync.
        folder = session.get(Folder, folder_id)
        if folder is None or folder.account_id not in acc_ids:
            raise LookupError("folder not found in account scope")
        if folder.sync_status == SyncStatus.PAUSED.value:
            raise ValueError("folder_not_selectable")
        key = f"account:{folder.account_id}:folder:{folder_id}:role:{folder.role or 'all'}"
        return [
            TargetCandidate(
                account_id=folder.account_id, folder_id=folder_id, folder_role=folder.role, target_key=key
            )
        ]

    targets: list[TargetCandidate] = []
    for aid in acc_ids:
        if folder_role is not None:
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
    """Create or retrieve idempotent SyncRequest, enqueuing actual worker jobs.

    Idempotency is keyed by client_request_id plus intent: the same ID with the
    same normalized scope/mode/trigger returns the existing request; the same ID
    with a different intent is a conflict (callers map it to 409). A unique
    violation from a concurrent insert is resolved by savepoint rollback and a
    re-read, never surfaced as a 500.
    """
    if not 1 <= len(client_request_id) <= 64:
        raise ValueError("client_request_id must be between 1 and 64 characters")
    if group_id is not None and (account_id is not None or folder_id is not None):
        raise ValueError("group_id cannot be combined with account_id or folder_id")

    canonical_scope = _canonical_scope(
        scope, account_id=account_id, group_id=group_id, folder_id=folder_id, folder_role=folder_role
    )

    existing = session.scalar(
        select(SyncRequest).where(SyncRequest.client_request_id == client_request_id)
    )
    if existing is not None:
        if _intent_matches(existing, mode=mode, trigger=trigger, canonical_scope=canonical_scope):
            return existing, False
        raise ValueError("client_request_id_conflict")

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
        scope=canonical_scope,
        created_at=now,
        finished_at=now if not candidates else None,
    )
    try:
        with session.begin_nested():
            session.add(req)
            session.flush()

            for cand in candidates:
                target = SyncRequestTarget(
                    id=uuid.uuid4(),
                    request_id=request_id,
                    account_id=cand.account_id,
                    folder_id=cand.folder_id,
                    target_key=cand.target_key,
                    requested_generation=uuid.uuid4(),
                    state="queued",
                    created_at=now,
                )
                session.add(target)
                session.flush()

                # Enqueue the worker job and bind this target to the actual
                # execution in the same transaction (design §5.2): a pending
                # deduplicated job is observed under its own generation; a
                # CLAIMED job's observer binds the pre-allocated successor
                # generation, never the running execution.
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
                        phase = "delta"
                    else:
                        job = enqueue_job(
                            session,
                            job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                            account_id=cand.account_id,
                            payload={"request_id": str(request_id)},
                            priority=20,
                            dedupe_key=f"sync:{cand.account_id}",
                        )
                        phase = "folder_discovery"
                    generation, bound_job = binding_generation_for(session, job)
                    bind_target(
                        session,
                        target=target,
                        execution_generation=generation,
                        job=bound_job,
                        phase=phase,
                        folder_id=cand.folder_id,
                        status="queued",
                    )
                    # For delta the bound execution is the logical root.
                    target.requested_generation = generation
                else:
                    # Full scan: reuse the in-flight scan's root generation
                    # when one is already running for this account, so the
                    # new request observes the same scan instead of forcing
                    # a second cursor reset (design §5.2/§5.3).
                    root_generation = _inflight_full_root_generation(session, cand.account_id)
                    if root_generation is None:
                        root_generation = uuid.uuid4()
                    job = enqueue_job(
                        session,
                        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                        account_id=cand.account_id,
                        payload={
                            "request_id": str(request_id),
                            "full": True,
                            "scan_generation": str(root_generation),
                        },
                        priority=50,
                        dedupe_key=f"sync:{cand.account_id}",
                    )
                    generation, bound_job = binding_generation_for(session, job)
                    bind_target(
                        session,
                        target=target,
                        execution_generation=generation,
                        job=bound_job,
                        phase="folder_discovery",
                        folder_id=cand.folder_id,
                        status="queued",
                    )
                    target.requested_generation = root_generation

            session.flush()
    except IntegrityError:
        # A concurrent request with the same client_request_id won the insert;
        # the savepoint rollback left the session usable, so re-read and apply
        # the same intent rules instead of failing with a 500.
        existing = session.scalar(
            select(SyncRequest).where(SyncRequest.client_request_id == client_request_id)
        )
        if existing is None:
            raise
        if _intent_matches(existing, mode=mode, trigger=trigger, canonical_scope=canonical_scope):
            return existing, False
        raise ValueError("client_request_id_conflict") from None
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

    # Read-only: request state/finished_at are persisted by the settlement
    # path (mail_core.sync.execution.refresh_requests) in the write
    # transaction; GET never mutates them (design §5.2).
    current_state = req.state
    if total == 0:
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


#: Scope keys that identify *whose* mail a request syncs. They must match
#: exactly, in both directions: a request carrying an identity key the
#: query did not specify belongs to a narrower (different) scope and must
#: never be returned for it — the pre-fix subset matcher did exactly that,
#: leaking a single account's progress into the global view (DEFECT 5).
_IDENTITY_SCOPE_KEYS = ("account_id", "group_id", "folder_id", "all")

#: The canonical scope stored for a global (all-accounts) request, as
#: created by POST /api/accounts/sync-all (``scope={"all": True}``).
_GLOBAL_SCOPE: dict[str, Any] = {"all": True}


def _scope_matches(canonical: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Whether a stored canonical scope is the scope a list query asked for.

    Matching is scope-exact on the identity keys (account/group/folder/all),
    mirroring the exact canonical comparison used for idempotency in
    ``_intent_matches``. ``folder_role`` is the one legitimate exception:
    stored delta scopes always carry it (DeltaSyncIn defaults it to
    "inbox" and the frontend pairs every identity with a role), while a
    query may specify an identity without a role — an omitted role means
    "any role within this identity scope", so a stored role does not
    contradict it. When the query does specify a role, it must be equal.
    A query with no filters at all is the global query: only requests
    whose canonical scope is exactly the global scope match it.
    """
    if not wanted:
        return canonical == _GLOBAL_SCOPE
    for key in _IDENTITY_SCOPE_KEYS:
        if canonical.get(key) != wanted.get(key):
            return False
    if "folder_role" in wanted and canonical.get("folder_role") != wanted["folder_role"]:
        return False
    return True


def list_recent_sync_requests(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    folder_role: str | None = None,
    states: tuple[str, ...] = ("queued", "running"),
    limit: int = 50,
) -> list[SyncRequestOut]:
    """Recent unfinished requests matching a scope (repair design §6).

    The frontend progress hook uses this after a reload to re-adopt the
    current scope's in-flight request instead of POSTing a duplicate.
    Matching is scope-exact (see ``_scope_matches``): a scoped request is
    never returned for a different scope, and the unfiltered (global)
    query returns only global requests. Results are newest first and
    capped at 50.
    """
    wanted = _canonical_scope(
        None,
        account_id=account_id,
        group_id=group_id,
        folder_id=folder_id,
        folder_role=folder_role,
    )
    capped = max(1, min(int(limit), 50))
    rows = list(
        session.scalars(
            select(SyncRequest)
            .where(SyncRequest.state.in_(states))
            .order_by(SyncRequest.created_at.desc())
            .limit(200)
        ).all()
    )
    reports: list[SyncRequestOut] = []
    for req in rows:
        canonical = _canonical_scope(req.scope)
        if not _scope_matches(canonical, wanted):
            continue
        report = get_sync_request_report(session, req.id)
        if report is not None:
            reports.append(report)
        if len(reports) >= capped:
            break
    return reports


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
