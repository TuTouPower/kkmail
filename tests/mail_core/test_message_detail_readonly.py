from types import SimpleNamespace
import uuid
from unittest.mock import Mock

from mail_core.mail.application import message_details
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage.models import Message, MessageArchiveState


def test_detail_with_archive_status_does_not_mutate_or_enqueue(monkeypatch):
    message_id = uuid.uuid4()
    detail = SimpleNamespace(account_id=uuid.uuid4(), parse_error=None)
    state = SimpleNamespace(state=ArchiveState.METADATA_SYNCED.value, priority=2)
    message = SimpleNamespace(remote_id="remote-message")
    session = Mock()
    session.get.side_effect = lambda model, _message_id: {
        MessageArchiveState: state,
        Message: message,
    }.get(model)
    enqueue = Mock()
    monkeypatch.setattr(message_details, "get_message_detail", lambda *_args: detail)
    monkeypatch.setattr(message_details, "enqueue_job", enqueue)

    result = message_details.get_message_detail_with_archive_status(session, message_id)

    assert result == (detail, False)
    assert state.priority == 2
    enqueue.assert_not_called()
    session.commit.assert_not_called()


def test_sync_message_body_only_enqueues_high_priority_archive(monkeypatch):
    message_id = uuid.uuid4()
    account_id = uuid.uuid4()
    job_id = uuid.uuid4()
    state = SimpleNamespace(
        state=ArchiveState.METADATA_SYNCED.value,
        priority=2,
        retry_count=0,
        last_error=None,
        pause_reason=None,
        claimed_by=None,
        claimed_at=None,
        updated_at=None,
    )
    message = SimpleNamespace(account_id=account_id, remote_id="verified-remote-id")
    session = Mock()
    session.get.side_effect = lambda model, _message_id: {
        Message: message,
        MessageArchiveState: state,
    }.get(model)

    class SessionFactory:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            return False

    enqueue = Mock(return_value=SimpleNamespace(id=job_id))
    run_archive_batch = Mock()
    monkeypatch.setattr(message_details, "get_session_factory", lambda: SessionFactory)
    monkeypatch.setattr(message_details, "enqueue_job", enqueue)
    monkeypatch.setattr("mail_core.blobs.archive.run_archive_batch", run_archive_batch)

    result = message_details.sync_message_body(message_id)

    assert result == job_id
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.priority == 0
    enqueue.assert_called_once()
    run_archive_batch.assert_not_called()
    session.commit.assert_called_once()


def test_sync_body_route_returns_accepted_job_contract(monkeypatch):
    from fastapi.testclient import TestClient

    from mail_core.api import mail
    from mail_core.api.app import app
    from tests.mail_core.conftest import TEST_API_KEY

    message_id = uuid.uuid4()
    job_id = uuid.uuid4()
    monkeypatch.setattr(mail, "sync_message_body", lambda _message_id: job_id)
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    response = client.post(f"/api/mail/messages/{message_id}/sync-body")

    assert response.status_code == 202
    assert response.json() == {
        "message_id": str(message_id),
        "job_id": str(job_id),
        "status": "queued",
    }

def test_detail_out_serializes_shared_detail_and_attachment_fields():
    from mail_core.api.mail import _detail_out
    from mail_core.mail.application.queries import AttachmentItem, MessageDetail

    message_id, account_id, attachment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    detail = MessageDetail(
        id=message_id,
        account_id=account_id,
        subject="Subject",
        from_address="sender@example.test",
        from_name="Sender",
        to_addresses=["to@example.test"],
        cc_addresses=["cc@example.test"],
        sort_time=None,
        is_read=False,
        is_flagged=True,
        has_attachments=True,
        snippet="Snippet",
        body_text="Body",
        body_html=None,
        body="Body",
        body_type="text",
        parse_error=None,
        attachments=[
            AttachmentItem(
                id=attachment_id,
                filename="part.txt",
                content_type="text/plain",
                size_bytes=4,
                is_inline=False,
            )
        ],
    )

    result = _detail_out(detail, True)

    assert result.id == str(message_id)
    assert result.from_ == "Sender <sender@example.test>"
    assert result.to == "to@example.test"
    assert result.cc == "cc@example.test"
    assert result.is_archived is True
    assert result.attachments[0].contentType == "text/plain"


def test_detail_out_structures_recipient_addresses_and_keeps_unparseable_text():
    from mail_core.api.mail import _detail_out
    from mail_core.mail.application.queries import MessageDetail

    detail = MessageDetail(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        subject="Recipients",
        from_address="sender@example.test",
        from_name="Sender",
        to_addresses=[
            '"Doe, Jane" <jane@example.test>, Team <team@example.test>',
            "malformed recipient",
            "valid@example.test, malformed",
            "bad@bad..example",
        ],
        cc_addresses=["Copy <copy@example.test>"],
        sort_time=None,
        is_read=True,
        is_flagged=False,
        has_attachments=False,
        snippet=None,
        body_text=None,
        body_html=None,
        body="",
        body_type="empty",
        parse_error=None,
        attachments=[],
    )

    result = _detail_out(detail, None)

    assert result.to == '"Doe, Jane" <jane@example.test>, Team <team@example.test>, malformed recipient, valid@example.test, malformed, bad@bad..example'
    assert [(address.name, address.address) for address in result.to_addresses[:2]] == [
        ("Doe, Jane", "jane@example.test"),
        ("Team", "team@example.test"),
    ]
    assert result.to_addresses[2].address is None
    assert result.to_addresses[2].text == "malformed recipient"
    assert result.to_addresses[3].address == "valid@example.test"
    assert result.to_addresses[4].address is None
    assert result.to_addresses[4].text == "malformed"
    assert result.to_addresses[5].address is None
    assert result.to_addresses[5].text == "bad@bad..example"
    assert result.cc == "Copy <copy@example.test>"
    assert [(address.name, address.address) for address in result.cc_addresses] == [("Copy", "copy@example.test")]
