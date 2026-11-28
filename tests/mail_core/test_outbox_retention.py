"""Package G-part-2 PostgreSQL coverage for outbox retention (R13, §9.2).

Skipped in unit mode (no MAIL_CORE_DATABASE_URL). All assertions are
relative to the shared publication stream state observed at runtime, so
the tests stay deterministic under the suite's shuffled order: before the
prefix assertions, every already-published row above the watermark is
backdated so the continuous-prefix computation has a known starting state.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from mail_core.api import sse as sse_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.outbox import prune_published, pruned_through_seq, publication_head
from mail_core.realtime.publication import get_publication_state, publish_committed_batch

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

OLD = timedelta(days=30)


def _publish(session, payloads):
    for payload in payloads:
        session.add(OutboxEvent(event_type="sync.progress", payload=payload))
    session.commit()
    batch = publish_committed_batch(session, limit=1000)
    session.commit()
    return batch


def test_prune_published_prefix_blocker_and_unpublished_survivor():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        _, head_before = publication_head(session)
        watermark_before = pruned_through_seq(session)
        # Known starting state: every published row still retained becomes
        # expired, so the prefix runs until the fresh blocker inserted next.
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq.is_not(None))
            .where(OutboxEvent.publication_seq > watermark_before)
            .values(published_at=now - OLD)
        )
        session.commit()
        prior_retained = head_before - watermark_before

        batch = _publish(session, [{"kind": "blocker"}])
        blocker_seq = batch.last_seq
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == blocker_seq)
            .values(published_at=now)
        )
        session.commit()

        tail = _publish(session, [{"kind": "tail-old"}])
        tail_seq = tail.last_seq
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == tail_seq)
            .values(published_at=now - OLD)
        )
        session.commit()

        # Insert the survivor only after publication: publish_committed_batch
        # publishes every committed unpublished row, so adding it before the
        # blocker would publish it too and defeat the retention guarantee.
        unpublished = OutboxEvent(event_type="sync.progress", payload={"kind": "unpublished"})
        session.add(unpublished)
        session.commit()
        unpublished_id = unpublished.id

    with Session() as session:
        deleted = prune_published(session, now=now)
        session.commit()
        # The expired prefix (all prior retained rows) is deleted; the
        # fresh blocker stops the prefix, so the old tail row behind it and
        # the unpublished row both survive.
        assert deleted == prior_retained
        assert pruned_through_seq(session) == blocker_seq - 1
        assert session.get(OutboxEvent, unpublished_id) is not None
        tail_row = session.scalar(
            select(OutboxEvent).where(OutboxEvent.publication_seq == tail_seq)
        )
        assert tail_row is not None

    # Backdate the blocker too: the rest of the prefix now drains, while
    # the unpublished row still survives regardless of age.
    with Session() as session:
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == blocker_seq)
            .values(published_at=now - OLD)
        )
        session.commit()
        deleted = prune_published(session, now=now)
        session.commit()
        assert deleted == 2
        assert pruned_through_seq(session) == tail_seq
        assert session.get(OutboxEvent, unpublished_id) is not None
        assert session.get(OutboxEvent, unpublished_id).publication_seq is None


def test_replay_cursor_below_watermark_gets_retention_gap():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    # Per-test isolation truncates the publication state, so advance the
    # watermark inside this test instead of depending on another test's
    # leftovers (which also made this skip under the required full suite).
    with Session() as session:
        batch = _publish(session, [{"kind": "pruned"}])
        pruned_seq = batch.last_seq
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == pruned_seq)
            .values(published_at=now - OLD)
        )
        session.commit()
        assert prune_published(session, now=now) >= 1
        session.commit()
        epoch, head_seq = publication_head(session)
        watermark = pruned_through_seq(session)

    assert watermark >= pruned_seq
    assert watermark <= head_seq

    # Cursor one below the watermark: the gap to head may be tiny, but the
    # next row the client needs has been pruned.
    plan = sse_mod._build_replay(f"v2:{epoch}:{watermark - 1}", None)
    assert len(plan.frames) == 1
    _, event, payload = plan.frames[0]
    assert event == "client.resync_hint"
    assert payload["reason"] == "retention_gap"

    # A cursor at the head replays normally (nothing to send, no hint).
    plan = sse_mod._build_replay(f"v2:{epoch}:{head_seq}", None)
    assert plan.frames == []
    assert plan.cursor_seq == head_seq


def test_two_dispatchers_with_established_baselines_both_receive_events():
    Session = get_session_factory()
    dispatchers = [OutboxDispatcher(), OutboxDispatcher()]

    async def run():
        queues = [dispatcher.subscribe() for dispatcher in dispatchers]
        try:
            # Establish both baselines against the current head.
            for dispatcher in dispatchers:
                dispatcher.dispatch_once()
            baselines = [dispatcher._last_dispatched_seq for dispatcher in dispatchers]

            with Session() as session:
                batch = _publish(session, [{"kind": "dual", "n": 1}, {"kind": "dual", "n": 2}])
                dual_seqs = {batch.first_seq, batch.last_seq}

            for dispatcher in dispatchers:
                dispatcher.dispatch_once()
            received = []
            for queue in queues:
                ids = []
                while not queue.empty():
                    ids.append(queue.get_nowait()["publication_seq"])
                received.append(ids)
            return baselines, dual_seqs, received
        finally:
            for dispatcher, queue in zip(dispatchers, queues):
                dispatcher.unsubscribe(queue)

    baselines, dual_seqs, received = asyncio.run(run())
    for events in received:
        assert dual_seqs <= set(events), f"dual events missing from {events}"


def _pg_backend_pid(session) -> int:
    from sqlalchemy import text

    return int(session.scalar(text("SELECT pg_backend_pid()")))


def _run_prune_on_second_connection(Session, *, now, backend_pids: dict[str, int]) -> None:
    import threading

    errors: list[BaseException] = []

    def _prune_worker():
        try:
            with Session() as prune_session:
                backend_pids["pruner"] = _pg_backend_pid(prune_session)
                assert prune_published(prune_session, now=now) >= 1
                prune_session.commit()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=_prune_worker)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert not errors, f"pruner thread failed: {errors[0]!r}"


def test_replay_prune_interleaving_during_snapshot_real_pg(monkeypatch):
    """Finding 3 (SSE snapshot isolation): prune committing after replay opens its
    REPEATABLE READ snapshot must not drop seq=1 or skip it silently."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        batch = _publish(session, [{"kind": "sse-old"}, {"kind": "sse-recent"}])
        first_seq, second_seq = batch.first_seq, batch.last_seq
        assert first_seq is not None and second_seq is not None
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == first_seq)
            .values(published_at=now - OLD)
        )
        session.commit()
        epoch, _ = publication_head(session)

    cursor = f"v2:{epoch}:{first_seq - 1}"
    original_fetch = sse_mod.fetch_published_since
    backend_pids: dict[str, int] = {}

    def prune_on_second_conn(session, *, after_seq, limit=100, account_id=None):
        backend_pids["reader"] = _pg_backend_pid(session)
        _run_prune_on_second_connection(Session, now=now, backend_pids=backend_pids)
        return original_fetch(session, after_seq=after_seq, limit=limit, account_id=account_id)

    monkeypatch.setattr(sse_mod, "fetch_published_since", prune_on_second_conn)
    plan = sse_mod._build_replay(cursor, None)
    assert backend_pids["reader"] != backend_pids["pruner"]
    kinds = [frame[2].get("kind") for frame in plan.frames]
    assert kinds == ["sse-old", "sse-recent"]
    assert plan.cursor_seq == second_seq


def test_replay_post_fetch_prune_guard_real_pg(monkeypatch):
    """Finding 3 (SSE post-fetch watermark guard + two-connection interleaving):
    even if a reader has already inspected cursor/watermark outside snapshot isolation,
    pruning seq=1 on a second PG connection triggers client.resync_hint(retention_gap)
    instead of silently skipping seq=1 and emitting only seq=2."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        batch = _publish(session, [{"kind": "sse-old"}, {"kind": "sse-recent"}])
        first_seq, second_seq = batch.first_seq, batch.last_seq
        assert first_seq is not None and second_seq is not None
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == first_seq)
            .values(published_at=now - OLD)
        )
        session.commit()
        epoch, _ = publication_head(session)

    cursor = f"v2:{epoch}:{first_seq - 1}"
    original_fetch = sse_mod.fetch_published_since
    backend_pids: dict[str, int] = {}

    # Force READ COMMITTED to exercise the post-fetch watermark guard on real PG.
    monkeypatch.setattr(sse_mod, "_enter_repeatable_read", lambda _s: None)

    def prune_before_fetch(session, *, after_seq, limit=100, account_id=None):
        backend_pids["reader"] = _pg_backend_pid(session)
        _run_prune_on_second_connection(Session, now=now, backend_pids=backend_pids)
        return original_fetch(session, after_seq=after_seq, limit=limit, account_id=account_id)

    monkeypatch.setattr(sse_mod, "fetch_published_since", prune_before_fetch)
    plan = sse_mod._build_replay(cursor, None)
    assert backend_pids["reader"] != backend_pids["pruner"]
    assert len(plan.frames) == 1
    _, event, payload = plan.frames[0]
    assert event == "client.resync_hint"
    assert payload["reason"] == "retention_gap"
    assert payload["pruned_through_seq"] >= first_seq
    assert payload["last_seq"] == first_seq - 1
    assert plan.cursor_seq == second_seq


def test_dispatcher_phase1_to_phase2_prune_interleaving_real_pg(monkeypatch):
    """Finding 3 (Dispatcher two-connection interleaving): pruner deletes seq=1
    between Phase 1 watermark check and Phase 2 fetch; dispatcher must emit
    client.resync_hint(retention_gap) and never silently advance over seq=1."""
    from mail_core.realtime import outbox as outbox_mod

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        batch = _publish(session, [{"kind": "disp-old"}, {"kind": "disp-recent"}])
        first_seq, second_seq = batch.first_seq, batch.last_seq
        assert first_seq is not None and second_seq is not None
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == first_seq)
            .values(published_at=now - OLD)
        )
        session.commit()

    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True
    dispatcher._last_dispatched_seq = first_seq - 1

    original_fetch = outbox_mod.fetch_published_since
    backend_pids: dict[str, int] = {}

    def prune_between_phase1_and_phase2(session, *, after_seq, limit=100, account_id=None):
        # Run pruner BEFORE emitting any SQL on Phase 2's session so Phase 2's
        # REPEATABLE READ snapshot begins strictly after the prune commits.
        _run_prune_on_second_connection(Session, now=now, backend_pids=backend_pids)
        backend_pids["reader"] = _pg_backend_pid(session)
        return original_fetch(session, after_seq=after_seq, limit=limit, account_id=account_id)

    monkeypatch.setattr(outbox_mod, "fetch_published_since", prune_between_phase1_and_phase2)

    async def run():
        queue = dispatcher.subscribe()
        try:
            count = dispatcher.dispatch_once()
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            return count, events
        finally:
            dispatcher.unsubscribe(queue)

    count, events = asyncio.run(run())
    assert backend_pids["reader"] != backend_pids["pruner"]
    assert count == 0
    assert dispatcher._last_dispatched_seq == second_seq
    assert len(events) == 1
    assert events[0]["event"] == "client.resync_hint"
    assert events[0]["data"]["reason"] == "retention_gap"
    assert events[0]["data"]["pruned_through_seq"] >= first_seq
    assert events[0]["data"]["last_seq"] == first_seq - 1


def test_dispatcher_phase2_snapshot_interleaving_real_pg(monkeypatch):
    """Finding 3 (Dispatcher Phase 2 REPEATABLE READ snapshot): prune committing
    after Phase 2 fetches rows keeps snapshot consistency so seq=1 and seq=2
    are both delivered cleanly without a spurious gap."""
    from mail_core.realtime import outbox as outbox_mod

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        batch = _publish(session, [{"kind": "snap-old"}, {"kind": "snap-recent"}])
        first_seq, second_seq = batch.first_seq, batch.last_seq
        assert first_seq is not None and second_seq is not None
        session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.publication_seq == first_seq)
            .values(published_at=now - OLD)
        )
        session.commit()

    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True
    dispatcher._last_dispatched_seq = first_seq - 1

    original_fetch = outbox_mod.fetch_published_since
    backend_pids: dict[str, int] = {}

    def fetch_then_prune(session, *, after_seq, limit=100, account_id=None):
        rows = original_fetch(session, after_seq=after_seq, limit=limit, account_id=account_id)
        backend_pids["reader"] = _pg_backend_pid(session)
        _run_prune_on_second_connection(Session, now=now, backend_pids=backend_pids)
        return rows

    monkeypatch.setattr(outbox_mod, "fetch_published_since", fetch_then_prune)

    async def run():
        queue = dispatcher.subscribe()
        try:
            count = dispatcher.dispatch_once()
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            return count, events
        finally:
            dispatcher.unsubscribe(queue)

    count, events = asyncio.run(run())
    assert backend_pids["reader"] != backend_pids["pruner"]
    assert count == 2
    assert dispatcher._last_dispatched_seq == second_seq
    assert [ev["data"]["kind"] for ev in events] == ["snap-old", "snap-recent"]


def test_ac003_open_sync_requests_preserved_beyond_24h():
    """AC-003: open sync request targets (queued/running) protect linked jobs past 24h."""
    import uuid
    from mail_core.mail.domain.enums import ExecutionOrigin, JobStatus, JobType
    from mail_core.mail.storage.models import Account, SyncRequest, SyncRequestTarget, SyncRequestTargetJob, WorkerJob
    from mail_core.sync.jobs import prune_completed_jobs
    from mail_core.sync.retention import COMPLETED_JOB_RETENTION

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    beyond_window = now - (COMPLETED_JOB_RETENTION + timedelta(hours=12))

    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"ac003-{uuid.uuid4().hex[:6]}@example.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
            sync_enabled=True,
        )
        session.add(acc)
        session.flush()

        open_req = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"open-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="running",
            scope={},
        )
        closed_req = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"closed-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="complete",
            scope={},
        )
        session.add_all([open_req, closed_req])
        session.flush()

        open_target = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=open_req.id,
            account_id=acc.id,
            target_key=f"{acc.id}:open",
            requested_generation=uuid.uuid4(),
            state="running",
        )
        closed_target = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=closed_req.id,
            account_id=acc.id,
            target_key=f"{acc.id}:closed",
            requested_generation=uuid.uuid4(),
            state="complete",
        )
        session.add_all([open_target, closed_target])
        session.flush()

        preserved_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.FAILED.value,
            updated_at=beyond_window,
            payload={},
        )
        prunable_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.DONE.value,
            updated_at=beyond_window,
            payload={},
        )
        session.add_all([preserved_job, prunable_job])
        session.flush()

        session.add_all([
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=open_target.id,
                job_id=preserved_job.id,
                status="failed",
                error_code="job_failed",
            ),
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=closed_target.id,
                job_id=prunable_job.id,
                status="complete",
            ),
        ])
        preserved_id, prunable_id = preserved_job.id, prunable_job.id
        session.commit()

    with Session() as session:
        deleted = prune_completed_jobs(session, now=now)
        session.commit()
        assert deleted == 1
        assert session.get(WorkerJob, preserved_id) is not None
        assert session.get(WorkerJob, prunable_id) is None
