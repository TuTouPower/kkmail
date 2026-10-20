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
    assert fake_row.pause_reason is None
    assert fake_row.claimed_by is None
    assert session.add.called
