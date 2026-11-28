"""t095 Finding 4 & AC-003/AC-004 real PG and stub-socket regression tests."""

from __future__ import annotations

import contextlib
import os
import socketserver
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

import mail_core.sync.delta as delta_mod
from mail_core.accounts.health import mark_credential_invalid
from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    FolderRemoteState,
    JobStatus,
    JobType,
    SyncActivity,
)
from mail_core.mail.storage.models import (
    Account,
    AccountPatrolState,
    Folder,
    FolderPatrolStatus,
    SyncCheckpoint,
    WorkerJob,
)
from mail_core.providers.base import DeltaPage, FolderStatus
from mail_core.providers.http import PermanentAuthError, RateLimitedError
from mail_core.providers.imap import ImapProvider
from mail_core.sync.idle_watcher import (
    IdleCandidate,
    IdleWatcherConfig,
    IdleWatcherManager,
)
from mail_core.sync.patrol import (
    PATROL_COOLDOWN_S,
    PatrolConfig,
    schedule_folder_status_patrol,
)

_PG_SKIP = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_patrol_account(
    session,
    *,
    roles: tuple[str, ...] = ("sent", "trash"),
    config: dict | None = None,
    with_inbox_baseline: bool = False,
) -> tuple[Account, dict[str, Folder]]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"t095fix-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref=f"ref-{uuid.uuid4().hex[:8]}",
        sync_enabled=True,
        connectivity_state=ConnectivityState.CONNECTED.value,
        credential_state=CredentialState.VALID.value,
        sync_activity=SyncActivity.IDLE.value,
        config=dict(config or {}),
    )
    session.add(acc)
    session.flush()
    folders: dict[str, Folder] = {}
    for role in roles:
        folder = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id=f"{role.upper()}-{uuid.uuid4().hex[:6]}",
            name=role.title(),
            role=role,
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(folder)
        session.flush()
        if with_inbox_baseline or role != "inbox":
            session.add(
                SyncCheckpoint(
                    account_id=acc.id,
                    folder_id=folder.id,
                    cursor={"modseq": 1},
                    full_scan_complete=True,
                )
            )
        folders[role] = folder
    session.flush()
    return acc, folders


def _patrol_cfg(*, interval_s: float = 0.0) -> PatrolConfig:
    return PatrolConfig(
        enabled=True,
        interval_s=interval_s,
        max_probes=200,
        max_unprobed_s=0.0,
    )


@_PG_SKIP
def test_patrol_releases_transaction_during_probe_and_preserves_concurrent_config_edits():
    """Finding 4: patrol holds no DB tx/pool conn during network probe and preserves concurrent Account.config edits."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(
            session,
            roles=("sent", "trash"),
            config={
                "outbound_proxy": "socks5://127.0.0.1:1080",
                "sync_settings": {"days": 30},
            },
        )
        acc_id = acc.id
        folder_ids = [f.id for f in folders.values()]
        session.commit()

    observed_during_failure_probe: dict[str, object] = {}
    probed_fail: list[str] = []

    with Session() as patrol:
        class _FailTransportProvider:
            def probe_folder_status(self, remote_id: str):
                probed_fail.append(remote_id)
                observed_during_failure_probe["in_tx"] = patrol.in_transaction()
                observed_during_failure_probe["checkedout_before_fg"] = (
                    get_engine().pool.checkedout()
                )
                with Session() as fg:
                    idle_in_tx = fg.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid() "
                            "AND state = 'idle in transaction'"
                        )
                    )
                    observed_during_failure_probe["idle_in_tx"] = int(idle_in_tx or 0)
                    row = fg.get(Account, acc_id)
                    row.config = {
                        **(row.config or {}),
                        "outbound_proxy": "socks5://127.0.0.1:1090",
                        "concurrent_fg_key": "keep-me",
                    }
                    fg.commit()
                raise ConnectionError("network unreachable")

        now = datetime.now(timezone.utc)
        res = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailTransportProvider(),
            now=now,
        )
        patrol.commit()

    assert res.failed == 1
    assert len(probed_fail) == 1
    assert observed_during_failure_probe == {
        "in_tx": False,
        "checkedout_before_fg": 0,
        "idle_in_tx": 0,
    }

    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert acc_row.connectivity_state == ConnectivityState.CONNECTED.value
        # t097: the cooldown lives in account_patrol_state, never in config.
        assert "patrol_cooldown_until" not in acc_row.config
        patrol_state = session.get(AccountPatrolState, acc_id)
        assert patrol_state is not None and patrol_state.cooldown_until is not None
        assert acc_row.config["outbound_proxy"] == "socks5://127.0.0.1:1090"
        assert acc_row.config["concurrent_fg_key"] == "keep-me"
        assert acc_row.config["sync_settings"] == {"days": 30}
        fps_rows = list(
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(folder_ids)
                )
            ).all()
        )
        assert len(fps_rows) == 1

    # Recovery after cooldown expires must ALSO run outside DB tx and preserve concurrent edits when clearing cooldown.
    observed_during_recovery: dict[str, object] = {}
    recovery_edited = False

    with Session() as patrol:
        class _HealthyProvider:
            def probe_folder_status(self, _remote_id: str):
                nonlocal recovery_edited
                if not recovery_edited:
                    recovery_edited = True
                    observed_during_recovery["in_tx"] = patrol.in_transaction()
                    observed_during_recovery["checkedout_before_fg"] = (
                        get_engine().pool.checkedout()
                    )
                    with Session() as fg:
                        idle_in_tx = fg.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND pid <> pg_backend_pid() "
                                "AND state = 'idle in transaction'"
                            )
                        )
                        observed_during_recovery["idle_in_tx"] = int(idle_in_tx or 0)
                        row = fg.get(Account, acc_id)
                        row.config = {
                            **(row.config or {}),
                            "recovery_concurrent_edit": True,
                        }
                        fg.commit()
                return FolderStatus(messages=3, uidnext=4, unseen=1, highestmodseq=9)

        res2 = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _HealthyProvider(),
            now=now + timedelta(seconds=PATROL_COOLDOWN_S + 5),
        )
        patrol.commit()

    assert res2.probed == 2
    assert res2.failed == 0
    assert observed_during_recovery == {
        "in_tx": False,
        "checkedout_before_fg": 0,
        "idle_in_tx": 0,
    }
    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert "patrol_cooldown_until" not in acc_row.config
        # t097: the lease holder's recovery success cleared the patrol state.
        assert session.get(AccountPatrolState, acc_id) is None
        assert acc_row.config["outbound_proxy"] == "socks5://127.0.0.1:1090"
        assert acc_row.config["concurrent_fg_key"] == "keep-me"
        assert acc_row.config["sync_settings"] == {"days": 30}
        assert acc_row.config["recovery_concurrent_edit"] is True


@_PG_SKIP
@pytest.mark.parametrize("recovery_succeeds", [True, False])
def test_patrol_half_open_expired_cooldown_single_holder_across_workers(recovery_succeeds: bool):
    """AC-004: two concurrent workers racing after cooldown expiry yield strictly one half-open probe."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    expired_until = now - timedelta(seconds=10)
    with Session() as session:
        acc, _folders = _seed_patrol_account(
            session,
            roles=("sent",),
            config={"keep": "yes"},
        )
        acc_id = acc.id
        # t097: an expired cooldown lives in account_patrol_state.
        session.add(
            AccountPatrolState(account_id=acc_id, cooldown_until=expired_until)
        )
        session.commit()

    entered_probe = threading.Event()
    release_probe = threading.Event()
    probe_calls: list[str] = []
    probe_lock = threading.Lock()
    results: dict[str, object] = {}

    def _run_worker(name: str, *, hold_inside_probe: bool) -> None:
        with Session() as session:
            class _Provider:
                def probe_folder_status(self, remote_id: str):
                    with probe_lock:
                        probe_calls.append(f"{name}:{remote_id}")
                    if hold_inside_probe:
                        entered_probe.set()
                        assert release_probe.wait(timeout=5.0)
                    if not recovery_succeeds:
                        raise ConnectionError("still unreachable")
                    return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

            res = schedule_folder_status_patrol(
                session,
                config=_patrol_cfg(),
                provider_factory=lambda _a: _Provider(),
                now=now,
            )
            session.commit()
            results[name] = res

    t1 = threading.Thread(target=_run_worker, args=("w1",), kwargs={"hold_inside_probe": True})
    t1.start()
    assert entered_probe.wait(timeout=5.0)

    # Worker 2 races while Worker 1 is actively executing the half-open probe.
    _run_worker("w2", hold_inside_probe=False)
    release_probe.set()
    t1.join(timeout=5.0)
    assert not t1.is_alive()

    assert len(probe_calls) == 1
    assert results["w1"].probed == (1 if recovery_succeeds else 0)
    assert results["w1"].failed == (0 if recovery_succeeds else 1)
    assert results["w2"].probed == 0
    assert results["w2"].failed == 0

    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert acc_row.config["keep"] == "yes"
        assert "patrol_cooldown_until" not in acc_row.config
        patrol_state = session.get(AccountPatrolState, acc_id)
        if recovery_succeeds:
            assert patrol_state is None
        else:
            assert patrol_state is not None
            assert patrol_state.cooldown_until != expired_until


@_PG_SKIP
def test_patrol_auth_failure_invalidates_preserves_config_and_isolates_shared_endpoint():
    """AC-004: AUTH failure invalidates acc_a, preserves config, skips siblings, and spares shared-endpoint acc_b."""
    Session = get_session_factory()
    shared_cfg = {
        "imap_host": "imap.shared.example",
        "imap_port": 993,
        "outbound_proxy": "http://proxy.local:8080",
    }
    with Session() as session:
        acc_a, folders_a = _seed_patrol_account(session, roles=("sent", "trash"), config=shared_cfg)
        acc_b, folders_b = _seed_patrol_account(session, roles=("sent",), config=shared_cfg)
        acc_a_id, acc_b_id = acc_a.id, acc_b.id
        a_folder_ids = [f.id for f in folders_a.values()]
        session.commit()

    probed_by_account: dict[uuid.UUID, list[str]] = {acc_a_id: [], acc_b_id: []}

    def _factory(account: Account):
        class _Prov:
            def probe_folder_status(self, remote_id: str):
                probed_by_account[account.id].append(remote_id)
                if account.id == acc_a_id:
                    with Session() as fg:
                        row = fg.get(Account, acc_a_id)
                        row.config = {**(row.config or {}), "user_note": "preserve-on-auth-fail"}
                        fg.commit()
                    raise PermanentAuthError("invalid credentials")
                return FolderStatus(messages=5, uidnext=6, unseen=1, highestmodseq=10)

        return _Prov()

    now = datetime.now(timezone.utc)
    with Session() as patrol:
        res = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=_factory,
            now=now,
        )
        patrol.commit()

    assert res.failed == 1
    assert res.probed == 1
    assert len(probed_by_account[acc_a_id]) == 1
    assert len(probed_by_account[acc_b_id]) == 1

    with Session() as session:
        row_a = session.get(Account, acc_a_id)
        row_b = session.get(Account, acc_b_id)
        assert row_a.credential_state == CredentialState.INVALID.value
        assert row_a.sync_enabled is False
        assert row_a.sync_activity == SyncActivity.IDLE.value
        assert row_a.config["outbound_proxy"] == "http://proxy.local:8080"
        assert row_a.config["user_note"] == "preserve-on-auth-fail"
        assert "last_synced_at" in row_a.config
        # t097: cooldown is patrol state, not a config key.
        assert "patrol_cooldown_until" not in row_a.config
        assert session.get(AccountPatrolState, acc_a_id) is not None

        assert row_b.credential_state == CredentialState.VALID.value
        assert row_b.connectivity_state == ConnectivityState.CONNECTED.value
        assert row_b.sync_enabled is True
        assert "patrol_cooldown_until" not in (row_b.config or {})
        assert session.get(AccountPatrolState, acc_b_id) is None

        fps_a = list(
            session.scalars(
                select(FolderPatrolStatus).where(FolderPatrolStatus.folder_id.in_(a_folder_ids))
            ).all()
        )
        assert len(fps_a) == 1

    # Also verify direct mark_credential_invalid preserves concurrent committed Account.config edits even from stale session.
    with Session() as stale, Session() as concurrent:
        stale_b = stale.get(Account, acc_b_id)
        assert stale_b is not None
        conc_b = concurrent.get(Account, acc_b_id)
        conc_b.config = {**(conc_b.config or {}), "concurrent_proxy_edit": "socks5://127.0.0.1:9999"}
        concurrent.commit()

        mark_credential_invalid(stale, acc_b_id)
        stale.commit()

    with Session() as session:
        refreshed_b = session.get(Account, acc_b_id)
        assert refreshed_b.credential_state == CredentialState.INVALID.value
        assert refreshed_b.sync_enabled is False
        assert refreshed_b.config["concurrent_proxy_edit"] == "socks5://127.0.0.1:9999"
        assert "last_synced_at" in refreshed_b.config


@_PG_SKIP
def test_patrol_single_folder_unknown_error_does_not_short_circuit_account():
    """AC-004: single-folder UNKNOWN failure stays isolated to that folder and still probes siblings."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        sent_id, trash_id = folders["sent"].id, folders["trash"].id
        sent_rid = folders["sent"].remote_id
        session.commit()

    probed: list[str] = []

    class _MixedProvider:
        def probe_folder_status(self, remote_id: str):
            probed.append(remote_id)
            if remote_id == sent_rid:
                raise RuntimeError("SELECT mailbox corrupt")
            return FolderStatus(messages=2, uidnext=3, unseen=0, highestmodseq=4)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _MixedProvider(),
            now=datetime.now(timezone.utc),
        )
        session.commit()

    assert res.failed == 1
    assert res.probed == 1
    assert len(probed) == 2
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.credential_state == CredentialState.VALID.value
        assert row.connectivity_state == ConnectivityState.CONNECTED.value
        assert "patrol_cooldown_until" not in (row.config or {})
        assert session.get(AccountPatrolState, acc_id) is None
        assert session.get(FolderPatrolStatus, sent_id).last_probe_failures == 1
        assert session.get(FolderPatrolStatus, trash_id).last_probe_failures == 0


@_PG_SKIP
def test_patrol_rate_limited_control_error_does_not_mark_unreachable_and_slows_rotation():
    """AC-004: RateLimitedError (CONTROL) never marks UNREACHABLE/cooldown and slows folder rotation."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        sent_id = folders["sent"].id
        sent_rid = folders["sent"].remote_id
        session.commit()

    class _RateLimitedProvider:
        def probe_folder_status(self, remote_id: str):
            if remote_id == sent_rid:
                raise RateLimitedError("429 too many requests", retry_after_seconds=30.0)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(interval_s=1200.0),
            provider_factory=lambda _a: _RateLimitedProvider(),
            now=now,
        )
        session.commit()

    assert res.failed == 1
    assert res.probed == 1
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.connectivity_state == ConnectivityState.CONNECTED.value
        assert row.credential_state == CredentialState.VALID.value
        assert "patrol_cooldown_until" not in (row.config or {})
        assert session.get(AccountPatrolState, acc_id) is None
        fps_sent = session.get(FolderPatrolStatus, sent_id)
        assert fps_sent.last_probe_at == now
        assert fps_sent.last_probe_failures == 1

    # Next sweep within interval_s skips the rate-limited folder (slowed rotation).
    probed_again: list[str] = []

    class _RecorderProvider:
        def probe_folder_status(self, remote_id: str):
            probed_again.append(remote_id)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res2 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(interval_s=1200.0),
            provider_factory=lambda _a: _RecorderProvider(),
            now=now + timedelta(seconds=60),
        )
        session.commit()

    assert res2.probed == 0
    assert res2.failed == 0
    assert res2.skipped_not_due >= 2
    assert probed_again == []


@_PG_SKIP
def test_foreground_sync_bypasses_active_patrol_cooldown(monkeypatch):
    """AC-004: foreground sync runs immediately even while patrol cooldown is active."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_patrol_account(
            session,
            roles=("inbox", "sent"),
            with_inbox_baseline=True,
        )
        acc_id = acc.id
        inbox_id = folders["inbox"].id
        session.commit()

    class _FailPatrolProvider:
        def probe_folder_status(self, _rid: str):
            raise ConnectionError("patrol transport down")

    with Session() as session:
        r1 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailPatrolProvider(),
            now=now,
        )
        session.commit()
    assert r1.failed == 1

    # Verify patrol itself respects active cooldown.
    with Session() as session:
        r2 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailPatrolProvider(),
            now=now + timedelta(seconds=30),
        )
        session.commit()
    assert r2.probed == 0 and r2.failed == 0 and r2.skipped_not_due >= 1

    # Foreground sync must bypass patrol cooldown and execute immediately.
    delta_called: list[str] = []

    class _HealthyDeltaProvider:
        def delta_changes(self, remote_id: str, _cursor: dict):
            delta_called.append(remote_id)
            return DeltaPage(changes=[], next_cursor={"modseq": 2}, exhausted=True)

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _HealthyDeltaProvider())
    fg_res = delta_mod.sync_folder_delta(
        acc_id,
        inbox_id,
        worker_id="fg-worker",
        execution_origin=ExecutionOrigin.FOREGROUND,
    )
    assert fg_res["status"] == "ok"
    assert len(delta_called) == 1


@_PG_SKIP
def test_patrol_caller_open_tx_compatibility_without_premature_commit():
    """Caller-owned uncommitted fixture transaction stays uncommitted across patrol sweep."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent",), config={"keep": "tx"})
        acc_id = acc.id
        sent_id = folders["sent"].id
        assert session.in_transaction() is True

        class _FailProv:
            def probe_folder_status(self, _rid: str):
                raise ConnectionError("boom")

        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailProv(),
            now=datetime.now(timezone.utc),
        )
        assert res.failed == 1
        assert session.in_transaction() is True
        assert "patrol_cooldown_until" not in (session.get(Account, acc_id).config or {})
        assert session.get(AccountPatrolState, acc_id) is not None
        assert session.get(FolderPatrolStatus, sent_id) is not None
        session.rollback()

    with Session() as session:
        assert session.get(Account, acc_id) is None


# ---------------------------------------------------------------------------
# Commit 2: t095 AC-003 IDLE closing-thread quota & real ImapIdleSession tests
# ---------------------------------------------------------------------------


class _StubImapHandler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self) -> None:
        server = self.server  # type: ignore[attr-defined]
        with server.lock:
            server.connect_count += 1
            conn_idx = server.connect_count
        if server.greeting_gate is not None:
            server.greeting_gate.wait(timeout=10.0)
        try:
            self._send("* OK Stub IMAP ready")
        except OSError:
            return
        while True:
            try:
                raw = self.rfile.readline()
            except OSError:
                return
            if not raw:
                return
            line = raw.decode("utf-8", "replace").strip()
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            tag, cmd = parts[0], parts[1].upper()
            try:
                if cmd == "CAPABILITY":
                    caps = "IMAP4rev1 CONDSTORE" if server.no_idle else "IMAP4rev1 IDLE CONDSTORE"
                    self._send(f"* CAPABILITY {caps}")
                    self._send(f"{tag} OK CAPABILITY completed")
                elif cmd == "LOGIN":
                    self._send(f"{tag} OK LOGIN completed")
                elif cmd == "ID":
                    self._send(f"{tag} OK ID completed")
                elif cmd in ("SELECT", "EXAMINE"):
                    with server.lock:
                        server.select_count += 1
                    self._send("* 1 EXISTS")
                    self._send("* OK [UIDVALIDITY 100] UIDs valid")
                    self._send("* OK [UIDNEXT 2] Predicted next UID")
                    self._send(f"{tag} OK [READ-WRITE] SELECT completed")
                elif cmd == "IDLE":
                    with server.lock:
                        server.idle_count += 1
                    self._send("+ idling")
                    if server.drop_on_connect == conn_idx:
                        if server.drop_trigger is not None:
                            server.drop_trigger.wait(timeout=10.0)
                        try:
                            self.connection.close()
                        except OSError:
                            pass
                        return
                    done = self.rfile.readline()
                    if not done:
                        return
                    with server.lock:
                        server.done_count += 1
                    if server.ignore_done:
                        # Simulate hung server that never acknowledges DONE; wait until client drops socket.
                        while True:
                            tail = self.rfile.readline()
                            if not tail:
                                return
                    self._send(f"{tag} OK IDLE terminated")
                elif cmd == "LOGOUT":
                    self._send("* BYE logging out")
                    self._send(f"{tag} OK LOGOUT completed")
                    return
                else:
                    self._send(f"{tag} BAD unknown command")
            except OSError:
                return


class _StubImapServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        *,
        no_idle: bool = False,
        greeting_gate: threading.Event | None = None,
        drop_on_connect: int = 0,
        drop_trigger: threading.Event | None = None,
        ignore_done: bool = False,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _StubImapHandler)
        self.lock = threading.Lock()
        self.no_idle = no_idle
        self.greeting_gate = greeting_gate
        self.drop_on_connect = drop_on_connect
        self.drop_trigger = drop_trigger
        self.ignore_done = ignore_done
        self.connect_count = 0
        self.select_count = 0
        self.idle_count = 0
        self.done_count = 0


@pytest.fixture()
def stub_imap_servers(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    servers: list[_StubImapServer] = []

    def _spawn(**kwargs) -> _StubImapServer:
        srv = _StubImapServer(**kwargs)
        servers.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    yield _spawn
    for srv in servers:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass


class _FakeMultiDbSession:
    """In-memory DB session double keyed by account/folder UUIDs for unit-mode manager tests."""

    def __init__(self, accounts: dict[uuid.UUID, Account], folders: dict[uuid.UUID, Folder]):
        self._accounts = accounts
        self._folders = folders

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, model, key):  # noqa: ANN001, ANN202
        if model is Account:
            return self._accounts.get(key)
        if model is Folder:
            return self._folders.get(key)
        return None

    def scalar(self, _statement):  # noqa: ANN001, ANN202
        return None

    def add(self, _obj) -> None:
        pass

    def begin_nested(self):
        return contextlib.nullcontext()

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        pass


def _live_idle_threads() -> tuple[list[threading.Thread], list[threading.Thread]]:
    live = [t for t in threading.enumerate() if t.is_alive()]
    watchers = [
        t
        for t in live
        if t.name.startswith("imap-idle-")
        and t.name not in ("imap-idle-watcher", "imap-idle-reader")
    ]
    readers = [t for t in live if t.name == "imap-idle-reader"]
    return watchers, readers


def _wait_until(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _make_memory_idle_accounts(
    count: int,
    servers: list[_StubImapServer],
    *,
    now: datetime,
) -> tuple[dict[uuid.UUID, Account], dict[uuid.UUID, Folder], list[IdleCandidate]]:
    accounts: dict[uuid.UUID, Account] = {}
    folders: dict[uuid.UUID, Folder] = {}
    candidates: list[IdleCandidate] = []
    for idx in range(count):
        acc_id = uuid.uuid4()
        folder_id = uuid.uuid4()
        port = servers[idx].server_address[1]
        acc = Account(
            id=acc_id,
            email=f"idle-{idx}-{acc_id.hex[:6]}@example.test",
            provider="imap",
            credential_ref=f"ref-{idx}",
            sync_enabled=True,
            config={"imap_host": "127.0.0.1", "imap_port": port, "use_ssl": False},
        )
        folder = Folder(
            id=folder_id,
            account_id=acc_id,
            remote_id="INBOX",
            name="Inbox",
            role="inbox",
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        accounts[acc_id] = acc
        folders[folder_id] = folder
        candidates.append(
            IdleCandidate(
                account_id=acc_id,
                folder_id=folder_id,
                inbox_latest_arrival_at=now - timedelta(minutes=idx + 1),
                inbox_has_messages=True,
                other_latest_arrival_at=None,
                account_created_at=now - timedelta(hours=1),
                credential_fingerprint=f"fp-{idx}",
            )
        )
    return accounts, folders, candidates


def _open_real_idle_session(account_snapshot: Account, folder_snapshot: Folder):
    cfg = dict(account_snapshot.config or {})
    provider = ImapProvider(
        host=str(cfg["imap_host"]),
        port=int(cfg["imap_port"]),
        username=account_snapshot.email,
        password="secret",
        use_ssl=False,
        timeout=5.0,
        permit_factory=None,
    )
    return provider.open_idle_session(folder_snapshot.remote_id)


def test_idle_quota_bounds_real_os_threads_across_excess_accounts(stub_imap_servers):
    """AC-003: 12 real IMAP accounts with quota=4 never exceed 4 watchers + 4 readers (<= 8 OS threads)."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    servers = [stub_imap_servers() for _ in range(12)]
    accounts, folders, candidates = _make_memory_idle_accounts(12, servers, now=now)

    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_open_real_idle_session,
        config=IdleWatcherConfig(
            enabled=True,
            quota=4,
            max_duration_s=30.0,
            backoff_base_s=0.05,
            backoff_max_s=0.2,
            hysteresis_s=300.0,
            reconcile_interval_s=0.05,
        ),
    )
    manager._load_candidates = lambda: list(candidates)  # noqa: SLF001
    manager.start()
    try:
        expected_top = {c.account_id for c in candidates[:4]}

        def _ready_and_bounded() -> bool:
            w, r = _live_idle_threads()
            assert len(w) <= 4
            assert len(r) <= 4
            assert len(w) + len(r) <= 8
            return manager.held_account_ids() == expected_top

        assert _wait_until(_ready_and_bounded)
        max_watchers = 0
        max_readers = 0
        max_total = 0
        for _ in range(10):
            watchers, readers = _live_idle_threads()
            max_watchers = max(max_watchers, len(watchers))
            max_readers = max(max_readers, len(readers))
            max_total = max(max_total, len(watchers) + len(readers))
            assert len(watchers) <= 4
            assert len(readers) <= 4
            assert len(watchers) + len(readers) <= 8
            time.sleep(0.03)
        assert max_watchers == 4
        assert max_readers == 4
        assert max_total == 8
    finally:
        manager.stop()

    assert _wait_until(lambda: _live_idle_threads() == ([], []))


def test_idle_slow_close_and_rotation_bounds_live_os_threads(stub_imap_servers):
    """AC-003: slow-closing watch occupies its quota seat until its thread exits, never exceeding 2*quota."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    servers = [stub_imap_servers() for _ in range(5)]
    accounts, folders, candidates = _make_memory_idle_accounts(5, servers, now=now)
    evicted_id = candidates[3].account_id
    challenger_id = candidates[4].account_id

    slow_close_release = threading.Event()
    slow_close_entered = threading.Event()

    class _SlowCloseSessionWrapper:
        def __init__(self, inner):
            self._inner = inner

        @property
        def reader_thread(self) -> threading.Thread:
            return self._inner.reader_thread

        def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
            return self._inner.wait_for_change(timeout_s=timeout_s, stop_event=stop_event)

        def close(self) -> None:
            slow_close_entered.set()
            slow_close_release.wait(timeout=10.0)
            self._inner.close()

    def _factory(account_snapshot: Account, folder_snapshot: Folder):
        sess = _open_real_idle_session(account_snapshot, folder_snapshot)
        if account_snapshot.id == evicted_id:
            return _SlowCloseSessionWrapper(sess)
        return sess

    state_candidates = list(candidates)
    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_factory,
        config=IdleWatcherConfig(
            enabled=True,
            quota=4,
            max_duration_s=30.0,
            backoff_base_s=0.05,
            backoff_max_s=0.2,
            hysteresis_s=300.0,
            reconcile_interval_s=60.0,
            close_timeout_s=0.15,
        ),
    )
    manager._load_candidates = lambda: list(state_candidates)  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        initial_top = {c.account_id for c in candidates[:4]}
        assert _wait_until(lambda: manager.held_account_ids() == initial_top)
        watchers, readers = _live_idle_threads()
        assert len(watchers) == 4 and len(readers) == 4

        # Make challenger (index 4) strictly hotter than evicted (index 3), forcing seat rotation.
        state_candidates[4] = IdleCandidate(
            account_id=challenger_id,
            folder_id=candidates[4].folder_id,
            inbox_latest_arrival_at=now + timedelta(minutes=5),
            inbox_has_messages=True,
            other_latest_arrival_at=None,
            account_created_at=candidates[4].account_created_at,
            credential_fingerprint=candidates[4].credential_fingerprint,
        )
        manager._reconcile_once()  # noqa: SLF001

        assert _wait_until(slow_close_entered.is_set, timeout_s=3.0)
        # Evicted thread is still alive in slow close -> occupies a seat -> challenger must NOT open yet!
        assert challenger_id not in manager._watches  # noqa: SLF001
        assert len(manager._closing_threads) == 1  # noqa: SLF001
        watchers_mid, readers_mid = _live_idle_threads()
        assert len(watchers_mid) <= 4
        assert len(readers_mid) <= 4
        assert len(watchers_mid) + len(readers_mid) <= 8

        # Another reconcile tick while still closing must keep blocking replacement.
        manager._reconcile_once()  # noqa: SLF001
        assert challenger_id not in manager._watches  # noqa: SLF001
        watchers_mid2, readers_mid2 = _live_idle_threads()
        assert len(watchers_mid2) + len(readers_mid2) <= 8

        # Release the stalled close -> thread finishes -> next reconcile prunes it and opens challenger.
        slow_close_release.set()
        assert _wait_until(lambda: not any(t.is_alive() for t in manager._closing_threads))  # noqa: SLF001
        manager._reconcile_once()  # noqa: SLF001
        assert manager._closing_threads == []  # noqa: SLF001
        expected_after = {candidates[0].account_id, candidates[1].account_id, candidates[2].account_id, challenger_id}
        assert _wait_until(lambda: manager.held_account_ids() == expected_after)
        watchers_end, readers_end = _live_idle_threads()
        assert len(watchers_end) == 4 and len(readers_end) == 4
    finally:
        slow_close_release.set()
        manager.stop()

    assert _wait_until(lambda: _live_idle_threads() == ([], []))


def test_idle_hung_done_closes_socket_and_exits_reader_promptly(stub_imap_servers):
    """ImapIdleSession.close cleanly shuts down socket/file so reader exits even when server ignores DONE."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    srv = stub_imap_servers(ignore_done=True)
    accounts, folders, candidates = _make_memory_idle_accounts(1, [srv], now=now)
    acc_id = candidates[0].account_id

    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_open_real_idle_session,
        config=IdleWatcherConfig(
            enabled=True,
            quota=1,
            max_duration_s=30.0,
            reconcile_interval_s=60.0,
            close_timeout_s=0.3,
        ),
    )
    active_candidates = list(candidates)
    manager._load_candidates = lambda: list(active_candidates)  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        watchers, readers = _live_idle_threads()
        assert len(watchers) == 1 and len(readers) == 1
        active_candidates.clear()
        started = time.monotonic()
        manager._reconcile_once()  # noqa: SLF001
        elapsed = time.monotonic() - started
        assert elapsed < 3.0
        assert _wait_until(lambda: _live_idle_threads() == ([], []))
    finally:
        manager.stop()


def test_idle_live_reader_without_watcher_still_occupies_quota():
    """AC-003: an un-joined live reader thread continues occupying a quota seat after its watcher exits."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    acc0_id, f0_id = uuid.uuid4(), uuid.uuid4()
    acc1_id, f1_id = uuid.uuid4(), uuid.uuid4()
    accounts = {
        acc0_id: Account(id=acc0_id, email="r0@example.test", provider="imap", credential_ref="r0", sync_enabled=True, config={}),
        acc1_id: Account(id=acc1_id, email="r1@example.test", provider="imap", credential_ref="r1", sync_enabled=True, config={}),
    }
    folders = {
        f0_id: Folder(id=f0_id, account_id=acc0_id, remote_id="INBOX", name="Inbox", role="inbox", remote_state=FolderRemoteState.ACTIVE.value),
        f1_id: Folder(id=f1_id, account_id=acc1_id, remote_id="INBOX", name="Inbox", role="inbox", remote_state=FolderRemoteState.ACTIVE.value),
    }
    c0 = IdleCandidate(
        account_id=acc0_id,
        folder_id=f0_id,
        inbox_latest_arrival_at=now - timedelta(minutes=2),
        inbox_has_messages=True,
        other_latest_arrival_at=None,
        account_created_at=now - timedelta(hours=1),
        credential_fingerprint="fp-0",
    )
    c1 = IdleCandidate(
        account_id=acc1_id,
        folder_id=f1_id,
        inbox_latest_arrival_at=now + timedelta(minutes=10),
        inbox_has_messages=True,
        other_latest_arrival_at=None,
        account_created_at=now - timedelta(hours=1),
        credential_fingerprint="fp-1",
    )

    reader_release = threading.Event()
    opened: list[uuid.UUID] = []

    class _LingeringReaderSession:
        def __init__(self, aid: uuid.UUID) -> None:
            self._aid = aid
            self._reader = threading.Thread(
                target=lambda: reader_release.wait(timeout=10.0),
                name="imap-idle-reader",
                daemon=True,
            )
            self._reader.start()

        @property
        def reader_thread(self) -> threading.Thread:
            return self._reader

        def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
            stop_event.wait(timeout_s)
            return "stopped"

        def close(self) -> None:
            # Watcher exits promptly while reader remains blocked on reader_release.
            pass

    def _factory(account_snapshot: Account, _folder_snapshot: Folder):
        opened.append(account_snapshot.id)
        return _LingeringReaderSession(account_snapshot.id)

    state_candidates = [c0]
    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_factory,
        config=IdleWatcherConfig(enabled=True, quota=1, reconcile_interval_s=60.0, close_timeout_s=0.2),
    )
    manager._load_candidates = lambda: list(state_candidates)  # noqa: SLF001
    try:
        manager._reconcile_once()  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc0_id})

        # Evict c0 in favor of c1: watcher exits immediately, reader lingers.
        state_candidates[:] = [c0, c1]
        manager._reconcile_once()  # noqa: SLF001

        assert acc1_id not in manager._watches  # noqa: SLF001
        assert len(manager._closing_threads) == 1  # noqa: SLF001
        watchers_mid, readers_mid = _live_idle_threads()
        assert watchers_mid == []
        assert len(readers_mid) == 1

        # Reconcile again while reader is still alive: c1 must still wait.
        manager._reconcile_once()  # noqa: SLF001
        assert acc1_id not in manager._watches  # noqa: SLF001

        # Unblock reader -> next reconcile reaps it and opens c1.
        reader_release.set()
        assert _wait_until(lambda: _live_idle_threads() == ([], []))
        manager._reconcile_once()  # noqa: SLF001
        assert manager._closing_threads == []  # noqa: SLF001
        assert _wait_until(lambda: manager.held_account_ids() == {acc1_id})
        assert opened == [acc0_id, acc1_id]
    finally:
        reader_release.set()
        manager.stop()

    assert _wait_until(lambda: _live_idle_threads() == ([], []))


def test_idle_slow_connect_does_not_block_other_accounts(stub_imap_servers):
    """AC-003: one slow-connecting account never delays other accounts from idling."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    connect_gate = threading.Event()
    servers = [
        stub_imap_servers(greeting_gate=connect_gate),
        stub_imap_servers(),
        stub_imap_servers(),
        stub_imap_servers(),
    ]
    accounts, folders, candidates = _make_memory_idle_accounts(4, servers, now=now)
    slow_id = candidates[0].account_id
    fast_ids = {c.account_id for c in candidates[1:]}

    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_open_real_idle_session,
        config=IdleWatcherConfig(
            enabled=True,
            quota=4,
            max_duration_s=30.0,
            reconcile_interval_s=0.05,
        ),
    )
    manager._load_candidates = lambda: list(candidates)  # noqa: SLF001
    manager.start()
    try:
        assert _wait_until(lambda: fast_ids.issubset(manager.held_account_ids()), timeout_s=3.0)
        assert manager.snapshot().get(slow_id) == "connecting"
        assert slow_id not in manager.held_account_ids()

        connect_gate.set()
        assert _wait_until(lambda: manager.held_account_ids() == ({slow_id} | fast_ids))
        watchers, readers = _live_idle_threads()
        assert len(watchers) == 4 and len(readers) == 4
    finally:
        connect_gate.set()
        manager.stop()

    assert _wait_until(lambda: _live_idle_threads() == ([], []))


def test_idle_renew_on_timeout_with_real_imap_idle_session(stub_imap_servers):
    """AC-003: IDLE session renews cleanly across max_duration_s timeouts without thread leaks."""
    assert _live_idle_threads() == ([], [])
    now = datetime.now(timezone.utc)
    srv = stub_imap_servers()
    accounts, folders, candidates = _make_memory_idle_accounts(1, [srv], now=now)
    acc_id = candidates[0].account_id

    manager = IdleWatcherManager(
        lambda: _FakeMultiDbSession(accounts, folders),
        idle_session_factory=_open_real_idle_session,
        config=IdleWatcherConfig(
            enabled=True,
            quota=2,
            max_duration_s=0.25,
            reconcile_interval_s=0.1,
        ),
    )
    manager._load_candidates = lambda: list(candidates)  # noqa: SLF001
    manager.start()
    try:
        assert _wait_until(lambda: manager.held_account_ids() == {acc_id})
        assert _wait_until(lambda: srv.idle_count >= 3 and srv.done_count >= 2, timeout_s=5.0)
        assert srv.connect_count == 1
        assert manager.snapshot().get(acc_id) == "idling"
        watchers, readers = _live_idle_threads()
        assert len(watchers) == 1 and len(readers) == 1
    finally:
        manager.stop()

    assert _wait_until(lambda: _live_idle_threads() == ([], []))


@_PG_SKIP
def test_idle_disconnect_catchup_cancel_and_polling_fallback_real_pg(monkeypatch, stub_imap_servers):
    """AC-003 real PG: disconnect triggers catch-up delta job, no-IDLE falls back to polling, cancel stops all threads."""
    from mail_core.worker.main import schedule_periodic_inbox_sync

    assert _live_idle_threads() == ([], [])
    monkeypatch.setenv("KKMAIL_TEST_IDLE_SECRET", '{"password": "secret"}')

    drop_trigger = threading.Event()
    srv_drop = stub_imap_servers(drop_on_connect=1, drop_trigger=drop_trigger)
    srv_no_idle = stub_imap_servers(no_idle=True)

    Session = get_session_factory()
    with Session() as session:
        acc_drop = Account(
            id=uuid.uuid4(),
            email=f"idle-drop-{uuid.uuid4().hex[:6]}@example.test",
            provider="imap",
            credential_ref="env:KKMAIL_TEST_IDLE_SECRET",
            sync_enabled=True,
            config={
                "imap_host": "127.0.0.1",
                "imap_port": srv_drop.server_address[1],
                "use_ssl": False,
            },
        )
        acc_no_idle = Account(
            id=uuid.uuid4(),
            email=f"idle-fallback-{uuid.uuid4().hex[:6]}@example.test",
            provider="imap",
            credential_ref="env:KKMAIL_TEST_IDLE_SECRET",
            sync_enabled=True,
            config={
                "imap_host": "127.0.0.1",
                "imap_port": srv_no_idle.server_address[1],
                "use_ssl": False,
            },
        )
        session.add_all([acc_drop, acc_no_idle])
        session.flush()
        inbox_drop = Folder(
            id=uuid.uuid4(),
            account_id=acc_drop.id,
            remote_id="INBOX",
            name="Inbox",
            role="inbox",
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        inbox_no_idle = Folder(
            id=uuid.uuid4(),
            account_id=acc_no_idle.id,
            remote_id="INBOX",
            name="Inbox",
            role="inbox",
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add_all([inbox_drop, inbox_no_idle])
        session.flush()
        old_settled = datetime.now(timezone.utc) - timedelta(hours=2)
        for aid, fid in ((acc_drop.id, inbox_drop.id), (acc_no_idle.id, inbox_no_idle.id)):
            session.add(
                SyncCheckpoint(
                    account_id=aid,
                    folder_id=fid,
                    cursor={"modseq": 1},
                    full_scan_complete=True,
                    last_delta_settled_at=old_settled,
                )
            )
        drop_acc_id, drop_inbox_id = acc_drop.id, inbox_drop.id
        no_idle_acc_id, no_idle_inbox_id = acc_no_idle.id, inbox_no_idle.id
        session.commit()

    def _jobs_for(aid: uuid.UUID, fid: uuid.UUID) -> list[WorkerJob]:
        with Session() as session:
            return list(
                session.scalars(
                    select(WorkerJob).where(
                        WorkerJob.dedupe_key == f"delta:{aid}:{fid}",
                        WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                    )
                ).all()
            )

    manager = IdleWatcherManager(
        Session,
        config=IdleWatcherConfig(
            enabled=True,
            quota=4,
            max_duration_s=30.0,
            backoff_base_s=0.05,
            backoff_max_s=0.1,
            hysteresis_s=300.0,
            reconcile_interval_s=0.05,
        ),
    )
    manager.start()
    try:
        # 1. acc_drop connects and enqueues first catchup delta; acc_no_idle enters polling fallback.
        assert _wait_until(lambda: drop_acc_id in manager.held_account_ids())
        assert _wait_until(lambda: manager.snapshot().get(no_idle_acc_id) == "fallback")
        assert _wait_until(lambda: len(_jobs_for(drop_acc_id, drop_inbox_id)) == 1)
        assert _jobs_for(no_idle_acc_id, no_idle_inbox_id) == []

        # 2. Remove first catchup job, force socket drop, verify reconnect + catchup delta job!
        with Session() as session:
            job = session.scalar(
                select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{drop_acc_id}:{drop_inbox_id}")
            )
            assert job is not None
            session.delete(job)
            session.commit()
        assert _jobs_for(drop_acc_id, drop_inbox_id) == []

        drop_trigger.set()
        assert _wait_until(lambda: srv_drop.connect_count >= 2, timeout_s=5.0)
        assert _wait_until(lambda: len(_jobs_for(drop_acc_id, drop_inbox_id)) == 1, timeout_s=5.0)
        assert _wait_until(lambda: manager.held_account_ids() == {drop_acc_id})

        # 3. Periodic polling covers acc_no_idle (fallback) while skipping held acc_drop.
        with Session() as session:
            enqueued = schedule_periodic_inbox_sync(
                session,
                idle_held_account_ids=manager.held_account_ids(),
                poll_interval_s=60.0,
                now=datetime.now(timezone.utc),
            )
            session.commit()
        assert enqueued == 1
        no_idle_jobs = _jobs_for(no_idle_acc_id, no_idle_inbox_id)
        assert len(no_idle_jobs) == 1
        assert no_idle_jobs[0].priority == 75

        # Even with its catchup job cleared, held acc_drop is skipped by polling.
        with Session() as session:
            drop_job = session.scalar(
                select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{drop_acc_id}:{drop_inbox_id}")
            )
            assert drop_job is not None and drop_job.priority == 60
            session.delete(drop_job)
            session.commit()
        with Session() as session:
            skipped_while_held = schedule_periodic_inbox_sync(
                session,
                idle_held_account_ids=manager.held_account_ids(),
                poll_interval_s=60.0,
                now=datetime.now(timezone.utc),
            )
            session.commit()
        assert skipped_while_held == 0
        assert _jobs_for(drop_acc_id, drop_inbox_id) == []

        watchers, readers = _live_idle_threads()
        assert len(watchers) == 1 and len(readers) == 1
    finally:
        drop_trigger.set()
        manager.stop()

    # 4. Cancel / stop cleans up every watcher & reader thread and polling resumes for acc_drop.
    assert _wait_until(lambda: _live_idle_threads() == ([], []))
    assert manager.held_account_ids() == set()
    with Session() as session:
        resumed_enqueued = schedule_periodic_inbox_sync(
            session,
            idle_held_account_ids=manager.held_account_ids(),
            poll_interval_s=60.0,
            now=datetime.now(timezone.utc),
        )
        session.commit()
    assert resumed_enqueued == 1
    assert len(_jobs_for(drop_acc_id, drop_inbox_id)) == 1
