"""IMAP remote_id namespacing + fetch_mime folder requirement."""

from __future__ import annotations

import pytest

from mail_core.providers.imap import (
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
