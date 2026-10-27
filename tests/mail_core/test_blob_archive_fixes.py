"""Tests for blob archive fixes:
- A25: Quota recovery rescheduling paused archives
- A26: Full-text search (FTS) index synchronization on body archive
- A35: Cross-process digest advisory lock and GC unlink race prevention
- A36: Strict hard quota reservation, sizing, and release
- A38: Stable MIME part identifier and attachment UUID preservation
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

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
    QuotaExceededError,
    acquire_blob_digest_lock,
    check_quota,
    digest_to_lock_id,
    estimate_encrypted_size,
    get_active_reserved_bytes,
    prune_expired_quota_reservations,
    release_quota_reservation,
    reserve_quota,
)
import mail_core.blobs.quota as quota_mod
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
    MessageBlobLink,
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
    unlinked = unlink_gc_paths([blob_path], root=tmp_path)
    assert unlinked == 0
    assert blob_path.is_file(), "Active blob file must NOT be deleted by GC!"

    # Now simulate ref_count becoming 0 and blob deleted from DB
    with Session() as session:
        session.delete(blob)
        session.commit()

    # Now unlink succeeds
    unlinked2 = unlink_gc_paths([blob_path], root=tmp_path)
    assert unlinked2 == 1
    assert not blob_path.exists(), "Unreferenced blob file should now be deleted."


def test_a26_mime_publish_holds_digest_lock_against_gc(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_V1", base64.b64encode(b"A" * 32).decode())
    monkeypatch.setenv("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")
    store = DictCredentialStore({"cred-ref": "pass"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    raw_mime = (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Digest lock race\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"The file must survive concurrent GC.\r\n"
    )
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [RemoteMessageMeta("mime-race", "Digest lock race", "sender@example.com", "Sender", now, False, False, uid=1)],
        {"mime-race": raw_mime},
    )
    monkeypatch.setattr(engine_mod, "build_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(archive_mod, "build_provider", lambda *args, **kwargs: provider)
    original_put = BlobStore.put
    published = threading.Event()
    allow_archive = threading.Event()
    put_timeout = 10

    def publish_then_pause(blob_store, data):
        result = original_put(blob_store, data)
        if data == raw_mime:
            published.set()
            if not allow_archive.wait(put_timeout):
                raise TimeoutError("test did not release MIME publication")
        return result

    monkeypatch.setattr(BlobStore, "put", publish_then_pause)
    Session = get_session_factory()
    pool = ThreadPoolExecutor(max_workers=2)
    archive_future = None
    gc_future = None
    waiting_for_digest_lock = False
    try:
        with Session() as session:
            account, folder = _setup_account_and_folder(session, store)
            message = Message(
                account_id=account.id,
                remote_id="mime-race",
                subject="Digest lock race",
                from_address="sender@example.com",
                sort_time=now,
            )
            session.add(message)
            session.flush()
            session.add(MessageArchiveState(message_id=message.id, state=ArchiveState.ARCHIVE_PENDING.value))
            session.commit()
            account_id = account.id
            message_id = message.id

        archive_future = pool.submit(
            run_archive_batch,
            account_id=account_id,
            worker_id="mime-publish-worker",
            store=store,
            payload={"batch_size": 10},
        )
        assert published.wait(10), "archive did not publish the MIME blob"
        digest = hashlib.sha256(raw_mime).hexdigest()
        blob_path = BlobStore(tmp_path, keyring=Keyring({1: b"A" * 32}, active_version=1)).path_for(digest)
        assert blob_path.is_file()

        gc_started = threading.Event()

        def gc_unlink():
            gc_started.set()
            return unlink_gc_paths([blob_path], root=tmp_path)

        gc_future = pool.submit(gc_unlink)
        assert gc_started.wait(5)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not gc_future.done():
            with Session() as session:
                waiting_for_digest_lock = bool(
                    session.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE locktype = 'advisory' AND NOT granted "
                            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()))"
                        )
                    )
                )
            if waiting_for_digest_lock:
                break
            time.sleep(0.02)

        allow_archive.set()
        archive_result = archive_future.result(timeout=15)
        gc_unlinked = gc_future.result(timeout=15)
        assert waiting_for_digest_lock, "GC did not wait on the publisher's digest lock"
        assert archive_result["status"] == "ok"
        assert archive_result["completed"] == 1
        assert gc_unlinked == 0
        assert blob_path.is_file()
        with Session() as session:
            blob = session.scalar(select(MessageBlob).where(MessageBlob.content_sha256 == digest))
            assert blob is not None
            assert session.get(MessageBlobLink, message_id) is not None
        assert BlobStore(tmp_path, keyring=Keyring({1: b"A" * 32}, active_version=1)).get(digest) == raw_mime
    finally:
        allow_archive.set()
        pool.shutdown(wait=True)
        set_credential_store(None)


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

        # Excess reservation is rejected (A108: raises QuotaExceededError,
        # no longer an ambiguous None shared with "nothing to reserve").
        with pytest.raises(QuotaExceededError):
            reserve_quota(
                session,
                root=tmp_path,
                needed_bytes=4500,
                worker_id=worker_id,
                hard_limit_bytes=5000,
            )

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


def test_a23_concurrent_hard_quota_reservations_cannot_oversubscribe(tmp_path, monkeypatch):
    Session = get_session_factory()
    get_active = quota_mod.get_active_reserved_bytes
    with Session() as session:
        baseline_reserved = get_active(session)

    def delay_after_read(session, now=None):
        reserved = get_active(session, now=now)
        time.sleep(0.5)
        return reserved

    monkeypatch.setattr(quota_mod, "get_active_reserved_bytes", delay_after_read)
    start = threading.Barrier(2)

    def reserve(worker_id: str):
        with Session() as session:
            start.wait(timeout=5)
            try:
                reservation_id = reserve_quota(
                    session,
                    root=tmp_path,
                    needed_bytes=60,
                    worker_id=worker_id,
                    hard_limit_bytes=baseline_reserved + 100,
                )
            except QuotaExceededError:
                # A108: the losing reservation raises instead of returning
                # None; None here is this test's own "rejected" sentinel.
                session.commit()
                return None
            session.commit()
            return reservation_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("quota-a", "quota-b")))

    assert sum(result is not None for result in results) == 1
    with Session() as session:
        assert get_active(session) == baseline_reserved + 60


def test_a23_quota_advisory_lock_releases_on_commit_and_rollback(tmp_path):
    Session = get_session_factory()
    with Session() as session:
        baseline_reserved = get_active_reserved_bytes(session)
    lock_params = {
        "namespace": quota_mod.QUOTA_RESERVATION_LOCK_NAMESPACE,
        "resource": quota_mod.QUOTA_RESERVATION_LOCK_RESOURCE,
    }
    try_lock = text("SELECT pg_try_advisory_xact_lock(:namespace, :resource)")

    with Session() as first:
        assert reserve_quota(
            first,
            root=tmp_path,
            needed_bytes=60,
            worker_id="quota-rollback",
            hard_limit_bytes=baseline_reserved + 100,
        ) is not None
        with Session() as second:
            assert second.scalar(try_lock, lock_params) is False
            second.rollback()
        first.rollback()

    with Session() as after_rollback:
        assert after_rollback.scalar(try_lock, lock_params) is True
        after_rollback.rollback()

    with Session() as rejected:
        with pytest.raises(QuotaExceededError):
            reserve_quota(
                rejected,
                root=tmp_path,
                needed_bytes=200,
                worker_id="quota-rejected",
                hard_limit_bytes=baseline_reserved + 100,
            )
        with Session() as second:
            assert second.scalar(try_lock, lock_params) is False
            second.rollback()
        rejected.commit()

    with Session() as after_rejection:
        assert after_rejection.scalar(try_lock, lock_params) is True
        after_rejection.rollback()


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
