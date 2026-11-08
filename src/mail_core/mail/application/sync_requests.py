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
    # A21: Decoupled inbox terminal state & background full sync status
    inbox_ready: bool = False
    background_request_id: str | None = None
    background_state: Literal["queued", "running", "complete", "failed"] | None = None
    background_errors: list[SyncTargetErrorOut] = Field(default_factory=list)


_SCOPE_KEYS = (
    "account_id",
    "group_id",
    "folder_id",
    "folder_role",
    "all",
    "background",
    "parent_request_id",
)


def _canonical_scope(
    scope: dict[str, Any] | None,
    *,
    account_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    folder_role: str | None = None,
    background: bool | None = None,
    parent_request_id: uuid.UUID | str | None = None,
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
            canonical[key] = bool(value) if key in ("all", "background") else str(value)
    for key, value in (
        ("account_id", account_id),
        ("group_id", group_id),
        ("folder_id", folder_id),
        ("folder_role", folder_role),
        ("background", background),
        ("parent_request_id", parent_request_id),
    ):
        if value is not None:
            canonical[key] = bool(value) if key in ("all", "background") else str(value)
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
    mode: str = "delta",
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
            # Non-selectable folders are excluded from synchronization
            # everywhere else in the system: role resolution below filters
            # them out, and the execution layer completes their jobs as
            # "skipped" (folder_not_selectable). They are paused by design
            # (Gmail virtual labels, \Noselect structure nodes, remotely
            # vanished folders) yet remain navigable views, so an explicit
            # id pointing at one resolves to an empty target set — the
            # request completes with zero targets — instead of a 422 the
            # UI's routine navigation sync cannot act on (p060).
            return []
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
        elif mode == "delta":
            # A21: If an account has a known selectable inbox, decouple inbox sync
            # so the primary sync request resolves directly to the inbox folder.
            inbox = session.scalars(
                select(Folder)
                .where(Folder.account_id == aid)
                .where(Folder.role == "inbox")
                .where(Folder.sync_status != SyncStatus.PAUSED.value)
            ).first()
            if inbox is not None:
                key = f"account:{aid}:folder:{inbox.id}:role:inbox"
                targets.append(TargetCandidate(account_id=aid, folder_id=inbox.id, folder_role="inbox", target_key=key))
            else:
                key = f"account:{aid}:folder:all:role:all"
                targets.append(TargetCandidate(account_id=aid, folder_id=None, folder_role=None, target_key=key))
        else:
            # Entire account (full scan discovery)
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
        mode=mode,
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

            # A21: Decouple inbox sync from background full sync (folder discovery + sibling folders)
            # When requesting a delta sync on account scope, accounts with an existing inbox have their
            # main request target mapped to the inbox folder (settles immediately upon inbox delta completion).
            # We schedule a background SyncRequest for full folder discovery and sibling folder sync.
            bg_account_ids = [
                cand.account_id
                for cand in candidates
                if cand.folder_id is not None and cand.folder_role == "inbox"
            ]
            if mode == "delta" and bg_account_ids and not scope.get("background") and folder_id is None:
                bg_request_id = uuid.uuid4()
                bg_client_req_id = f"bg_{request_id.hex}"
                bg_scope: dict[str, Any] = {"background": True, "parent_request_id": str(request_id)}
                if account_id is not None:
                    bg_scope["account_id"] = str(account_id)
                elif group_id is not None:
                    bg_scope["group_id"] = str(group_id)
                else:
                    bg_scope["all"] = True
                bg_req = SyncRequest(
                    id=bg_request_id,
                    client_request_id=bg_client_req_id,
                    mode="delta",
                    trigger=trigger,
                    state="queued",
                    scope=_canonical_scope(bg_scope),
                    created_at=now,
                )
                session.add(bg_req)
                session.flush()

                for aid in bg_account_ids:
                    bg_target = SyncRequestTarget(
                        id=uuid.uuid4(),
                        request_id=bg_request_id,
                        account_id=aid,
                        folder_id=None,
                        target_key=f"account:{aid}:folder:all:role:all",
                        requested_generation=uuid.uuid4(),
                        state="queued",
                        created_at=now,
                    )
                    session.add(bg_target)
                    session.flush()

                    bg_job = enqueue_job(
                        session,
                        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                        account_id=aid,
                        payload={"request_id": str(bg_request_id)},
                        priority=60,
                        dedupe_key=f"sync:{aid}",
                    )
                    bg_gen, bg_bound_job = binding_generation_for(session, bg_job)
                    bind_target(
                        session,
                        target=bg_target,
                        execution_generation=bg_gen,
                        job=bg_bound_job,
                        phase="folder_discovery",
                        folder_id=None,
                        status="queued",
                    )
                    bg_target.requested_generation = bg_gen

                req_scope = dict(req.scope or {})
                req_scope["background_request_id"] = str(bg_request_id)
                req.scope = req_scope

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


def _build_report(
    req: SyncRequest,
    targets: list[SyncRequestTarget],
    *,
    background_req: SyncRequest | None = None,
    background_targets: list[SyncRequestTarget] | None = None,
) -> SyncRequestOut:
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

    # A21: Decoupled inbox ready and background sync status
    inbox_targets = [t for t in targets if ":role:inbox" in t.target_key]
    if inbox_targets:
        inbox_ready = all(t.state == "complete" for t in inbox_targets)
    else:
        inbox_ready = current_state == "complete"
    bg_request_id_str: str | None = None
    bg_state: Literal["queued", "running", "complete", "failed"] | None = None
    bg_errors: list[SyncTargetErrorOut] = []

    if background_req is not None:
        bg_request_id_str = str(background_req.id)
        bg_state = background_req.state  # type: ignore[assignment]
        if background_targets:
            bg_errors = [
                SyncTargetErrorOut(target_id=str(t.id), code=t.error_code or "error", safe_message=t.safe_error)
                for t in background_targets
                if t.state == "failed"
            ]
    else:
        raw_bg_id = (req.scope or {}).get("background_request_id")
        if raw_bg_id:
            bg_request_id_str = str(raw_bg_id)

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
        inbox_ready=inbox_ready,
        background_request_id=bg_request_id_str,
        background_state=bg_state,
        background_errors=bg_errors,
    )


def get_sync_request_report(session: Session, request_id: uuid.UUID) -> SyncRequestOut | None:
    req = session.get(SyncRequest, request_id)
    if req is None:
        return None
    targets = list(
        session.scalars(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
        ).all()
    )
    bg_req = None
    bg_targets = None
    bg_id_str = (req.scope or {}).get("background_request_id")
    if bg_id_str:
        try:
            bg_id = uuid.UUID(str(bg_id_str))
            bg_req = session.get(SyncRequest, bg_id)
            if bg_req is not None:
                bg_targets = list(
                    session.scalars(
                        select(SyncRequestTarget).where(SyncRequestTarget.request_id == bg_id)
                    ).all()
                )
        except (ValueError, TypeError):
            pass
    return _build_report(req, targets, background_req=bg_req, background_targets=bg_targets)


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
    stored scopes may carry it ("inbox" by default), while a
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
    if bool(canonical.get("background")) != bool(wanted.get("background")):
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

    # Push the scope filter into SQL as far as it goes (A143): stored
    # scopes are canonical (identity values stored as strings), and
    # _scope_matches requires every identity key to be exactly equal --
    # a key the query did not specify must be absent (NULL) in storage,
    # and a specified folder_role must be equal. The Python matcher
    # below re-checks every row, so the SQL conditions only narrow.
    # The unfiltered (global) query has no pushable key; it is served
    # by the batched scan below instead of the old fixed 200-row window,
    # which starved older matching requests behind 200 newer unrelated
    # ones.
    conditions = [SyncRequest.state.in_(states)]
    if wanted:
        for key in _IDENTITY_SCOPE_KEYS:
            element = SyncRequest.scope[key]
            if key in wanted:
                conditions.append(element.as_string() == str(wanted[key]))
            else:
                conditions.append(element.as_string().is_(None))
        if "folder_role" in wanted:
            conditions.append(SyncRequest.scope["folder_role"].as_string() == str(wanted["folder_role"]))

    matched: list[SyncRequest] = []
    batch_size = 200
    offset = 0
    while len(matched) < capped:
        rows = list(
            session.scalars(
                select(SyncRequest)
                .where(*conditions)
                .order_by(SyncRequest.created_at.desc(), SyncRequest.id.desc())
                .limit(batch_size)
                .offset(offset)
            ).all()
        )
        if not rows:
            break
        for req in rows:
            if _scope_matches(_canonical_scope(req.scope), wanted):
                matched.append(req)
                if len(matched) >= capped:
                    break
        if len(rows) < batch_size:
            break
        offset += batch_size

    if not matched:
        return []

    # One batched target load for all matched requests (previously one
    # report query per request -- N+1), assembled in memory (A143).
    targets_by_request: dict[uuid.UUID, list[SyncRequestTarget]] = {}
    for target in session.scalars(
        select(SyncRequestTarget).where(
            SyncRequestTarget.request_id.in_([req.id for req in matched])
        )
    ).all():
        targets_by_request.setdefault(target.request_id, []).append(target)

    # Batch load background requests if any
    bg_ids: list[uuid.UUID] = []
    for req in matched:
        bg_id_str = (req.scope or {}).get("background_request_id")
        if bg_id_str:
            try:
                bg_ids.append(uuid.UUID(str(bg_id_str)))
            except (ValueError, TypeError):
                pass
    bg_requests: dict[uuid.UUID, SyncRequest] = {}
    bg_targets_by_request: dict[uuid.UUID, list[SyncRequestTarget]] = {}
    if bg_ids:
        for bg_r in session.scalars(select(SyncRequest).where(SyncRequest.id.in_(bg_ids))).all():
            bg_requests[bg_r.id] = bg_r
        for target in session.scalars(select(SyncRequestTarget).where(SyncRequestTarget.request_id.in_(bg_ids))).all():
            bg_targets_by_request.setdefault(target.request_id, []).append(target)

    reports: list[SyncRequestOut] = []
    for req in matched:
        bg_req = None
        bg_targets = None
        bg_id_str = (req.scope or {}).get("background_request_id")
        if bg_id_str:
            try:
                b_uuid = uuid.UUID(str(bg_id_str))
                bg_req = bg_requests.get(b_uuid)
                bg_targets = bg_targets_by_request.get(b_uuid, [])
            except (ValueError, TypeError):
                pass
        reports.append(
            _build_report(
                req,
                targets_by_request.get(req.id, []),
                background_req=bg_req,
                background_targets=bg_targets,
            )
        )
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
