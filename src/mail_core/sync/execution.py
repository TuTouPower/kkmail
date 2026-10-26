"""Sync-request execution tracking: bindings, settlement, aggregation (R06).

Implements repair design §5.1/§5.2. A ``SyncRequestTarget`` is satisfied by
one or more job *executions*, recorded relationally in
``SyncRequestTargetJob`` rows keyed by ``(target_id, execution_generation)``:

- a pending deduplicated job is reused under its own ``execution_generation``;
- a request arriving while its job is CLAIMED binds the successor generation
  pre-allocated exactly once in the job's ``_queue_next`` payload — never the
  running execution;
- ``complete_job`` creates/binds the successor and carries still-open targets
  in the same transaction, except when the successor is the next periodic
  poll round (periodic polling uses an independent generation and inherits
  no observers);
- retriable failure keeps targets open on the same generation; terminal
  failure, account/folder deletion, or a lost execution fails them with a
  stable ``error_code`` and a sanitized message.

Settlement lock order (design §5.2) is fixed: WorkerJob row → generation
coordination lock (advisory) → binding rows → ALL Targets of every
affected request (UUID ascending, one pass, before any Target is held)
→ Requests (UUID ascending). Request state and ``finished_at`` are derived
from target aggregation and persisted here, in the write transaction; the
report endpoint is read-only. Every persisted request state change emits a
``sync.request_updated`` Outbox event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobStatus, OutboxEventType
from mail_core.mail.storage.models import (
    OutboxEvent,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)

OPEN_BINDING_STATES = ("queued", "running")
TERMINAL_BINDING_STATES = ("complete", "failed")
TERMINAL_TARGET_STATES = ("complete", "failed")

BASELINE_REQUIRED_MESSAGE = (
    "Folder has no completed baseline scan; a full initialization scan is required before delta sync"
)
EXECUTION_LOST_MESSAGE = "The bound sync execution no longer exists"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lock_generation(session: Session, generation: uuid.UUID) -> None:
    """Per-generation coordination lock, taken after the WorkerJob row lock."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": str(generation)},
    )


def ensure_successor_generation(session: Session, job: WorkerJob) -> uuid.UUID:
    """Return the successor generation for a CLAIMED job, allocating it once.

    The generation lives in the job's ``_queue_next`` payload so that
    ``complete_job`` creates the successor with exactly this generation and
    requests bound to it are satisfied by that successor — not by the
    currently running execution.
    """
    payload = dict(job.payload or {})
    queue_next = dict(payload.get("_queue_next") or {})
    existing = queue_next.get("execution_generation")
    if existing:
        try:
            return uuid.UUID(str(existing))
        except (ValueError, TypeError):
            pass
    generation = uuid.uuid4()
    queue_next["execution_generation"] = str(generation)
    payload["_queue_next"] = queue_next
    job.payload = payload
    session.flush()
    return generation


def binding_generation_for(session: Session, job: WorkerJob) -> tuple[uuid.UUID, WorkerJob | None]:
    """Generation a new observer of ``job`` must bind, and the job row if live.

    PENDING jobs bind their own generation. CLAIMED jobs bind the pre-allocated
    successor generation with no job row yet (``job_id`` stays NULL until
    ``complete_job`` materializes the successor).
    """
    if job.status == JobStatus.CLAIMED.value:
        return ensure_successor_generation(session, job), None
    return job.execution_generation, job


def find_active_job(session: Session, dedupe_key: str) -> WorkerJob | None:
    return session.scalar(
        select(WorkerJob)
        .where(WorkerJob.dedupe_key == dedupe_key)
        .where(WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]))
        .limit(1)
    )


def bind_target(
    session: Session,
    *,
    target: SyncRequestTarget,
    execution_generation: uuid.UUID,
    job: WorkerJob | None = None,
    phase: str = "sync",
    folder_id: uuid.UUID | None = None,
    status: str = "queued",
) -> SyncRequestTargetJob:
    """Create or update the (target, generation) binding row."""
    binding = session.scalar(
        select(SyncRequestTargetJob).where(
            SyncRequestTargetJob.target_id == target.id,
            SyncRequestTargetJob.execution_generation == execution_generation,
        )
    )
    if binding is None:
        binding = SyncRequestTargetJob(
            id=uuid.uuid4(),
            target_id=target.id,
            execution_generation=execution_generation,
            job_id=job.id if job is not None else None,
            phase=phase,
            folder_id=folder_id if folder_id is not None else target.folder_id,
            status=status,
            created_at=_now(),
        )
        session.add(binding)
    else:
        if job is not None and binding.job_id is None:
            binding.job_id = job.id
        if binding.phase == "sync" and phase != "sync":
            binding.phase = phase
        if binding.folder_id is None and folder_id is not None:
            binding.folder_id = folder_id
    session.flush()
    return binding


def _aggregate_target(session: Session, target: SyncRequestTarget) -> None:
    """Derive one target's state from its bindings (bindings already locked)."""
    bindings = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.target_id == target.id)
            .order_by(SyncRequestTargetJob.created_at, SyncRequestTargetJob.id)
        ).all()
    )
    if not bindings:
        return
    if any(b.status in OPEN_BINDING_STATES for b in bindings):
        target.state = (
            "running"
            if any(b.status == "running" or b.status == "complete" for b in bindings)
            else "queued"
        )
        target.finished_at = None
        return
    failed = [b for b in bindings if b.status == "failed"]
    if failed:
        target.state = "failed"
        target.error_code = failed[0].error_code or "sync_failed"
        target.safe_error = failed[0].safe_error
    else:
        target.state = "complete"
        target.error_code = None
        target.safe_error = None
    target.finished_at = _now()


def refresh_requests(session: Session, request_ids: Iterable[uuid.UUID]) -> None:
    """Re-aggregate targets and persist request state/finished_at + Outbox event.

    This is the only place request state moves after creation; the report
    endpoint never writes.

    Lock acquisition follows the settlement lock order in two phases,
    regardless of entry point: Phase 1 locks ALL involved
    ``SyncRequestTarget`` rows (UUID ascending), Phase 2 locks ALL involved
    ``SyncRequest`` rows (UUID ascending), and only then does Phase 3
    aggregate and persist. Taking a Request lock before its Target locks
    (the old per-request loop) inverts the order used by callers that
    already hold Target locks (``settle_job_bindings``) and deadlocks
    against them. Callers holding Target locks are only safe because
    ``settle_job_bindings`` pre-locks this same full Target set before
    holding any single Target: a caller holding merely a subset of a
    request's Targets would wait on the remaining (possibly lower) rows
    here while another settler holds them and waits back.
    """
    ids = sorted({rid for rid in request_ids if rid is not None})
    if not ids:
        return
    # Phase 1: lock every involved Target first, UUID ascending.
    targets_by_request: dict[uuid.UUID, list[SyncRequestTarget]] = {}
    for target in session.scalars(
        select(SyncRequestTarget)
        .where(SyncRequestTarget.request_id.in_(ids))
        .order_by(SyncRequestTarget.id)
        .with_for_update()
    ).all():
        targets_by_request.setdefault(target.request_id, []).append(target)
    # Phase 2: lock every involved Request, UUID ascending.
    requests = {
        req.id: req
        for req in session.scalars(
            select(SyncRequest)
            .where(SyncRequest.id.in_(ids))
            .order_by(SyncRequest.id)
            .with_for_update()
        ).all()
    }
    # Phase 3: aggregate and persist, reusing the already-locked rows.
    for request_id in ids:
        req = requests.get(request_id)
        if req is None:
            continue
        targets = targets_by_request.get(request_id, [])
        for target in targets:
            _aggregate_target(session, target)
        if not targets:
            continue
        if all(t.state in TERMINAL_TARGET_STATES for t in targets):
            new_state = "failed" if any(t.state == "failed" for t in targets) else "complete"
        elif any(t.state in ("running", "complete", "failed") for t in targets):
            new_state = "running"
        else:
            new_state = "queued"
        if req.state != new_state:
            req.state = new_state
            req.finished_at = _now() if new_state in TERMINAL_TARGET_STATES else None
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.SYNC_REQUEST_UPDATED.value,
                    account_id=None,
                    payload={"request_id": str(request_id), "state": new_state, "mode": req.mode},
                )
            )
    session.flush()


def _successor_is_periodic(job: WorkerJob, successor: WorkerJob | None, result: dict | None) -> bool:
    """A successor carrying a new ``poll_round`` is the next periodic poll.

    Poll rounds are independent executions: they must not inherit the
    observers of the round that just finished (design §5.2). Continuation
    successors (pagination, retries, claimed-job wakeups) never advance
    ``poll_round``.
    """
    if successor is None:
        return False
    successor_payload = successor.payload or {}
    if "poll_round" not in successor_payload:
        return False
    if result and result.get("exhausted"):
        return True
    try:
        return int(successor_payload.get("poll_round") or 0) > int((job.payload or {}).get("poll_round") or 0)
    except (TypeError, ValueError):
        return False


def _bind_initialization(session: Session, *, target: SyncRequestTarget, folder_id: uuid.UUID | None) -> None:
    """Bind a delta target to the in-flight initialization (metadata) scan."""
    if target.account_id is None or folder_id is None:
        return
    job = find_active_job(session, f"metadata:{target.account_id}:{folder_id}")
    if job is None:
        return
    generation, bound_job = binding_generation_for(session, job)
    bind_target(
        session,
        target=target,
        execution_generation=generation,
        job=bound_job,
        phase="initialization",
        folder_id=folder_id,
        status="queued",
    )


def settle_job_bindings(
    session: Session,
    job: WorkerJob,
    *,
    outcome: str,
    result: dict | None = None,
    error_code: str | None = None,
    safe_error: str | None = None,
    successor: WorkerJob | None = None,
) -> set[uuid.UUID]:
    """Settle every binding observing ``job``'s execution generation.

    ``outcome`` is one of ``"complete"``, ``"failed"`` (terminal) or
    ``"retriable"`` (targets stay open, progress retained, same generation).
    Callers must already hold the WorkerJob row lock (complete_job/fail_job
    do); this function then takes the generation lock, the binding locks,
    and — before mutating anything — locks ALL Targets of every affected
    request in one UUID-ascending pass (the same set
    :func:`refresh_requests` will lock). Locking only this job's target
    subset first deadlocks two workers settling different jobs of the
    same request: each would enter the refresh phase already holding a
    set member and wait on a lower member the other holds.
    Returns the affected request IDs; callers persist the aggregation via
    :func:`refresh_requests` in the same transaction (see jobs.py).
    """
    generation = getattr(job, "execution_generation", None)
    if generation is None or not hasattr(session, "scalars"):
        return set()
    lock_generation(session, generation)
    bindings = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.execution_generation == generation)
            .order_by(SyncRequestTargetJob.target_id)
            .with_for_update()
        ).all()
    )
    if not bindings:
        return set()
    target_ids = sorted({b.target_id for b in bindings})
    # Planning read (no lock): which requests do these targets belong to?
    affected_request_ids = sorted(
        {
            rid
            for rid in session.scalars(
                select(SyncRequestTarget.request_id).where(
                    SyncRequestTarget.id.in_(target_ids)
                )
            ).all()
            if rid is not None
        }
    )
    # Pre-lock the full target set of every affected request, UUID
    # ascending, before this transaction holds any single Target row:
    # refresh_requests later re-locks the same rows (a no-op), so the
    # settlement path never waits on a Target while holding another.
    targets = {
        t.id: t
        for t in session.scalars(
            select(SyncRequestTarget)
            .where(SyncRequestTarget.request_id.in_(affected_request_ids))
            .order_by(SyncRequestTarget.id)
            .with_for_update()
        ).all()
    } if affected_request_ids else {}
    now = _now()
    periodic = _successor_is_periodic(job, successor, result)
    successor_generation = getattr(successor, "execution_generation", None) if successor is not None else None
    request_ids: set[uuid.UUID] = set()
    for binding in bindings:
        target = targets.get(binding.target_id)
        if target is None:
            continue
        request_ids.add(target.request_id)
        if binding.status in TERMINAL_BINDING_STATES:
            continue
        if outcome == "retriable":
            # Same generation retries: keep the target open with its progress.
            binding.status = "queued"
            binding.finished_at = None
            continue
        if outcome == "failed":
            binding.status = "failed"
            binding.error_code = error_code or "job_failed"
            binding.safe_error = (safe_error or "")[:500] or None
            binding.finished_at = now
            continue
        # outcome == "complete"
        if result and result.get("baseline_required"):
            binding.status = "failed"
            binding.error_code = "baseline_required"
            binding.safe_error = BASELINE_REQUIRED_MESSAGE
            binding.finished_at = now
            continue
        binding.status = "complete"
        binding.finished_at = now
        if result and result.get("await_initialization"):
            _bind_initialization(session, target=target, folder_id=binding.folder_id or target.folder_id)
        elif successor is not None and successor_generation is not None and not periodic:
            bind_target(
                session,
                target=target,
                execution_generation=successor_generation,
                job=successor,
                phase=binding.phase,
                folder_id=binding.folder_id,
                status="queued",
            )
    session.flush()
    return request_ids


def mark_bindings_running(session: Session, jobs: list[WorkerJob]) -> None:
    """Claim-time hook: bindings attached to newly claimed jobs become running."""
    job_ids = [j.id for j in jobs if getattr(j, "id", None) is not None]
    if not job_ids or not hasattr(session, "scalars"):
        return
    bindings = list(
        session.scalars(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.job_id.in_(job_ids),
                SyncRequestTargetJob.status == "queued",
            )
        ).all()
    )
    if not bindings:
        return
    for binding in bindings:
        binding.status = "running"
    session.flush()
    target_ids = {b.target_id for b in bindings}
    request_ids = {
        t.request_id
        for t in session.scalars(
            select(SyncRequestTarget).where(SyncRequestTarget.id.in_(list(target_ids)))
        ).all()
    }
    refresh_requests(session, request_ids)


def reset_bindings_for_job(session: Session, job: WorkerJob) -> set[uuid.UUID]:
    """Reclaim hook: a reclaimed claim's running bindings return to queued."""
    if not hasattr(session, "scalars"):
        return set()
    bindings = list(
        session.scalars(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.job_id == job.id,
                SyncRequestTargetJob.status == "running",
            )
        ).all()
    )
    if not bindings:
        return set()
    for binding in bindings:
        binding.status = "queued"
    session.flush()
    target_ids = {b.target_id for b in bindings}
    return {
        t.request_id
        for t in session.scalars(
            select(SyncRequestTarget).where(SyncRequestTarget.id.in_(list(target_ids)))
        ).all()
    }


def fail_open_targets(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    error_code: str,
    safe_error: str,
) -> set[uuid.UUID]:
    """Fail every still-open target for an account/folder being deleted.

    Deletion paths call this before removing the entity so associated sync
    requests converge to an explicit failure instead of pointing at a gone
    account/folder (design §5.2).
    """
    stmt = select(SyncRequestTarget).where(SyncRequestTarget.state.in_(["queued", "running"]))
    if account_id is not None:
        stmt = stmt.where(SyncRequestTarget.account_id == account_id)
    if folder_id is not None:
        stmt = stmt.where(SyncRequestTarget.folder_id == folder_id)
    targets = list(session.scalars(stmt.order_by(SyncRequestTarget.id).with_for_update()).all())
    now = _now()
    request_ids: set[uuid.UUID] = set()
    for target in targets:
        bindings = list(
            session.scalars(
                select(SyncRequestTargetJob).where(
                    SyncRequestTargetJob.target_id == target.id,
                    SyncRequestTargetJob.status.in_(OPEN_BINDING_STATES),
                )
            ).all()
        )
        for binding in bindings:
            binding.status = "failed"
            binding.error_code = error_code
            binding.safe_error = safe_error[:500]
            binding.finished_at = now
        target.state = "failed"
        target.error_code = error_code
        target.safe_error = safe_error[:500]
        target.finished_at = now
        request_ids.add(target.request_id)
    session.flush()
    refresh_requests(session, request_ids)
    return request_ids


def _live_execution_generations(session: Session) -> set[uuid.UUID]:
    """Generations executable right now: live jobs' own generations plus
    the successor generations pre-allocated in their ``_queue_next``."""
    live: set[uuid.UUID] = set(
        session.scalars(
            select(WorkerJob.execution_generation).where(
                WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value])
            )
        ).all()
    )
    for payload in session.scalars(
        select(WorkerJob.payload).where(
            WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value])
        )
    ).all():
        queue_next = (payload or {}).get("_queue_next") or {}
        generation = queue_next.get("execution_generation")
        if generation:
            try:
                live.add(uuid.UUID(str(generation)))
            except (ValueError, TypeError):
                pass
    return live


def converge_orphaned_bindings(session: Session, *, limit: int = 200) -> int:
    """Worker inspection/reaper path: converge bindings whose execution is gone.

    Bindings pointing at a terminal job that somehow never settled, or whose
    generation has no live job and no pre-allocated successor, become explicit
    failures instead of leaving requests ``running`` forever. Also refreshes
    any still-open requests so persisted state matches target aggregation.
    """
    from mail_core.security.redact import safe_error

    live_generations = _live_execution_generations(session)
    refreshed_live_generations: set[uuid.UUID] | None = None

    bindings = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.status.in_(OPEN_BINDING_STATES))
            .order_by(SyncRequestTargetJob.created_at)
            .limit(max(1, int(limit)))
        ).all()
    )
    now = _now()
    changed = 0
    touched_target_ids: set[uuid.UUID] = set()
    for binding in bindings:
        job = session.get(WorkerJob, binding.job_id) if binding.job_id is not None else None
        if job is not None:
            if job.status == JobStatus.FAILED.value:
                binding.status = "failed"
                binding.error_code = "job_failed"
                binding.safe_error = (safe_error(job.last_error) or "")[:500] or None
                binding.finished_at = now
            elif job.status == JobStatus.DONE.value:
                binding.status = "complete"
                binding.finished_at = now
            elif job.status == JobStatus.CANCELLED.value:
                binding.status = "failed"
                binding.error_code = "job_cancelled"
                binding.safe_error = "The bound sync job was cancelled"
                binding.finished_at = now
            else:
                continue
        elif binding.execution_generation in live_generations:
            continue  # Pending job or pre-allocated successor: still executable.
        else:
            # Decision-time recheck: this binding was committed by a
            # request that bound a CLAIMED job's pre-allocated successor
            # (bind_target + ensure_successor_generation commit together),
            # possibly AFTER the snapshot above was taken — the patrol can
            # then see the binding but not its generation and would fail
            # a healthy queued request as execution_lost. Recompute the
            # live set once, now, before condemning any binding on it.
            if refreshed_live_generations is None:
                refreshed_live_generations = _live_execution_generations(session)
            if binding.execution_generation in refreshed_live_generations:
                continue
            binding.status = "failed"
            binding.error_code = "execution_lost"
            binding.safe_error = EXECUTION_LOST_MESSAGE
            binding.finished_at = now
        changed += 1
        touched_target_ids.add(binding.target_id)
    if touched_target_ids:
        request_ids = {
            t.request_id
            for t in session.scalars(
                select(SyncRequestTarget).where(SyncRequestTarget.id.in_(list(touched_target_ids)))
            ).all()
        }
        refresh_requests(session, request_ids)
    # Persist aggregation for any request still marked open (bounded sweep).
    open_request_ids = list(
        session.scalars(
            select(SyncRequest.id)
            .where(SyncRequest.state.in_(["queued", "running"]))
            .order_by(SyncRequest.created_at)
            .limit(max(1, int(limit)))
        ).all()
    )
    if open_request_ids:
        refresh_requests(session, open_request_ids)
    return changed
