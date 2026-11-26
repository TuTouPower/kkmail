"""Unit and integration tests for mail_core.net policy, proxies, OAuth, and image proxy (t089)."""

from __future__ import annotations

import os
import socket
import threading
import uuid

import pytest

from mail_core.accounts.connection import validate_connection
from mail_core.accounts.service import create_account, update_account
from mail_core.config import ConfigError, load_config
from mail_core.mail.storage.models import Account
from mail_core.net import (
    EndpointBulkhead,
    EndpointCircuitOpenError,
    NetworkSecurityError,
    OutboundSecurityPolicy,
    ProxyParseError,
    ProxyTunnelError,
    dial_stream,
    matches_no_proxy,
    parse_proxy_url,
    resolve_outbound_proxy,
)
from mail_core.providers.factory import build_provider
from mail_core.providers.graph import GraphProvider
from mail_core.providers.host_security import (
    MICROSOFT_DOMAINS,
    MICROSOFT_IMAP_HOSTS,
    reject_microsoft_imap,
)
from mail_core.providers.http import ProviderHttpError
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import default_urllib_token_post, urllib_json_request
from mail_core.security.credentials import DictCredentialStore
from mail_core.security.remote_image_proxy import (
    SSRFSecurityError,
    fetch_safe_remote_image,
)
from tests.mail_core.outbound_fixtures import (
    LoopbackHttpConnectProxy,
    LoopbackHttpsServer,
    LoopbackSocks5Proxy,
    VALID_1X1_PNG,
    client_ssl_context,
    write_self_signed_cert,
)


def test_proxy_url_parsing_and_credential_redaction():
    cfg = parse_proxy_url("http://alice:s3cret%21@proxy.internal:7890")
    assert cfg.scheme == "http"
    assert cfg.host == "proxy.internal"
    assert cfg.port == 7890
    assert cfg.username == "alice"
    assert cfg.password == "s3cret!"
    assert cfg.safe_key() == "http://proxy.internal:7890"
    assert "s3cret" not in repr(cfg)
    assert "alice" not in str(cfg)

    socks = parse_proxy_url("socks5h://[::1]:1080")
    assert socks.scheme == "socks5h"
    assert socks.host == "::1"
    assert socks.port == 1080
    assert socks.safe_key() == "socks5h://[::1]:1080"

    for bad in ("", "ftp://proxy:21", "http://bad host:8080", "http://proxy:99999", "http://proxy/path"):
        with pytest.raises(ProxyParseError):
            parse_proxy_url(bad)


def test_no_proxy_matching_and_precedence():
    assert matches_no_proxy("imap.163.com", 993, "163.com,10.0.0.0/8") is True
    assert matches_no_proxy("imap.gmail.com", 993, ".163.com,imap.qq.com:143") is False
    assert matches_no_proxy("imap.qq.com", 993, "imap.qq.com:143") is False
    assert matches_no_proxy("imap.qq.com", 143, "imap.qq.com:143") is True
    assert matches_no_proxy("10.2.3.4", 993, "10.0.0.0/8") is True
    assert matches_no_proxy("anything.test", 993, "*") is True

    env = {
        "HTTPS_PROXY": "http://127.0.0.1:7890",
        "https_proxy": "http://127.0.0.1:7899",
        "HTTP_PROXY": "http://127.0.0.1:7891",
        "ALL_PROXY": "socks5h://127.0.0.1:1080",
        "NO_PROXY": "imap.163.com",
    }
    resolved_env = resolve_outbound_proxy("imap.gmail.com", 993, env=env)
    assert resolved_env is not None and resolved_env.port == 7890
    resolved_lower = resolve_outbound_proxy("imap.gmail.com", 993, env={"https_proxy": "http://127.0.0.1:7899"})
    assert resolved_lower is not None and resolved_lower.port == 7899
    assert resolve_outbound_proxy("imap.163.com", 993, env=env) is None
    resolved_explicit = resolve_outbound_proxy(
        "imap.gmail.com", 993, explicit_proxy="socks5h://127.0.0.1:1081", env=env
    )
    assert resolved_explicit is not None and resolved_explicit.scheme == "socks5h"
    assert resolve_outbound_proxy("imap.gmail.com", 993, proxy_mode="direct", env=env) is None


def test_account_and_central_config_validation_and_graph_wiring():
    with pytest.raises(ConfigError, match="outbound_proxy"):
        load_config({"MAIL_CORE_OUTBOUND_PROXY": "socks4://127.0.0.1:1080"})
    cfg = load_config(
        {
            "MAIL_CORE_OUTBOUND_PROXY": "http://proxy.internal:7890",
            "MAIL_CORE_CONNECT_TIMEOUT_S": "7.5",
            "MAIL_CORE_CIRCUIT_COOLDOWN_S": "15",
        }
    )
    assert cfg.outbound_proxy == "http://proxy.internal:7890"
    assert cfg.outbound_connect_timeout_s == 7.5
    assert cfg.outbound_circuit_cooldown_s == 15.0

    validate_connection(
        "user@gmail.com",
        "imap",
        {"imap_host": "imap.gmail.com", "outbound_proxy": "socks5h://127.0.0.1:1080", "proxy_mode": "auto"},
        {"password": "pw"},
    )
    with pytest.raises(ValueError, match="outbound_proxy"):
        validate_connection(
            "user@gmail.com",
            "imap",
            {"imap_host": "imap.gmail.com", "outbound_proxy": "bad://x"},
            {"password": "pw"},
        )
    with pytest.raises(ValueError, match="proxy_mode"):
        validate_connection(
            "user@gmail.com",
            "imap",
            {"imap_host": "imap.gmail.com", "proxy_mode": "tor"},
            {"password": "pw"},
        )

    store = DictCredentialStore(
        {
            "ref-imap": {"password": "pw"},
            "ref-graph": {"client_id": "cid", "refresh_token": "rt"},
        }
    )
    imap_acc = Account(
        email="user@gmail.com",
        provider="imap",
        credential_ref="ref-imap",
        config={"imap_host": "imap.gmail.com", "outbound_proxy": "http://127.0.0.1:7890", "proxy_mode": "auto"},
    )
    imap_provider = build_provider(imap_acc, store)
    assert isinstance(imap_provider, ImapProvider)
    assert imap_provider.outbound_proxy == "http://127.0.0.1:7890"
    assert "secretpass" not in repr(
        ImapProvider(
            host="imap.gmail.com",
            port=993,
            username="u",
            password="p",
            outbound_proxy="http://u:secretpass@127.0.0.1:7890",
        )
    )

    graph_acc = Account(
        email="user@outlook.com",
        provider="graph",
        credential_ref="ref-graph",
        config={"outbound_proxy": "https://127.0.0.1:7443", "proxy_mode": "direct"},
    )
    graph_provider = build_provider(graph_acc, store)
    assert isinstance(graph_provider, GraphProvider)
    token_client = getattr(graph_provider.transport, "token_client")
    assert token_client.outbound_proxy == "https://127.0.0.1:7443"
    assert token_client.proxy_mode == "direct"


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")
def test_update_account_clears_blank_proxy_mode_and_outbound_proxy_pg():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = create_account(
            session,
            email=f"proxy-clear-{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            config={
                "imap_host": "imap.gmail.com",
                "outbound_proxy": "http://127.0.0.1:7890",
                "proxy_mode": "direct",
            },
            credentials={"password": "pw"},
        )
        updated = update_account(
            session,
            acc.id,
            config_patch={"proxy_mode": "", "outbound_proxy": "   "},
        )
        assert "proxy_mode" not in (updated.config or {})
        assert "outbound_proxy" not in (updated.config or {})
        session.rollback()


def test_microsoft_imap_blacklist_frozen_and_complete():
    assert isinstance(MICROSOFT_DOMAINS, frozenset)
    assert isinstance(MICROSOFT_IMAP_HOSTS, frozenset)
    for domain in ("outlook.com", "outlook.de", "hotmail.com", "live.com", "live.fr", "live.de", "msn.com"):
        with pytest.raises(ValueError, match="Microsoft IMAP"):
            reject_microsoft_imap(f"user@{domain}", {"imap_host": "imap.custom.test"})
    for host in ("outlook.office365.com", "imap-mail.outlook.com", "imap.outlook.com", "imap.hotmail.com", "outlook.office.com"):
        with pytest.raises(ValueError, match="Microsoft IMAP"):
            reject_microsoft_imap("user@custom.test", {"imap_host": host})


def test_direct_pin_ip_prevents_dns_rebinding_toctou_and_blocks_mixed_ips():
    policy = OutboundSecurityPolicy(allow_private_hosts=False)

    attempted_dials: list[tuple[str, int]] = []
    with pytest.raises(NetworkSecurityError, match="private or loopback"):
        dial_stream(
            "imap.rebind.test",
            993,
            security_policy=policy,
            bulkhead=None,
            resolver=lambda *_a: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 993)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 993)),
            ],
            connector=lambda addr, _t: attempted_dials.append(addr),
        )
    assert attempted_dials == []

    calls: dict[str, Any] = {"resolve": 0, "dialed": []}

    class _DummySock:
        def settimeout(self, t):
            self.t = t

        def close(self):
            pass

    def rebinding_resolver(*_a):
        calls["resolve"] += 1
        if calls["resolve"] == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 993))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 993))]

    sock = dial_stream(
        "imap.rebind.test",
        993,
        security_policy=policy,
        bulkhead=None,
        resolver=rebinding_resolver,
        connector=lambda addr, _t: (calls["dialed"].append(addr), _DummySock())[1],
    )
    assert isinstance(sock, _DummySock)
    assert calls["resolve"] == 1
    assert calls["dialed"] == [("93.184.216.34", 993)]

    proxy_cfg = parse_proxy_url("http://127.0.0.1:7890")
    for private_target in ("127.0.0.1", "169.254.169.254", "::1", "localhost", "db.local"):
        with pytest.raises(NetworkSecurityError, match="SSRF protection"):
            dial_stream(
                private_target,
                993,
                proxy=proxy_cfg,
                security_policy=policy,
                bulkhead=None,
                connector=lambda addr, _t: attempted_dials.append(addr),
            )
    assert attempted_dials == []


def test_remote_image_proxy_direct_http_https_and_ssrf_with_proxy_env(tmp_path: Any, monkeypatch: pytest.MonkeyPatch):
    cert, key = write_self_signed_cert(tmp_path, ["img.example.test"], prefix="img")
    client_ctx = client_ssl_context([cert])

    with LoopbackHttpsServer(cert, key) as https_img_srv, LoopbackHttpsServer(None, None) as http_img_srv:
        with LoopbackHttpConnectProxy("127.0.0.1", https_img_srv.port) as http_proxy, LoopbackSocks5Proxy(
            "127.0.0.1", https_img_srv.port
        ) as socks_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{http_proxy.port}")
            monkeypatch.setenv("MAIL_CORE_OUTBOUND_PROXY", f"socks5h://127.0.0.1:{socks_proxy.port}")

            real_getaddrinfo = socket.getaddrinfo

            def fake_getaddrinfo(host, port, *args, **kwargs):
                if str(host) == "img.example.test":
                    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(port)))]
                return real_getaddrinfo(host, port, *args, **kwargs)

            # 1. Non-allowlisted loopback resolution must still raise SSRFSecurityError.
            monkeypatch.setattr("mail_core.security.remote_image_proxy.socket.getaddrinfo", fake_getaddrinfo)
            with pytest.raises(SSRFSecurityError, match="SSRF blocked IP"):
                fetch_safe_remote_image("https://img.example.test/pixel.png")

            # 2. When loopback CIDR is explicitly allowlisted, fetch_safe_remote_image
            # runs full connect_ips_with_fallback -> wrap_tls_socket(SNI) -> HTTPConnection
            # directly to the pinned IP and sends ZERO requests to any proxy.
            monkeypatch.setenv("MAIL_CORE_PROXY_ALLOW_CIDRS", "127.0.0.1/32")
            monkeypatch.setattr("mail_core.security.remote_image_proxy.ssl.create_default_context", lambda: client_ctx)
            real_create = socket.create_connection

            def redirect_standard_port(address: tuple[str, int], timeout: float) -> socket.socket:
                host, port = address
                if port == 443:
                    return real_create((host, https_img_srv.port), timeout=timeout)
                if port == 80:
                    return real_create((host, http_img_srv.port), timeout=timeout)
                raise AssertionError(f"unexpected port {port}")

            monkeypatch.setattr("mail_core.net.dialer._default_connector", redirect_standard_port)

            ctype_tls, chunks_tls = fetch_safe_remote_image("https://img.example.test/pixel.png")
            assert ctype_tls == "image/png"
            assert b"".join(chunks_tls) == VALID_1X1_PNG
            assert https_img_srv.sni_seen == ["img.example.test"]

            ctype_plain, chunks_plain = fetch_safe_remote_image("http://img.example.test/pixel.png")
            assert ctype_plain == "image/png"
            assert b"".join(chunks_plain) == VALID_1X1_PNG
            assert http_proxy.requests == []
            assert socks_proxy.connects == []


def test_oauth_urllib_honors_http_https_socks5h_no_proxy_and_errors(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
):
    target_cert, target_key = write_self_signed_cert(tmp_path, ["graph.test"], prefix="graph")
    proxy_cert, proxy_key = write_self_signed_cert(tmp_path, ["proxy.local"], prefix="proxy")
    combined_ctx = client_ssl_context([target_cert, proxy_cert])
    monkeypatch.setattr("ssl.create_default_context", lambda *a, **kw: combined_ctx)

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(
        "mail_core.net.dialer.socket.getaddrinfo",
        lambda host, port, *a: (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(port)))]
            if str(host) in ("proxy.local", "graph.test")
            else real_getaddrinfo(host, port, *a)
        ),
    )

    with LoopbackHttpsServer(target_cert, target_key) as https_srv:
        url = f"https://graph.test:{https_srv.port}/v1.0/me"

        with LoopbackHttpConnectProxy("127.0.0.1", https_srv.port) as http_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{http_proxy.port}")
            assert urllib_json_request("GET", url, timeout=5.0)["ok"] is True
            assert http_proxy.requests == [f"graph.test:{https_srv.port}"]

        with LoopbackHttpConnectProxy(
            "127.0.0.1", https_srv.port, tls_cert_key=(proxy_cert, proxy_key)
        ) as https_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"https://proxy.local:{https_proxy.port}")
            assert urllib_json_request("GET", url, timeout=5.0)["ok"] is True
            assert https_proxy.requests == [f"graph.test:{https_srv.port}"]

        with LoopbackSocks5Proxy("127.0.0.1", https_srv.port) as socks_proxy:
            monkeypatch.setenv("HTTPS_PROXY", f"socks5h://127.0.0.1:{socks_proxy.port}")
            token_data = default_urllib_token_post("POST", url, {"grant_type": "refresh_token"}, timeout=5.0)
            assert token_data["access_token"] == "tok-123"
            assert socks_proxy.connects == [(0x03, "graph.test", https_srv.port)]

            # SSRF through proxy (127.0.0.1 target) maps cleanly to ProviderHttpError (no bare ValueError leak).
            with pytest.raises(ProviderHttpError, match="security policy"):
                default_urllib_token_post("POST", f"https://127.0.0.1:{https_srv.port}/token", {"grant_type": "refresh_token"})

            # Circuit-open in proxy path fast-fails with EndpointCircuitOpenError (no AmbiguousOutcomeError / 3x retry).
            from mail_core.net import default_bulkhead

            bh = default_bulkhead()
            key = (f"socks5h://127.0.0.1:{socks_proxy.port}", "graph.test", https_srv.port)
            bh.record_transport_failure(key)
            bh.record_transport_failure(key)
            sleeps: list[float] = []
            with pytest.raises(EndpointCircuitOpenError):
                urllib_json_request("POST", url, {"x": 1}, timeout=5.0, _sleep_fn=sleeps.append)
            assert sleeps == []
            bh.reset()

            # MAIL_CORE_NO_PROXY bypasses proxy and connects direct.
            monkeypatch.setenv("MAIL_CORE_NO_PROXY", "graph.test")
            monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
            assert urllib_json_request("GET", url, timeout=5.0)["ok"] is True
            assert len(socks_proxy.connects) == 1


def test_urlopen_outbound_default_ports_and_host_header_through_proxies(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
):
    """HTTPS URLs without explicit :port must tunnel to 443 (never HTTP default 80) and omit :443 in Host."""
    from mail_core.net import default_bulkhead
    from mail_core.net.http_client import _DialedHTTPConnection, _DialedHTTPSConnection

    https_conn = _DialedHTTPSConnection("graph.test")
    assert https_conn.port == 443
    assert https_conn.default_port == 443
    tls_conn_via_base = _DialedHTTPConnection("graph.test", use_tls=True)
    assert tls_conn_via_base.port == 443
    assert tls_conn_via_base.default_port == 443
    ipv6_https_conn = _DialedHTTPSConnection("[2001:db8::1]")
    assert ipv6_https_conn.host == "2001:db8::1"
    assert ipv6_https_conn.port == 443
    assert ipv6_https_conn.default_port == 443
    explicit_https_conn = _DialedHTTPSConnection("graph.test:8443")
    assert explicit_https_conn.port == 8443
    plain_conn = _DialedHTTPConnection("plain.test")
    assert plain_conn.port == 80
    assert plain_conn.default_port == 80

    target_cert, target_key = write_self_signed_cert(tmp_path, ["graph.test"], prefix="graph-default")
    client_ctx = client_ssl_context([target_cert])
    monkeypatch.setattr("ssl.create_default_context", lambda *a, **kw: client_ctx)

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(
        "mail_core.net.dialer.socket.getaddrinfo",
        lambda host, port, *a: (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(port)))]
            if str(host) in ("graph.test", "plain.test")
            else real_getaddrinfo(host, port, *a)
        ),
    )

    default_bulkhead().reset()
    try:
        with LoopbackHttpsServer(target_cert, target_key) as https_srv, LoopbackHttpsServer(
            None, None
        ) as http_srv:
            # Port 80 routes to plaintext HTTP server; port 443 routes to TLS server.
            # If HTTPS mistakenly dialed port 80, TLS handshake fails with WRONG_VERSION_NUMBER.
            with LoopbackHttpConnectProxy(
                "127.0.0.1",
                http_srv.port,
                port_map={
                    80: ("127.0.0.1", http_srv.port),
                    443: ("127.0.0.1", https_srv.port),
                },
            ) as http_proxy:
                monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{http_proxy.port}")
                monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{http_proxy.port}")

                https_data = urllib_json_request(
                    "GET", "https://graph.test/v1.0/me", timeout=5.0
                )
                assert https_data["ok"] is True
                token_data = default_urllib_token_post(
                    "POST",
                    "https://graph.test/oauth2/v2.0/token",
                    {"grant_type": "refresh_token"},
                    timeout=5.0,
                )
                assert token_data["access_token"] == "tok-123"
                plain_data = urllib_json_request(
                    "GET", "http://plain.test/health", timeout=5.0
                )
                assert plain_data["ok"] is True

                assert http_proxy.requests == [
                    "graph.test:443",
                    "graph.test:443",
                    "plain.test:80",
                ]
                assert https_srv.sni_seen == ["graph.test", "graph.test"]
                assert https_srv.host_headers == ["graph.test", "graph.test"]
                assert http_srv.host_headers == ["plain.test"]

            with LoopbackSocks5Proxy("127.0.0.1", https_srv.port) as socks_proxy:
                monkeypatch.setenv("HTTPS_PROXY", f"socks5h://127.0.0.1:{socks_proxy.port}")
                https_via_socks = urllib_json_request(
                    "GET", "https://graph.test/v1.0/me", timeout=5.0
                )
                assert https_via_socks["ok"] is True
                assert socks_proxy.connects == [(0x03, "graph.test", 443)]
    finally:
        default_bulkhead().reset()
