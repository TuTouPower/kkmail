from __future__ import annotations

from mail_core.blobs.archive import parse_mime_content


def test_parse_mime_plain_and_html():
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Test Email\r\n"
        b"Content-Type: multipart/alternative; boundary=\"boundary42\"\r\n\r\n"
        b"--boundary42\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Plain body text\r\n"
        b"--boundary42\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>HTML body text</p>\r\n"
        b"--boundary42--\r\n"
    )
    plain, html, atts = parse_mime_content(raw)
    assert plain == "Plain body text"
    assert html == "<p>HTML body text</p>"
    assert len(atts) == 0


def test_parse_mime_with_attachments_and_inlines():
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: With Attachment\r\n"
        b"Content-Type: multipart/mixed; boundary=\"mixed-boundary\"\r\n\r\n"
        b"--mixed-boundary\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello world\r\n"
        b"--mixed-boundary\r\n"
        b"Content-Type: application/pdf; name=\"doc.pdf\"\r\n"
        b"Content-Disposition: attachment; filename=\"doc.pdf\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"JVBERi0xLjQK\r\n"
        b"--mixed-boundary\r\n"
        b"Content-Type: image/png\r\n"
        b"Content-Disposition: inline\r\n"
        b"Content-ID: <logo123>\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n"
        b"iVBORw0KGgo=\r\n"
        b"--mixed-boundary--\r\n"
    )
    plain, html, atts = parse_mime_content(raw)
    assert plain == "Hello world"
    assert html is None
    assert len(atts) == 2

    # Verify attachment 1 (PDF)
    att1 = atts[0]
    assert att1["filename"] == "doc.pdf"
    assert att1["content_type"] == "application/pdf"
    assert att1["size_bytes"] == len(b"%PDF-1.4\n")
    assert not att1["is_inline"]

    # Verify attachment 2 (Inline image)
    att2 = atts[1]
    assert att2["content_type"] == "image/png"
    assert att2["content_id"] == "logo123"
    assert att2["is_inline"] is True


def test_resume_quota_paused_archives_transition():
    from mail_core.blobs.archive import resume_quota_paused_archives
    from mail_core.mail.domain import ArchiveState
    from unittest.mock import MagicMock
    import uuid

    session = MagicMock()
    fake_row = MagicMock()
    fake_row.state = ArchiveState.ARCHIVE_PAUSED_QUOTA.value
    acc_id = uuid.uuid4()
    fake_row.message_id = uuid.uuid4()
    session.scalars.return_value.all.return_value = [fake_row]

    resumed = resume_quota_paused_archives(session, account_id=acc_id)
    assert resumed == 1
    assert fake_row.state == ArchiveState.ARCHIVE_PENDING.value


def test_archive_distinguishes_mime_parse_from_storage_failures():
    from unittest.mock import MagicMock, patch
    import uuid
    from mail_core.blobs.archive import run_archive_batch
    from mail_core.mail.domain.enums import ArchiveState
    from mail_core.mail.storage.models import Account, Message, MessageArchiveState

    acc_id = uuid.uuid4()
    mid = uuid.uuid4()

    fake_state = MessageArchiveState(
        message_id=mid,
        state=ArchiveState.ARCHIVE_IN_PROGRESS.value,
        claimed_by="worker-1",
        retry_count=0,
    )
    fake_msg = Message(
        id=mid,
        account_id=acc_id,
        remote_id="remote-1",
    )
    fake_acc = Account(
        id=acc_id,
        email="test@example.com",
        provider="imap",
        credential_ref="cred-1",
        config={},
    )

    fake_session = MagicMock()
    fake_session.__enter__.return_value = fake_session
    fake_session.__exit__.return_value = False

    def get_mock(model, key):
        if model is MessageArchiveState and key == mid:
            return fake_state
        if model is Message and key == mid:
            return fake_msg
        if model is Account and key == acc_id:
            return fake_acc
        return None

    fake_session.get.side_effect = get_mock
    fake_session.scalars.return_value.all.return_value = []
    fake_session.scalar.return_value = None

    # Mock provider returning raw email with attachment
    fake_provider = MagicMock()
    fake_provider.fetch_mime.return_value = (
        b"From: a@b.c\r\nSubject: s\r\nContent-Type: multipart/mixed; boundary=\"b\"\r\n\r\n"
        b"--b\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
        b"--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"att.pdf\"\r\n\r\nPDF_DATA\r\n--b--"
    )

    fake_blob_store = MagicMock()
    # First put is for raw mime message (succeeds)
    # Second put is for attachment (fails with IOError)
    write_ok = MagicMock()
    write_ok.size_bytes = 100
    write_ok.content_sha256 = "sha256"
    write_ok.key_version = 1
    write_ok.storage_path = "p"

    call_count = [0]
    def put_side_effect(data):
        call_count[0] += 1
        if call_count[0] == 1:
            return write_ok
        raise OSError("Disk full / I/O error writing attachment")

    fake_blob_store.put.side_effect = put_side_effect

    fake_quota = MagicMock()
    fake_quota.paused = False
    fake_quota.used_bytes = 0
    fake_quota.hard_reached = False
    fake_quota.hard_exceeded = False
    fake_quota.soft_exceeded = False

    with (
        patch("mail_core.db.session.get_session_factory", return_value=lambda: fake_session),
        patch("mail_core.blobs.archive.BlobStore", return_value=fake_blob_store),
        patch("mail_core.blobs.archive.check_quota", return_value=fake_quota),
        patch("mail_core.blobs.archive.build_provider", return_value=fake_provider),
        patch("mail_core.blobs.archive.assert_fencing"),
            patch("mail_core.blobs.archive.acquire_lease"),
            patch("mail_core.blobs.archive.renew_lease"),
            patch("mail_core.blobs.archive.release_lease"),
        patch("mail_core.blobs.archive.enqueue_job"),
            patch("mail_core.blobs.archive.claim_archive_batch", return_value=[mid]),
    ):
        res = run_archive_batch(account_id=acc_id, worker_id="worker-1", payload={"batch_size": 1})

    # Must NOT be ARCHIVE_COMPLETE; must be ARCHIVE_PENDING with retry_count incremented
    assert fake_state.state == ArchiveState.ARCHIVE_PENDING.value
    assert fake_state.retry_count == 1
    assert "Disk full" in fake_state.last_error
    assert fake_state.claimed_by is None
