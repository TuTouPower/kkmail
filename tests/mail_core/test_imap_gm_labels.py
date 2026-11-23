"""Gmail X-GM-LABELS are read during normal metadata fetch (t086)."""

from __future__ import annotations

from mail_core.providers.base import RemoteMessageMeta
from mail_core.providers.imap import (
    ImapProvider,
    _has_gm_labels,
    _parse_gm_labels,
    _parse_message_meta_from_fetch,
)


def test_parse_gm_labels_handles_special_and_quoted_labels():
    assert _parse_gm_labels(r'1 (UID 1 FLAGS (\Seen) X-GM-LABELS (\Important "Work Stuff" \Inbox))') == (
        "\\Important",
        "Work Stuff",
        "\\Inbox",
    )
    assert _parse_gm_labels("1 (UID 1 FLAGS ())") == ()


def test_has_gm_labels_uses_capability_without_raising():
    class _Caps:
        def capability(self):
            return "OK", [b"IMAP4rev1 X-GM-EXT-1 AUTH=PLAIN"]

    class _NoCaps:
        def capability(self):
            return "NO", []

    class _Broken:
        def capability(self):
            raise OSError("offline")

    assert _has_gm_labels(_Caps())
    assert not _has_gm_labels(_NoCaps())
    assert not _has_gm_labels(_Broken())


def test_meta_parser_carries_labels():
    blob = (
        r'1 (UID 1 FLAGS (\Seen) X-GM-LABELS (\Important) INTERNALDATE "21-Oct-2026 10:00:00 +0000")'.encode(),
        b"From: user@example.test\r\nSubject: Labeled\r\n\r\n",
    )
    meta = _parse_message_meta_from_fetch(blob, 1, "INBOX", 7, ("\\Important",))
    assert isinstance(meta, RemoteMessageMeta)
    assert meta.labels == ("\\Important",)


class _FakeClient:
    def __init__(self):
        self.fetch_fields: list[str] = []

    def capability(self):
        return "OK", [b"IMAP4rev1 X-GM-EXT-1"]

    def select(self, *_args, **_kwargs):
        return "OK", [b"1"]

    def status(self, *_args, **_kwargs):
        return "OK", [b"INBOX (UIDVALIDITY 7)"]

    def logout(self):
        return "OK", []

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"1 2"]
        if command == "FETCH":
            self.fetch_fields.append(str(args[1]))
            return "OK", [
                (
                    f'{uid} (UID {uid} FLAGS () X-GM-LABELS (\\Important) INTERNALDATE "21-Oct-2026 10:00:00 +0000")'.encode(),
                    f"From: user@example.test\r\nSubject: Message {uid}\r\n\r\n".encode(),
                )
                for uid in (1, 2)
            ]
        return "NO", []


def test_fetch_metadata_page_requests_and_parses_labels():
    client = _FakeClient()
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    page = provider.fetch_metadata_page("INBOX", None)
    assert "X-GM-LABELS" in client.fetch_fields[0]
    assert page.items[0].labels == ("\\Important",)
