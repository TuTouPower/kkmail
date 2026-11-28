"""t095 AC-007 combined regression: IDLE disconnect -> polling fallback -> outbox retention_gap resync -> embedded readiness recovery."""

from __future__ import annotations

import os
import socketserver
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, select, update

from mail_core.api import sse as sse_mod
from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.liveness import write_liveness_stamp
from mail_core.mail.domain.enums import FolderRemoteState, JobType
from mail_core.mail.storage.models import Account, Folder, OutboxEvent, SyncCheckpoint, WorkerJob
from mail_core.readiness import get_readiness_probe
from mail_core.realtime.listener import get_outbox_listener
from mail_core.realtime.outbox import prune_published, publication_head
from mail_core.realtime.publication import publish_committed_batch
from mail_core.sync.idle_watcher import IdleWatcherConfig, IdleWatcherManager
from mail_core.worker.heartbeat import record_heartbeat
from mail_core.worker.main import schedule_periodic_inbox_sync

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class _CombinedImapHandler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        srv = self.server  # type: ignore[attr-defined]
        assert isinstance(srv, _CombinedImapServer)
        try:
            self._send("* OK stub IMAP4rev1 ready")
        except OSError:
            return
        while True:
            try:
                raw = self.rfile.readline()
            except OSError:
                return
            if not raw:
                return
            parts = raw.decode("utf-8", errors="replace").strip().split(None, 2)
            if len(parts) < 2:
                continue
            tag, cmd = parts[0], parts[1].upper()
            try:
                if cmd == "CAPABILITY":
                    cap = "IMAP4rev1 CONDSTORE" if srv.no_idle else "IMAP4rev1 IDLE CONDSTORE"
                    self._send(f"* CAPABILITY {cap}")
                    self._send(f"{tag} OK CAPABILITY completed")
                elif cmd == "LOGIN":
                    self._send(f"{tag} OK LOGIN completed")
                elif cmd == "ID":
                    self._send(f"{tag} OK ID completed")
                elif cmd in ("SELECT", "EXAMINE"):
                    self._send("* 1 EXISTS")
                    self._send("* OK [UIDVALIDITY 100] UIDs valid")
                    self._send("* OK [UIDNEXT 2] Predicted next UID")
                    self._send(f"{tag} OK [READ-WRITE] SELECT completed")
                elif cmd == "IDLE":
                    if srv.no_idle:
                        self._send(f"{tag} BAD IDLE disabled")
                        continue
                    self._send("+ idling")
                    # Block until test trips disconnect or closes socket, then drop abruptly.
                    srv.drop_trigger.wait(timeout=10.0)
                    return
                elif cmd == "DONE":
                    self._send(f"{tag} OK IDLE terminated")
                elif cmd == "LOGOUT":
                    self._send("* BYE")
                    self._send(f"{tag} OK LOGOUT completed")
                    return
                else:
                    self._send(f"{tag} BAD unknown")
            except OSError:
                return


class _CombinedImapServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _CombinedImapHandler)
        self.no_idle = False
        self.drop_trigger = threading.Event()


def _wait_until(predicate, *, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_t095_ac007_combined_idle_fallback_outbox_resync_and_embedded_readiness_recovery(
    monkeypatch, tmp_path
):
    """End-to-end combined PG regression across IDLE fallback, SSE retention_gap, and embedded /ready recovery."""
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    monkeypatch.setenv("KKMAIL_TEST_COMBINED_SECRET", '{"password": "secret"}')
    stamp_file = tmp_path / "embedded-liveness.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))

    get_readiness_probe().invalidate()

    srv = _CombinedImapServer()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Session = get_session_factory()

    listener = get_outbox_listener()
    listener.start()
    assert _wait_until(lambda: listener.listen_ready, timeout_s=5.0)

    sql_statements: list[str] = []

    def _capture_sql(_conn, _cursor, statement, _params, _ctx, _many):
        sql_statements.append(str(statement).strip().upper())

    engine = Session().get_bind()
    event.listen(engine, "before_cursor_execute", _capture_sql)

    try:
        write_liveness_stamp(progress=1, worker_id="combined-embedded")
        with Session() as session:
            _epoch0, head_before_prune = publication_head(session)
            record_heartbeat(session, worker_id="combined-embedded", active_jobs=0)
            acc = Account(
                id=uuid.uuid4(),
                email=f"combined-{uuid.uuid4().hex[:6]}@example.test",
                provider="imap",
                credential_ref="env:KKMAIL_TEST_COMBINED_SECRET",
                sync_enabled=True,
                config={
                    "imap_host": "127.0.0.1",
                    "imap_port": srv.server_address[1],
                    "use_ssl": False,
                },
            )
            session.add(acc)
            session.flush()
            inbox = Folder(
                id=uuid.uuid4(),
                account_id=acc.id,
                remote_id="INBOX",
                name="Inbox",
                role="inbox",
                remote_state=FolderRemoteState.ACTIVE.value,
            )
            session.add(inbox)
            session.flush()
            session.add(
                SyncCheckpoint(
                    account_id=acc.id,
                    folder_id=inbox.id,
                    cursor={"modseq": 1},
                    full_scan_complete=True,
                    last_delta_settled_at=datetime.now(timezone.utc) - timedelta(hours=2),
                )
            )
            for idx in range(3):
                session.add(OutboxEvent(event_type="sync.progress", payload={"step": idx}))
            session.commit()
            acc_id, inbox_id = acc.id, inbox.id

            publish_committed_batch(session, limit=100)
            session.commit()
            epoch, head_after_publish = publication_head(session)
            assert head_after_publish >= head_before_prune + 3

        # Phase 1: Embedded /ready starts healthy (200) with zero ROLLBACK SQL.
        client = TestClient(app)
        sql_statements.clear()
        ready_ok = client.get("/ready")
        assert ready_ok.status_code == 200
        assert ready_ok.json()["status"] == "ready"
        assert ready_ok.json()["worker"] is True
        assert not any(stmt.startswith("ROLLBACK") for stmt in sql_statements)

        # Phase 2: IDLE holds account (exempt from polling), then server drops IDLE capability -> fallback polling schedules delta.
        manager = IdleWatcherManager(
            Session,
            config=IdleWatcherConfig(
                enabled=True,
                quota=2,
                max_duration_s=30.0,
                backoff_base_s=0.05,
                backoff_max_s=0.1,
                reconcile_interval_s=0.05,
            ),
        )
        manager.start()
        try:
            assert _wait_until(lambda: manager.held_account_ids() == {acc_id}, timeout_s=5.0)
            # Clear initial catch-up job; polling skips while IDLE holds the seat.
            with Session() as session:
                session.execute(
                    delete(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{acc_id}:{inbox_id}")
                )
                session.commit()
            with Session() as session:
                assert (
                    schedule_periodic_inbox_sync(
                        session,
                        idle_held_account_ids=manager.held_account_ids(),
                        poll_interval_s=60.0,
                        now=datetime.now(timezone.utc),
                    )
                    == 0
                )
                session.commit()

            # Drop active IDLE socket and mark server non-IDLE -> manager falls back and relinquishes seat.
            srv.no_idle = True
            srv.drop_trigger.set()
            assert _wait_until(
                lambda: manager.snapshot().get(acc_id) == "fallback"
                and acc_id not in manager.held_account_ids(),
                timeout_s=5.0,
            )
            with Session() as session:
                enqueued = schedule_periodic_inbox_sync(
                    session,
                    idle_held_account_ids=manager.held_account_ids(),
                    poll_interval_s=60.0,
                    now=datetime.now(timezone.utc),
                )
                session.commit()
                assert enqueued == 1
                delta_job = session.scalar(
                    select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{acc_id}:{inbox_id}")
                )
                assert delta_job is not None
                assert delta_job.priority == 75
        finally:
            srv.drop_trigger.set()
            manager.stop()

        # Phase 3: Prune published outbox rows past expired cursor -> _build_replay emits retention_gap resync_hint.
        stale_cursor = f"v2:{epoch}:0"
        with Session() as session:
            session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.publication_seq.is_not(None))
                .where(OutboxEvent.publication_seq <= head_after_publish - 1)
                .values(published_at=datetime.now(timezone.utc) - timedelta(days=2))
            )
            session.commit()
            deleted = prune_published(session, now=datetime.now(timezone.utc))
            session.commit()
            assert deleted >= 2

        replay_plan = sse_mod._build_replay(stale_cursor, None)
        assert any(
            event_name == "client.resync_hint" and payload.get("reason") == "retention_gap"
            for _cid, event_name, payload in replay_plan.frames
        )

        # Phase 4: Embedded liveness stamp loss drops /ready to 503 (invalidating cache); fresh stamp restores 200 with zero ROLLBACK.
        stamp_file.unlink()
        get_readiness_probe().invalidate()
        sql_statements.clear()
        degraded = client.get("/ready")
        assert degraded.status_code == 503
        assert degraded.json()["status"] == "not_ready"
        assert degraded.json()["worker"] is False
        assert degraded.json()["reason"] == "worker_not_running"
        assert get_readiness_probe().cached_worker_active() is None

        write_liveness_stamp(progress=2, worker_id="combined-embedded")
        recovered = client.get("/ready")
        assert recovered.status_code == 200
        assert recovered.json()["status"] == "ready"
        assert recovered.json()["worker"] is True
        assert not any(stmt.startswith("ROLLBACK") for stmt in sql_statements)
    finally:
        event.remove(engine, "before_cursor_execute", _capture_sql)
        try:
            listener.stop()
        except Exception:
            pass
        get_readiness_probe().invalidate()
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
