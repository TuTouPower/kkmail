import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from mail_core.mail.application.mutations import _primary_location


def test_primary_location_prefers_inbox_then_uses_folder_id_for_ties():
    message_id = uuid.uuid4()
    inbox_folder = SimpleNamespace(id=uuid.uuid4(), remote_id="INBOX", role="inbox")
    archive_folder = SimpleNamespace(id=uuid.uuid4(), remote_id="Archive", role="archive")
    other_folder_2 = SimpleNamespace(id=uuid.UUID(int=2), remote_id="other-2", role="other")
    other_folder_1 = SimpleNamespace(id=uuid.UUID(int=1), remote_id="other-1", role="other")
    rows = [
        (SimpleNamespace(folder_id=archive_folder.id), archive_folder),
        (SimpleNamespace(folder_id=other_folder_2.id), other_folder_2),
        (SimpleNamespace(folder_id=inbox_folder.id), inbox_folder),
        (SimpleNamespace(folder_id=other_folder_1.id), other_folder_1),
    ]
    session = MagicMock()
    session.execute.return_value.all.return_value = rows

    folder, location = _primary_location(session, message_id)

    assert folder is inbox_folder
    assert location.folder_id == inbox_folder.id

    session.execute.return_value.all.return_value = rows[1:2] + rows[3:4]
    folder, location = _primary_location(session, message_id)

    assert folder is other_folder_1
    assert location.folder_id == other_folder_1.id
