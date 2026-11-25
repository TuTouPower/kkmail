"""Integration tests for IMAP proxy tunnels, dual-stack timeouts, bulkhead, and worker deferral."""

from __future__ import annotations

import errno
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.net import (
    EndpointBulkhead,
    EndpointCircuitOpenError,
    NetworkSecurityError,
    OutboundSecurityPolicy,
    ProxyTunnelError,
    dial_stream,
    parse_proxy_url,
    wrap_tls_socket,
)
from mail_core.providers.connection_slots import (
    InMemoryPermitFactory,
    TrafficClass,
    is_capacity_error,
)
from mail_core.providers.imap import ImapProvider
from mail_core.sync.jobs import reschedule_job
from mail_core.worker.handlers import _evaluate_result
from tests.mail_core.outbound_fixtures import (
    LoopbackHttpConnectProxy,
    LoopbackSocks5Proxy,
    LoopbackTlsImapServer,
    SilentAcceptServer,
    client_ssl_context,
    write_self_signed_cert,
)


def test_imap_sync_and_idle_via_http_https_and_socks5h_proxies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", raising=False)
    imap_cert, imap_key = write_self_signed_cert(tmp_path, ["imap.test", "imap.https-proxy.test"], prefix="imap")
    proxy_cert, proxy_key = write_self_signed_cert(tmp_path, ["proxy.local"], prefix="proxy")
    combined_ctx = client_ssl_context([imap_cert, proxy_cert])
    monkeypatch.setattr("ssl.create_default_context", lambda *a, **kw: combined_ctx)
    monkeypatch.setattr("mail_core.providers.imap.ssl.create_default_context", lambda: combined_ctx)

    with LoopbackTlsImapServer(imap_cert, imap_key) as imap_srv:
        # 1. HTTP CONNECT proxy + IDLE session
        with LoopbackHttpConnectProxy(
            "127.0.0.1", imap_srv.port, expected_auth=("proxyuser", "proxypass")
        ) as http_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"http://proxyuser:proxypass@127.0.0.1:{http_proxy.port}")
            provider = ImapProvider(
                host="imap.test",
                port=993,
                username="u@gmail.com",
                password="app-password",
                connect_timeout=5.0,
                timeout=30.0,
                bulkhead=None,
            )
            assert [f.remote_id for f in provider.list_folders()] == ["INBOX"]
            idle = provider.open_idle_session("INBOX")
            try:
                assert idle.wait_for_change(timeout_s=5.0, stop_event=threading.Event()) == "changed"
            finally:
                idle.close()
            assert http_proxy.requests == ["imap.test:993", "imap.test:993"]

        # 2. HTTPS TLS-in-TLS CONNECT proxy + IDLE session (verifies outer TLS + inner TLS + SNI!)
        with LoopbackHttpConnectProxy(
            "127.0.0.1", imap_srv.port, tls_cert_key=(proxy_cert, proxy_key)
        ) as https_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"https://proxy.local:{https_proxy.port}")
            real_getaddrinfo = socket.getaddrinfo
            monkeypatch.setattr(
                "mail_core.net.dialer.socket.getaddrinfo",
                lambda host, port, *a: (
                    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(port)))]
                    if str(host) == "proxy.local"
                    else real_getaddrinfo(host, port, *a)
                ),
            )
            provider = ImapProvider(
                host="imap.https-proxy.test",
                port=993,
                username="u@gmail.com",
                password="app-password",
                connect_timeout=5.0,
                timeout=30.0,
                bulkhead=None,
            )
            assert [f.remote_id for f in provider.list_folders()] == ["INBOX"]
            assert https_proxy.requests == ["imap.https-proxy.test:993"]
            assert imap_srv.sni_seen[-1] == "imap.https-proxy.test"

        # 3. proxy_mode="direct" ignores HTTPS_PROXY cleanly
        monkeypatch.setattr(
            "mail_core.net.dialer.socket.getaddrinfo",
            lambda host, port, *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(port)))],
        )
        direct_provider = ImapProvider(
            host="imap.test",
            port=imap_srv.port,
            username="u",
            password="p",
            proxy_mode="direct",
            security_policy=OutboundSecurityPolicy(allow_private_hosts=True),
            bulkhead=None,
        )
        assert [f.remote_id for f in direct_provider.list_folders()] == ["INBOX"]


def test_imap_via_socks5_and_socks5h_proxies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", raising=False)
    cert, key = write_self_signed_cert(tmp_path, ["imap.remote-only.test"], prefix="socks")
    ctx = client_ssl_context([cert])
    monkeypatch.setattr("mail_core.providers.imap.ssl.create_default_context", lambda: ctx)

    dns_lookups: list[str] = []
    real_getaddrinfo = socket.getaddrinfo

    def spy_getaddrinfo(host, *args, **kwargs):
        dns_lookups.append(str(host))
        if str(host) == "imap.remote-only.test":
            raise AssertionError("socks5h must not locally resolve target host")
        return real_getaddrinfo(host, *args, **kwargs)

    with LoopbackTlsImapServer(cert, key) as imap_srv, LoopbackSocks5Proxy(
        "127.0.0.1", imap_srv.port, expected_auth=("u", "p")
    ) as socks_srv:
        monkeypatch.setattr("mail_core.net.dialer.socket.getaddrinfo", spy_getaddrinfo)
        monkeypatch.setenv("ALL_PROXY", f"socks5h://u:p@127.0.0.1:{socks_srv.port}")
        provider = ImapProvider(
            host="imap.remote-only.test",
            port=993,
            username="u@gmail.com",
            password="pw",
            connect_timeout=5.0,
            bulkhead=None,
        )
        assert [f.remote_id for f in provider.list_folders()] == ["INBOX"]
        assert socks_srv.connects == [(0x03, "imap.remote-only.test", 993)]
        assert "imap.remote-only.test" not in dns_lookups

    # Plain socks5:// resolves locally and enforces Pin-IP SSRF before dialing proxy.
    with LoopbackSocks5Proxy("127.0.0.1", 1) as socks_srv:
        with pytest.raises(NetworkSecurityError, match="private or loopback"):
            dial_stream(
                "imap.socks5-local.test",
                993,
                proxy=parse_proxy_url(f"socks5://127.0.0.1:{socks_srv.port}"),
                security_policy=OutboundSecurityPolicy(allow_private_hosts=False),
                resolver=lambda *_a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 993))],
                bulkhead=None,
            )
        assert socks_srv.connects == []


def test_proxy_http_407_and_502_behavior():
    with LoopbackHttpConnectProxy("127.0.0.1", 1, expected_auth=("right", "secret")) as proxy_srv:
        proxy_cfg = parse_proxy_url(f"http://wrong:badpass@127.0.0.1:{proxy_srv.port}")
        bh = EndpointBulkhead(failure_threshold=1, cooldown_s=30.0)
        with pytest.raises(ProxyTunnelError) as ei:
            dial_stream("imap.gmail.com", 993, proxy=proxy_cfg, connect_timeout=3.0, bulkhead=bh)
        assert ei.value.status == 407
        assert "badpass" not in str(ei.value)
        assert "wrong" not in str(ei.value)
        assert bh.snapshot() == {}

    with LoopbackHttpConnectProxy("127.0.0.1", 1, forced_status=502) as bad_gw:
        proxy_cfg = parse_proxy_url(f"http://127.0.0.1:{bad_gw.port}")
        bh = EndpointBulkhead(failure_threshold=1, cooldown_s=30.0)
        with pytest.raises(ProxyTunnelError) as ei_502:
            dial_stream("imap.gmail.com", 993, proxy=proxy_cfg, connect_timeout=3.0, bulkhead=bh)
        assert ei_502.value.status == 502
        assert bh.snapshot()[(proxy_cfg.safe_key(), "imap.gmail.com", 993)]["state"] == "open"


def test_dual_stack_timeout_priority_silent_socket_cutoff_and_io_timeout_none(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = {"now": 0.0}
    attempts: list[tuple[str, float]] = []

    def fake_connect(addr: tuple[str, int], timeout: float):
        ip, _ = addr
        attempts.append((ip, timeout))
        if ":" in ip:
            raise OSError(errno.ENETUNREACH, "Network is unreachable")
        clock["now"] += timeout
        raise TimeoutError("timed out")

    with pytest.raises(TimeoutError):
        dial_stream(
            "imap.gmail.com",
            993,
            connect_timeout=8.0,
            per_attempt_timeout=3.0,
            io_timeout=60.0,
            bulkhead=None,
            security_policy=OutboundSecurityPolicy(allow_private_hosts=False),
            resolver=lambda *_a: [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2404:6800:4008::6d", 993, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("108.177.97.108", 993)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("108.177.97.109", 993)),
            ],
            connector=fake_connect,
            clock=lambda: clock["now"],
        )
    assert attempts == [("108.177.97.108", 3.0), ("108.177.97.109", 3.0), ("2404:6800:4008::6d", 2.0)]

    # Real silent TCP socket stalls TLS ServerHello -> connect_timeout=0.2s cuts off fast instead of 60s!
    with SilentAcceptServer() as silent_srv:
        monkeypatch.setenv("MAIL_CORE_CONNECT_TIMEOUT_S", "0.2")
        provider = ImapProvider(
            host="127.0.0.1",
            port=silent_srv.port,
            username="u",
            password="p",
            use_ssl=True,
            timeout=60.0,
            security_policy=OutboundSecurityPolicy(allow_private_hosts=True),
            bulkhead=None,
        )
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            provider.list_folders()
        assert time.monotonic() - t0 < 2.0

    # io_timeout=None resets blocking socket timeout after dial; exhausted TLS budget raises TimeoutError.
    with SilentAcceptServer() as srv:
        sock = dial_stream(
            "127.0.0.1",
            srv.port,
            tls=False,
            connect_timeout=2.0,
            io_timeout=None,
            bulkhead=None,
            security_policy=OutboundSecurityPolicy(allow_private_hosts=True),
        )
        try:
            assert sock.gettimeout() is None
        finally:
            sock.close()

    with pytest.raises(TimeoutError, match="TLS handshake budget exhausted"):
        wrap_tls_socket(MagicMock(), server_hostname="imap.test", deadline=10.0, clock=lambda: 10.5)


def test_real_imap_bulkhead_permit_isolation_and_half_open_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cert, key = write_self_signed_cert(tmp_path, ["imap.gmail.com", "imap.163.com"], prefix="bh")
    ctx = client_ssl_context([cert])
    monkeypatch.setattr("mail_core.providers.imap.ssl.create_default_context", lambda: ctx)

    factory = InMemoryPermitFactory()
    clock = {"now": 0.0}
    bh = EndpointBulkhead(failure_threshold=2, cooldown_s=30.0, clock=lambda: clock["now"])
    real_create = socket.create_connection

    with SilentAcceptServer() as blackhole_srv, LoopbackTlsImapServer(cert, key) as healthy_srv:
        gmail_target_port = {"port": blackhole_srv.port}

        def route_connector(addr: tuple[str, int], timeout: float) -> socket.socket:
            ip, _port = addr
            if ip == "108.177.97.108":
                return real_create(("127.0.0.1", gmail_target_port["port"]), timeout=timeout)
            if ip == "220.181.12.101":
                return real_create(("127.0.0.1", healthy_srv.port), timeout=timeout)
            raise AssertionError(f"unexpected ip {ip}")

        monkeypatch.setattr("mail_core.net.dialer._default_connector", route_connector)
        real_getaddrinfo = socket.getaddrinfo

        def fake_getaddrinfo(host, port, *a):
            if str(host) == "imap.gmail.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("108.177.97.108", int(port)))]
            if str(host) == "imap.163.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("220.181.12.101", int(port)))]
            return real_getaddrinfo(host, port, *a)

        monkeypatch.setattr("mail_core.net.dialer.socket.getaddrinfo", fake_getaddrinfo)

        # 1. Two consecutive real DialedIMAP4_SSL connect timeouts trip the circuit.
        for i in range(2):
            p = ImapProvider(
                host="imap.gmail.com",
                port=993,
                username=f"g{i}@gmail.com",
                password="pw",
                connect_timeout=0.15,
                per_attempt_timeout=0.15,
                timeout=60.0,
                bulkhead=bh,
                permit_factory=factory,
                traffic_class=TrafficClass.BACKGROUND,
            )
            with pytest.raises(TimeoutError):
                p.list_folders()
        assert factory.snapshot()["current"] == 0

        # 2. Occupy 6 background slots (only 2 foreground left); storm 10 Gmail requests -> all fast-fail!
        # Meanwhile real DialedIMAP4_SSL sync to healthy imap.163.com succeeds without ProviderCapacityUnavailable.
        held_bg = [factory.acquire(TrafficClass.BACKGROUND) for _ in range(6)]
        try:
            def storm_gmail(idx: int) -> None:
                p = ImapProvider(
                    host="imap.gmail.com",
                    port=993,
                    username=f"g{idx}@gmail.com",
                    password="pw",
                    connect_timeout=0.15,
                    bulkhead=bh,
                    permit_factory=factory,
                    traffic_class=TrafficClass.FOREGROUND,
                )
                with pytest.raises(EndpointCircuitOpenError):
                    p.list_folders()

            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(storm_gmail, range(10)))

            healthy = ImapProvider(
                host="imap.163.com",
                port=993,
                username="u@163.com",
                password="pw",
                connect_timeout=2.0,
                bulkhead=bh,
                permit_factory=factory,
                traffic_class=TrafficClass.FOREGROUND,
            )
            assert [f.remote_id for f in healthy.list_folders()] == ["INBOX"]
            assert factory.snapshot()["current"] == 6
        finally:
            for perm in held_bg:
                perm.release()

        # 3. Cooldown elapses -> failed half-open probe via real ImapProvider re-opens cooldown!
        clock["now"] = 31.0
        probe_fail = ImapProvider(
            host="imap.gmail.com",
            port=993,
            username="probe@gmail.com",
            password="pw",
            connect_timeout=0.15,
            bulkhead=bh,
            permit_factory=factory,
        )
        with pytest.raises(TimeoutError):
            probe_fail.list_folders()
        assert bh.snapshot()[("direct", "imap.gmail.com", 993)]["state"] == "open"
        assert factory.snapshot()["current"] == 0

        # 4. Next cooldown elapses & endpoint recovers -> real ImapProvider probe succeeds & closes circuit!
        clock["now"] = 62.0
        gmail_target_port["port"] = healthy_srv.port
        probe_ok = ImapProvider(
            host="imap.gmail.com",
            port=993,
            username="probe@gmail.com",
            password="pw",
            connect_timeout=2.0,
            bulkhead=bh,
            permit_factory=factory,
        )
        assert [f.remote_id for f in probe_ok.list_folders()] == ["INBOX"]
        assert bh.snapshot() == {}
        assert factory.snapshot()["current"] == 0


def test_circuit_open_deferral_preserves_retry_after_without_burning_failure_attempts():
    exc = EndpointCircuitOpenError(
        "circuit open",
        endpoint=("direct", "imap.gmail.com", 993),
        retry_after_s=45.0,
    )
    assert exc.retry_after_seconds == 45.0
    assert is_capacity_error(exc) is True

    # Simulate _evaluate_result on capacity_unavailable deferral returned by delta/reconcile.
    session = MagicMock()
    job = SimpleNamespace(
        id="job-1",
        account_id=None,
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        status=JobStatus.CLAIMED.value,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        payload={},
        failure_attempts=0,
        attempts=1,
        run_after=datetime.now(timezone.utc),
        last_error=None,
        execution_generation=None,
        dedupe_key=None,
        priority=60,
    )
    session.get.return_value = job
    session.scalars.return_value.all.return_value = []
    before = datetime.now(timezone.utc)
    ok = _evaluate_result(
        session,
        job,
        {"status": "capacity_unavailable", "retry_after": exc.retry_after_seconds},
        "w1",
    )
    assert ok is False
    assert job.failure_attempts == 0
    assert (job.run_after - before).total_seconds() >= 44.0

    # Also verify direct reschedule_job handles retry_after_seconds when passed directly.
    job.status = JobStatus.CLAIMED.value
    job.locked_by = "w1"
    reschedule_job(session, job, worker_id="w1", delay_seconds=exc.retry_after_seconds, now=before)
    assert (job.run_after - before).total_seconds() == 45.0
