"""IMAP remote_id namespacing + fetch_mime folder requirement."""

from __future__ import annotations

import pytest

from mail_core.providers.imap import (
    _quote_mailbox,
    format_imap_remote_id,
    imap_uid_for_command,
    parse_imap_remote_id,
    ImapProvider,
)


def test_format_parse_roundtrip():
    rid = format_imap_remote_id("INBOX", 42, 7)
    assert "\x1f" in rid
    assert parse_imap_remote_id(rid) == (42, "INBOX", 7)
    assert imap_uid_for_command(rid) == "7"
    assert imap_uid_for_command("99") == "99"


def test_format_distinct_across_folders():
    a = format_imap_remote_id("INBOX", 1, 5)
    b = format_imap_remote_id("Sent", 1, 5)
    assert a != b


def test_fetch_mime_requires_folder_without_namespace():
    p = ImapProvider(host="127.0.0.1", port=1, username="u", password="p", use_ssl=False)
    with pytest.raises(ValueError, match="folder"):
        p.fetch_mime("123")


def test_quote_mailbox_spaces_and_special_chars():
    assert _quote_mailbox("INBOX") == "INBOX"
    assert _quote_mailbox("Deleted Items") == '"Deleted Items"'
    assert _quote_mailbox("Junk Email") == '"Junk Email"'
    assert _quote_mailbox('"Already Quoted"') == '"Already Quoted"'
    assert _quote_mailbox('Folder "Quote"') == '"Folder \\"Quote\\""'
    assert _quote_mailbox("Folder\\Backslash") == '"Folder\\\\Backslash"'


@pytest.mark.parametrize("control", ["\r", "\n", "\x00", "\x1f", "\x7f", "\x85"])
def test_quote_mailbox_rejects_control_characters(control):
    with pytest.raises(ValueError, match="control characters"):
        _quote_mailbox(f"Folder{control}Name")


def test_imap_provider_quotes_folder_in_commands():
    from unittest.mock import MagicMock

    p = ImapProvider(host="127.0.0.1", port=1, username="u", password="p", use_ssl=False)
    mock_client = MagicMock()
    mock_client.select.return_value = ("OK", [b"1"])
    # A368: apply verifies the UID exists via FETCH (FLAGS UID) first.
    mock_client.uid.side_effect = lambda cmd, *args: (
        ("OK", [b"1 (FLAGS () UID 1)"]) if cmd == "FETCH" else ("OK", [b""])
    )
    mock_client.status.return_value = ("OK", [b"UIDVALIDITY 12345"])
    mock_client.response.return_value = ("OK", [b"COPYUID 12345 1 200"])
    p._connect = lambda: mock_client

    # Test apply MOVE to a folder with spaces
    res = p.apply_remote_operation(
        "move",
        {"remote_id": "1", "dest_folder_remote_id": "Deleted Items", "folder_remote_id": "Sent Items"},
    )
    assert res.success is True
    mock_client.select.assert_called_with('"Sent Items"')
    mock_client.uid.assert_called_with("MOVE", "1", '"Deleted Items"')
    assert res.remote_state is not None
    assert res.remote_state.get("folder_remote_id") == "Deleted Items"


def test_imap_provider_move_without_copyuid_graceful():
    from unittest.mock import MagicMock

    p = ImapProvider(host="127.0.0.1", port=1, username="u", password="p", use_ssl=False)
    mock_client = MagicMock()
    mock_client.select.return_value = ("OK", [b"1"])
    # A368: apply verifies the UID exists via FETCH (FLAGS UID) first.
    mock_client.uid.side_effect = lambda cmd, *args: (
        ("OK", [b"1 (FLAGS () UID 1)"]) if cmd == "FETCH" else ("OK", [b""])
    )
    mock_client.status.return_value = ("OK", [b"UIDVALIDITY 12345"])
    mock_client.response.return_value = ("NO", [])
    p._connect = lambda: mock_client

    res = p.apply_remote_operation(
        "move",
        {"remote_id": "1", "dest_folder_remote_id": "Archive", "folder_remote_id": "INBOX"},
    )
    assert res.success is True
    assert res.remote_state == {"folder_remote_id": "Archive"}


@pytest.mark.parametrize(
    ("op_type", "destination_field"),
    [("move", "dest_folder_remote_id"), ("trash", "trash_folder_remote_id")],
)
def test_imap_remote_write_rejects_control_destination_before_connect(
    monkeypatch,
    op_type,
    destination_field,
):
    provider = ImapProvider(host="imap.example.com", port=993, username="u", password="p", use_ssl=False)
    monkeypatch.setattr(provider, "_connect", lambda: pytest.fail("must reject destination before connecting"))
    result = provider.apply_remote_operation(
        op_type,
        {
            "remote_id": "1",
            "folder_remote_id": "INBOX",
            destination_field: "Archive\r\nUID STORE 1 +FLAGS (\\Deleted)",
        },
    )

    assert result.success is False
    assert "control characters" in (result.error or "")


def test_imap_provider_list_folders_sent_mapping():
    from unittest.mock import MagicMock

    p = ImapProvider(host="127.0.0.1", port=1, username="u", password="p", use_ssl=False)
    mock_client = MagicMock()
    mock_client.list.return_value = (
        "OK",
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "\xe5\xb7\xb2\xe5\x8f\x91\xe9\x80\x81"',
            b'(\\HasNoChildren) "/" "\xe5\xb7\xb2\xe5\x8f\x91\xe9\x80\x81\xe9\x82\xae\xe4\xbb\xb6"',
            b'(\\HasNoChildren \\Sent) "/" "CustomSentFolder"',
            b'(\\HasNoChildren) "/" "OtherFolder"',
        ],
    )
    p._connect = lambda: mock_client
    folders = p.list_folders()
    by_name = {f.name: f.role for f in folders}
    assert by_name["INBOX"] == "inbox"
    assert by_name["已发送"] == "sent"
    assert by_name["已发送邮件"] == "sent"
    assert by_name["CustomSentFolder"] == "sent"
    assert by_name["OtherFolder"] == "other"
