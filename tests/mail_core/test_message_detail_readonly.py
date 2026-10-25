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
