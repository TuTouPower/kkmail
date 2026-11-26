"""Regression invariants, protocol surface, and AST complexity tests for t093."""

from __future__ import annotations

import ast
import imaplib
import os
import pathlib
import socket
import typing
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, update

import mail_core.sync.remote_push as remote_push_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ExecutionOrigin, RemoteOperationStatus
from mail_core.mail.domain.failures import FailurePhase, StructuredFailure, failure_phase_of
from mail_core.mail.storage.models import Account, AccountSyncLease, Message, RemoteOperation, WorkerJob
from mail_core.net.bulkhead import EndpointCircuitOpenError
from mail_core.providers.base import (
    IdleNotSupportedError,
    MailProvider,
    RateLimitHint,
    RemoteOperationItem,
    RemoteOperationResult,
)
from mail_core.providers.http import RateLimitedError
from mail_core.providers.imap import ImapProvider, format_imap_remote_id
from mail_core.sync.leases import acquire_lease
from mail_core.sync.remote_push_errors import get_retry_after_seconds
from mail_core.sync.remote_push_move import RemoteIdentityConflict, persist_move_remote_state

ROOT = pathlib.Path(__file__).resolve().parents[2]
pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _cyclomatic_complexity(node: ast.AST) -> int:
    c = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp),
        ):
            c += 1
        elif isinstance(child, ast.BoolOp):
            c += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            c += 1 + len(child.ifs)
    return c


def test_t093_complexity_budget_under_15():
    """AC-001/002/003: split modules and refactored ImapProvider methods stay below CC 15 and inside class."""
    imap_path = ROOT / "src/mail_core/providers/imap.py"
    imap_tree = ast.parse(imap_path.read_text(encoding="utf-8"))
    imap_cls = next(
        node for node in imap_tree.body if isinstance(node, ast.ClassDef) and node.name == "ImapProvider"
    )
    class_methods = {
        node.name: node for node in imap_cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module_funcs = {
        node.name: node for node in imap_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for required_method in ("apply_remote_operations", "open_idle_session", "rate_limit_hint"):
        assert required_method in class_methods, f"{required_method} missing from class ImapProvider"
        cc = _cyclomatic_complexity(class_methods[required_method])
        assert cc < 15, f"ImapProvider.{required_method} has CC={cc} (>= 15)"
    for helper in ("_collect_imap_capabilities", "_open_idle_mailbox", "_cleanup_failed_idle_client"):
        assert helper in module_funcs, f"{helper} missing from imap.py module top level"
        cc = _cyclomatic_complexity(module_funcs[helper])
        assert cc < 15, f"imap.py:{helper} has CC={cc} (>= 15)"

    for rel_path in (
        "src/mail_core/providers/imap_wire.py",
        "src/mail_core/providers/imap_writeback.py",
        "src/mail_core/sync/remote_push.py",
        "src/mail_core/sync/remote_push_errors.py",
        "src/mail_core/sync/remote_push_move.py",
    ):
        path = ROOT / rel_path
        assert path.is_file(), f"missing refactored module: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cc = _cyclomatic_complexity(node)
                assert cc < 15, f"{path.name}:{node.name} has CC={cc} (>= 15)"


def test_t093_imap_provider_public_surface_contract():
    """AC-004: ImapProvider preserves every MailProvider method including rate_limit_hint."""
    provider = ImapProvider("imap.example.com", 993, "acc@example.com", "pw", use_ssl=False)
    for member in typing.get_protocol_members(MailProvider):
        assert hasattr(ImapProvider, member), f"ImapProvider missing MailProvider member {member}"
        assert callable(getattr(provider, member))
    hint = provider.rate_limit_hint()
    assert hint == RateLimitHint(max_requests_per_minute=120, reason="imap default")


def _fake_provider_with(client):
    provider = ImapProvider("imap.example.com", 993, "acc@example.com", "pw", use_ssl=False)
    provider._connect_with_permit = lambda: (client, None)
    provider._close_client = lambda _c, _p: None
    return provider


def test_t093_imap_writeback_flag_symmetry_validation_and_exception_boundaries():
    """AC-001: validation, symmetric Seen/Flagged STORE+FETCH fallback, failures, and exception rules."""

    class _ImapClient:
        def __init__(self) -> None:
            self.fail_seen_store = False
            self.fail_flagged_store = False
            self.fail_select_folders: set[str] = set()
            self.raise_on_folder: dict[str, Exception] = {}

        def select(self, mailbox: str):
            clean = mailbox.strip('"')
            if clean in self.raise_on_folder:
                raise self.raise_on_folder[clean]
            if clean in self.fail_select_folders:
                return "NO", [b"select denied"]
            return "OK", [b"10"]

        def status(self, mailbox: str, _names: str):
            clean = mailbox.strip('"')
            return "OK", [f'"{clean}" (UIDVALIDITY 10)'.encode()]

        def uid(self, cmd: str, *args: str):
            if cmd == "STORE":
                _uid_set, flag_op, flag_val = args
                if "\\Seen" in flag_val:
                    if self.fail_seen_store:
                        return "NO", [b"store seen denied"]
                    # Omit untagged FLAGS on STORE to force FETCH fallback
                    return "OK", []
                if "\\Flagged" in flag_val:
                    if self.fail_flagged_store:
                        return "NO", [b"store flagged denied"]
                    if flag_op == "-FLAGS":
                        return "OK", [(b"1 (UID 13 FLAGS (\\Seen))", b"")]
                    return "OK", [(b"1 (UID 11 FLAGS (\\Flagged))", b"")]
            if cmd == "FETCH":
                uid_set = args[0]
                if uid_set in ("1", "1:3"):
                    return "OK", [(b"1 (UID 1 FLAGS (\\Seen))", b""), (b"2 (UID 2 FLAGS ())", b"")]
                if uid_set in ("11:12", "12"):
                    return "OK", []
                if uid_set == "21:22":
                    return "OK", [(b"1 (UID 21 FLAGS (\\Seen))", b"")]
            if cmd == "MOVE":
                return "OK", [b"[COPYUID 22 21 901]"]
            return "NO", []

        def response(self, _name: str):
            return "NO", []

    connect_calls = 0

    def _counting_connect():
        nonlocal connect_calls
        connect_calls += 1
        return client, None

    client = _ImapClient()
    provider = _fake_provider_with(client)
    provider._connect_with_permit = _counting_connect

    assert provider.apply_remote_operations([]) == []
    only_invalid_id = uuid.uuid4()
    invalid_only = dict(provider.apply_remote_operations([RemoteOperationItem(only_invalid_id, "mark_read", {})]))
    assert invalid_only[only_invalid_id].error == "missing remote_id"
    assert connect_calls == 0

    ids = [uuid.uuid4() for _ in range(12)]
    ops = [
        RemoteOperationItem(ids[0], "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 1), "folder_remote_id": "Other", "is_read": True}),
        RemoteOperationItem(ids[1], "mark_read", {"remote_id": "INBOX:bad:uid", "folder_remote_id": "INBOX", "is_read": True}),
        RemoteOperationItem(ids[2], "move", {"remote_id": format_imap_remote_id("INBOX", 10, 5), "folder_remote_id": "INBOX"}),
        RemoteOperationItem(ids[3], "move", {"remote_id": format_imap_remote_id("INBOX", 10, 5), "folder_remote_id": "INBOX", "dest_folder_remote_id": "Bad\nName"}),
        RemoteOperationItem(ids[4], "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 1), "is_read": True}),
        RemoteOperationItem(ids[5], "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 2), "is_read": True}),
        RemoteOperationItem(ids[6], "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 3), "is_read": True}),
        RemoteOperationItem(ids[7], "set_flag", {"remote_id": format_imap_remote_id("INBOX", 10, 11), "is_flagged": True}),
        RemoteOperationItem(ids[8], "set_flag", {"remote_id": format_imap_remote_id("INBOX", 10, 12), "is_flagged": True}),
        RemoteOperationItem(ids[9], "set_flag", {"remote_id": format_imap_remote_id("INBOX", 10, 13), "is_flagged": False}),
        RemoteOperationItem(ids[10], "move", {"remote_id": format_imap_remote_id("INBOX", 10, 21), "dest_folder_remote_id": "Archive"}),
        RemoteOperationItem(ids[11], "move", {"remote_id": format_imap_remote_id("INBOX", 10, 22), "dest_folder_remote_id": "Archive"}),
    ]
    res = dict(provider.apply_remote_operations(ops))
    assert "does not match" in str(res[ids[0]].error)
    assert "invalid numeric UID" in str(res[ids[1]].error)
    assert res[ids[2]].error == "missing dest_folder_remote_id"
    assert "control characters" in str(res[ids[3]].error)
    assert res[ids[4]].success is True and res[ids[4]].remote_state == {"is_read": True}
    assert "STORE Seen for UID 2" in str(res[ids[5]].error)
    assert "UID 3 not found" in str(res[ids[6]].error)
    assert res[ids[7]].success is True and res[ids[7]].remote_state == {"is_flagged": True}
    assert "UID 12 not found" in str(res[ids[8]].error)
    assert res[ids[9]].success is True and res[ids[9]].remote_state == {"is_flagged": False}
    assert res[ids[10]].success is True and res[ids[10]].remote_state["uid"] == 901
    assert "UID 22 not found" in str(res[ids[11]].error)

    # STORE NO failure for Seen and Flagged + SELECT NO failure
    client.fail_seen_store = True
    client.fail_flagged_store = True
    client.fail_select_folders = {"BadSelect"}
    id_s, id_f, id_sel = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fail_res = dict(
        provider.apply_remote_operations([
            RemoteOperationItem(id_s, "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 1), "is_read": True}),
            RemoteOperationItem(id_f, "set_flag", {"remote_id": format_imap_remote_id("INBOX", 10, 11), "is_flagged": True}),
            RemoteOperationItem(id_sel, "mark_read", {"remote_id": format_imap_remote_id("BadSelect", 10, 1), "is_read": True}),
        ])
    )
    assert fail_res[id_s].error == "STORE Seen failed"
    assert fail_res[id_f].error == "STORE Flagged failed"
    assert fail_res[id_sel].error == "select BadSelect failed"
    client.fail_seen_store = False
    client.fail_flagged_store = False
    client.fail_select_folders.clear()

    # Non-transport RuntimeError on untouched batch is converted to per-item StructuredFailure
    client.raise_on_folder["INBOX"] = RuntimeError("unexpected bug")
    non_transport = dict(provider.apply_remote_operations([ops[4]]))
    assert non_transport[ids[4]].success is False
    assert isinstance(non_transport[ids[4]].failure, StructuredFailure)

    # Transport/IMAP4 error with no prior success re-raises
    client.raise_on_folder["INBOX"] = imaplib.IMAP4.error("session dropped")
    with pytest.raises(imaplib.IMAP4.error):
        provider.apply_remote_operations([ops[4]])

    # Prior success isolates subsequent folder IMAP4 error with StructuredFailure
    client.raise_on_folder = {"FailBox": imaplib.IMAP4.error("second folder boom")}
    id_ok, id_fail = uuid.uuid4(), uuid.uuid4()
    mixed = dict(
        provider.apply_remote_operations([
            RemoteOperationItem(id_ok, "mark_read", {"remote_id": format_imap_remote_id("INBOX", 10, 1), "is_read": True}),
            RemoteOperationItem(id_fail, "mark_read", {"remote_id": format_imap_remote_id("FailBox", 10, 2), "is_read": True}),
        ])
    )
    assert mixed[id_ok].success is True
    assert mixed[id_fail].success is False
    assert isinstance(mixed[id_fail].failure, StructuredFailure)

    # Capacity error re-raises even when earlier folder succeeded
    client.raise_on_folder = {
        "FailBox": EndpointCircuitOpenError("open", endpoint=("direct", "imap.example.com", 993), retry_after_s=10.0)
    }
    with pytest.raises(EndpointCircuitOpenError):
        provider.apply_remote_operations([ops[4], RemoteOperationItem(id_fail, "mark_read", {"remote_id": format_imap_remote_id("FailBox", 10, 2), "is_read": True})])


def test_t093_open_idle_session_success_attribution_and_cleanup():
    """AC-002: readonly SELECT, capability() fallback, real socket settimeout(None), error phase, and close."""
    timeouts: list[float | None] = []
    sock_closed: list[bool] = []

    class _Sock:
        def settimeout(self, val):
            timeouts.append(val)

        def shutdown(self, _how):
            pass

        def close(self):
            sock_closed.append(True)

    # 1. Success via capability() only + verify readonly=True and settimeout(None)
    client_cap = MagicMock()
    client_cap.capabilities = ()
    client_cap.capability.return_value = ("OK", [b"IMAP4rev1 IDLE"])
    client_cap.select.return_value = ("OK", [b"1"])
    client_cap.readline.return_value = b""
    client_cap.sock = _Sock()
    provider = ImapProvider("imap.example.com", 993, "acc@example.com", "pw", use_ssl=False)
    provider._connect = lambda: client_cap
    idle_sess = provider.open_idle_session("Sent Messages")
    try:
        assert idle_sess._client is client_cap
        client_cap.select.assert_called_once_with('"Sent Messages"', readonly=True)
        assert timeouts == [None]
    finally:
        idle_sess.close()
        idle_sess._reader.join(timeout=1.0)

    # 2. Success with capability() raising while handshake advertised IDLE + real OS socket timeout cleared
    timeouts.clear()
    real_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    idle_sess_real = None
    try:
        real_sock.settimeout(2.5)
        assert real_sock.gettimeout() == 2.5
        client_real = MagicMock()
        client_real.capabilities = ("IMAP4rev1", "IDLE")
        client_real.capability.side_effect = RuntimeError("cap failed")
        client_real.select.return_value = ("OK", [b"1"])
        client_real.readline.return_value = b""
        client_real.sock = real_sock
        provider._connect = lambda: client_real
        idle_sess_real = provider.open_idle_session("INBOX")
        client_real.select.assert_called_once_with("INBOX", readonly=True)
        assert real_sock.gettimeout() is None
    finally:
        if idle_sess_real is not None:
            idle_sess_real.close()
            idle_sess_real._reader.join(timeout=1.0)
        real_sock.close()

    # 3. Failing select triggers IdleNotSupportedError with FailurePhase.IMAP + socket close
    sock_closed.clear()
    client1 = MagicMock()
    client1.capabilities = ("IMAP4rev1", "IDLE")
    client1.capability.return_value = ("OK", [b"IMAP4rev1 IDLE"])
    client1.select.return_value = ("NO", [b"missing"])
    client1.sock = _Sock()
    provider._connect = lambda: client1
    with pytest.raises(IdleNotSupportedError) as exc1:
        provider.open_idle_session("INBOX")
    assert failure_phase_of(exc1.value) is FailurePhase.IMAP
    assert sock_closed == [True]

    # 4. Capacity error bypasses FailurePhase.IMAP attachment and still closes socket
    sock_closed.clear()
    client2 = MagicMock()
    client2.capabilities = ("IMAP4rev1", "IDLE")
    client2.capability.return_value = ("OK", [b"IMAP4rev1 IDLE"])
    client2.select.side_effect = EndpointCircuitOpenError("open", endpoint=("direct", "imap.example.com", 993), retry_after_s=5.0)
    client2.sock = _Sock()
    provider._connect = lambda: client2
    with pytest.raises(EndpointCircuitOpenError) as exc2:
        provider.open_idle_session("INBOX")
    assert failure_phase_of(exc2.value) is None
    assert sock_closed == [True]


def test_t093_get_retry_after_seconds_bounds_and_fallback():
    """AC-003: get_retry_after_seconds extracts positive numeric hints and clamps [1, 86400]."""
    assert get_retry_after_seconds(None, fallback=30.0) == 30.0
    assert get_retry_after_seconds(None, fallback=0.1) == 1.0
    assert get_retry_after_seconds(RateLimitedError("rl", retry_after_seconds=42.5)) == 42.5
    assert get_retry_after_seconds(RateLimitedError("rl", retry_after_seconds=0.2)) == 1.0
    assert get_retry_after_seconds(RateLimitedError("rl", retry_after_seconds=200000.0)) == 86400.0
    assert get_retry_after_seconds(RateLimitedError("rl", retry_after_seconds=0)) == 60.0
    bad = type("_Bad", (Exception,), {"retry_after_seconds": "not-a-number"})()
    assert get_retry_after_seconds(bad, fallback=15.0) == 15.0


@pytestmark_db
def test_t093_remote_push_cas_and_identity_conflicts(monkeypatch):
    """AC-003: CAS conflict resets PENDING with BACKGROUND followup; duplicate ID and missing COPYUID fail cleanly."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = Account(email=f"t093-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        session.add(acc)
        session.flush()
        msg_src = Message(account_id=acc.id, remote_id="rid-src", subject="Src", sort_time=now)
        msg_dup = Message(account_id=acc.id, remote_id="rid-taken", subject="Taken", sort_time=now)
        msg_nocopyuid = Message(account_id=acc.id, remote_id="rid-nocopyuid", subject="NoCopyUid", sort_time=now)
        session.add_all([msg_src, msg_dup, msg_nocopyuid])
        op_cas = RemoteOperation(
            account_id=acc.id,
            entity_key="msg:cas-1:read",
            op_type="mark_read",
            desired_state={"remote_id": "cas-1", "is_read": True, "revision": 1},
            status="pending",
        )
        op_conflict = RemoteOperation(
            account_id=acc.id,
            entity_key="msg:rid-src:move",
            op_type="move",
            desired_state={"remote_id": "rid-src", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
            status="pending",
        )
        op_missing_copyuid = RemoteOperation(
            account_id=acc.id,
            entity_key="msg:rid-nocopyuid:move",
            op_type="move",
            desired_state={"remote_id": "rid-nocopyuid", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
            status="pending",
        )
        session.add_all([op_cas, op_conflict, op_missing_copyuid])
        session.commit()
        aid, cas_id, conflict_id, nocopyuid_id, nocopy_msg_id = (
            acc.id,
            op_cas.id,
            op_conflict.id,
            op_missing_copyuid.id,
            msg_nocopyuid.id,
        )

    def _apply_and_race(items):
        with Session() as race_sess:
            row = race_sess.get(RemoteOperation, cas_id)
            row.desired_state = {"remote_id": "cas-1", "is_read": False, "revision": 2}
            race_sess.commit()
        out = []
        for it in items:
            if it.op_id == cas_id:
                out.append((it.op_id, RemoteOperationResult(success=True)))
            elif it.op_id == conflict_id:
                out.append((it.op_id, RemoteOperationResult(success=True, remote_state={"folder_remote_id": "Archive", "remote_id": "rid-taken"})))
            else:
                out.append((it.op_id, RemoteOperationResult(success=True, remote_state={"folder_remote_id": "Archive"})))
        return out

    monkeypatch.setattr(
        remote_push_mod,
        "build_provider",
        lambda *_a, **_k: type("_RaceP", (), {"apply_remote_operations": staticmethod(_apply_and_race)})(),
    )
    res = remote_push_mod.push_remote_operations(aid, worker_id="w-cas", execution_origin=ExecutionOrigin.BACKGROUND)
    assert res == {"status": "ok", "pushed": 0, "failed": 2}

    with Session() as session:
        refreshed_cas = session.get(RemoteOperation, cas_id)
        refreshed_conflict = session.get(RemoteOperation, conflict_id)
        refreshed_nocopy = session.get(RemoteOperation, nocopyuid_id)
        assert refreshed_cas.status == RemoteOperationStatus.PENDING.value
        assert refreshed_conflict.status == RemoteOperationStatus.FAILED.value
        assert "RemoteIdentityConflict" in str(refreshed_conflict.last_error)
        assert refreshed_nocopy.status == RemoteOperationStatus.FAILED.value
        assert "RemoteIdentityConflict" in str(refreshed_nocopy.last_error)
        assert session.get(Message, nocopy_msg_id).remote_id == "rid-nocopyuid"
        followup = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"remote-op-push:{aid}"))
        assert followup is not None and followup.execution_origin == ExecutionOrigin.BACKGROUND.value
        with pytest.raises(RemoteIdentityConflict, match="COPYUID"):
            persist_move_remote_state(
                session,
                account_id=aid,
                provider_type="imap",
                op_type="move",
                desired_state={"remote_id": "rid-nocopyuid", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
                remote_state={"folder_remote_id": "Archive"},
            )
        session.rollback()


@pytestmark_db
def test_t093_remote_push_lease_busy_returns_without_mutating_ops():
    """AC-003: active lease held by another worker yields lease_busy without touching PENDING ops."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"t093-busy-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        session.add(acc)
        session.flush()
        op = RemoteOperation(
            account_id=acc.id,
            entity_key="msg:busy-1:read",
            op_type="mark_read",
            desired_state={"remote_id": "busy-1", "is_read": True},
            status="pending",
        )
        session.add(op)
        acquire_lease(session, account_id=acc.id, owner_id="w-holder")
        session.commit()
        aid, oid = acc.id, op.id

    res = remote_push_mod.push_remote_operations(aid, worker_id="w-challenger", execution_origin="foreground")
    assert res == {"status": "lease_busy"}
    with Session() as session:
        row = session.get(RemoteOperation, oid)
        assert row.status == RemoteOperationStatus.PENDING.value
        assert row.attempts == 0


@pytestmark_db
def test_t093_remote_push_chunk_heartbeat_fencing_break(monkeypatch):
    """AC-003: FencingMismatch in chunk heartbeat stops subsequent chunks and leaves IN_PROGRESS."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"t093-hb-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        session.add(acc)
        session.flush()
        ops = [
            RemoteOperation(
                account_id=acc.id,
                entity_key=f"msg:chunk-{idx}:read",
                op_type="mark_read",
                desired_state={"remote_id": f"chunk-{idx}", "is_read": True},
                status="pending",
            )
            for idx in range(105)
        ]
        session.add_all(ops)
        session.commit()
        op_ids = [op.id for op in ops]
        aid = acc.id

    chunks_seen: list[int] = []

    def _apply_and_steal_lease(chunk):
        chunks_seen.append(len(chunk))
        with Session() as steal_sess:
            steal_sess.execute(
                update(AccountSyncLease)
                .where(AccountSyncLease.account_id == aid)
                .values(fencing_token=AccountSyncLease.fencing_token + 1)
            )
            steal_sess.commit()
        return [(it.op_id, RemoteOperationResult(success=True)) for it in chunk]

    monkeypatch.setattr(
        remote_push_mod,
        "build_provider",
        lambda *_a, **_k: type("_ChunkP", (), {"apply_remote_operations": staticmethod(_apply_and_steal_lease)})(),
    )
    res = remote_push_mod.push_remote_operations(aid, worker_id="w-chunk", execution_origin="foreground")
    assert res == {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
    assert chunks_seen == [100]
    with Session() as session:
        statuses = {row.status for row in session.scalars(select(RemoteOperation).where(RemoteOperation.id.in_(op_ids))).all()}
        assert statuses == {RemoteOperationStatus.IN_PROGRESS.value}


@pytestmark_db
def test_t093_remote_push_claim_and_capacity_fencing_mismatch(monkeypatch):
    """AC-003: FencingMismatch during claim assert/heartbeat or capacity defer returns fencing_mismatch safely."""
    Session = get_session_factory()
    with Session() as session:
        acc1 = Account(email=f"t093-c1-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        acc2 = Account(email=f"t093-c2-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        acc3 = Account(email=f"t093-c3-{uuid.uuid4().hex[:8]}@example.test", provider="imap", config={}, sync_enabled=True)
        session.add_all([acc1, acc2, acc3])
        session.flush()
        op1 = RemoteOperation(
            account_id=acc1.id, entity_key="msg:cap-f:read", op_type="mark_read",
            desired_state={"remote_id": "cap-f", "is_read": True}, status="pending",
        )
        op2 = RemoteOperation(
            account_id=acc2.id, entity_key="msg:clm-f:read", op_type="mark_read",
            desired_state={"remote_id": "clm-f", "is_read": True}, status="pending",
        )
        op3 = RemoteOperation(
            account_id=acc3.id, entity_key="msg:clm-exp:read", op_type="mark_read",
            desired_state={"remote_id": "clm-exp", "is_read": True}, status="pending",
        )
        session.add_all([op1, op2, op3])
        session.commit()
        aid1, oid1, aid2, oid2, aid3, oid3 = acc1.id, op1.id, acc2.id, op2.id, acc3.id, op3.id

    def _build_steal_and_capacity_err(*_a, **_k):
        with Session() as steal_sess:
            steal_sess.execute(
                update(AccountSyncLease)
                .where(AccountSyncLease.account_id == aid1)
                .values(fencing_token=AccountSyncLease.fencing_token + 1)
            )
            steal_sess.commit()
        raise EndpointCircuitOpenError("open", endpoint=("direct", "imap.example.com", 993), retry_after_s=5.0)

    monkeypatch.setattr(remote_push_mod, "build_provider", _build_steal_and_capacity_err)
    res1 = remote_push_mod.push_remote_operations(aid1, worker_id="w-cap", execution_origin="foreground")
    assert res1 == {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
    with Session() as session:
        assert session.get(RemoteOperation, oid1).status == RemoteOperationStatus.IN_PROGRESS.value

    real_mark = remote_push_mod.mark_remote_operation

    def _mark_and_bump_same_session(sess, op_row, **kwargs):
        out = real_mark(sess, op_row, **kwargs)
        # Modify the locked lease row in the same uncommitted TX so heartbeat_lease fails cleanly without deadlock.
        sess.execute(
            update(AccountSyncLease)
            .where(AccountSyncLease.account_id == aid2)
            .values(fencing_token=AccountSyncLease.fencing_token + 1)
        )
        return out

    monkeypatch.setattr(remote_push_mod, "mark_remote_operation", _mark_and_bump_same_session)
    res2 = remote_push_mod.push_remote_operations(aid2, worker_id="w-claim", execution_origin="foreground")
    assert res2 == {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
    with Session() as session:
        assert session.get(RemoteOperation, oid2).status == RemoteOperationStatus.PENDING.value

    # Expired lease TTL triggers assert_fencing FencingMismatch at start of claim TX
    monkeypatch.setattr(remote_push_mod, "mark_remote_operation", real_mark)
    res3 = remote_push_mod.push_remote_operations(
        aid3, worker_id="w-exp", execution_origin="foreground", lease_ttl=timedelta(seconds=-1)
    )
    assert res3 == {"status": "fencing_mismatch", "pushed": 0, "failed": 0}
    with Session() as session:
        assert session.get(RemoteOperation, oid3).status == RemoteOperationStatus.PENDING.value
