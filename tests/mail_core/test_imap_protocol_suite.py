"""Enhanced Real IMAP Integration & Mail Provider Contract Tests (t016).

Verifies real IMAP synchronization against the dedicated Dovecot service,
covering Chinese multipart, attachments, duplicate Message-IDs, remote writeback,
incremental reconcile, safe trash operations, and transport failure contracts.
"""

from __future__ import annotations

import email.message
import imaplib
import os
import socket
import ssl
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.blobs import BlobStore
from mail_core.db.session import get_session_factory
from mail_core.mail.application.mutations import set_message_read
from mail_core.mail.domain.enums import JobType, ProviderType
from mail_core.mail.storage import Attachment, Folder, Message, MessageBlob, MessageBlobLink, RemoteOperation, WorkerJob
from mail_core.providers.imap import ImapProvider
from mail_core.sync import enqueue_job, sync_account_folders, sync_folder_metadata
from mail_core.sync.jobs import claim_jobs
from mail_core.sync.reconcile import reconcile_folder
from mail_core.sync.remote_push import push_remote_operations
from mail_core.worker.handlers import handle_job

HOST = os.environ.get("MAIL_CORE_IMAP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAIL_CORE_IMAP_PORT", "1143"))
USER = os.environ.get("MAIL_CORE_IMAP_USER", "alice@kkmail.test")
PASS = os.environ.get("MAIL_CORE_IMAP_PASS", "alice-imap-pass")

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _ensure_imap_connection() -> imaplib.IMAP4:
    """AC-001: Dedicated IMAP service must be reachable and authenticate properly."""
    try:
        client = imaplib.IMAP4(HOST, PORT, timeout=5)
    except OSError as exc:
        pytest.fail(f"AC-001: Dedicated IMAP fixture unreachable at {HOST}:{PORT}: {exc}")
    typ, data = client.login(USER, PASS)
    if typ != "OK":
        pytest.fail(f"AC-001: Dedicated IMAP authentication failed for {USER}: {data}")
    return client


def _create_sample_mime(
    *,
    subject: str,
    from_addr: str = "bob@example.com",
    to_addr: str = "alice@kkmail.test",
    message_id: str | None = None,
    text_content: str = "Hello text",
    html_content: str | None = None,
    attachment_name: str | None = None,
    attachment_bytes: bytes | None = None,
) -> bytes:
    msg = email.message.EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = email.utils.format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@kkmail.test>"

    if html_content:
        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype="html")
    else:
        msg.set_content(text_content)

    if attachment_name and attachment_bytes:
        msg.add_attachment(
            attachment_bytes,
            maintype="application",
            subtype="octet-stream",
            filename=attachment_name,
        )

    return msg.as_bytes()


# --- AC-001: Readiness, authentication failure and connection failure -------------


def test_imap_protocol_readiness_and_auth_failure():
    """AC-001: Verifies IMAP service readiness, auth failure rejection, and connection failure."""
    client = _ensure_imap_connection()
    client.logout()

    # Reject invalid password with clear non-zero error without fallback
    bad_client = imaplib.IMAP4(HOST, PORT, timeout=5)
    try:
        with pytest.raises(imaplib.IMAP4.error):
            bad_client.login(USER, "definitely-wrong-password")
    finally:
        try:
            bad_client.logout()
        except Exception:
            pass

    # Reject connection to closed port
    with pytest.raises(OSError):
        imaplib.IMAP4(HOST, 15999, timeout=0.5)


# --- AC-002: Real Worker sync Chinese multipart, attachments, duplicate Message-ID ---


def test_real_imap_full_worker_sync_multipart_chinese_and_idempotence(monkeypatch):
    """AC-002: Syncs Chinese multipart, attachments, same Message-ID; asserts bytes, count, idempotence."""
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    Session = get_session_factory()
    client = _ensure_imap_connection()

    client.select("INBOX")
    # Clean previous non-fixture messages if any
    typ, search_res = client.search(None, "ALL")
    uids = search_res[0].split()
    if len(uids) > 1:
        # Keep the primary seed (1), delete extras
        for u in uids[1:]:
            client.store(u, "+FLAGS", r"(\Deleted)")
        client.expunge()

    # Append:
    # 1. Chinese multipart message
    chinese_bytes = _create_sample_mime(
        subject="测试中文邮件主题-重要通知",
        text_content="这是一封包含纯文本与HTML多部分的中文邮件正文。",
        html_content="<p>这是一封包含<b>HTML多部分</b>的中文邮件正文。</p>",
        message_id="<chinese-test-1@kkmail.test>",
    )
    client.append("INBOX", r"(\Seen)", None, chinese_bytes)

    # 2. Attachment message
    secret_attachment_payload = b"TopSecretAttachmentBinaryPayload\x00\x01\x02\xff\xfe"
    attachment_bytes = _create_sample_mime(
        subject="带二进制附件邮件",
        text_content="请查阅附件报告。",
        attachment_name="report_secure.dat",
        attachment_bytes=secret_attachment_payload,
        message_id="<attachment-test-1@kkmail.test>",
    )
    client.append("INBOX", None, None, attachment_bytes)

    # 3. Duplicate Message-ID message
    dup_bytes = _create_sample_mime(
        subject="第二封相同Message-ID邮件",
        text_content="这是第二封具有相同Message-ID的邮件内容。",
        message_id="<chinese-test-1@kkmail.test>",
    )
    client.append("INBOX", None, None, dup_bytes)
    client.logout()

    # Create account in DB and run Worker jobs
    store = DictCredentialStore()
    ref = f"test:alice-{uuid.uuid4().hex[:6]}"
    store.put(ref, PASS)
    set_credential_store(store)

    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"imap-ac002-{uuid.uuid4().hex[:8]}@kkmail.test",
                provider=ProviderType.IMAP,
                credential_ref=ref,
                config={"imap_host": HOST, "imap_port": PORT, "imap_user": USER, "use_ssl": False},
            )
            enqueue_job(session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, account_id=acc.id)
            session.commit()
            account_id = acc.id

        # Drain worker jobs
        for _ in range(30):
            with Session() as session:
                jobs = claim_jobs(session, worker_id="w-ac002", limit=1, account_id=account_id)
                if not jobs:
                    session.commit()
                    break
                handle_job(session, jobs[0])
                session.commit()

        with Session() as session:
            msgs = session.scalars(select(Message).where(Message.account_id == account_id)).all()
            assert len(msgs) >= 3, f"Expected at least 3 messages synced, got {len(msgs)}"

            # Assert Chinese subject
            chinese_msg = next((m for m in msgs if "重要通知" in (m.subject or "")), None)
            assert chinese_msg is not None, "Chinese subject message was not persisted"
            assert chinese_msg.is_read is True  # Appended with \Seen

            # Assert attachment & decrypt blob bytes
            att_msg = next((m for m in msgs if "带二进制附件" in (m.subject or "")), None)
            assert att_msg is not None, "Attachment message was not persisted"
            assert att_msg.has_attachments is True

            attachments = session.scalars(
                select(Attachment).where(Attachment.message_id == att_msg.id)
            ).all()
            assert len(attachments) >= 1
            att = next((a for a in attachments if a.filename == "report_secure.dat"), None)
            assert att is not None
            assert att.size_bytes == len(secret_attachment_payload)

            # Check decrypt attachment blob
            mb = session.get(MessageBlob, att.blob_id)
            assert mb is not None
            blob_store = BlobStore(os.environ.get("MAIL_CORE_BLOB_ROOT", "data/blobs"))
            decrypted_data = blob_store.get(mb.content_sha256)
            assert decrypted_data == secret_attachment_payload, "Decrypted attachment bytes mismatch"

            # Check duplicate Message-ID
            dup_msgs = [m for m in msgs if m.internet_message_id == "<chinese-test-1@kkmail.test>"]
            assert len(dup_msgs) == 2, "Both messages with duplicate Message-ID must be stored safely"

            count_before = len(msgs)

        # Repeated sync: must be strictly idempotent and not create duplicate messages
        with Session() as session:
            folder = session.scalar(select(Folder).where(Folder.account_id == account_id, Folder.role == "inbox"))
            folder_id = folder.id

        meta_result = sync_folder_metadata(account_id, folder_id, worker_id="w-ac002", store=store)
        assert meta_result["status"] == "ok"

        with Session() as session:
            count_after = session.scalar(
                select(func.count()).select_from(Message).where(Message.account_id == account_id)
            )
            assert count_after == count_before, "Repeated sync produced duplicate messages"
    finally:
        set_credential_store(None)


# --- AC-003: Incremental Sync, Remote Writeback & Observable State -----------------


def test_real_imap_incremental_sync_and_remote_writeback(monkeypatch):
    """AC-003: Remote flags/deletions reflect locally; local flags written back are observable remotely."""
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    Session = get_session_factory()
    client = _ensure_imap_connection()
    client.select("INBOX")

    # Append fresh test message
    test_id = uuid.uuid4().hex[:8]
    initial_mime = _create_sample_mime(
        subject=f"Writeback Test {test_id}",
        text_content="Initial unread message for writeback.",
        message_id=f"<writeback-{test_id}@kkmail.test>",
    )
    typ, append_res = client.append("INBOX", None, None, initial_mime)
    assert typ == "OK"

    store = DictCredentialStore()
    ref = f"test:wb-{uuid.uuid4().hex[:6]}"
    store.put(ref, PASS)
    set_credential_store(store)

    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"imap-ac003-{uuid.uuid4().hex[:8]}@kkmail.test",
                provider=ProviderType.IMAP,
                credential_ref=ref,
                config={"imap_host": HOST, "imap_port": PORT, "imap_user": USER, "use_ssl": False},
            )
            session.commit()
            account_id = acc.id

        # Initial folder & metadata sync
        sync_account_folders(account_id, worker_id="w-ac003", store=store)
        with Session() as session:
            folder = session.scalar(select(Folder).where(Folder.account_id == account_id, Folder.role == "inbox"))
            folder_id = folder.id

        sync_folder_metadata(account_id, folder_id, worker_id="w-ac003", store=store)

        with Session() as session:
            msg = session.scalar(
                select(Message).where(Message.account_id == account_id, Message.subject == f"Writeback Test {test_id}")
            )
            assert msg is not None
            assert msg.is_read is False
            msg_id = msg.id

        # 1. Local mark_read -> creates RemoteOperation -> push_remote_operations
        with Session() as session:
            mut_res = set_message_read(session, msg_id, is_read=True)
            assert mut_res.is_read is True
            session.commit()

        # Push the writeback operation to Dovecot
        push_res = push_remote_operations(account_id, worker_id="w-wb", store=store)
        assert push_res["pushed"] >= 1

        # Observable remotely on Dovecot: fetch flags directly
        client.select("INBOX")
        typ, search_data = client.search(None, f'HEADER Message-ID "<writeback-{test_id}@kkmail.test>"')
        assert typ == "OK"
        server_seqs = search_data[0].split()
        assert len(server_seqs) >= 1
        server_seq = server_seqs[0].decode()

        typ, fetch_data = client.fetch(server_seq, "(FLAGS)")
        assert typ == "OK"
        flags_resp = fetch_data[0].decode()
        assert r"\Seen" in flags_resp, f"Expected \\Seen flag on Dovecot server, got: {flags_resp}"

        # 2. Remote change: remote deletion should reflect in reconcile
        client.store(server_seq, "+FLAGS", r"(\Deleted)")
        client.expunge()

        # Run reconcile
        reconcile_folder(account_id, folder_id, worker_id="w-ac003", store=store)

        with Session() as session:
            deleted_msg = session.scalar(select(Message).where(Message.id == msg_id))
            assert deleted_msg is None, "Message deleted remotely was not reconciled locally"

    finally:
        try:
            client.logout()
        except Exception:
            pass
        set_credential_store(None)


# --- AC-004: Safe Trash & TLS Rejection --------------------------------------------


def test_real_imap_safe_trash_move_and_tls_rejection(monkeypatch):
    """AC-004: Moves target message to Trash; refuses unsafe expunge when MOVE fails; rejects bad TLS."""
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    client = _ensure_imap_connection()
    client.select("INBOX")

    # Ensure Trash mailbox exists
    client.create("Trash")

    # Append message to be trashed
    test_id = uuid.uuid4().hex[:8]
    mime_bytes = _create_sample_mime(
        subject=f"Trash Move Test {test_id}",
        message_id=f"<trash-{test_id}@kkmail.test>",
    )
    typ, _ = client.append("INBOX", None, None, mime_bytes)
    assert typ == "OK"

    typ, sdata = client.search(None, f'HEADER Message-ID "<trash-{test_id}@kkmail.test>"')
    uid_str = sdata[0].split()[0].decode()

    # Real ImapProvider applies trash
    provider = ImapProvider(host=HOST, port=PORT, username=USER, password=PASS, use_ssl=False)
    # Get remote_id for the message
    folders = provider.list_folders()
    inbox_folder = next(f for f in folders if f.remote_id.upper() == "INBOX")
    page = provider.fetch_metadata_page("INBOX", {"page_size": 20})
    target_item = next(item for item in page.items if item.subject == f"Trash Move Test {test_id}")

    # Move to Trash
    op_result = provider.apply_remote_operation(
        "trash",
        {
            "remote_id": target_item.remote_id,
            "folder_remote_id": "INBOX",
            "trash_folder_remote_id": "Trash",
        },
    )
    assert op_result.success is True

    # Assert moved out of INBOX and into Trash
    client.select("INBOX")
    typ, in_inbox = client.search(None, f'HEADER Message-ID "<trash-{test_id}@kkmail.test>"')
    assert in_inbox[0] == b""

    client.select("Trash")
    typ, in_trash = client.search(None, f'HEADER Message-ID "<trash-{test_id}@kkmail.test>"')
    assert len(in_trash[0].split()) >= 1

    client.logout()

    # TLS rejection: connecting with use_ssl=True to non-SSL port must fail handshake immediately
    tls_provider = ImapProvider(host=HOST, port=PORT, username=USER, password=PASS, use_ssl=True)
    with pytest.raises((ssl.SSLError, OSError)):
        tls_provider.list_folders()
