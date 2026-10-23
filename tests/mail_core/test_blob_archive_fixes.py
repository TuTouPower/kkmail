"""Tests for blob archive fixes:
- A25: Quota recovery rescheduling paused archives
- A26: Full-text search (FTS) index synchronization on body archive
- A35: Cross-process digest advisory lock and GC unlink race prevention
- A36: Strict hard quota reservation, sizing, and release
- A38: Stable MIME part identifier and attachment UUID preservation
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.blobs.archive import (
    maybe_resume_quota_paused_archives,
    parse_mime_content,
    resume_quota_paused_archives,
    run_archive_batch,
)
from mail_core.blobs.crypto import Keyring
from mail_core.blobs.gc import unlink_gc_paths
from mail_core.blobs.quota import (
    acquire_blob_digest_lock,
    check_quota,
    digest_to_lock_id,
    estimate_encrypted_size,
    get_active_reserved_bytes,
    prune_expired_quota_reservations,
    release_quota_reservation,
    reserve_quota,
)
from mail_core.blobs.store import BlobStore
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState, JobStatus, JobType
from mail_core.mail.storage.models import (
    Attachment,
    BlobQuotaReservation,
    Folder,
    Message,
    MessageArchiveState,
    MessageBlob,
    MessageBody,
    MessageSearch,
    WorkerJob,
)
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.search.index import search_messages
from mail_core.sync import sync_account_folders, sync_folder_metadata
import mail_core.blobs.archive as archive_mod
import mail_core.sync.engine as engine_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _setup_account_and_folder(session, store: DictCredentialStore):
    acc = create_account(
        session,
        email=f"blob-test-{uuid.uuid4().hex[:8]}@example.com",
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


def test_a25_quota_recovery_reschedules_paused_archives(tmp_path, monkeypatch):
    """A25: Paused quota archives are automatically resumed and reenqueued when capacity recovers."""
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    Session = get_session_factory()
    store = DictCredentialStore({"cred-ref": "pass"})
    set_credential_store(store)

    try:
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, store)
            account_id = acc.id
            msg = Message(
                account_id=account_id,
                remote_id="msg-paused-1",
                subject="Paused Msg",
                from_address="sender@example.com",
                sort_time=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.flush()

            st = MessageArchiveState(
                message_id=msg.id,
                state=ArchiveState.ARCHIVE_PAUSED_QUOTA.value,
                pause_reason="quota",
                claimed_by="dead-worker",
            )
            session.add(st)
            session.commit()
            mid = msg.id

        # Check recovery helper resets state to pending and enqueues job with dedupe_key
        resumed = maybe_resume_quota_paused_archives(account_id=account_id)
        assert resumed == 1

        with Session() as session:
            st = session.get(MessageArchiveState, mid)
            assert st.state == ArchiveState.ARCHIVE_PENDING.value
            assert st.pause_reason is None
            assert st.claimed_by is None

            # Verify deduplicated job enqueued
            job = session.scalar(
                select(WorkerJob)
                .where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                    WorkerJob.status == JobStatus.PENDING.value,
                )
            )
            assert job is not None
            assert job.dedupe_key == f"archive_mime_batch:{account_id}"

            # Idempotent call does not re-resume already pending tasks
            assert maybe_resume_quota_paused_archives(account_id=account_id) == 0
    finally:
        set_credential_store(None)


def test_a26_body_archive_synchronizes_fts_search(tmp_path, monkeypatch):
    """A26: Body parsing commits MessageBody and synchronously updates FTS in the same transaction."""
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    store = DictCredentialStore({"cred-ref": "pass"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    unique_keyword = f"raresecret_{uuid.uuid4().hex[:10]}"

    raw_mime = (
        "From: secret_sender@example.com\r\n"
        "To: me@example.com\r\n"
        "Subject: Meeting Notes\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"This contains our top secret keyword {unique_keyword} inside body text.\r\n"
    ).encode()

    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("m1", "Meeting Notes", "secret_sender@example.com", "Secret", now, False, False, uid=1)], {"m1": raw_mime})

    orig_engine = engine_mod.build_provider
    orig_archive = archive_mod.build_provider
    engine_mod.build_provider = lambda *a, **kw: provider
    archive_mod.build_provider = lambda *a, **kw: provider
    Session = get_session_factory()

    try:
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, store)
            account_id = acc.id
            msg = Message(
                account_id=account_id,
                remote_id="m1",
                subject="Meeting Notes",
                from_address="secret_sender@example.com",
                snippet="Meeting notes snippet without the keyword",
                sort_time=now,
            )
            session.add(msg)
            session.flush()
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.ARCHIVE_PENDING.value))
            session.commit()
            mid = msg.id

        result = run_archive_batch(
            account_id=account_id,
            worker_id="fts-worker",
            store=store,
            payload={"batch_size": 10},
        )
        assert result["status"] == "ok"
        assert result["completed"] == 1

        with Session() as session:
            # MessageBody recorded text
            body = session.get(MessageBody, mid)
            assert body is not None
            assert unique_keyword in body.text_plain

            # FTS message_search has the body text and can be queried
            search_row = session.get(MessageSearch, mid)
            assert search_row is not None
            assert unique_keyword in search_row.body_text

            hits = search_messages(session, account_ids=[account_id], query=unique_keyword)
            assert hits == [mid]
    finally:
        engine_mod.build_provider = orig_engine
        archive_mod.build_provider = orig_archive
        set_credential_store(None)


def test_a35_gc_digest_lock_and_race_prevention(tmp_path):
    """A35: Advisory lock serializes publish/unlink and GC safety check preserves newly referenced blobs."""
    Session = get_session_factory()
    digest = hashlib.sha256(b"shared-test-content-a35").hexdigest()
    lock_id = digest_to_lock_id(digest)

    # 1. Verify lock_id is within 64-bit signed integer range
    assert -(2**63) <= lock_id <= (2**63 - 1)

    # 2. Test advisory lock acquisition on Postgres
    with Session() as session:
        acquire_blob_digest_lock(session, digest)
        session.commit()

    # 3. Simulate race condition: GC prepares to unlink a file, but an active MessageBlob exists
    store = BlobStore(tmp_path)
    res = store.put(b"shared-test-content-a35")
    blob_path = store.path_for(res.content_sha256)
    assert blob_path.is_file()

    with Session() as session:
        blob = MessageBlob(
            content_sha256=res.content_sha256,
            key_version=res.key_version,
            size_bytes=res.size_bytes,
            storage_path=res.storage_path,
            ref_count=1,
        )
        session.add(blob)
        session.commit()

    # unlink_gc_paths should inspect the DB under lock and skip unlinking since live_refs > 0
    unlinked = unlink_gc_paths([blob_path])
    assert unlinked == 0
    assert blob_path.is_file(), "Active blob file must NOT be deleted by GC!"

    # Now simulate ref_count becoming 0 and blob deleted from DB
    with Session() as session:
        session.delete(blob)
        session.commit()

    # Now unlink succeeds
    unlinked2 = unlink_gc_paths([blob_path])
    assert unlinked2 == 1
    assert not blob_path.exists(), "Unreferenced blob file should now be deleted."


def test_a36_strict_hard_quota_reservation_and_release(tmp_path, monkeypatch):
    """A36: Sizing is based on actual ciphertext bytes; hard limit rejects oversized writes and cleans up reservations."""
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    Session = get_session_factory()
    store = BlobStore(tmp_path)

    # Test estimate_encrypted_size calculation
    pt = b"hello world"
    est = estimate_encrypted_size(len(pt))
    res = store.put(pt)
    assert res.size_bytes == est  # Exact ciphertext frame match

    # Test reserve_quota and release_quota_reservation
    worker_id = "test-worker-a36"
    with Session() as session:
        # Reserve under limit
        rid = reserve_quota(
            session,
            root=tmp_path,
            needed_bytes=1000,
            worker_id=worker_id,
            hard_limit_bytes=5000,
        )
        assert rid is not None
        session.commit()

        # Active reservations tracked
        active = get_active_reserved_bytes(session)
        assert active >= 1000

        # Excess reservation fails (1000 reserved + 4500 needed > 5000 hard limit)
        rid2 = reserve_quota(
            session,
            root=tmp_path,
            needed_bytes=4500,
            worker_id=worker_id,
            hard_limit_bytes=5000,
        )
        assert rid2 is None, "Should reject reservation that exceeds hard limit"

        # Release reservation
        release_quota_reservation(session, rid)
        session.commit()

        active_after = get_active_reserved_bytes(session)
        assert active_after == 0

    # Test pruning expired reservations
    with Session() as session:
        expired_res = BlobQuotaReservation(
            id=uuid.uuid4(),
            worker_id="crashed-worker",
            reserved_bytes=2000,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        session.add(expired_res)
        session.commit()

        pruned = prune_expired_quota_reservations(session)
        assert pruned >= 1
        session.commit()


def test_a38_multiple_attachments_same_filename_preserved_and_idempotent(tmp_path, monkeypatch):
    """A38: Stable MIME part identities preserve multiple attachments with the same name and no Content-ID."""
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    store = DictCredentialStore({"cred-ref": "pass"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)

    # MIME email containing two different attachments both named "invoice.pdf" and without Content-ID
    pdf1_content = b"%PDF-1.4 invoice version 1 content " + b"X" * 100
    pdf2_content = b"%PDF-1.4 invoice version 2 different content " + b"Y" * 100

    raw_mime = (
        b"From: billing@example.com\r\n"
        b"To: user@example.com\r\n"
        b"Subject: Two Invoices Attached\r\n"
        b"Content-Type: multipart/mixed; boundary=\"part-boundary\"\r\n\r\n"
        b"--part-boundary\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Please find both invoices attached.\r\n"
        b"--part-boundary\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"invoice.pdf\"\r\n\r\n"
        + pdf1_content
        + b"\r\n--part-boundary\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"invoice.pdf\"\r\n\r\n"
        + pdf2_content
        + b"\r\n--part-boundary--\r\n"
    )

    # 1. Verify parser produces distinct stable part_ids
    plain, html, atts = parse_mime_content(raw_mime)
    assert len(atts) == 2
    assert atts[0]["filename"] == "invoice.pdf"
    assert atts[1]["filename"] == "invoice.pdf"
    assert atts[0]["part_id"] != atts[1]["part_id"]
    assert atts[0]["data"] == pdf1_content
    assert atts[1]["data"] == pdf2_content

    # 2. Run archive batch and verify database preservation
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("inv-msg", "Invoices", "billing@example.com", "Billing", now, False, True, uid=10)], {"inv-msg": raw_mime})

    orig_engine = engine_mod.build_provider
    orig_archive = archive_mod.build_provider
    engine_mod.build_provider = lambda *a, **kw: provider
    archive_mod.build_provider = lambda *a, **kw: provider
    Session = get_session_factory()

    try:
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, store)
            account_id = acc.id
            msg = Message(
                account_id=account_id,
                remote_id="inv-msg",
                subject="Two Invoices Attached",
                from_address="billing@example.com",
                sort_time=now,
            )
            session.add(msg)
            session.flush()
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.ARCHIVE_PENDING.value))
            session.commit()
            mid = msg.id

        result = run_archive_batch(
            account_id=account_id,
            worker_id="att-worker",
            store=store,
            payload={"batch_size": 10},
        )
        assert result["status"] == "ok"
        assert result["completed"] == 1

        with Session() as session:
            db_atts = session.scalars(
                select(Attachment).where(Attachment.message_id == mid).order_by(Attachment.part_id.asc())
            ).all()
            assert len(db_atts) == 2, "Both attachments must be preserved, none silently dropped!"
            att1, att2 = db_atts
            assert att1.filename == "invoice.pdf"
            assert att2.filename == "invoice.pdf"
            assert att1.part_id != att2.part_id
            assert att1.blob_id != att2.blob_id
            att1_uuid = att1.id
            att2_uuid = att2.id

            # 3. Test archive replay idempotency: UUIDs must be preserved
            st = session.get(MessageArchiveState, mid)
            st.state = ArchiveState.ARCHIVE_PENDING.value
            session.commit()

        replay_result = run_archive_batch(
            account_id=account_id,
            worker_id="att-worker-replay",
            store=store,
            payload={"batch_size": 10},
        )
        assert replay_result["status"] == "ok"

        with Session() as session:
            replayed_atts = session.scalars(
                select(Attachment).where(Attachment.message_id == mid).order_by(Attachment.part_id.asc())
            ).all()
            assert len(replayed_atts) == 2
            assert replayed_atts[0].id == att1_uuid, "Existing attachment UUID must be preserved across replay"
            assert replayed_atts[1].id == att2_uuid, "Existing attachment UUID must be preserved across replay"
    finally:
        engine_mod.build_provider = orig_engine
        archive_mod.build_provider = orig_archive
        set_credential_store(None)


def test_archive_mime_backfills_only_missing_headers_and_preserves_provider_time(tmp_path):
    """MIME may fill missing subject but must not invent or replace provider received time."""
    cred_store = DictCredentialStore({"cred-ref": {"token": "secret"}})
    set_credential_store(cred_store)

    mime_with_empty_subject = (
        b"From: Restored Sender <restored@example.com>\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Restored Subject From MIME\r\n"
        b"Date: Sun, 20 Sep 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Hello restored world!\r\n"
    )
    mime_with_existing_subject = (
        b"From: Another Sender <another@example.com>\r\n"
        b"Subject: Must Not Replace Existing Subject\r\n"
        b"Date: Sun, 20 Sep 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello unknown date!\r\n"
    )
    mime_with_missing_subject = (
        b"From: Unknown Sender <unknown@example.com>\r\n"
        b"Subject: Backfilled Subject With Unknown Received Time\r\n"
        b"Date: Sun, 20 Sep 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello missing subject!\r\n"
    )

    received_time = datetime(2026, 10, 22, 9, 56, 0, tzinfo=timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta("m_empty_subject", "", "provider@example.com", "Provider", received_time, True, False, uid=11),
            RemoteMessageMeta("m_unknown_time", "Existing Subject", "known@example.com", "Known", None, True, False, uid=12),
            RemoteMessageMeta("m_unknown_time_missing_subject", "", "unknown@example.com", "Unknown", None, True, False, uid=13),
        ],
        {
            "m_empty_subject": mime_with_empty_subject,
            "m_unknown_time": mime_with_existing_subject,
            "m_unknown_time_missing_subject": mime_with_missing_subject,
        },
    )

    orig_engine = engine_mod.build_provider
    orig_archive = archive_mod.build_provider
    engine_mod.build_provider = lambda *a, **kw: provider
    archive_mod.build_provider = lambda *a, **kw: provider

    try:
        keyring = Keyring({1: b"A" * 32}, active_version=1)
        store = BlobStore(tmp_path / "blobs", keyring=keyring)

        Session = get_session_factory()
        with Session() as session:
            acc, folder = _setup_account_and_folder(session, cred_store)
            account_id = acc.id
            folder_id = folder.id

            msg = Message(
                account_id=account_id,
                remote_id="m_empty_subject",
                subject="",
                from_address="provider@example.com",
                from_name="Provider",
                sort_time=received_time,
            )
            unknown = Message(
                account_id=account_id,
                remote_id="m_unknown_time",
                subject="Existing Subject",
                from_address="known@example.com",
                from_name="Known",
                sort_time=None,
            )
            unknown_with_missing_subject = Message(
                account_id=account_id,
                remote_id="m_unknown_time_missing_subject",
                subject="",
                from_address="unknown@example.com",
                from_name="Unknown",
                sort_time=None,
            )
            session.add(msg)
            session.add(unknown)
            session.add(unknown_with_missing_subject)
            session.flush()
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.ARCHIVE_PENDING.value))
            session.add(
                MessageArchiveState(
                    message_id=unknown.id,
                    state=ArchiveState.METADATA_SYNCED.value,
                    priority=99,
                )
            )
            session.add(
                MessageArchiveState(
                    message_id=unknown_with_missing_subject.id,
                    state=ArchiveState.ARCHIVE_PENDING.value,
                )
            )
            session.commit()
            mids = {
                msg.remote_id: msg.id,
                unknown.remote_id: unknown.id,
                unknown_with_missing_subject.remote_id: unknown_with_missing_subject.id,
            }

        result = run_archive_batch(
            account_id=account_id,
            worker_id="backfill-worker",
            store=store,
            payload={"batch_size": 10},
        )
        assert result["status"] == "ok"
        assert result["completed"] == 3

        with Session() as session:
            repaired_msg = session.get(Message, mids["m_empty_subject"])
            unknown_time_msg = session.get(Message, mids["m_unknown_time"])
            unknown_subject_msg = session.get(Message, mids["m_unknown_time_missing_subject"])
            assert repaired_msg is not None
            assert unknown_time_msg is not None
            assert unknown_subject_msg is not None
            assert repaired_msg.subject == "Restored Subject From MIME"
            assert repaired_msg.from_address == "provider@example.com"
            assert repaired_msg.from_name == "Provider"
            assert repaired_msg.sort_time == received_time
            assert unknown_time_msg.subject == "Existing Subject"
            assert unknown_time_msg.from_address == "known@example.com"
            assert unknown_time_msg.sort_time is None
            assert unknown_subject_msg.subject == "Backfilled Subject With Unknown Received Time"
            assert unknown_subject_msg.from_address == "unknown@example.com"
            assert unknown_subject_msg.sort_time is None

            # FTS must also reflect the backfilled subject and sender
            search_row = session.get(MessageSearch, mids["m_empty_subject"])
            assert search_row is not None
            assert search_row.subject == "Restored Subject From MIME"
            assert "provider@example.com" in search_row.from_text
    finally:
        engine_mod.build_provider = orig_engine
        archive_mod.build_provider = orig_archive
        set_credential_store(None)
