"""Integration tests for the global provider connection budget (R11 / §7).

These tests exercise the *real* provider / transport call paths — IMAP
provider methods, Graph HTTP requests, the OAuth Bearer transport,
and the stdlib urllib transport against a local HTTP server — with a
counting permit factory at the boundary.  Helper-only tests live in
``test_provider_connection_slots.py`` and do not count as integration
evidence for this package.

The multi-process PostgreSQL test at the bottom is gated on
``MAIL_CORE_DATABASE_URL`` (dedicated control connections); in unit mode
it skips and the in-process factory verifies the same 8/6 accounting.
"""

from __future__ import annotations

import imaplib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from mail_core.providers.connection_slots import (
    TOTAL_SLOTS,
    InMemoryPermitFactory,
    ProviderCapacityUnavailable,
    ProviderControlError,
    TrafficClass,
    traffic_class_for_job,
)
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider, format_imap_remote_id


@pytest.fixture()
def factory():
    f = InMemoryPermitFactory()
    f.reset()
    yield f
    f.reset()


class _CountingIMAP:
    """Fake IMAP endpoint at the imaplib boundary; counts live connections."""

    instances: list["_CountingIMAP"] = []
    live = 0
    peak = 0
    peer_ip = "8.8.8.8"
    login_error: Exception | None = None
    _lock = threading.Lock()

    @classmethod
    def reset(cls):
        with cls._lock:
            cls.instances = []
            cls.live = 0
            cls.peak = 0
            cls.peer_ip = "8.8.8.8"
            cls.login_error = None

    def __init__(self, host, port, timeout=None, ssl_context=None):
        with self._lock:
            type(self).instances.append(self)
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)
        self.sock = SimpleNamespace(
            getpeername=lambda: (type(self).peer_ip, 993),
            close=lambda: None,
        )

    def login(self, *a):
        if type(self).login_error is not None:
            raise type(self).login_error
        return ("OK", [b""])

    def logout(self):
        with type(self)._lock:
            type(self).live -= 1
        return ("OK", [b""])

    def list(self, *a):
        return ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])

    def select(self, *a, **k):
        return ("OK", [b"1"])

    def status(self, *a, **k):
        return ("OK", [b"INBOX (UIDVALIDITY 7)"])

    def uid(self, cmd, *args):
        if cmd == "FETCH":
            return ("OK", [(b"1 (UID 42)", b"mime-bytes")])
        return ("OK", [b""])


@pytest.fixture()
def fake_imap(monkeypatch):
    _CountingIMAP.reset()
    monkeypatch.setattr("mail_core.providers.imap.imaplib.IMAP4_SSL", _CountingIMAP)
    return _CountingIMAP


def _imap_provider(factory, traffic_class=TrafficClass.FOREGROUND):
    return ImapProvider(
        host="imap.test",
        port=993,
        username="u",
        password="p",
        traffic_class=traffic_class,
        permit_factory=factory,
    )


# ---------------------------------------------------------------------------
# IMAP integration
# ---------------------------------------------------------------------------


def test_background_saturation_keeps_reserved_slots_for_foreground(factory, fake_imap):
    held = [factory.acquire(TrafficClass.BACKGROUND) for _ in range(6)]
    try:
        assert factory.snapshot()["current_background"] == 6
        # A 7th background execution cannot even connect: the permit is
        # acquired before the real connection is established.
        with pytest.raises(ProviderCapacityUnavailable):
            _imap_provider(factory, TrafficClass.BACKGROUND).list_folders()
        assert fake_imap.instances == []

        # Foreground still gets a reserved slot (0/1) and connects.
        folders = _imap_provider(factory, TrafficClass.FOREGROUND).list_folders()
        assert [f.remote_id for f in folders] == ["INBOX"]
        assert len(fake_imap.instances) == 1
        # One-shot connection released its permit on logout.
        assert factory.snapshot()["current"] == 6
    finally:
        for permit in held:
            permit.release()
    assert factory.snapshot()["current"] == 0


def test_imap_reused_session_counts_exactly_one_connection(factory, fake_imap):
    provider = _imap_provider(factory)
    provider.open_session()
    try:
        assert factory.snapshot()["current"] == 1
        remote_id = format_imap_remote_id("INBOX", 7, 42)
        for _ in range(3):
            assert provider.fetch_mime(remote_id) == b"mime-bytes"
        # Still one connection, one permit, for the session's lifetime.
        assert len(fake_imap.instances) == 1
        assert factory.snapshot()["current"] == 1
        assert factory.snapshot()["peak"] == 1
    finally:
        provider.close_session()
    assert factory.snapshot()["current"] == 0
    assert fake_imap.live == 0


def test_imap_auth_failure_releases_permit(factory, fake_imap):
    fake_imap.login_error = imaplib.IMAP4.error("NO auth failed")
    with pytest.raises(imaplib.IMAP4.error):
        _imap_provider(factory).list_folders()
    assert len(fake_imap.instances) == 1  # connection was attempted
    assert factory.snapshot()["current"] == 0  # permit released


def test_imap_peer_verification_failure_releases_permit(factory, fake_imap):
    fake_imap.peer_ip = "10.0.0.9"  # private peer: SSRF check must reject
    with pytest.raises(ValueError, match="private or loopback"):
        _imap_provider(factory).list_folders()
    assert factory.snapshot()["current"] == 0


def test_control_failure_stops_imap_before_any_io(factory, fake_imap):
    class BrokenFactory:
        def acquire(self, traffic_class):
            raise ProviderControlError("control connection refused")

    provider = _imap_provider(BrokenFactory())
    with pytest.raises(ProviderControlError):
        provider.list_folders()
    assert fake_imap.instances == []  # no provider I/O was attempted


# ---------------------------------------------------------------------------
# Graph HTTP integration
# ---------------------------------------------------------------------------


def test_http_capacity_shortage_never_reaches_transport(factory):
    held = [factory.acquire(TrafficClass.FOREGROUND) for _ in range(TOTAL_SLOTS)]
    calls = []

    def transport(method, path, params):
        if path == "/me/mailFolders":
            calls.append(path)
            return {"value": []}
        return {}

    provider = GraphProvider(
        credential_ref="cred",
        transport=transport,
        permit_factory=factory,
    )
    try:
        with pytest.raises(ProviderCapacityUnavailable):
            provider.list_folders()
        assert calls == []  # transport never invoked without a permit
    finally:
        held.pop().release()
    assert provider.list_folders() == []
    assert len(calls) == 1
    for permit in held:
        permit.release()
    assert factory.snapshot()["current"] == 0


def test_graph_requests_acquire_and_release_per_call(factory):
    def transport(method, path, params):
        assert factory.snapshot()["current"] == 1  # permit held during I/O
        return {"id": "folder-inbox"}

    provider = GraphProvider(
        credential_ref="cred",
        transport=transport,
        permit_factory=factory,
    )
    provider.list_folders()
    assert factory.snapshot()["current"] == 0
    assert factory.snapshot()["peak"] == 1


def test_concurrent_executions_never_exceed_eight(factory):
    release = threading.Event()
    entered = threading.Semaphore(0)

    def transport(method, path, params):
        entered.release()
        assert release.wait(timeout=10)
        return {"labels": []}

    providers = [
        GraphProvider(credential_ref="c", transport=transport, permit_factory=factory)
        for _ in range(8)
    ]
    threads = [threading.Thread(target=p.list_folders) for p in providers]
    for t in threads:
        t.start()
    for _ in range(8):
        assert entered.acquire(timeout=10)
    assert factory.snapshot()["current"] == 8

    # Ninth concurrent execution (either class) is deferred, not queued
    # past the limit.
    ninth = GraphProvider(credential_ref="c", transport=transport, permit_factory=factory)
    with pytest.raises(ProviderCapacityUnavailable):
        ninth.list_folders()
    background = GraphProvider(
        credential_ref="c",
        transport=transport,
        traffic_class=TrafficClass.BACKGROUND,
        permit_factory=factory,
    )
    with pytest.raises(ProviderCapacityUnavailable):
        background.list_folders()

    release.set()
    for t in threads:
        t.join(timeout=10)
    assert factory.snapshot()["peak"] == 8
    assert factory.snapshot()["current"] == 0


# ---------------------------------------------------------------------------
# OAuth refresh ordering
# ---------------------------------------------------------------------------


def test_oauth_refresh_releases_permit_before_mail_api_call(factory):
    from mail_core.accounts.credentials import DictCredentialStore
    from mail_core.providers.oauth import BearerTransport, OAuthTokenClient

    store = DictCredentialStore(
        {
            "oauth:g": json.dumps(
                {
                    "refresh_token": "rt",
                    "client_id": "cid",
                    "client_secret": "sec",
                    "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                }
            )
        }
    )
    observed = {}

    def token_post(method, url, form, headers):
        # The refresh request itself holds exactly one permit.
        observed["during_refresh"] = factory.snapshot()["current"]
        return {"access_token": "at-1", "expires_in": 3600}

    client = OAuthTokenClient(
        credential_ref="oauth:g",
        store=store,
        provider="graph",
        http_post=token_post,
        permit_factory=factory,
        traffic_class=TrafficClass.FOREGROUND,
    )

    def api(method, url, params, headers):
        # By the time the mail API transport runs, the refresh permit
        # must already be released (no nested slot holding).
        observed["during_api"] = factory.snapshot()["current"]
        return {"ok": True}

    transport = BearerTransport(
        token_client=client, inner=api, base_url="https://graph.microsoft.com"
    )
    assert transport("GET", "/v1.0/me", {}) == {"ok": True}
    assert observed["during_refresh"] == 1
    assert observed["during_api"] == 0
    assert factory.snapshot()["peak"] == 1  # never 2: refresh and API never overlap
    assert factory.snapshot()["current"] == 0


# ---------------------------------------------------------------------------
# Real urllib transport against a local HTTP server (socket boundary)
# ---------------------------------------------------------------------------


def test_urllib_request_releases_permit_during_retry_wait(factory):
    from mail_core.providers.oauth import urllib_json_request

    attempts = {"n": 0}
    server_peak = {"now": 0, "peak": 0}
    server_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            with server_lock:
                server_peak["now"] += 1
                server_peak["peak"] = max(server_peak["peak"], server_peak["now"])
            try:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    body = b"busy"
                    self.send_response(503)
                    self.send_header("Retry-After", "1")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    body = b'{"ok": true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            finally:
                with server_lock:
                    server_peak["now"] -= 1

        def log_message(self, *args):  # keep test output clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sleep_observations = []
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1.0/me/profile"
        result = urllib_json_request(
            "GET",
            url,
            {},
            {},
            timeout=5,
            _sleep_fn=lambda delay: sleep_observations.append(factory.snapshot()["current"]),
            permit_factory=factory,
            traffic_class=TrafficClass.FOREGROUND,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result == {"ok": True}
    assert attempts["n"] == 2
    # The retry wait ran with NO permit held, and each attempt held one.
    assert sleep_observations == [0]
    assert factory.snapshot()["peak"] == 1
    assert factory.snapshot()["current"] == 0
    assert server_peak["peak"] == 1


# ---------------------------------------------------------------------------
# Traffic-class propagation
# ---------------------------------------------------------------------------


def test_traffic_class_derived_from_job_type_and_message_id():
    assert traffic_class_for_job("archive_mime_batch") is TrafficClass.BACKGROUND
    assert traffic_class_for_job("archive_mime_batch", payload={}) is TrafficClass.BACKGROUND
    # On-demand archive (message specified) is foreground.
    assert (
        traffic_class_for_job("archive_mime_batch", payload={"message_id": "m-1"})
        is TrafficClass.FOREGROUND
    )
    assert traffic_class_for_job("archive_mime_batch", message_id="m-1") is TrafficClass.FOREGROUND
    for job_type in (
        "sync_account_folders",
        "sync_folder_metadata",
        "sync_folder_delta",
        "reconcile_folder",
        "remote_operation_push",
    ):
        assert traffic_class_for_job(job_type) is TrafficClass.FOREGROUND


def test_build_provider_propagates_traffic_class_and_factory(factory):
    from mail_core.accounts.credentials import DictCredentialStore
    from mail_core.mail.storage.models import Account
    from mail_core.providers.factory import build_provider

    store = DictCredentialStore({"ref": {"password": "pw"}})
    account = Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref",
        config={"imap_host": "8.8.8.8", "imap_port": 993},
    )
    provider = build_provider(
        account,
        store,
        traffic_class=TrafficClass.BACKGROUND,
        permit_factory=factory,
    )
    assert provider.traffic_class is TrafficClass.BACKGROUND
    assert provider.permit_factory is factory

    graph_store = DictCredentialStore(
        {"g": json.dumps({"refresh_token": "r", "client_id": "c"})}
    )
    graph_account = Account(email="g@b.com", provider="graph", credential_ref="g", config={})
    graph_provider = build_provider(
        graph_account,
        graph_store,
        token_http=lambda *a, **k: {},
        api_http=lambda *a, **k: {},
        traffic_class=TrafficClass.BACKGROUND,
        permit_factory=factory,
    )
    assert graph_provider.traffic_class is TrafficClass.BACKGROUND
    token_client = graph_provider.transport.token_client
    assert token_client.traffic_class is TrafficClass.BACKGROUND
    assert token_client.permit_factory is factory


# ---------------------------------------------------------------------------
# Multi-process accounting against real PostgreSQL (CI / PG-gated)
# ---------------------------------------------------------------------------


def _hold_permits(count: int, traffic: str, ready, release) -> None:
    from mail_core.providers.connection_slots import DedicatedSlotPermitFactory

    factory = DedicatedSlotPermitFactory()
    permits = [factory.acquire(traffic) for _ in range(count)]
    ready.set()
    release.wait(timeout=30)
    for permit in permits:
        permit.release()


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set (multi-process PG budget test)",
)
def test_multiprocess_global_budget_postgres():
    import multiprocessing as mp

    from mail_core.providers.connection_slots import DedicatedSlotPermitFactory

    ctx = mp.get_context("fork")
    ready1, ready2 = ctx.Event(), ctx.Event()
    release = ctx.Event()
    p1 = ctx.Process(target=_hold_permits, args=(4, "foreground", ready1, release))
    p2 = ctx.Process(target=_hold_permits, args=(4, "foreground", ready2, release))
    p1.start()
    p2.start()
    holder_terminated = False
    try:
        assert ready1.wait(timeout=15) and ready2.wait(timeout=15)
        factory = DedicatedSlotPermitFactory()
        # All 8 slots are held by other processes.
        with pytest.raises(ProviderCapacityUnavailable):
            factory.acquire(TrafficClass.FOREGROUND)
        with pytest.raises(ProviderCapacityUnavailable):
            factory.acquire(TrafficClass.BACKGROUND)
        # Killing a holder frees its slots once PostgreSQL sees the
        # control connections close.
        p1.terminate()
        holder_terminated = True
        p1.join(timeout=10)
        deadline = time.monotonic() + 15
        acquired = None
        while time.monotonic() < deadline:
            try:
                acquired = factory.acquire(TrafficClass.FOREGROUND)
                break
            except ProviderCapacityUnavailable:
                time.sleep(0.25)
        assert acquired is not None, "slots of a killed holder were never released"
        acquired.release()
    finally:
        # Cleanup must never block forever. A terminated holder may have
        # died while holding the shared Event's internal condition lock
        # (multiprocessing locks have no owner-death recovery), so once
        # any holder was terminated, release.set() itself could wait on
        # that orphaned lock without a timeout -- the previous finally
        # did exactly that and hung the full gate. Only signal release
        # when no holder was killed; afterwards rely on terminate ->
        # join(timeout) -> kill escalation and never touch the Event
        # again. (Children also self-limit via release.wait(timeout=30).)
        if not holder_terminated:
            release.set()
        for proc in (p1, p2):
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=10)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=10)
