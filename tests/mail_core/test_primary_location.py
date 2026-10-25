import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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


def test_resolve_imap_trash_folder():
    from mail_core.mail.application.mutations import (
        _resolve_imap_trash_folder,
        UnaddressableMessageError,
    )
    from mail_core.mail.storage.models import Folder

    account_id = uuid.uuid4()
    mock_session = MagicMock()

    # 1. Exactly one trash folder
    mock_trash = Folder(account_id=account_id, remote_id="INBOX.Deleted Items", role="trash", sync_status="idle")
    mock_session.scalars.return_value.all.return_value = [mock_trash]
    resolved = _resolve_imap_trash_folder(mock_session, account_id)
    assert resolved == "INBOX.Deleted Items"

    # 2. No trash folder -> raises
    mock_session.scalars.return_value.all.return_value = []
    with pytest.raises(UnaddressableMessageError, match="no selectable trash folder"):
        _resolve_imap_trash_folder(mock_session, account_id)

    # 3. Multiple trash folders -> raises
    mock_trash2 = Folder(account_id=account_id, remote_id="Trash2", role="trash", sync_status="idle")
    mock_session.scalars.return_value.all.return_value = [mock_trash, mock_trash2]
    with pytest.raises(UnaddressableMessageError, match="multiple ambiguous"):
        _resolve_imap_trash_folder(mock_session, account_id)
