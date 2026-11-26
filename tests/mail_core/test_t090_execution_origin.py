"""End-to-end execution_origin enforcement, inheritance, and background isolation tests (t090)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
import mail_core.sync.remote_push as remote_push_mod
from mail_core.accounts.service import enqueue_account_sync
from mail_core.db.session import get_session_factory
from mail_core.mail.application.message_details import sync_message_body
from mail_core.mail.application.mutations import set_message_read
from mail_core.mail.application.sync_requests import create_sync_request
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    JobStatus,
    JobType,
    FolderRemoteState,
)
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderPatrolStatus,
    Message,
    MessageArchiveState,
    MessageLocation,
    SyncCheckpoint,
    WorkerJob,
)
from mail_core.net.bulkhead import EndpointCircuitOpenError
from mail_core.providers.base import (
    DeltaPage,
    FolderStatus,
    MetadataPage,
    RemoteMessageMeta,
    RemoteOperationResult,
)
from mail_core.providers.http import CursorInvalidError, PermanentAuthError, RateLimitedError
from mail_core.sync.idle_watcher import IdleWatcherManager, _Watch
from mail_core.sync.jobs import claim_jobs, complete_job, enqueue_job
from mail_core.sync.leases import acquire_lease
from mail_core.sync.patrol import PatrolConfig, schedule_folder_status_patrol
from mail_core.worker.handlers import handle_job
from mail_core.worker.main import schedule_periodic_inbox_sync

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)


def _seed_account_and_folders(session, *, baseline: bool = True):
    acc = Account(
        id=uuid.uuid4(),
        email=f"t090-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref="ref-t090",
        sync_enabled=True,
        connectivity_state=ConnectivityState.CONNECTED.value,
        credential_state=CredentialState.VALID.value,
        config={},
    )
    session.add(acc)
    session.flush()
    inbox = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id="INBOX",
        name="INBOX",
        role="inbox",
        remote_state=FolderRemoteState.ACTIVE.value,
    )
    sent = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id="SENT",
        name="SENT",
        role="sent",
        remote_state=FolderRemoteState.ACTIVE.value,
    )
    session.add_all([inbox, sent])
    session.flush()
    for folder in (inbox, sent):
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                cursor={"modseq": 1},
                full_scan_complete=baseline,
            )
        )
    session.flush()
    return acc.id, inbox.id, sent.id


def _run_job(Session, job_id: uuid.UUID, *, worker_id: str = "w-t090") -> bool:
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        if job.status == JobStatus.PENDING.value:
            job.status = JobStatus.CLAIMED.value
            job.locked_by = worker_id
            job.attempts = (job.attempts or 0) + 1
            session.commit()
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            ok = handle_job(session, job, worker_id=worker_id)
        session.commit()
        return ok


def test_t090_enqueue_requires_explicit_origin_and_entrypoints_declare_accurately():
    """AC-002: enqueue_job rejects omitted/invalid execution_origin and explicit entrypoints tag accurately."""
    Session = get_session_factory()
    with Session() as session:
        aid, inbox_id, sent_id = _seed_account_and_folders(session)
        msg = Message(
            id=uuid.uuid4(),
            account_id=aid,
            remote_id="uid-1",
            subject="body fetch",
            from_address="a@example.test",
            sort_time=_NOW,
        )
        session.add(msg)
        session.flush()
        session.add(MessageArchiveState(message_id=msg.id, state="metadata_synced"))
        session.add(MessageLocation(message_id=msg.id, folder_id=inbox_id, uid=1))

        empty_kwargs: dict[str, Any] = {}
        with pytest.raises(TypeError):
            enqueue_job(session, job_type=JobType.SYNC_FOLDER_DELTA.value, account_id=aid, **empty_kwargs)
        with pytest.raises(TypeError):
            enqueue_account_sync(session, aid, **empty_kwargs)
        bad_origins: tuple[Any, ...] = (None, "", "silent", 123)
        for bad in bad_origins:
            with pytest.raises(ValueError):
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    execution_origin=bad,
                    account_id=aid,
                )

        manual_sync_id = enqueue_account_sync(session, aid, execution_origin=ExecutionOrigin.FOREGROUND)
        assert session.get(WorkerJob, manual_sync_id).execution_origin == ExecutionOrigin.FOREGROUND.value

        mut = set_message_read(session, msg.id, is_read=True)
        assert mut.operation_id is not None
        push_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == aid,
                WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value,
            )
        )
        assert push_job is not None and push_job.execution_origin == ExecutionOrigin.FOREGROUND.value

        req_bg, created = create_sync_request(
            session,
            client_request_id=f"bg-explicit-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(aid), "background": True},
            account_id=aid,
            folder_id=sent_id,
        )
        assert created
        bg_req_job = session.scalar(
            select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid}:{sent_id}")
        )
        assert bg_req_job is not None
        assert bg_req_job.execution_origin == ExecutionOrigin.BACKGROUND.value
        assert "background" not in (bg_req_job.payload or {})
        assert bg_req_job.payload["request_id"] == str(req_bg.id)
        session.commit()
        msg_id = msg.id

    res = sync_message_body(msg_id)
    assert res is not None and res.job_id is not None
    with Session() as session:
        assert session.get(WorkerJob, res.job_id).execution_origin == ExecutionOrigin.FOREGROUND.value


def test_t090_periodic_patrol_and_idle_background_isolation(monkeypatch):
    """AC-003: periodic inbox poll, STATUS patrol, and IDLE catch-up emit background jobs without polluting health."""
    Session = get_session_factory()
    with Session() as session:
        aid1, inbox1, sent1 = _seed_account_and_folders(session)
        aid2, _inbox2, sent2 = _seed_account_and_folders(session)
        aid3, inbox3, _sent3 = _seed_account_and_folders(session)
        session.add(
            FolderPatrolStatus(
                folder_id=sent2,
                last_status=FolderStatus(messages=1, uidnext=2, unseen=1, highestmodseq=1).to_dict(),
                last_probe_at=_NOW - timedelta(hours=2),
                last_probe_failures=0,
            )
        )
        session.commit()

        # 1. worker/main periodic poll
        now_future = datetime.now(timezone.utc) + timedelta(minutes=5)
        count = schedule_periodic_inbox_sync(session, poll_interval_s=60.0, now=now_future)
        assert count >= 1
        session.commit()
        poll_job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid1}:{inbox1}"))
        assert poll_job is not None
        assert poll_job.execution_origin == ExecutionOrigin.BACKGROUND.value
        assert "background" not in (poll_job.payload or {})

        # 2. patrol STATUS change detection
        class _ChangedProbe:
            def probe_folder_status(self, _remote_id):
                return FolderStatus(messages=2, uidnext=3, unseen=2, highestmodseq=2)

        patrol_res = schedule_folder_status_patrol(
            session,
            provider_factory=lambda _acc: _ChangedProbe(),
            config=PatrolConfig(enabled=True, interval_s=60.0, max_probes=50, max_unprobed_s=120.0),
            now=now_future,
        )
        assert patrol_res.changed >= 1
        session.commit()
        patrol_job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid2}:{sent2}"))
        assert patrol_job is not None
        assert patrol_job.execution_origin == ExecutionOrigin.BACKGROUND.value
        assert "background" not in (patrol_job.payload or {})
        poll_jid, patrol_jid = poll_job.id, patrol_job.id

    # 3. IdleWatcher catch-up enqueue
    manager = IdleWatcherManager(Session)
    watch = _Watch(
        account_id=aid3,
        folder_id=inbox3,
        fingerprint="fp",
        account_snapshot=Account(id=aid3, email="idle@example.test", provider="imap", config={}),
        folder_remote_id="INBOX",
    )
    manager._enqueue_delta(watch)
    with Session() as session:
        idle_job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid3}:{inbox3}"))
        assert idle_job is not None
        assert idle_job.execution_origin == ExecutionOrigin.BACKGROUND.value
        assert "background" not in (idle_job.payload or {})
        idle_jid = idle_job.id

    class _TimeoutProvider:
        def delta_changes(self, _rid, _cursor):
            raise TimeoutError("proxy handshake timed out")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _TimeoutProvider())
    for jid, aid in ((poll_jid, aid1), (patrol_jid, aid2), (idle_jid, aid3)):
        assert _run_job(Session, jid) is False
        with Session() as session:
            acc = session.get(Account, aid)
            assert acc.connectivity_state == ConnectivityState.CONNECTED.value
            assert acc.credential_state == CredentialState.VALID.value
            job = session.get(WorkerJob, jid)
            assert job.status == JobStatus.PENDING.value
            assert job.execution_origin == ExecutionOrigin.BACKGROUND.value


def _assert_single_job_origin_and_delete(Session, dedupe_key: str, expected_origin: str) -> None:
    with Session() as session:
        job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == dedupe_key))
        assert job is not None and job.execution_origin == expected_origin
        session.delete(job)
        session.commit()


def _assert_job_origin(Session, dedupe_key: str, expected_origin: str) -> None:
    with Session() as session:
        job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == dedupe_key))
        assert job is not None and job.execution_origin == expected_origin


def test_t090_background_continuations_rebuilds_and_push_fallback_inherit(monkeypatch):
    """AC-003: LeaseBusy/RateLimited/CircuitOpen/paging/CursorInvalid/metadata/remote_push inherit origin."""
    Session = get_session_factory()
    with Session() as session:
        aid, inbox_id, sent_id = _seed_account_and_folders(session)
        session.commit()

    # Branch 1: LeaseBusy during background delta
    with Session() as session:
        acquire_lease(session, account_id=aid, owner_id="other-worker", ttl=timedelta(minutes=5))
        session.commit()
    res_busy = delta_mod.sync_folder_delta(
        aid, inbox_id, worker_id="w-busy", execution_origin=ExecutionOrigin.BACKGROUND
    )
    assert res_busy["status"] == "lease_busy"
    _assert_single_job_origin_and_delete(Session, f"delta:{aid}:{inbox_id}", ExecutionOrigin.BACKGROUND.value)
    with Session() as session:
        from mail_core.sync.leases import release_lease

        release_lease(session, account_id=aid, owner_id="other-worker", fencing_token=1)
        session.commit()

    # Branch 2: RateLimited + CircuitOpen + unexhausted page during background delta
    class _RateLimitProvider:
        def delta_changes(self, _rid, _cur):
            raise RateLimitedError("429", retry_after_seconds=12)

    class _CircuitProvider:
        def delta_changes(self, _rid, _cur):
            raise EndpointCircuitOpenError(
                "circuit open",
                endpoint=("direct", "imap.gmail.com", 993),
                retry_after_s=15.0,
            )

    class _PartialProvider:
        def delta_changes(self, _rid, _cur):
            return DeltaPage(changes=[], next_cursor={"modseq": 2}, exhausted=False)

    class _CursorInvalidProvider:
        def delta_changes(self, _rid, _cur):
            raise CursorInvalidError("uidvalidity changed")

    for prov_cls, wid in ((_RateLimitProvider, "w-rl"), (_CircuitProvider, "w-co"), (_PartialProvider, "w-pg")):
        monkeypatch.setattr(delta_mod, "build_provider", lambda *a, _p=prov_cls, **k: _p())
        delta_mod.sync_folder_delta(aid, inbox_id, worker_id=wid, execution_origin="background")
        _assert_single_job_origin_and_delete(Session, f"delta:{aid}:{inbox_id}", ExecutionOrigin.BACKGROUND.value)

    # Branch 3: CursorInvalid -> SYNC_FOLDER_METADATA -> exhausted=True -> RECONCILE_FOLDER & SYNC_FOLDER_DELTA
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _CursorInvalidProvider())
    res_cur = delta_mod.sync_folder_delta(aid, sent_id, worker_id="w-ci", execution_origin="background")
    assert res_cur["status"] == "cursor_invalid"
    _assert_job_origin(Session, f"metadata:{aid}:{sent_id}", ExecutionOrigin.BACKGROUND.value)

    class _MetaExhaustedProvider:
        def fetch_metadata_page(self, _rid, _cur):
            return MetadataPage(
                items=[RemoteMessageMeta("m1", "sub", "a@b.c", "A", _NOW, False, False)],
                next_cursor={"modseq": 5},
                exhausted=True,
            )

    monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: _MetaExhaustedProvider())
    res_meta = engine_mod.sync_folder_metadata(
        aid, sent_id, worker_id="w-meta", execution_origin=ExecutionOrigin.BACKGROUND
    )
    assert res_meta["exhausted"] is True
    for dk in (f"reconcile:{aid}:{sent_id}", f"delta:{aid}:{sent_id}", f"archive_mime_batch:{aid}"):
        _assert_job_origin(Session, dk, ExecutionOrigin.BACKGROUND.value)

    # Branch 4: public push_remote_operations move fallback missing target folder discovery stays BACKGROUND
    from mail_core.mail.storage.models import RemoteOperation

    with Session() as session:
        msg_move = Message(id=uuid.uuid4(), account_id=aid, remote_id="move-1", subject="move me", from_address="a@b.c", sort_time=_NOW)
        session.add(msg_move)
        op_move = RemoteOperation(
            account_id=aid,
            entity_key="msg:move-1:move",
            op_type="move",
            desired_state={"remote_id": "move-1", "folder_remote_id": "INBOX", "dest_folder_remote_id": "NEW_FOLDER"},
            status="pending",
        )
        session.add(op_move)
        session.commit()
        op_move_id, msg_move_id = op_move.id, msg_move.id

    monkeypatch.setattr(
        remote_push_mod,
        "build_provider",
        lambda *_a, **_k: type(
            "_MoveProvider",
            (),
            {
                "apply_remote_operations": lambda _self, items: [
                    (items[0].op_id, RemoteOperationResult(success=True, remote_state={"folder_remote_id": "NEW_FOLDER", "remote_id": "move-2"}))
                ]
            },
        )(),
    )
    res_move = remote_push_mod.push_remote_operations(aid, worker_id="w-move", execution_origin=ExecutionOrigin.BACKGROUND)
    assert res_move == {"status": "ok", "pushed": 1, "failed": 0}
    _assert_job_origin(Session, f"sync-folders:{aid}", ExecutionOrigin.BACKGROUND.value)
    with Session() as session:
        assert session.get(RemoteOperation, op_move_id).status == "done"
        assert session.get(Message, msg_move_id).remote_id == "move-2"


def test_t090_metadata_and_discovery_background_reschedules_inherit(monkeypatch):
    """p097: sync_account_folders & sync_folder_metadata background reschedules/full binding inherit origin."""
    from mail_core.mail.storage.models import SyncRequestTarget, SyncRequestTargetJob
    from mail_core.sync.leases import release_lease

    Session = get_session_factory()
    with Session() as session:
        aid, _inbox_id, sent_id = _seed_account_and_folders(session, baseline=False)
        session.commit()

    def _clear(dkey: str | None = None) -> None:
        _assert_single_job_origin_and_delete(Session, dkey, ExecutionOrigin.BACKGROUND.value) if dkey else None

    # 1. sync_account_folders CAPACITY_ERRORS & RateLimitedError
    for exc_factory, status in (
        (lambda: EndpointCircuitOpenError("co", endpoint=("direct", "imap.test", 993), retry_after_s=10.0), "capacity_unavailable"),
        (lambda: RateLimitedError("429", retry_after_seconds=12), "rate_limited"),
    ):
        def _fail_list(_f=exc_factory):
            raise _f()

        monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, _fn=_fail_list, **_k: type("_P", (), {"list_folder_catalog": staticmethod(_fn)})())
        assert engine_mod.sync_account_folders(aid, worker_id="w-disc", execution_origin="background")["status"] == status
        _clear(f"sync:{aid}")

    # 2. sync_folder_metadata LeaseBusy -> background
    with Session() as session:
        holder_lease = acquire_lease(session, account_id=aid, owner_id="holder", ttl=timedelta(minutes=5))
        holder_token = holder_lease.fencing_token
        session.commit()
    assert engine_mod.sync_folder_metadata(aid, sent_id, worker_id="w-lb", execution_origin="background")["status"] == "lease_busy"
    _clear(f"metadata:{aid}:{sent_id}")
    with Session() as session:
        release_lease(session, account_id=aid, owner_id="holder", fencing_token=holder_token)
        session.commit()

    # 3. sync_folder_metadata CAPACITY_ERRORS / RateLimitedError / CursorInvalidError / exhausted=False
    meta_dk = f"metadata:{aid}:{sent_id}"
    for fetch_fn, want_status in (
        (lambda _rid, _c: (_ for _ in ()).throw(EndpointCircuitOpenError("co", endpoint=("direct", "imap.test", 993), retry_after_s=10.0)), "capacity_unavailable"),
        (lambda _rid, _c: (_ for _ in ()).throw(RateLimitedError("429", retry_after_seconds=15)), "rate_limited"),
        (lambda _rid, _c: (_ for _ in ()).throw(CursorInvalidError("uidvalidity reset")), "cursor_invalid"),
        (lambda _rid, _c: MetadataPage(items=[], next_cursor={"modseq": 2}, exhausted=False), "ok"),
    ):
        monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, _fn=fetch_fn, **_k: type("_MP", (), {"fetch_metadata_page": staticmethod(_fn)})())
        assert engine_mod.sync_folder_metadata(aid, sent_id, worker_id="w-m", execution_origin="background", max_pages=1)["status"] == want_status
        _clear(meta_dk)

    # 4. sync_folder_metadata full=True and request_id is not None -> reconcile inherits BACKGROUND and binds target
    with Session() as session:
        session.execute(delete(WorkerJob).where(WorkerJob.account_id == aid))
        req, _ = create_sync_request(session, client_request_id=f"p097-full-{uuid.uuid4().hex}", mode="full", trigger="manual", scope={"account_id": str(aid), "folder_id": str(sent_id), "background": True}, account_id=aid, folder_id=sent_id)
        session.commit()
        scan_gen = uuid.UUID(session.scalar(select(WorkerJob).where(WorkerJob.account_id == aid)).payload["scan_generation"])
        req_id = req.id
        session.execute(delete(SyncRequestTargetJob))
        session.execute(delete(WorkerJob).where(WorkerJob.account_id == aid))
        session.commit()

    monkeypatch.setattr(
        engine_mod,
        "build_provider",
        lambda *_a, **_k: type("_DoneMP", (), {"fetch_metadata_page": staticmethod(lambda _r, _c: MetadataPage(items=[], next_cursor={"modseq": 9}, exhausted=True))})(),
    )
    assert engine_mod.sync_folder_metadata(aid, sent_id, worker_id="w-full", execution_origin="background", full=True, scan_generation=scan_gen, request_id=req_id)["exhausted"] is True
    for dk in (f"reconcile:{aid}:{sent_id}", f"delta:{aid}:{sent_id}", f"archive_mime_batch:{aid}"):
        _assert_job_origin(Session, dk, ExecutionOrigin.BACKGROUND.value)
    with Session() as session:
        target = session.scalar(select(SyncRequestTarget).where(SyncRequestTarget.request_id == req_id))
        assert target is not None and session.scalar(select(SyncRequestTargetJob).where(SyncRequestTargetJob.target_id == target.id, SyncRequestTargetJob.phase == "reconcile")) is not None


def test_t090_push_remote_operations_retries_and_followup_inherit(monkeypatch):
    """p097: push_remote_operations capacity/retry/rate-limit/batch/delayed followups inherit BACKGROUND."""
    from mail_core.mail.storage.models import RemoteOperation

    Session = get_session_factory()
    with Session() as session:
        aid, _inbox_id, _sent_id = _seed_account_and_folders(session)
        op1 = RemoteOperation(account_id=aid, entity_key="msg:1:read", op_type="mark_read", desired_state={"remote_id": "1", "is_read": True}, status="pending")
        op2 = RemoteOperation(account_id=aid, entity_key="msg:2:read", op_type="mark_read", desired_state={"remote_id": "2", "is_read": True}, status="pending", attempts=2)
        session.add_all([op1, op2])
        session.commit()
        op1_id, op2_id = op1.id, op2.id

    push_dk = f"remote-op-push:{aid}"
    co_err = EndpointCircuitOpenError("co", endpoint=("direct", "imap.test", 993), retry_after_s=15.0)
    # 1. Capacity on build_provider & batch apply -> capacity_unavailable + BACKGROUND
    for mode in ("build", "apply"):
        if mode == "build":
            monkeypatch.setattr(remote_push_mod, "build_provider", lambda *_a, **_k: (_ for _ in ()).throw(co_err))
        else:
            monkeypatch.setattr(remote_push_mod, "build_provider", lambda *_a, **_k: type("_P", (), {"apply_remote_operations": staticmethod(lambda _i: (_ for _ in ()).throw(co_err))})())
        assert remote_push_mod.push_remote_operations(aid, worker_id="w-p", execution_origin="background")["status"] == "capacity_unavailable"
        _assert_single_job_origin_and_delete(Session, push_dk, ExecutionOrigin.BACKGROUND.value)
        with Session() as session:
            for oid in (op1_id, op2_id):
                op = session.get(RemoteOperation, oid)
                op.next_attempt_at = None
            session.commit()

    # 2. Rate-limit + transient per-op failure -> delayed followup inherits BACKGROUND
    monkeypatch.setattr(
        remote_push_mod,
        "build_provider",
        lambda *_a, **_k: type(
            "_FailP",
            (),
            {
                "apply_remote_operations": staticmethod(
                    lambda items: [
                        (items[0].op_id, RemoteOperationResult(success=False, error="HTTP 429 rate limited", remote_state={"retry_after": 30})),
                        (items[1].op_id, RemoteOperationResult(success=False, error="connection reset by peer")),
                    ]
                )
            },
        )(),
    )
    assert remote_push_mod.push_remote_operations(aid, worker_id="w-r", execution_origin="background")["failed"] == 2
    _assert_single_job_origin_and_delete(Session, push_dk, ExecutionOrigin.BACKGROUND.value)

    # 3. Empty eligible work with future next_attempt_at -> delayed followup inherits BACKGROUND
    assert remote_push_mod.push_remote_operations(aid, worker_id="w-d", execution_origin="background")["pushed"] == 0
    _assert_single_job_origin_and_delete(Session, push_dk, ExecutionOrigin.BACKGROUND.value)

    # 4. Partial batch (limit=1 of 2 ready ops) -> immediate followup inherits BACKGROUND
    with Session() as session:
        for oid in (op1_id, op2_id):
            op = session.get(RemoteOperation, oid)
            op.next_attempt_at = None
            op.attempts = 0
        session.commit()
    monkeypatch.setattr(
        remote_push_mod,
        "build_provider",
        lambda *_a, **_k: type("_OkP", (), {"apply_remote_operations": staticmethod(lambda items: [(it.op_id, RemoteOperationResult(success=True)) for it in items])})(),
    )
    assert remote_push_mod.push_remote_operations(aid, worker_id="w-b", execution_origin="background", limit=1)["pushed"] == 1
    _assert_single_job_origin_and_delete(Session, push_dk, ExecutionOrigin.BACKGROUND.value)


def test_t090_coalescing_precedence_successor_inheritance_and_fg_vs_auth(monkeypatch):
    """AC-003/AC-004: successor inherits/promotes origin cleanly, foreground transport degrades, AUTH invalidates both."""
    Session = get_session_factory()
    with Session() as session:
        aid, inbox_id, sent_id = _seed_account_and_folders(session)
        key_p = f"delta:{aid}:{inbox_id}"
        j1 = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(inbox_id)},
            dedupe_key=key_p,
        )
        assert j1.execution_origin == ExecutionOrigin.BACKGROUND.value
        # Background coalescing onto pending background keeps background
        j1_bg = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(inbox_id)},
            dedupe_key=key_p,
        )
        assert j1_bg.id == j1.id and j1_bg.execution_origin == ExecutionOrigin.BACKGROUND.value
        # Foreground coalescing onto pending background promotes to foreground; reverse does not demote
        j1_fg = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=aid,
            payload={"folder_id": str(inbox_id)},
            dedupe_key=key_p,
        )
        assert j1_fg.execution_origin == ExecutionOrigin.FOREGROUND.value
        j1_no_demote = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(inbox_id)},
            dedupe_key=key_p,
        )
        assert j1_no_demote.execution_origin == ExecutionOrigin.FOREGROUND.value
        session.delete(j1)
        session.commit()

    # Claimed background job + has_more -> successor stays background
    with Session() as session:
        bg_job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(sent_id)},
            dedupe_key=f"delta:{aid}:{sent_id}",
        )
        session.commit()
        claimed = claim_jobs(session, worker_id="w-succ", limit=1, job_types=[JobType.SYNC_FOLDER_DELTA.value])
        assert len(claimed) == 1 and claimed[0].id == bg_job.id
        succ = complete_job(session, claimed[0], worker_id="w-succ", result={"has_more": True})
        assert succ is not None
        assert succ.execution_origin == ExecutionOrigin.BACKGROUND.value
        session.delete(succ)
        session.commit()

    # Claimed background job + foreground waiter -> in-flight stays background, successor promotes to foreground
    with Session() as session:
        bg2 = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(sent_id)},
            dedupe_key=f"delta:{aid}:{sent_id}",
        )
        session.commit()
        claimed2 = claim_jobs(session, worker_id="w-mix", limit=1, job_types=[JobType.SYNC_FOLDER_DELTA.value])[0]
        same = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=aid,
            payload={"folder_id": str(sent_id)},
            dedupe_key=f"delta:{aid}:{sent_id}",
        )
        assert same.id == claimed2.id
        assert claimed2.execution_origin == ExecutionOrigin.BACKGROUND.value
        succ_fg = complete_job(session, claimed2, worker_id="w-mix", result={"status": "ok"})
        assert succ_fg is not None and succ_fg.execution_origin == ExecutionOrigin.FOREGROUND.value
        session.commit()
        succ_fg_id = succ_fg.id

    # Foreground transport failure DOES degrade connectivity (AC-004)
    class _BrokenTransport:
        def delta_changes(self, _rid, _cur):
            raise TimeoutError("foreground timeout")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _BrokenTransport())
    assert _run_job(Session, succ_fg_id) is False
    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.connectivity_state == ConnectivityState.DEGRADED.value
        assert acc.credential_state == CredentialState.VALID.value

    # Background AUTH failure still invalidates credentials (AC-004)
    class _AuthFailProvider:
        def delta_changes(self, _rid, _cur):
            raise PermanentAuthError("bad credentials")

    with Session() as session:
        auth_bg = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid,
            payload={"folder_id": str(inbox_id)},
            dedupe_key=f"delta:{aid}:{inbox_id}",
        )
        session.commit()
        auth_bg_id = auth_bg.id

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _AuthFailProvider())
    assert _run_job(Session, auth_bg_id) is False
    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.credential_state == CredentialState.INVALID.value
        assert acc.sync_enabled is False
