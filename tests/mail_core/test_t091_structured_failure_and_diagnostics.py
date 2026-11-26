"""End-to-end tests for StructuredFailure allowlist diagnostics and redaction separation (t091)."""

from __future__ import annotations

import contextlib
import errno
import imaplib
import io
import json
import logging
import os
import socket
import ssl
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

import mail_core.net.bulkhead as bulkhead_mod
import mail_core.net.dialer as dial_mod
import mail_core.sync.delta as delta_mod
import mail_core.sync.reconcile as reconcile_mod
import mail_core.sync.remote_push as remote_push_mod
from mail_core.db.session import get_session_factory
from mail_core.logging_config import RedactingTraceFormatter
from mail_core.mail.application.accounts import list_accounts_app
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    JobStatus,
    JobType,
    RemoteOperationStatus,
    SyncStatus,
)
from mail_core.mail.domain.failures import (
    FailureDomain,
    FailurePhase,
    StructuredFailure,
    attach_failure_phase,
)
from mail_core.mail.storage.models import (
    Account,
    Folder,
    RemoteOperation,
    SyncCheckpoint,
    WorkerJob,
)
from mail_core.net.dialer import dial_stream
from mail_core.net.policy import OutboundSecurityPolicy
from mail_core.net.proxy import ProxyConfig
from mail_core.net.tunnel import ProxyTunnelError
from mail_core.providers.http import (
    AmbiguousOutcomeError,
    PermanentAuthError,
    ProviderHttpError,
    RateLimitedError,
)
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import (
    OAuthError,
    OAuthTokenClient,
    default_urllib_token_post,
    urllib_json_request,
)
from mail_core.security.credentials import DictCredentialStore
from mail_core.security.redact import RedactingFilter, redact, safe_error, safe_provider_summary
from mail_core.sync.context import classify_failure
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.remote_push import is_transient_error
from mail_core.worker.handlers import handle_job

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _direct_policy() -> OutboundSecurityPolicy:
    return OutboundSecurityPolicy(allow_private_hosts=True)


def test_t091_dialer_and_proxy_tls_attach_structured_phases():
    """AC-001: DNS, TCP, proxy_connect, TLS, IMAP, and HTTP attach allowlisted phases."""
    # Direct TCP unreachable (errno=101)
    with pytest.raises(OSError) as ei_tcp:
        dial_stream(
            "93.184.216.34",
            993,
            security_policy=_direct_policy(),
            bulkhead=None,
            connector=lambda _addr, _t: (_ for _ in ()).throw(OSError(errno.ENETUNREACH, "Network is unreachable")),
        )
    f_tcp = StructuredFailure.from_exception(ei_tcp.value)
    assert f_tcp.domain is FailureDomain.TRANSPORT
    assert f_tcp.phase is FailurePhase.TCP_CONNECT
    assert f_tcp.errno == errno.ENETUNREACH
    assert f_tcp.format() == f"OSError phase=tcp_connect errno={errno.ENETUNREACH}"

    # Direct TCP timeout with errno=ETIMEDOUT
    timeout_err = TimeoutError("connect timed out")
    timeout_err.errno = errno.ETIMEDOUT
    with pytest.raises(TimeoutError) as ei_to:
        dial_stream(
            "93.184.216.34",
            993,
            security_policy=_direct_policy(),
            bulkhead=None,
            connector=lambda _addr, _t: (_ for _ in ()).throw(timeout_err),
        )
    f_to = StructuredFailure.from_exception(ei_to.value)
    assert f_to.domain is FailureDomain.TRANSPORT
    assert f_to.phase is FailurePhase.TCP_CONNECT
    assert f_to.errno == errno.ETIMEDOUT
    assert f_to.format() == f"TimeoutError phase=tcp_connect errno={errno.ETIMEDOUT}"

    # DNS resolution failure
    with pytest.raises(socket.gaierror) as ei_dns:
        dial_stream(
            "imap.invalid.example",
            993,
            security_policy=_direct_policy(),
            bulkhead=None,
            resolver=lambda *_a: (_ for _ in ()).throw(socket.gaierror(-2, "name not resolved")),
        )
    f_dns = StructuredFailure.from_exception(ei_dns.value)
    assert f_dns.domain is FailureDomain.TRANSPORT
    assert f_dns.phase is FailurePhase.DNS
    assert "phase=dns" in f_dns.format()

    # Proxy HTTP 502 / SOCKS5 error
    proxy = ProxyConfig(scheme="socks5h", host="127.0.0.1", port=7890)
    with pytest.raises(ProxyTunnelError) as ei_proxy:
        dial_stream(
            "imap.gmail.com",
            993,
            proxy=proxy,
            security_policy=_direct_policy(),
            bulkhead=None,
            connector=lambda _addr, _t: (_ for _ in ()).throw(
                ProxyTunnelError("socks reject token=SECRET", socks_reply=5)
            ),
        )
    f_proxy = StructuredFailure.from_exception(ei_proxy.value)
    assert f_proxy.domain is FailureDomain.TRANSPORT
    assert f_proxy.phase is FailurePhase.PROXY_CONNECT
    assert f_proxy.socks_reply == 5
    assert f_proxy.format() == "ProxyTunnelError phase=proxy_connect socks_reply=5"
    assert "SECRET" not in f_proxy.format()

    # TLS verification error
    class _DummySock:
        def settimeout(self, _t):
            pass

        def close(self):
            pass

    class _BadSSLContext:
        def wrap_socket(self, _sock, server_hostname=None):
            raise ssl.SSLCertVerificationError(1, "cert mismatch")

    with pytest.raises(ssl.SSLError) as ei_tls:
        dial_stream(
            "93.184.216.34",
            993,
            tls=True,
            ssl_context=_BadSSLContext(),  # intentional stub SSL context
            security_policy=_direct_policy(),
            bulkhead=None,
            connector=lambda _addr, _t: _DummySock(),
        )
    f_tls = StructuredFailure.from_exception(ei_tls.value)
    assert f_tls.domain is FailureDomain.TRANSPORT
    assert f_tls.phase is FailurePhase.TLS
    assert f_tls.format() == "SSLCertVerificationError phase=tls errno=1"


def test_t091_imap_and_http_provider_failures_preserve_phase_and_unwrapping(monkeypatch):
    """AC-001: IMAP auth/protocol and HTTP 5xx/429/401/URLError preserve phase and status."""
    class _AuthRejectClient:
        sock = None

        def login(self, _u, _p):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials password=secret")

    prov_auth = ImapProvider(
        host="imap.gmail.com",
        port=993,
        username="u",
        password="p",
        client_factory=lambda *a, **k: _AuthRejectClient(),
    )
    with pytest.raises(PermanentAuthError) as ei_auth:
        prov_auth.list_folders()
    f_auth = StructuredFailure.from_exception(ei_auth.value)
    assert f_auth.domain is FailureDomain.AUTH
    assert f_auth.phase is FailurePhase.AUTH
    assert f_auth.format() == "PermanentAuthError phase=auth"

    class _PostDialTimeoutClient:
        sock = None

        def login(self, _u, _p):
            raise TimeoutError("LOGIN greeting timed out")

    prov_imap = ImapProvider(
        host="imap.gmail.com",
        port=993,
        username="u",
        password="p",
        client_factory=lambda *a, **k: _PostDialTimeoutClient(),
    )
    with pytest.raises(TimeoutError) as ei_imap:
        prov_imap.list_folders()
    f_imap = StructuredFailure.from_exception(ei_imap.value)
    assert f_imap.domain is FailureDomain.TRANSPORT
    assert f_imap.phase is FailurePhase.IMAP
    assert f_imap.format() == "TimeoutError phase=imap"

    # HTTP 429 & HTTP 503 via urllib_json_request + dialed URLError(OSError(101))
    dial_err = attach_failure_phase(OSError(errno.ENETUNREACH, "net unreach"), FailurePhase.TCP_CONNECT)

    def _raise_dial_url(_req, **_kw):
        raise urllib.error.URLError(dial_err)

    monkeypatch.setattr("mail_core.providers.oauth.urlopen_outbound", _raise_dial_url)
    with pytest.raises(ProviderHttpError) as ei_url:
        urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=lambda _s: None)
    f_url = StructuredFailure.from_exception(ei_url.value)
    assert f_url.domain is FailureDomain.TRANSPORT
    assert f_url.phase is FailurePhase.TCP_CONNECT
    assert f_url.errno == errno.ENETUNREACH
    assert f_url.format() == f"ProviderHttpError phase=tcp_connect errno={errno.ENETUNREACH}"

    def _raise_429(_req, **_kw):
        raise urllib.error.HTTPError(
            "https://login.microsoftonline.com/token",
            429,
            "Too Many Requests",
            {"Retry-After": "17"},
            io.BytesIO(b"secret body"),
        )

    monkeypatch.setattr("mail_core.providers.oauth.urlopen_outbound", _raise_429)
    with pytest.raises(RateLimitedError) as ei_429:
        default_urllib_token_post("POST", "https://login.microsoftonline.com/token", {"grant_type": "refresh_token"})
    f_429 = StructuredFailure.from_exception(ei_429.value)
    assert f_429.domain is FailureDomain.CONTROL
    assert f_429.phase is FailurePhase.HTTP
    assert f_429.http_status == 429
    assert f_429.retry_after_s == 17.0
    assert "phase=http status=429 retry_after=17.0" in f_429.format()


def test_t091_redaction_boundary_preserves_errno_and_masks_all_secrets():
    """AC-002: Allowlist diagnostics avoid code=[REDACTED] while OAuth code/token/DSN/JWT stay masked."""
    # Unstructured sensitive inputs MUST remain redacted
    secrets = (
        "https://app.example/cb?code=OAUTH_CODE_SECRET_1&state=STATE_XYZ",
        '{"code": "JSON_CODE_2", "access_token": "AT_3", "refresh_token": "RT_4"}',
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "Cookie: session=SECRET_COOKIE_5",
        "postgresql+psycopg://kkmail:DB_PASS_6@127.0.0.1:5432/kkmail",
    )
    for sample in secrets:
        red = redact(sample)
        for token in ("OAUTH_CODE_SECRET_1", "STATE_XYZ", "JSON_CODE_2", "AT_3", "RT_4", "eyJhbGciOiJIUzI1NiJ9", "SECRET_COOKIE_5", "DB_PASS_6"):
            assert token not in red
        assert "[REDACTED]" in red

    # StructuredFailure logs with RedactingFilter + RedactingTraceFormatter never emit code=[REDACTED]
    dial_err = attach_failure_phase(
        OSError(errno.ENETUNREACH, "GET https://x/cb?code=OAUTH_CODE_SECRET_7 token=TOK_8"),
        FailurePhase.TCP_CONNECT,
    )
    failure = StructuredFailure.from_exception(dial_err)
    assert failure.format() == f"OSError phase=tcp_connect errno={errno.ENETUNREACH}"
    assert safe_error(dial_err) == failure.format()
    assert safe_provider_summary(dial_err) == failure.format()
    assert safe_provider_summary(failure.format()) == failure.format()

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
    logger = logging.getLogger(f"t091.test.{uuid.uuid4().hex}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        try:
            raise ProviderHttpError(
                "https://cb.example/?code=LEAK_CODE_9&token=LEAK_TOK_10",
                status=503,
                body={"code": "LEAK_BODY_11"},
            ) from dial_err
        except ProviderHttpError as wrapper:
            attach_failure_phase(wrapper, FailurePhase.HTTP)
            logger.exception("worker failure projected=%s raw=%s", failure, "https://cb.example/?code=LEAK_ARG_12")
    finally:
        logger.removeHandler(handler)

    rendered = stream.getvalue()
    assert f"OSError phase=tcp_connect errno={errno.ENETUNREACH}" in rendered
    assert "ProviderHttpError phase=http status=503" in rendered
    assert "raw=https://cb.example/?code=[REDACTED]" in rendered
    assert "OSError code=[REDACTED]" not in rendered
    for secret in ("LEAK_CODE_9", "LEAK_TOK_10", "LEAK_BODY_11", "LEAK_ARG_12", "OAUTH_CODE_SECRET_7", "TOK_8"):
        assert secret not in rendered


def test_t091_single_source_classification_and_transient_helpers():
    """AC-003: Non-network OSErrors and free-text messages never become TRANSPORT; remote_push understands phases."""
    for code in (errno.ENOSPC, errno.EMFILE, errno.EACCES):
        exc = OSError(code, "local filesystem/fd limit")
        sf = StructuredFailure.from_exception(exc)
        assert sf.domain is FailureDomain.UNKNOWN
        assert classify_failure(exc).domain is FailureDomain.UNKNOWN
        assert safe_error(exc) == f"{type(exc).__name__} errno={code}"

    prose_exc = RuntimeError("network unreachable ENETUNREACH ProxyTunnelError status=502")
    assert StructuredFailure.from_exception(prose_exc).domain is FailureDomain.UNKNOWN
    assert classify_failure(prose_exc).domain is FailureDomain.UNKNOWN

    assert is_transient_error(None, f"OSError phase=tcp_connect errno={errno.ENETUNREACH}") is True
    assert is_transient_error(None, "ProxyTunnelError phase=proxy_connect status=502") is True
    assert is_transient_error(None, "ProviderHttpError phase=http status=503") is True
    assert is_transient_error(AmbiguousOutcomeError("ambiguous")) is False
    assert is_transient_error(None, "AmbiguousOutcomeError phase=http") is False

    # Untrusted prose in from_dict cannot inject arbitrary safe_reason text
    untrusted = StructuredFailure.from_dict(
        {
            "domain": "transport",
            "error_type": "OSError",
            "phase": "tcp_connect",
            "errno": 101,
            "safe_reason": "password=LEAKED_SECRET",
        }
    )
    assert untrusted is not None
    assert untrusted.safe_reason is None
    assert untrusted.format() == "OSError phase=tcp_connect errno=101"


@_requires_db
def test_t091_pg_worker_log_job_health_and_api_preserve_structured_diagnostics(monkeypatch):
    """AC-001/002/003: Full PG sync/reconcile/remote_push pipeline retains phase+errno without redaction loss."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"t091-{uuid.uuid4().hex[:8]}@example.test",
            provider="imap",
            credential_ref="ref-t091",
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
            sync_status=SyncStatus.IDLE.value,
        )
        session.add(inbox)
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=inbox.id,
                cursor={"modseq": 1},
                full_scan_complete=True,
            )
        )
        delta_job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=acc.id,
            payload={"folder_id": str(inbox.id)},
            dedupe_key=f"delta:{acc.id}:{inbox.id}",
        )
        delta_job.status = JobStatus.CLAIMED.value
        delta_job.locked_by = "w-t091"
        delta_job.attempts = 1
        session.commit()
        aid, inbox_id, jid = acc.id, inbox.id, delta_job.id

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
    pkg_logger = logging.getLogger("mail_core")
    pkg_logger.addHandler(handler)
    try:
        # 1. Foreground delta -> TCP ENETUNREACH via real dial_stream phase attachment
        class _TcpFailProvider:
            def delta_changes(self, _rid, _cur):
                dial_stream(
                    "93.184.216.34",
                    993,
                    security_policy=_direct_policy(),
                    bulkhead=bulkhead_mod.EndpointBulkhead(failure_threshold=99),
                    connector=lambda _addr, _t: (_ for _ in ()).throw(
                        OSError(errno.ENETUNREACH, "dial https://oauth?code=SECRET_OAUTH_1 failed")
                    ),
                )

        monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _TcpFailProvider())
        with Session() as session:
            job = session.get(WorkerJob, jid)
            with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
                assert handle_job(session, job, worker_id="w-t091") is False
            session.commit()

        expected_tcp = f"OSError phase=tcp_connect errno={errno.ENETUNREACH}"
        with Session() as session:
            job = session.get(WorkerJob, jid)
            acc_row = session.get(Account, aid)
            assert job.last_error == expected_tcp
            assert acc_row.connectivity_state == ConnectivityState.DEGRADED.value
            assert acc_row.config["last_connectivity_error"] == expected_tcp

        page = list_accounts_app()
        dto = next(item for item in page.accounts if item.id == str(aid))
        assert dto.last_connectivity_error == expected_tcp

        expected_proxy = _run_pg_reconcile_proxy_case(Session, monkeypatch, aid, inbox_id)
        _run_pg_remote_push_case(Session, monkeypatch, aid, expected_tcp)
    finally:
        pkg_logger.removeHandler(handler)

    log_text = stream.getvalue()
    assert expected_tcp in log_text and expected_proxy in log_text
    for secret in ("code=[REDACTED]", "SECRET_OAUTH_1", "PROXY_SECRET"):
        assert secret not in log_text


def _run_pg_reconcile_proxy_case(Session: Any, monkeypatch: Any, aid: uuid.UUID, inbox_id: uuid.UUID) -> str:
    """Exercise foreground reconcile against loopback HTTP 502 proxy and return expected summary."""
    with _http_502_proxy() as proxy_port:
        monkeypatch.setattr(
            reconcile_mod,
            "build_provider",
            lambda *a, **k: _make_test_imap(outbound_proxy=f"http://127.0.0.1:{proxy_port}", proxy_mode="auto"),
        )
        with Session() as session:
            rec_job = enqueue_job(
                session, job_type=JobType.RECONCILE_FOLDER.value,
                execution_origin=ExecutionOrigin.FOREGROUND, account_id=aid,
                payload={"folder_id": str(inbox_id)}, dedupe_key=f"reconcile:{aid}:{inbox_id}",
            )
            rec_job.status, rec_job.locked_by, rec_job.attempts = JobStatus.CLAIMED.value, "w-t091", 1
            rec_id = rec_job.id
            session.commit()
        with Session() as session:
            rec_job = session.get(WorkerJob, rec_id)
            with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
                assert handle_job(session, rec_job, worker_id="w-t091") is False
            session.commit()

    expected_proxy = "ProxyTunnelError phase=proxy_connect status=502"
    with Session() as session:
        assert session.get(WorkerJob, rec_id).last_error == expected_proxy
        assert session.get(Account, aid).config["last_connectivity_error"] == expected_proxy
    return expected_proxy


def _run_pg_remote_push_case(Session: Any, monkeypatch: Any, aid: uuid.UUID, expected_tcp: str) -> None:
    """Exercise remote push failure through real ImapProvider -> DialedIMAP4_SSL -> dial_stream."""
    monkeypatch.setattr(remote_push_mod, "build_provider", lambda *a, **k: _make_test_imap())
    with Session() as session:
        op = RemoteOperation(
            id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}",
            op_type="mark_read", desired_state={"remote_id": "99", "is_read": True, "revision": 1},
            status=RemoteOperationStatus.PENDING.value,
        )
        session.add(op)
        op_id = op.id
        session.commit()

    def _fail_connect(_addr: tuple[str, int], _timeout: float) -> socket.socket:
        raise OSError(errno.ENETUNREACH, "unreach")

    with monkeypatch.context() as push_mp:
        push_mp.setattr(dial_mod, "_default_connector", _fail_connect)
        res_push = remote_push_mod.push_remote_operations(
            aid, worker_id="w-t091", execution_origin=ExecutionOrigin.BACKGROUND, store=object(),
        )
    assert res_push["failed"] == 1
    with Session() as session:
        assert session.get(RemoteOperation, op_id).last_error == expected_tcp


def _make_test_imap(*, outbound_proxy: str | None = None, proxy_mode: str | None = None) -> ImapProvider:
    return ImapProvider(
        host="93.184.216.34",
        port=993,
        username="u",
        password="p",
        timeout=5.0,
        connect_timeout=5.0,
        per_attempt_timeout=5.0,
        outbound_proxy=outbound_proxy,
        proxy_mode=proxy_mode,
        security_policy=_direct_policy(),
        bulkhead=bulkhead_mod.EndpointBulkhead(failure_threshold=99),
    )


@contextlib.contextmanager
def _http_502_proxy() -> Iterator[int]:
    """Run a single-shot loopback HTTP proxy replying 502 with secret text."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(5.0)

    def _serve() -> None:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(2.0)
            try:
                conn.recv(1024)
            except OSError:
                pass
            conn.sendall(b"HTTP/1.1 502 Bad Gateway token=PROXY_SECRET\r\nContent-Length: 0\r\n\r\n")

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield srv.getsockname()[1]
    finally:
        srv.close()
        thread.join(timeout=2.0)


def test_t091_imap4_error_and_oauth_client_preserve_phase_and_status() -> None:
    """IMAP4.error/abort normalize cleanly and OAuthTokenClient preserves HTTP/transport phases."""
    imap_err = imaplib.IMAP4.error("[TRYAGAIN] server busy token=SECRET_IMAP")
    f_imap = StructuredFailure.from_exception(imap_err)
    assert (f_imap.domain, f_imap.phase, f_imap.error_type) == (FailureDomain.UNKNOWN, FailurePhase.IMAP, "IMAP4Error")
    assert f_imap.format() == safe_error(imap_err) == safe_provider_summary("IMAP4Error phase=imap") == "IMAP4Error phase=imap"
    assert "SECRET_IMAP" not in safe_error(imap_err)

    imap_abort = imaplib.IMAP4.abort("connection dropped token=SECRET_ABORT")
    f_abort = StructuredFailure.from_exception(imap_abort)
    assert (f_abort.domain, f_abort.phase, f_abort.error_type) == (FailureDomain.TRANSPORT, FailurePhase.IMAP, "IMAP4Abort")
    assert f_abort.format() == safe_error(imap_abort) == safe_provider_summary("IMAP4Abort phase=imap") == "IMAP4Abort phase=imap"
    assert StructuredFailure.from_text("IMAP4Abort phase=imap").domain is FailureDomain.TRANSPORT

    token_blob = json.dumps({
        "refresh_token": "rt-t091", "client_id": "cid-t091", "client_secret": "sec-t091",
        "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    })
    dial_err = attach_failure_phase(OSError(errno.ENETUNREACH, "Network is unreachable"), FailurePhase.TCP_CONNECT)
    net_http_err = ProviderHttpError("network error token=SECRET_OAUTH", status=None)
    net_http_err.__cause__ = urllib.error.URLError(dial_err)

    cases: list[tuple[Exception, FailureDomain, FailurePhase, int | None, int | None, float | None, str]] = [
        (ProviderHttpError("upstream down token=SEC", status=503), FailureDomain.TRANSPORT, FailurePhase.HTTP, 503, None, None, "OAuthError phase=http status=503"),
        (RateLimitedError("rate limited token=SEC", status=429, retry_after_seconds=9.0), FailureDomain.CONTROL, FailurePhase.HTTP, 429, None, 9.0, "OAuthError phase=http status=429 retry_after=9.0"),
        (ProviderHttpError("invalid_grant token=SEC", status=401), FailureDomain.AUTH, FailurePhase.AUTH, 401, None, None, "OAuthError phase=auth status=401"),
        (net_http_err, FailureDomain.TRANSPORT, FailurePhase.TCP_CONNECT, None, errno.ENETUNREACH, None, f"OAuthError phase=tcp_connect errno={errno.ENETUNREACH}"),
    ]
    for raised_exc, exp_domain, exp_phase, exp_status, exp_errno, exp_retry, exp_text in cases:
        store = DictCredentialStore({"oauth:t091": token_blob})
        client = OAuthTokenClient(
            credential_ref="oauth:t091", store=store, provider="graph",
            http_post=lambda *_a, exc=raised_exc: (_ for _ in ()).throw(exc),
        )
        with pytest.raises(OAuthError) as ei:
            client.get_access_token()
        parsed = StructuredFailure.from_exception(ei.value)
        assert (parsed.domain, parsed.phase, parsed.http_status, parsed.errno, parsed.retry_after_s) == (
            exp_domain, exp_phase, exp_status, exp_errno, exp_retry
        )
        assert parsed.format() == exp_text
        err_text = safe_error(ei.value)
        assert "SECRET_OAUTH" not in err_text and "sec-t091" not in err_text and "token=SEC" not in err_text
