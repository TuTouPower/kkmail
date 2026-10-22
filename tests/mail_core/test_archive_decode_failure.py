from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.api.app import app
from mail_core.blobs.archive import MimeParseError, run_archive_batch
from mail_core.blobs.crypto import Keyring
from mail_core.blobs.store import BlobStore
from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import get_message_detail
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage.models import (
    Account,
    Attachment,
    Folder,
    Message,
    MessageArchiveState,
    MessageBlob,
    MessageBlobLink,
    MessageBody,
)
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from tests.mail_core.conftest import TEST_API_KEY
import mail_core.blobs.archive as archive_mod
import mail_core.sync.engine as engine_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _setup_account_and_folder(session, store: DictCredentialStore):
    acc = create_account(
        session,
        email=f"decode-test-{uuid.uuid4().hex[:8]}@example.com",
        provider="memory",
        credential_ref="cred-ref",
    )
    folder = Folder(
        account_id=acc.id,
        name="INBOX",
        role="inbox",
        remote_id="INBOX",
    )
    session.add(folder)
    session.commit()
    return acc, folder


def test_archive_batch_body_decode_failure_and_batch_isolation(caplog):
    store = BlobStore(os.environ["MAIL_CORE_BLOB_ROOT"])

    raw_corrupt_body = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Corrupt Body\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n"
        b"Hello \xff\xfe corrupted\r\n"
    )
    raw_valid = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Valid Email\r\n"
        b"Content-Type: multipart/mixed; boundary=\"mix42\"\r\n\r\n"
        b"--mix42\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Valid plain text\r\n"
        b"--mix42\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"manual.pdf\"\r\n\r\n"
        b"%PDF-1.4 sample\r\n"
        b"--mix42--"
    )

    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta("msg-corrupt", "Corrupt Body", "alice@example.com", "Alice", now, False, False, uid=1),
            RemoteMessageMeta("msg-valid", "Valid Email", "alice@example.com", "Alice", now, False, True, uid=2),
        ],
        {
            "msg-corrupt": raw_corrupt_body,
            "msg-valid": raw_valid,
        },
    )

    orig_engine = engine_mod.build_provider
    orig_archive = archive_mod.build_provider
    engine_mod.build_provider = lambda *a, **kw: provider
    archive_mod.build_provider = lambda *a, **kw: provider
    cred_store = DictCredentialStore()
    set_credential_store(cred_store)
    Session = get_session_factory()

    try:
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, cred_store)
            account_id = acc.id

            m1 = Message(
                account_id=account_id,
                remote_id="msg-corrupt",
                subject="Corrupt Body",
                from_address="alice@example.com",
                sort_time=now,
            )
            m2 = Message(
                account_id=account_id,
                remote_id="msg-valid",
                subject="Valid Email",
                from_address="alice@example.com",
                sort_time=now,
            )
            session.add_all([m1, m2])
            session.flush()

            s1 = MessageArchiveState(message_id=m1.id, state=ArchiveState.ARCHIVE_PENDING.value)
            s2 = MessageArchiveState(message_id=m2.id, state=ArchiveState.ARCHIVE_PENDING.value)
            session.add_all([s1, s2])
            session.commit()
            mid_corrupt = m1.id
            mid_valid = m2.id

        with caplog.at_level(logging.WARNING, logger="mail_core.blobs.archive"):
            res = run_archive_batch(
                account_id=account_id,
                worker_id="test-worker",
                store=cred_store,
                payload={"batch_size": 10},
            )

        assert res["status"] == "ok"
        assert res["completed"] == 2

        with Session() as session:
            # 1. Corrupt message checks (AC-003, AC-004)
            st_corrupt = session.get(MessageArchiveState, mid_corrupt)
            assert st_corrupt.state == ArchiveState.ARCHIVE_COMPLETE.value

            link_corrupt = session.get(MessageBlobLink, mid_corrupt)
            assert link_corrupt is not None
            blob_corrupt = session.get(MessageBlob, link_corrupt.blob_id)
            assert blob_corrupt is not None
            # Raw MIME is preserved intact
            assert store.get(blob_corrupt.content_sha256) == raw_corrupt_body

            body_corrupt = session.get(MessageBody, mid_corrupt)
            assert body_corrupt is not None
            assert body_corrupt.parse_error is not None
            assert "body_decode_failed" in body_corrupt.parse_error or "UnicodeDecodeError" in body_corrupt.parse_error
            assert body_corrupt.text_plain is None
            assert body_corrupt.text_html is None

            # 2. Valid message in the same batch was NOT blocked (AC-004)
            st_valid = session.get(MessageArchiveState, mid_valid)
            assert st_valid.state == ArchiveState.ARCHIVE_COMPLETE.value

            body_valid = session.get(MessageBody, mid_valid)
            assert body_valid is not None
            assert body_valid.parse_error is None
            assert body_valid.text_plain == "Valid plain text"

            atts_valid = session.scalars(select(Attachment).where(Attachment.message_id == mid_valid)).all()
            assert len(atts_valid) == 1
            assert atts_valid[0].filename == "manual.pdf"

        # 3. Log redaction verification (AC-003): locates message and stage, no credentials/full body
        warning_logs = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
        matching_log = [log for log in warning_logs if str(mid_corrupt) in log]
        assert len(matching_log) == 1
        assert "stage=body" in matching_log[0] or "body_decode_failed" in matching_log[0]

        # 4. API endpoint verification (AC-006): HTTP 200 with parse_error
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        r_corrupt = client.get(f"/api/mail/messages/{mid_corrupt}")
        assert r_corrupt.status_code == 200
        data_corrupt = r_corrupt.json()
        assert data_corrupt["parse_error"] is not None
        assert "body_decode_failed" in data_corrupt["parse_error"] or "UnicodeDecodeError" in data_corrupt["parse_error"]
        assert data_corrupt["body"] == ""

        r_valid = client.get(f"/api/mail/messages/{mid_valid}")
        assert r_valid.status_code == 200
        data_valid = r_valid.json()
        assert data_valid["parse_error"] is None
        assert data_valid["body"] == "Valid plain text"
        assert len(data_valid["attachments"]) == 1

    finally:
        engine_mod.build_provider = orig_engine
        archive_mod.build_provider = orig_archive


def test_archive_batch_header_and_attachment_failures(caplog):
    store = BlobStore(os.environ["MAIL_CORE_BLOB_ROOT"])

    raw_bad_header = (
        b"From: =?unknown-charset?b?1234?=\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Bad Header MIME\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Body text\r\n"
    )
    raw_bad_attachment = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Bad Attachment MIME\r\n"
        b"Content-Type: multipart/mixed; boundary=\"b\"\r\n\r\n"
        b"--b\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Body text\r\n"
        b"--b\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename*=\"utf-8''%FF%FE%FD\"\r\n\r\n"
        b"PDF_DATA\r\n"
        b"--b--"
    )

    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta("msg-bad-hdr", "Bad Header", "alice@example.com", "Alice", now, False, False, uid=10),
            RemoteMessageMeta("msg-bad-att", "Bad Attachment", "alice@example.com", "Alice", now, False, True, uid=11),
        ],
        {
            "msg-bad-hdr": raw_bad_header,
            "msg-bad-att": raw_bad_attachment,
        },
    )

    orig_engine = engine_mod.build_provider
    orig_archive = archive_mod.build_provider
    engine_mod.build_provider = lambda *a, **kw: provider
    archive_mod.build_provider = lambda *a, **kw: provider
    cred_store = DictCredentialStore()
    set_credential_store(cred_store)
    Session = get_session_factory()

    try:
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, cred_store)
            account_id = acc.id

            m_hdr = Message(
                account_id=account_id,
                remote_id="msg-bad-hdr",
                subject="Bad Header",
                from_address="alice@example.com",
                sort_time=now,
            )
            m_att = Message(
                account_id=account_id,
                remote_id="msg-bad-att",
                subject="Bad Attachment",
                from_address="alice@example.com",
                sort_time=now,
            )
            session.add_all([m_hdr, m_att])
            session.flush()

            s_hdr = MessageArchiveState(message_id=m_hdr.id, state=ArchiveState.ARCHIVE_PENDING.value)
            s_att = MessageArchiveState(message_id=m_att.id, state=ArchiveState.ARCHIVE_PENDING.value)
            session.add_all([s_hdr, s_att])
            session.commit()
            mid_hdr = m_hdr.id
            mid_att = m_att.id

        with caplog.at_level(logging.WARNING, logger="mail_core.blobs.archive"):
            res = run_archive_batch(
                account_id=account_id,
                worker_id="test-worker",
                store=cred_store,
                payload={"batch_size": 10},
            )

        assert res["status"] == "ok"
        assert res["completed"] == 2

        with Session() as session:
            # Header error checks (AC-003)
            body_hdr = session.get(MessageBody, mid_hdr)
            assert body_hdr is not None
            assert body_hdr.parse_error is not None
            assert "header" in body_hdr.parse_error

            # Attachment error checks (AC-003)
            body_att = session.get(MessageBody, mid_att)
            assert body_att is not None
            assert body_att.parse_error is not None
            assert "attachment" in body_att.parse_error

        # API returns both errors with HTTP 200 (AC-006)
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        r_hdr = client.get(f"/api/mail/messages/{mid_hdr}")
        assert r_hdr.status_code == 200
        assert "header" in (r_hdr.json()["parse_error"] or "")

        r_att = client.get(f"/api/mail/messages/{mid_att}")
        assert r_att.status_code == 200
        assert "attachment" in (r_att.json()["parse_error"] or "")

    finally:
        engine_mod.build_provider = orig_engine
        archive_mod.build_provider = orig_archive


def test_read_does_not_mutate_or_scan_historical_data():
    """Verify that reading a message detail does not modify historical fields or perform speculative healing (AC-005)."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"hist-{uuid.uuid4().hex[:8]}@example.com",
            provider="memory",
            credential_ref="r",
        )
        session.add(acc)
        session.flush()

        now = datetime.now(timezone.utc)
        msg = Message(
            account_id=acc.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="Historical Message",
            from_address="manual-repair@example.com",
            sort_time=now,
            is_read=True,
            has_attachments=False,
            snippet="manually repaired content",
        )
        session.add(msg)
        session.flush()
        body = MessageBody(
            message_id=msg.id,
            text_plain="manually repaired plain content",
            text_html=None,
            parse_error=None,
            updated_at=now,
        )
        session.add(body)
        session.commit()
        mid = msg.id

    with Session() as session:
        detail = get_message_detail(session, mid)
        assert detail is not None
        assert detail.parse_error is None
        assert detail.body == "manually repaired plain content"

        # Verify DB records remain unchanged
        b_after = session.get(MessageBody, mid)
        assert b_after.text_plain == "manually repaired plain content"
        assert b_after.parse_error is None
        assert b_after.updated_at == now
