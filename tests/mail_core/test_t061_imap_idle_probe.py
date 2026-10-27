"""t061 provider-level tests: IMAP STATUS probe + IDLE watch session.

Runs against a minimal in-process fake IMAP server over a real socket
(no Docker, no external service). The server behaviours mirror the
t061 spike findings.
"""

from __future__ import annotations

import socketserver
import threading
import time

import pytest

from mail_core.providers.base import FolderStatus, IdleNotSupportedError
from mail_core.providers.imap import (
    IdleSessionDisconnected,
    ImapProvider,
    _parse_status_items,
)


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self) -> None:
        server = self.server  # type: ignore[attr-defined]
        self._send("* OK Fake IMAP ready")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").strip()
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            tag, cmd = parts[0], parts[1].upper()
            rest = parts[2] if len(parts) > 2 else ""
            if cmd == "CAPABILITY":
                caps = "IMAP4rev1 CONDSTORE" if server.no_idle else "IMAP4rev1 IDLE CONDSTORE"
                self._send(f"* CAPABILITY {caps}")
                self._send(f"{tag} OK CAPABILITY completed")
            elif cmd == "LOGIN":
                self._send(f"{tag} OK LOGIN completed")
            elif cmd == "ID":
                self._send(f"{tag} OK ID completed")
            elif cmd in ("SELECT", "EXAMINE"):
                self._send("* 2 EXISTS")
                self._send("* OK [UIDVALIDITY 12345] UIDs valid")
                self._send("* OK [UIDNEXT 3] Predicted next UID")
                self._send(f"{tag} OK [READ-WRITE] SELECT completed")
            elif cmd == "STATUS":
                folder = rest.split(" ")[0].strip('"')
                if server.status_mode == "missing_uidnext":
                    self._send(f"* STATUS {folder} (MESSAGES 4 UNSEEN 2)")
                elif server.status_mode == "garbage":
                    self._send(f"* STATUS {folder} ()")
                else:
                    self._send(
                        f"* STATUS {folder} (MESSAGES {server.message_count} "
                        f"UIDNEXT {server.uidnext} UNSEEN {server.unseen} HIGHESTMODSEQ 77)"
                    )
                self._send(f"{tag} OK STATUS completed")
            elif cmd == "IDLE":
                self._send("+ idling")
                if server.idle_mode == "push":

                    def _push() -> None:
                        time.sleep(0.2)
                        try:
                            self._send("* 3 EXISTS")
                        except OSError:
                            pass

                    threading.Thread(target=_push, daemon=True).start()
                elif server.idle_mode == "drop":
                    time.sleep(0.2)
                    self.connection.close()
                    return
                done = self.rfile.readline()
                if not done:
                    return
                self._send(f"{tag} OK IDLE terminated")
            elif cmd == "LOGOUT":
                self._send("* BYE logging out")
                self._send(f"{tag} OK LOGOUT completed")
                return
            else:
                self._send(f"{tag} BAD unknown command")


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *, idle_mode="silent", status_mode="full", no_idle=False):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.idle_mode = idle_mode
        self.status_mode = status_mode
        self.no_idle = no_idle
        self.message_count = 2
        self.uidnext = 3
        self.unseen = 1


@pytest.fixture()
def fake_server(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    servers: list[_Server] = []

    def _make(**kwargs) -> tuple[_Server, ImapProvider]:
        server = _Server(**kwargs)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        provider = ImapProvider(
            host="127.0.0.1",
            port=port,
            username="user@example.com",
            password="secret",
            use_ssl=False,
            timeout=10.0,
            permit_factory=None,
        )
        return server, provider

    yield _make
    for server in servers:
        server.shutdown()


def test_parse_status_items_full_and_missing():
    full = _parse_status_items([b"INBOX (MESSAGES 3 UIDNEXT 9 UNSEEN 1 HIGHESTMODSEQ 77)"])
    assert full == FolderStatus(messages=3, uidnext=9, unseen=1, highestmodseq=77)
    missing = _parse_status_items([b"INBOX (MESSAGES 3 UNSEEN 1)"])
    assert missing is not None
    assert missing.uidnext is None and missing.highestmodseq is None
    assert missing.messages == 3 and missing.unseen == 1
    assert _parse_status_items([b"INBOX ()"]) is None
    assert _parse_status_items([]) is None
    assert _parse_status_items(None) is None


def test_probe_folder_status_full(fake_server):
    _server, provider = fake_server()
    status = provider.probe_folder_status("INBOX")
    assert status == FolderStatus(messages=2, uidnext=3, unseen=1, highestmodseq=77)


def test_probe_folder_status_missing_uidnext(fake_server):
    _server, provider = fake_server(status_mode="missing_uidnext")
    status = provider.probe_folder_status("INBOX")
    assert status is not None
    assert status.messages == 4 and status.unseen == 2
    assert status.uidnext is None and status.highestmodseq is None


def test_probe_folder_status_garbage_returns_none(fake_server):
    _server, provider = fake_server(status_mode="garbage")
    assert provider.probe_folder_status("INBOX") is None


def test_idle_session_change_push(fake_server):
    _server, provider = fake_server(idle_mode="push")
    session = provider.open_idle_session("INBOX")
    try:
        outcome = session.wait_for_change(timeout_s=5, stop_event=threading.Event())
        assert outcome == "changed"
    finally:
        session.close()


def test_idle_session_stop_event(fake_server):
    _server, provider = fake_server(idle_mode="silent")
    session = provider.open_idle_session("INBOX")
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    try:
        started = time.monotonic()
        outcome = session.wait_for_change(timeout_s=30, stop_event=stop)
        assert outcome == "stopped"
        assert time.monotonic() - started < 3
    finally:
        session.close()


def test_idle_session_timeout_reentry(fake_server):
    _server, provider = fake_server(idle_mode="silent")
    session = provider.open_idle_session("INBOX")
    try:
        for _ in range(2):
            outcome = session.wait_for_change(timeout_s=0.6, stop_event=threading.Event())
            assert outcome == "timeout"
    finally:
        session.close()


def test_idle_session_drop_detected(fake_server):
    _server, provider = fake_server(idle_mode="drop")
    session = provider.open_idle_session("INBOX")
    try:
        with pytest.raises(IdleSessionDisconnected):
            session.wait_for_change(timeout_s=5, stop_event=threading.Event())
    finally:
        session.close()


def test_idle_not_supported_without_capability(fake_server):
    _server, provider = fake_server(no_idle=True)
    with pytest.raises(IdleNotSupportedError):
        provider.open_idle_session("INBOX")


class _CountingPermit:
    def __init__(self, factory: "_CountingPermitFactory"):
        self._factory = factory

    def release(self) -> None:
        self._factory.released += 1


class _CountingPermitFactory:
    """Permit factory double recording connection-slot acquisitions."""

    def __init__(self):
        self.acquired = 0
        self.released = 0

    def acquire(self, traffic_class):  # noqa: ANN001, ANN202
        self.acquired += 1
        return _CountingPermit(self)


def test_idle_session_uses_no_task_slot_but_probe_does(monkeypatch):
    """AC-005 two-pool separation (test f003): opening an IDLE session
    must acquire zero connection-slot permits; a STATUS probe (a
    transient task connection) acquires exactly one."""
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    server = _Server(idle_mode="silent")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    permits = _CountingPermitFactory()
    provider = ImapProvider(
        host="127.0.0.1",
        port=server.server_address[1],
        username="user@example.com",
        password="secret",
        use_ssl=False,
        timeout=10.0,
        permit_factory=permits,
    )
    try:
        session = provider.open_idle_session("INBOX")
        try:
            assert permits.acquired == 0
        finally:
            session.close()
        status = provider.probe_folder_status("INBOX")
        assert status is not None
        assert permits.acquired == 1
    finally:
        server.shutdown()
