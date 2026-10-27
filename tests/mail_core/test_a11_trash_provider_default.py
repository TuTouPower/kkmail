"""A11: trash_message must not hardcode trash_folder_remote_id="Trash" for
non-IMAP accounts (Graph's trash is "deleteditems"; passing "Trash" makes
the remote move fail after the local row is already deleted). Non-IMAP
accounts omit the key so each provider applies its own default; IMAP
accounts keep the resolved role='trash' folder remote_id."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mail_core.mail.application import mutations
from mail_core.mail.storage.models import Account, Message


def _run_trash(provider: str, *, trash_folder=None):
    account_id = uuid.uuid4()
    message_id = uuid.uuid4()
    msg = SimpleNamespace(id=message_id, account_id=account_id, remote_id="remote-1")
    account = SimpleNamespace(id=account_id, provider=provider)
    captured = {}

    session = MagicMock()

    def _get(model, key):
        if model is Message:
            return msg
        if model is Account:
            return account
        return None

    session.get.side_effect = _get
    session.execute.return_value.all.return_value = []  # _primary_location: none

    scalars_results = [
        MagicMock(**{"all.return_value": []}),  # _all_location_folder_ids
    ]
    if trash_folder is not None:
        scalars_results.append(MagicMock(**{"all.return_value": [trash_folder]}))
    scalars_results.append(MagicMock(**{"all.return_value": []}))  # location deletion loop
    session.scalars.side_effect = scalars_results

    def _enqueue(_session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    with (
        patch.object(mutations, "enqueue_remote_operation", side_effect=_enqueue),
        patch.object(mutations, "_recompute_stats_for_folders", lambda *a, **k: None),
        patch.object(mutations, "_wake_push", lambda *a, **k: None),
        patch.object(mutations, "try_notify_outbox", lambda *a, **k: None),
    ):
        result = mutations.trash_message(session, message_id)
    assert result.operation_id is not None
    return captured["desired_state"]


def test_graph_account_omits_trash_folder_key():
    desired = _run_trash("graph")
    assert "trash_folder_remote_id" not in desired
    assert desired["remote_id"] == "remote-1"


def test_stub_account_omits_trash_folder_key():
    desired = _run_trash("stub")
    assert "trash_folder_remote_id" not in desired


def test_imap_account_passes_resolved_trash_folder():
    trash_folder = SimpleNamespace(remote_id="INBOX.Deleted Items")
    desired = _run_trash("imap", trash_folder=trash_folder)
    assert desired["trash_folder_remote_id"] == "INBOX.Deleted Items"
