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
