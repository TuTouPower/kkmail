"""Sync-request completion driven by real work, not by ephemeral executions.

A ``SyncRequestTarget`` is fulfilled by a ``WorkerJob`` row that actually
exists. ``SyncRequestTargetJob`` links always carry a real ``job_id``;
retries and reclaims keep the same job row. When a deduplicated job is
CLAIMED and a newer request needs another pass, ``complete_job`` creates the
successor first and migrates the waiting links onto it in the same
transaction. Nothing is ever bound to a merely pre-allocated generation, so
the old ``execution_lost`` state and its internal error text cannot occur.

Lock order: WorkerJob row → all Targets of affected requests (UUID ascending)
→ Link rows → Requests (UUID ascending). Request state and ``finished_at``
are derived here and every persisted transition emits a
``sync.request_updated`` Outbox event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobStatus, OutboxEventType
from mail_core.mail.storage.models import (
    OutboxEvent,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)

OPEN_LINK_STATES = ("queued", "running")
_TERMINAL_FAILURE_STATES = ("partial", "failed", "cancelled", "blocked")
TERMINAL_TARGET_STATES = ("complete", *_TERMINAL_FAILURE_STATES)

BASELINE_REQUIRED_MESSAGE = (
    "Folder has no completed baseline scan; a full initialization scan is required before delta sync"
)
SYNC_INCOMPLETE_MESSAGE = "同步未能完成，请重试"
DEFAULT_FAILURE_MESSAGE = "同步失败，请稍后重试"
ACCOUNT_DELETED_MESSAGE = "账户已删除，无法完成同步"
FOLDER_DELETED_MESSAGE = "文件夹已删除，无法完成同步"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def bind_target(
    session: Session,
    *,
    target: SyncRequestTarget,
    job: WorkerJob,
    phase: str = "sync",
    folder_id: uuid.UUID | None = None,
    status: str = "queued",
    needs_successor: bool | None = None,
) -> SyncRequestTargetJob:
    """Create or refresh a link from ``target`` to an existing ``job``.

    The link is keyed by ``(target_id, job_id)``. A target that observes an
    already-CLAIMED job needs one further pass for its own data goal; that is
    recorded on the link and honoured when the job completes.
    """
    assert job.id is not None, "a sync target cannot be linked to a job without an id"
    if needs_successor is None:
        needs_successor = job.status == JobStatus.CLAIMED.value
    link = session.scalar(
        select(SyncRequestTargetJob).where(
            SyncRequestTargetJob.target_id == target.id,
            SyncRequestTargetJob.job_id == job.id,
        )
    )
    if link is None:
        link = SyncRequestTargetJob(
            id=uuid.uuid4(),
            target_id=target.id,
            job_id=job.id,
            needs_successor=needs_successor,
            phase=phase,
            folder_id=folder_id if folder_id is not None else target.folder_id,
            status=status,
            created_at=_now(),
        )
        session.add(link)
    else:
        if needs_successor:
            link.needs_successor = True
        if link.phase == "sync" and phase != "sync":
            link.phase = phase
        if link.folder_id is None and folder_id is not None:
            link.folder_id = folder_id
    if link.status in TERMINAL_TARGET_STATES and status in OPEN_LINK_STATES:
        link.status = status
        link.finished_at = None
        link.error_code = None
        link.safe_error = None
    if target.state in TERMINAL_TARGET_STATES and status in OPEN_LINK_STATES:
        target.state = "running" if status == "running" else "queued"
        target.finished_at = None
        target.error_code = None
        target.safe_error = None
    session.flush()
    return link


def migrate_waiting_links(session: Session, *, from_job: WorkerJob, to_job: WorkerJob) -> int:
    """Move links that need a fresh pass onto a newly created successor.

    Both jobs exist when this runs, so no link ever references a future
    execution. Called by ``complete_job`` in the same transaction that
    materializes the successor.
    """
    result = session.execute(
        update(SyncRequestTargetJob)
        .where(
            SyncRequestTargetJob.job_id == from_job.id,
            SyncRequestTargetJob.needs_successor.is_(True),
            SyncRequestTargetJob.status.in_(OPEN_LINK_STATES),
        )
        .values(job_id=to_job.id, needs_successor=False, status="queued", finished_at=None)
    )
    session.flush()
    return int(getattr(result, "rowcount", 0) or 0)


def has_waiting_links(session: Session, job: WorkerJob) -> bool:
    return session.scalar(
        select(SyncRequestTargetJob.id)
        .where(
            SyncRequestTargetJob.job_id == job.id,
            SyncRequestTargetJob.needs_successor.is_(True),
            SyncRequestTargetJob.status.in_(OPEN_LINK_STATES),
        )
        .limit(1)
    ) is not None


def _request_ids_for_target_ids(session: Session, target_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    ids = sorted({tid for tid in target_ids if tid is not None})
    if not ids:
        return []
    return sorted(
        {
            rid
            for rid in session.scalars(
                select(SyncRequestTarget.request_id).where(SyncRequestTarget.id.in_(ids))
            ).all()
            if rid is not None
        }
    )


def _lock_target_sets(session: Session, request_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, SyncRequestTarget]:
    ids = sorted({rid for rid in request_ids if rid is not None})
    if not ids:
        return {}
    return {
        t.id: t
        for t in session.scalars(
            select(SyncRequestTarget)
            .where(SyncRequestTarget.request_id.in_(ids))
            .order_by(SyncRequestTarget.id)
            .with_for_update()
        ).all()
    }


def _aggregate_target(session: Session, target: SyncRequestTarget) -> None:
    links = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.target_id == target.id)
            .order_by(SyncRequestTargetJob.created_at, SyncRequestTargetJob.id)
        ).all()
    )
    if any(link.status in OPEN_LINK_STATES for link in links):
        target.state = (
            "running"
            if any(link.status == "running" or link.status == "complete" for link in links)
            else "queued"
        )
        target.finished_at = None
        target.error_code = None
        target.safe_error = None
        return
    # Once a target is already terminal and has no open links, preserve its
    # settled state and error details even if historical job links were pruned.
    if target.state in TERMINAL_TARGET_STATES or not links:
        return
    failed = [link for link in links if link.status == "failed"]
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
    """Re-aggregate targets and persist request state + Outbox event."""
    ids = sorted({rid for rid in request_ids if rid is not None})
    if not ids:
        return
    targets_by_request: dict[uuid.UUID, list[SyncRequestTarget]] = {}
    for target in session.scalars(
        select(SyncRequestTarget)
        .where(SyncRequestTarget.request_id.in_(ids))
        .order_by(SyncRequestTarget.id)
        .with_for_update()
    ).all():
        targets_by_request.setdefault(target.request_id, []).append(target)
    requests = {
        req.id: req
        for req in session.scalars(
            select(SyncRequest).where(SyncRequest.id.in_(ids)).order_by(SyncRequest.id).with_for_update()
        ).all()
    }
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
            if req.state in _TERMINAL_FAILURE_STATES and any(
                t.state in _TERMINAL_FAILURE_STATES for t in targets
            ):
                new_state = req.state
            else:
                new_state = (
                    "failed"
                    if any(t.state in _TERMINAL_FAILURE_STATES for t in targets)
                    else "complete"
                )
        elif any(t.state in ("running", *TERMINAL_TARGET_STATES) for t in targets):
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


def find_active_job(session: Session, dedupe_key: str) -> WorkerJob | None:
    from mail_core.sync.jobs import active_dedupe_job_predicates

    return session.scalar(
        select(WorkerJob)
        .where(*active_dedupe_job_predicates(dedupe_key))
        .limit(1)
    )


def _rebind_to_initialization(
    session: Session, *, target: SyncRequestTarget, folder_id: uuid.UUID | None
) -> bool:
    """Hand a delta target to an in-flight metadata rebuild."""
    if target.account_id is None or folder_id is None:
        return False
    job = find_active_job(session, f"metadata:{target.account_id}:{folder_id}")
    if job is None:
        return False
    bind_target(
        session,
        target=target,
        job=job,
        phase="initialization",
        folder_id=folder_id,
        status="queued",
    )
    return True


def settle_job_links(
    session: Session,
    job: WorkerJob,
    *,
    outcome: str,
    result: dict | None = None,
    error_code: str | None = None,
    safe_error: str | None = None,
) -> set[uuid.UUID]:
    """Settle the links observing ``job``. Link rows are locked after targets."""
    if not hasattr(session, "scalars") or job.id is None:
        return set()
    planned_target_ids: list[uuid.UUID] = []
    for tid in session.scalars(
        select(SyncRequestTargetJob.target_id).where(SyncRequestTargetJob.job_id == job.id)
    ).all():
        if isinstance(tid, uuid.UUID) and tid not in planned_target_ids:
            planned_target_ids.append(tid)
    if not planned_target_ids:
        return set()
    planned_target_ids.sort()
    affected_request_ids = _request_ids_for_target_ids(session, planned_target_ids)
    targets = _lock_target_sets(session, affected_request_ids)
    links = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.job_id == job.id)
            .order_by(SyncRequestTargetJob.target_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if not links:
        return set()
    now = _now()
    request_ids: set[uuid.UUID] = set()
    for link in links:
        target = targets.get(link.target_id)
        if target is None:
            continue
        request_ids.add(target.request_id)
        if link.status not in OPEN_LINK_STATES:
            continue
        if outcome == "retriable":
            link.status = "queued"
            link.finished_at = None
            continue
        if outcome == "failed":
            link.status = "failed"
            link.error_code = error_code or "sync_failed"
            link.safe_error = (safe_error or DEFAULT_FAILURE_MESSAGE)[:500]
            link.finished_at = now
            continue
        if result and result.get("baseline_required"):
            link.status = "failed"
            link.error_code = "baseline_required"
            link.safe_error = BASELINE_REQUIRED_MESSAGE
            link.finished_at = now
            continue
        if result and result.get("await_initialization"):
            moved = _rebind_to_initialization(
                session, target=target, folder_id=link.folder_id or target.folder_id
            )
            if moved:
                link.status = "complete"
                link.finished_at = now
                continue
        link.status = "complete"
        link.finished_at = now
    session.flush()
    return request_ids


def mark_links_running(session: Session, jobs: list[WorkerJob]) -> None:
    """Claim hook: links attached to claimed jobs become running."""
    job_ids = [j.id for j in jobs if getattr(j, "id", None) is not None]
    if not job_ids or not hasattr(session, "scalars"):
        return
    planned = list(
        session.execute(
            select(SyncRequestTargetJob.id, SyncRequestTargetJob.target_id).where(
                SyncRequestTargetJob.job_id.in_(job_ids),
                SyncRequestTargetJob.status == "queued",
            )
        ).all()
    )
    if not planned:
        return
    _lock_target_sets(session, _request_ids_for_target_ids(session, [tid for _lid, tid in planned]))
    links = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.id.in_([lid for lid, _tid in planned]))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    mutated: set[uuid.UUID] = set()
    for link in links:
        if link.status != "queued":
            continue
        link.status = "running"
        mutated.add(link.target_id)
    session.flush()
    refresh_requests(session, _request_ids_for_target_ids(session, mutated))


def reset_links_for_job(session: Session, job: WorkerJob) -> set[uuid.UUID]:
    """Reclaim hook: running links return to queued on the same job row."""
    if not hasattr(session, "scalars") or job.id is None:
        return set()
    planned = list(
        session.execute(
            select(SyncRequestTargetJob.id, SyncRequestTargetJob.target_id).where(
                SyncRequestTargetJob.job_id == job.id,
                SyncRequestTargetJob.status == "running",
            )
        ).all()
    )
    if not planned:
        return set()
    _lock_target_sets(session, _request_ids_for_target_ids(session, [tid for _lid, tid in planned]))
    links = list(
        session.scalars(
            select(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.id.in_([lid for lid, _tid in planned]))
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    mutated: set[uuid.UUID] = set()
    for link in links:
        if link.status != "running":
            continue
        link.status = "queued"
        mutated.add(link.target_id)
    session.flush()
    return set(_request_ids_for_target_ids(session, mutated))


def fail_open_targets(
    session: Session,
    *,
    account_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    error_code: str,
    safe_error: str,
) -> set[uuid.UUID]:
    """Fail every still-open target for a deleted account/folder."""
    planned_stmt = select(SyncRequestTarget.id).where(SyncRequestTarget.state.in_(OPEN_LINK_STATES))
    if account_id is not None:
        planned_stmt = planned_stmt.where(SyncRequestTarget.account_id == account_id)
    if folder_id is not None:
        planned_stmt = planned_stmt.where(SyncRequestTarget.folder_id == folder_id)
    planned_ids = list(session.scalars(planned_stmt.order_by(SyncRequestTarget.id)).all())
    if not planned_ids:
        return set()
    locked = _lock_target_sets(session, _request_ids_for_target_ids(session, planned_ids))
    targets = [locked[tid] for tid in planned_ids if tid in locked and locked[tid].state in OPEN_LINK_STATES]
    if not targets:
        return set()
    link_ids = list(
        session.scalars(
            select(SyncRequestTargetJob.id).where(
                SyncRequestTargetJob.target_id.in_([t.id for t in targets]),
                SyncRequestTargetJob.status.in_(OPEN_LINK_STATES),
            )
        ).all()
    )
    if link_ids:
        session.execute(
            update(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.id.in_(link_ids))
            .values(status="failed", error_code=error_code, safe_error=safe_error[:500], finished_at=_now())
        )
    now = _now()
    request_ids: set[uuid.UUID] = set()
    for target in targets:
        target.state = "failed"
        target.error_code = error_code
        target.safe_error = safe_error[:500]
        target.finished_at = now
        request_ids.add(target.request_id)
    session.flush()
    refresh_requests(session, request_ids)
    return request_ids


def converge_stalled_targets(
    session: Session, *, limit: int = 200, stale_after: timedelta = timedelta(minutes=30)
) -> int:
    """Bound stale requests with a user-facing message.

    With links always pointing at real jobs, the only way a target can remain
    open indefinitely is a job that never advances (e.g. stranded in a
    terminal state without settlement, or never claimed). This sweep converges
    those targets instead of leaving the UI spinning forever. It never emits
    an internal implementation-detail error.
    """
    cutoff = _now() - stale_after
    planned = list(
        session.scalars(
            select(SyncRequestTarget.id)
            .where(SyncRequestTarget.state.in_(OPEN_LINK_STATES))
            .where(SyncRequestTarget.created_at < cutoff)
            .order_by(SyncRequestTarget.created_at)
            .limit(max(1, int(limit)))
        ).all()
    )
    if not planned:
        return 0
    locked = _lock_target_sets(session, _request_ids_for_target_ids(session, planned))
    targets = [
        locked[tid]
        for tid in planned
        if tid in locked and locked[tid].state in OPEN_LINK_STATES
    ]
    if not targets:
        return 0
    target_ids = [t.id for t in targets]
    # A target whose link still points at a live job is progressing, not
    # stalled: a large account legitimately stays open far longer than the
    # cutoff. Reclaim handles claimed jobs with a stale heartbeat; only
    # targets left with no executable work converge here.
    from mail_core.sync.jobs import active_job_status_predicate

    live_job_ids = set(
        session.scalars(
            select(WorkerJob.id).where(active_job_status_predicate())
        ).all()
    )
    live_target_ids = {
        lid_target
        for lid_target, job_id in session.execute(
            select(SyncRequestTargetJob.target_id, SyncRequestTargetJob.job_id).where(
                SyncRequestTargetJob.target_id.in_(target_ids),
                SyncRequestTargetJob.status.in_(OPEN_LINK_STATES),
            )
        ).all()
        if job_id in live_job_ids
    }
    stalled = [t for t in targets if t.id not in live_target_ids]
    if not stalled:
        return 0
    link_ids = list(
        session.scalars(
            select(SyncRequestTargetJob.id).where(
                SyncRequestTargetJob.target_id.in_([t.id for t in stalled]),
                SyncRequestTargetJob.status.in_(OPEN_LINK_STATES),
            )
        ).all()
    )
    if link_ids:
        session.execute(
            update(SyncRequestTargetJob)
            .where(SyncRequestTargetJob.id.in_(link_ids))
            .values(
                status="failed",
                error_code="sync_incomplete",
                safe_error=SYNC_INCOMPLETE_MESSAGE,
                finished_at=_now(),
            )
        )
    for target in stalled:
        target.state = "failed"
        target.error_code = "sync_incomplete"
        target.safe_error = SYNC_INCOMPLETE_MESSAGE
        target.finished_at = _now()
    request_ids = _request_ids_for_target_ids(session, [t.id for t in stalled])
    session.flush()
    refresh_requests(session, request_ids)
    return len(stalled)
