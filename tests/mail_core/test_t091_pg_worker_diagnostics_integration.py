"""End-to-end PG & redaction/domain regression tests for t091 findings."""

from __future__ import annotations

import errno
import http.client
import imaplib
import io
import logging
import socket
import ssl
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import mail_core.net.bulkhead as bulkhead_mod
import mail_core.net.dialer as dial_mod
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
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
    coerce_structured_failure,
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
from mail_core.providers.base import RemoteOperationItem, RemoteOperationResult
from mail_core.providers.http import PermanentAuthError, ProviderHttpError, RateLimitedError
from mail_core.providers.imap import ImapProvider, format_imap_remote_id
from mail_core.providers.oauth import OAuthError
from mail_core.security.redact import (
    RedactingFilter,
    format_safe_exception_chain,
    safe_error,
    safe_provider_summary,
)
from mail_core.sync.context import classify_failure
from mail_core.sync.jobs import enqueue_job, fail_job
from mail_core.sync.remote_push import is_transient_error
from mail_core.worker.handlers import handle_job

_requires_db = pytest.mark.skipif(
    not __import__("os").environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_t091_symbolic_code_logging_and_fail_job_decoupled_from_redact() -> None:
    """t091_code_f002/t091_test_f002: StructuredFailure symbolic code survives loggers without weakening redact()."""
    class DbError(Exception):
        status = 503
        code = "57P03"

    db_exc = DbError("cannot connect: password=SECRET_DB code=RAW_SECRET")
    db_failure = StructuredFailure.from_exception(db_exc)
    assert db_failure.format() == "DbError status=503 code=57P03"
    assert safe_error(db_exc) == "DbError status=503 code=57P03"

    # HTTPError deduplicates status == code so HTTP 401 never emits code=401
    http_401 = urllib.error.HTTPError("https://oauth/token?code=SECRET_Q", 401, "Unauthorized", {}, None)
    attach_failure_phase(http_401, FailurePhase.HTTP)
    assert StructuredFailure.from_exception(http_401).format() == "HTTPError phase=http status=401"

    # Test both formatter-only (default configure_logging) and filter+formatter logging
    for use_filter in (False, True):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        if use_filter:
            handler.addFilter(RedactingFilter())
        handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
        logger = logging.getLogger(f"t091.sym.{use_filter}.{uuid.uuid4().hex}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            try:
                raise http_401
            except urllib.error.HTTPError:
                logger.exception("structured=%s raw=%s bearer=%s", db_failure, "https://cb?code=SECRET_URL", "Bearer SECRET_JWT")
        finally:
            logger.removeHandler(handler)
        out = stream.getvalue()
        assert "structured=DbError status=503 code=57P03" in out
        assert "HTTPError phase=http status=401" in out
        assert "code=401" not in out
        assert "raw=https://cb?code=[REDACTED]" in out
        assert "bearer=Bearer [REDACTED]" in out
        for leak in ("SECRET_DB", "RAW_SECRET", "SECRET_Q", "SECRET_URL", "SECRET_JWT"):
            assert leak not in out

    # Chain helper directly preserves DbError code=57P03 while redacting traceback paths/secrets
    try:
        attach_failure_phase(db_exc, FailurePhase.IMAP)
        raise db_exc
    except DbError as caught:
        chain_text = format_safe_exception_chain((DbError, caught, caught.__traceback__))
    assert "DbError phase=imap status=503 code=57P03" in chain_text
    assert "SECRET_DB" not in chain_text

    # fail_job projects BaseException via StructuredFailure and preserves Retry-After
    class _FakeSession:
        def flush(self) -> None:
            return None

    fake_session: Any = _FakeSession()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    job: Any = SimpleNamespace(
        attempts=1, failure_attempts=0, status=JobStatus.CLAIMED.value,
        last_error=None, locked_by="w1", locked_at=now, run_after=now,
    )
    rl_exc = attach_failure_phase(
        RateLimitedError("rate limited https://x?code=SECRET", status=429, retry_after_seconds=17.0, body='{"error":"429"}'),
        FailurePhase.HTTP,
    )
    fail_job(fake_session, job, rl_exc, now=now)
    assert job.last_error == "RateLimitedError phase=http status=429 retry_after=17.0"
    assert job.run_after == now + timedelta(seconds=17)

    dial_err = attach_failure_phase(OSError(errno.ENETUNREACH, "unreach"), FailurePhase.TCP_CONNECT)
    wrapped_http = ProviderHttpError("transport error: network unreachable", status=None)
    wrapped_http.__cause__ = urllib.error.URLError(dial_err)
    fail_job(fake_session, job, wrapped_http, now=now)
    assert job.last_error == f"ProviderHttpError phase=tcp_connect errno={errno.ENETUNREACH}"


def test_t091_dns_http_disconnect_and_safe_reason_security_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """t091_code_f001/f004 & t091_test_f002: gaierror/RemoteDisconnected round-trip & from_dict rejects tail injections."""
    assert not hasattr(FailurePhase, "OPERATION")

    def _fail_dns(*_a: object, **_k: object) -> list[object]:
        raise socket.gaierror(8, "nodename nor servname provided token=SECRET_DNS")

    monkeypatch.setattr(dial_mod.socket, "getaddrinfo", _fail_dns)
    with pytest.raises(socket.gaierror) as ei_dns:
        dial_stream("imap.example.test", 993, security_policy=OutboundSecurityPolicy(allow_private_hosts=True), bulkhead=None)
    f_dns = StructuredFailure.from_exception(ei_dns.value)
    assert (f_dns.domain, f_dns.phase, f_dns.error_type, f_dns.errno) == (FailureDomain.TRANSPORT, FailurePhase.DNS, "gaierror", 8)
    assert f_dns.format() == "gaierror phase=dns errno=8"
    assert StructuredFailure.from_text("gaierror phase=dns errno=8").domain is FailureDomain.TRANSPORT
    assert is_transient_error(None, "gaierror phase=dns errno=8") is True
    assert classify_failure(ei_dns.value).domain is FailureDomain.TRANSPORT

    for proto_exc in (http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"partial")):
        f_proto = StructuredFailure.from_exception(proto_exc)
        assert f_proto.domain is FailureDomain.TRANSPORT
        assert StructuredFailure.from_text(f_proto.format()).domain is FailureDomain.TRANSPORT
        assert is_transient_error(None, f_proto.format()) is True

    # t091_code_f004: unanchored HTTP banner suffix injection in from_dict must be stripped
    injected = StructuredFailure.from_dict(
        {
            "domain": "transport",
            "error_type": "ProviderHttpError",
            "http_status": 502,
            "safe_reason": "HTTP 502 https://oauth/cb?code=SECRET_LEAK Authorization: Bearer eyJabc.def.ghi",
        }
    )
    assert injected is not None
    assert injected.safe_reason is None
    for text in (injected.format(), safe_provider_summary(injected), coerce_structured_failure({"domain": "transport", "error_type": "ProviderHttpError", "safe_reason": "HTTP 502 https://x?code=LEAK"}).format()):
        assert "SECRET_LEAK" not in text and "eyJabc" not in text
    valid_banner = StructuredFailure.from_dict({"domain": "transport", "error_type": "ProviderHttpError", "safe_reason": "HTTP 502"})
    assert valid_banner is not None and valid_banner.safe_reason == "HTTP 502"


def _seed_pg_account_and_inbox(Session: Any) -> tuple[uuid.UUID, uuid.UUID]:
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"t091-pg-{uuid.uuid4().hex[:8]}@example.test",
            provider="imap",
            credential_ref="ref-t091-pg",
            sync_enabled=True,
            connectivity_state=ConnectivityState.CONNECTED.value,
            credential_state=CredentialState.VALID.value,
            config={},
        )
        session.add(acc)
        session.flush()
        inbox = Folder(
            id=uuid.uuid4(), account_id=acc.id, remote_id="INBOX",
            name="INBOX", role="inbox", sync_status=SyncStatus.IDLE.value,
        )
        session.add(inbox)
        session.flush()
        session.add(SyncCheckpoint(account_id=acc.id, folder_id=inbox.id, cursor={"modseq": 1}, full_scan_complete=True))
        session.commit()
        return acc.id, inbox.id


def _run_pg_job(
    Session: Any,
    *,
    job_type: JobType,
    account_id: uuid.UUID,
    payload: dict[str, str],
) -> uuid.UUID:
    with Session() as session:
        job = enqueue_job(
            session,
            job_type=job_type.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=account_id,
            payload=payload,
            dedupe_key=f"{job_type.value}:{uuid.uuid4().hex}",
        )
        job.status, job.locked_by, job.attempts = JobStatus.CLAIMED.value, "w-t091-pg", 1
        jid = job.id
        session.commit()
    with Session() as session:
        job = session.get(WorkerJob, jid)
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            assert handle_job(session, job, worker_id="w-t091-pg") is False
        session.commit()
    return jid


@_requires_db
def test_t091_pg_sync_account_folders_http_and_retry_after_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """t091_test_f001: SYNC_ACCOUNT_FOLDERS / DELTA preserve HTTP 503 / OAuth 429 Retry-After in PG."""
    Session = get_session_factory()
    aid, inbox_id = _seed_pg_account_and_inbox(Session)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
    pkg_logger = logging.getLogger("mail_core")
    pkg_logger.addHandler(handler)
    try:
        # 1. ProviderHttpError 503 thrown by sync_account_folders into handle_job except boundary
        err_503 = attach_failure_phase(ProviderHttpError("upstream https://x?code=SECRET_503", status=503), FailurePhase.HTTP)
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(list_folder_catalog=lambda: (_ for _ in ()).throw(err_503)))
        jid_503 = _run_pg_job(Session, job_type=JobType.SYNC_ACCOUNT_FOLDERS, account_id=aid, payload={})
        with Session() as session:
            assert session.get(WorkerJob, jid_503).last_error == "ProviderHttpError phase=http status=503"
            assert session.get(Account, aid).config["last_connectivity_error"] == "ProviderHttpError phase=http status=503"

        # 2. OAuthError 429 thrown by sync_account_folders into handle_job except boundary preserves retry_after=17.0
        before_429 = datetime.now(timezone.utc)
        oauth_acc_429 = attach_failure_phase(OAuthError("token HTTP 429", status=429, retry_after_seconds=17.0), FailurePhase.HTTP)
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(list_folder_catalog=lambda: (_ for _ in ()).throw(oauth_acc_429)))
        jid_429 = _run_pg_job(Session, job_type=JobType.SYNC_ACCOUNT_FOLDERS, account_id=aid, payload={})
        with Session() as session:
            j429 = session.get(WorkerJob, jid_429)
            assert j429.last_error == "OAuthError phase=http status=429 retry_after=17.0"
            assert j429.run_after >= before_429 + timedelta(seconds=16)

        # 3. RateLimitedError in sync_account_folders schedules delayed successor honoring Retry-After=17.0
        before_rl = datetime.now(timezone.utc)
        err_429 = attach_failure_phase(RateLimitedError("rate limited", status=429, retry_after_seconds=17.0, body='{"error":"429"}'), FailurePhase.HTTP)
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(list_folder_catalog=lambda: (_ for _ in ()).throw(err_429)))
        with Session() as session:
            rl_job = enqueue_job(
                session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, execution_origin=ExecutionOrigin.FOREGROUND,
                account_id=aid, payload={}, dedupe_key=f"rl:{uuid.uuid4().hex}",
            )
            rl_job.status, rl_job.locked_by, rl_job.attempts = JobStatus.CLAIMED.value, "w-t091-pg", 1
            rl_id = rl_job.id
            session.commit()
        with Session() as session:
            rl_row = session.get(WorkerJob, rl_id)
            with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
                assert handle_job(session, rl_row, worker_id="w-t091-pg") is True
            session.commit()
        with Session() as session:
            succ = session.query(WorkerJob).filter(WorkerJob.account_id == aid, WorkerJob.dedupe_key == f"sync:{aid}", WorkerJob.status == JobStatus.PENDING.value).one()
            assert succ.run_after >= before_rl + timedelta(seconds=16)

        # 4. Delta OAuthError 429 preserves retry_after_s through provider_error dict -> handlers.py:228
        before_delta = datetime.now(timezone.utc)
        oauth_429 = attach_failure_phase(OAuthError("token HTTP 429", status=429, retry_after_seconds=12.0), FailurePhase.HTTP)
        monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: SimpleNamespace(delta_changes=lambda *_a: (_ for _ in ()).throw(oauth_429)))
        jid_d429 = _run_pg_job(Session, job_type=JobType.SYNC_FOLDER_DELTA, account_id=aid, payload={"folder_id": str(inbox_id)})
        with Session() as session:
            jd = session.get(WorkerJob, jid_d429)
            assert jd.last_error == "OAuthError phase=http status=429 retry_after=12.0"
            assert jd.run_after >= before_delta + timedelta(seconds=11)
    finally:
        pkg_logger.removeHandler(handler)

    log_text = stream.getvalue()
    assert "ProviderHttpError phase=http status=503" in log_text
    assert "SECRET_503" not in log_text


@_requires_db
def test_t091_pg_sync_account_dialer_dns_tcp_tls_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """t091_test_f001: Real dial_stream DNS gaierror, TCP ETIMEDOUT & TLS SSLCertVerificationError via ImapProvider -> AccountOut DTO."""
    Session = get_session_factory()
    aid, _ = _seed_pg_account_and_inbox(Session)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
    pkg_logger = logging.getLogger("mail_core")
    pkg_logger.addHandler(handler)
    try:
        def _fail_dns(*_a: object, **_k: object) -> list[object]:
            raise socket.gaierror(8, "nodename nor servname provided")

        imap_dns = ImapProvider(host="imap.example.test", port=993, username="u", password="p", timeout=5.0, security_policy=OutboundSecurityPolicy(allow_private_hosts=True), bulkhead=bulkhead_mod.EndpointBulkhead(failure_threshold=99))
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: imap_dns)
        with monkeypatch.context() as mp_dns:
            mp_dns.setattr(dial_mod.socket, "getaddrinfo", _fail_dns)
            jid_dns = _run_pg_job(Session, job_type=JobType.SYNC_ACCOUNT_FOLDERS, account_id=aid, payload={})
        with Session() as session:
            assert session.get(WorkerJob, jid_dns).last_error == "gaierror phase=dns errno=8"
            assert session.get(Account, aid).config["last_connectivity_error"] == "gaierror phase=dns errno=8"

        def _timeout_connect(_addr: tuple[str, int], _t: float) -> socket.socket:
            err_to = TimeoutError("timed out")
            err_to.errno = errno.ETIMEDOUT
            raise err_to

        imap_ip = ImapProvider(host="93.184.216.34", port=993, username="u", password="p", timeout=5.0, security_policy=OutboundSecurityPolicy(allow_private_hosts=True), bulkhead=bulkhead_mod.EndpointBulkhead(failure_threshold=99))
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: imap_ip)
        with monkeypatch.context() as mp_to:
            mp_to.setattr(dial_mod, "_default_connector", _timeout_connect)
            jid_to = _run_pg_job(Session, job_type=JobType.SYNC_ACCOUNT_FOLDERS, account_id=aid, payload={})
        exp_to = f"TimeoutError phase=tcp_connect errno={errno.ETIMEDOUT}"
        with Session() as session:
            assert session.get(WorkerJob, jid_to).last_error == exp_to
            assert session.get(Account, aid).config["last_connectivity_error"] == exp_to

        class _DummySock:
            def close(self) -> None:
                return None

        class _FailTlsCtx:
            def wrap_socket(self, _s: object, server_hostname: str | None = None) -> object:
                raise ssl.SSLCertVerificationError("hostname mismatch token=SECRET_TLS")

        with monkeypatch.context() as mp_tls:
            mp_tls.setattr(dial_mod, "_default_connector", lambda _a, _t: _DummySock())
            mp_tls.setattr(dial_mod.ssl, "create_default_context", lambda: _FailTlsCtx())
            jid_tls = _run_pg_job(Session, job_type=JobType.SYNC_ACCOUNT_FOLDERS, account_id=aid, payload={})
        with Session() as session:
            assert session.get(WorkerJob, jid_tls).last_error == "SSLCertVerificationError phase=tls"
            assert session.get(Account, aid).config["last_connectivity_error"] == "SSLCertVerificationError phase=tls"
        dto = next(item for item in list_accounts_app().accounts if item.id == str(aid))
        assert dto.last_connectivity_error == "SSLCertVerificationError phase=tls"
    finally:
        pkg_logger.removeHandler(handler)

    assert "gaierror phase=dns errno=8" in stream.getvalue()
    assert "SECRET_TLS" not in stream.getvalue()


@_requires_db
def test_t091_pg_sync_folder_metadata_conn_and_auth_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """t091_test_f001: SYNC_FOLDER_METADATA preserves ConnectionError DSN redaction and 401 auth state."""
    Session = get_session_factory()
    aid, inbox_id = _seed_pg_account_and_inbox(Session)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s"))
    pkg_logger = logging.getLogger("mail_core")
    pkg_logger.addHandler(handler)
    try:
        conn_exc = ConnectionError("connection failed: postgresql://user:my_secret_password@host/db?token=ya29.secret")
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(fetch_metadata_page=lambda *_a: (_ for _ in ()).throw(conn_exc)))
        jid_conn = _run_pg_job(Session, job_type=JobType.SYNC_FOLDER_METADATA, account_id=aid, payload={"folder_id": str(inbox_id)})
        with Session() as session:
            assert session.get(WorkerJob, jid_conn).last_error == "ConnectionError"
            assert session.get(Account, aid).config["last_connectivity_error"] == "ConnectionError"

        auth_exc = attach_failure_phase(PermanentAuthError("bad auth token=SECRET_401"), FailurePhase.AUTH)
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(fetch_metadata_page=lambda *_a: (_ for _ in ()).throw(auth_exc)))
        jid_auth = _run_pg_job(Session, job_type=JobType.SYNC_FOLDER_METADATA, account_id=aid, payload={"folder_id": str(inbox_id)})
        with Session() as session:
            assert session.get(WorkerJob, jid_auth).last_error == "PermanentAuthError phase=auth"
            assert session.get(Account, aid).credential_state == CredentialState.INVALID.value

        aid_401, inbox_401 = _seed_pg_account_and_inbox(Session)
        http_401 = attach_failure_phase(ProviderHttpError("bad 401 token=SECRET_401", status=401), FailurePhase.HTTP)
        monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: SimpleNamespace(fetch_metadata_page=lambda *_a: (_ for _ in ()).throw(http_401)))
        jid_401 = _run_pg_job(Session, job_type=JobType.SYNC_FOLDER_METADATA, account_id=aid_401, payload={"folder_id": str(inbox_401)})
        with Session() as session:
            assert session.get(WorkerJob, jid_401).last_error == "ProviderHttpError phase=http status=401"
            assert session.get(Account, aid_401).credential_state == CredentialState.INVALID.value
    finally:
        pkg_logger.removeHandler(handler)

    log_text = stream.getvalue()
    assert "PermanentAuthError phase=auth" in log_text
    assert "ProviderHttpError phase=http status=401" in log_text
    for secret in ("my_secret_password", "ya29.secret", "SECRET_401"):
        assert secret not in log_text


@_requires_db
def test_t091_pg_remote_push_imap_session_abort_retries_and_preserves_business_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """t091_code_f003: ImapProvider mid-session abort/timeout retries PENDING; non-transient business strings stay intact."""
    Session = get_session_factory()
    aid, _ = _seed_pg_account_and_inbox(Session)

    # 1. Single-folder mid-session IMAP4.abort via client_factory -> re-raised -> PENDING retry
    class _AbortUidClient:
        sock = None

        def login(self, _u: str, _p: str) -> tuple[str, list[bytes]]:
            return "OK", []

        def select(self, _mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            return "OK", [b"1"]

        def status(self, _mailbox: str, _spec: str) -> tuple[str, list[bytes]]:
            return "OK", [b"INBOX (UIDVALIDITY 10)"]

        def uid(self, *_a: object) -> tuple[str, list[bytes]]:
            raise imaplib.IMAP4.abort("connection dropped token=SECRET_PUSH")

        def logout(self) -> tuple[str, list[bytes]]:
            return "OK", []

    monkeypatch.setattr(
        remote_push_mod, "build_provider",
        lambda *a, **k: ImapProvider(host="93.184.216.34", port=993, username="u", password="p", client_factory=lambda *a, **k: _AbortUidClient()),
    )
    with Session() as session:
        op1 = RemoteOperation(
            id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}",
            op_type="mark_read", desired_state={"remote_id": "99", "is_read": True, "revision": 1},
            status=RemoteOperationStatus.PENDING.value,
        )
        session.add(op1)
        op1_id = op1.id
        session.commit()

    res1 = remote_push_mod.push_remote_operations(aid, worker_id="w-t091-push", execution_origin=ExecutionOrigin.BACKGROUND, store=object())
    assert res1["failed"] == 1
    with Session() as session:
        row1 = session.get(RemoteOperation, op1_id)
        assert row1.status == RemoteOperationStatus.PENDING.value
        assert row1.last_error == "IMAP4Abort phase=imap"
        assert row1.next_attempt_at is not None

    # 2. Partial multi-folder batch via real ImapProvider: INBOX op succeeds, Sent op hits TimeoutError -> INBOX DONE, Sent PENDING TimeoutError
    class _PartialGroupImapClient:
        sock = None

        def login(self, _u: str, _p: str) -> tuple[str, list[bytes]]:
            return "OK", []

        def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            if "Sent" in mailbox:
                raise TimeoutError("mid-batch timeout token=SECRET_TIMEOUT")
            return "OK", [b"1"]

        def status(self, mailbox: str, _spec: str) -> tuple[str, list[bytes]]:
            return "OK", [b"INBOX (UIDVALIDITY 10)"]

        def uid(self, cmd: str, *_a: object) -> tuple[str, list[bytes]]:
            if cmd == "FETCH":
                return "OK", [b"1 (UID 101 FLAGS (\\Seen))"]
            return "OK", [b"1 (UID 101 FLAGS (\\Seen))"]

        def logout(self) -> tuple[str, list[bytes]]:
            return "OK", []

    monkeypatch.setattr(
        remote_push_mod, "build_provider",
        lambda *a, **k: ImapProvider(host="93.184.216.34", port=993, username="u", password="p", client_factory=lambda *a, **k: _PartialGroupImapClient()),
    )
    with Session() as session:
        session.get(RemoteOperation, op1_id).status = RemoteOperationStatus.DONE.value
        op_ok = RemoteOperation(id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}", op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 10, 101), "folder_remote_id": "INBOX", "is_read": True, "revision": 1}, status=RemoteOperationStatus.PENDING.value)
        op_to = RemoteOperation(id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}", op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("Sent", 10, 102), "folder_remote_id": "Sent", "is_read": True, "revision": 1}, status=RemoteOperationStatus.PENDING.value)
        op_biz = RemoteOperation(id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}", op_type="move", desired_state={"remote_id": "bad-uid", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive", "revision": 1}, status=RemoteOperationStatus.PENDING.value)
        session.add_all([op_ok, op_to, op_biz])
        ids = (op_ok.id, op_to.id, op_biz.id)
        session.commit()

    res2 = remote_push_mod.push_remote_operations(aid, worker_id="w-t091-push", execution_origin=ExecutionOrigin.BACKGROUND, store=object())
    assert (res2["pushed"], res2["failed"]) == (1, 2)
    with Session() as session:
        r_ok, r_to, r_biz = (session.get(RemoteOperation, oid) for oid in ids)
        assert r_ok.status == RemoteOperationStatus.DONE.value
        assert (r_to.status, r_to.last_error) == (RemoteOperationStatus.PENDING.value, "TimeoutError")
        assert r_biz.status == RemoteOperationStatus.FAILED.value
        assert "invalid numeric UID" in (r_biz.last_error or "")

    # 3. Real non-structured business error string ("IMAP server does not support atomic MOVE/delete") stays intact
    class _BizFailProvider:
        def apply_remote_operations(self, ops: list[RemoteOperationItem]) -> list[tuple[uuid.UUID, RemoteOperationResult]]:
            return [(ops[0].op_id, RemoteOperationResult(success=False, error="IMAP server does not support atomic MOVE/delete"))]

    monkeypatch.setattr(remote_push_mod, "build_provider", lambda *a, **k: _BizFailProvider())
    with Session() as session:
        op_move = RemoteOperation(id=uuid.uuid4(), account_id=aid, entity_key=f"msg:{uuid.uuid4()}", op_type="move", desired_state={"remote_id": "imap:10:INBOX:103", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive", "revision": 1}, status=RemoteOperationStatus.PENDING.value)
        session.add(op_move)
        move_id = op_move.id
        session.commit()

    res3 = remote_push_mod.push_remote_operations(aid, worker_id="w-t091-push", execution_origin=ExecutionOrigin.BACKGROUND, store=object())
    assert res3["failed"] == 1
    with Session() as session:
        r_move = session.get(RemoteOperation, move_id)
        assert (r_move.status, r_move.last_error) == (RemoteOperationStatus.FAILED.value, "IMAP server does not support atomic MOVE/delete")
