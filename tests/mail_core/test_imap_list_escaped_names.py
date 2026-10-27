"""A348: LIST response parsing must handle escaped quotes in mailbox names
and must not strip spaces that are inside the quotes.

Pre-fix the name group was ``"[^"]*"`` (truncating at the first ``\\"``) and
the captured name was ``.strip()``-ed, silently dropping a legitimate
trailing space from a quoted mailbox name so later SELECTs used a different
name than the server has.
"""

from __future__ import annotations

from mail_core.providers.imap import ImapProvider


class _FakeListClient:
    def __init__(self, lines):
        self._lines = lines

    def list(self):
        return "OK", self._lines

    def logout(self):
        return "BYE", [b"bye"]


def _catalog(lines):
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (_FakeListClient(lines), None)
    return provider.list_folder_catalog()


def test_list_name_with_escaped_quotes_is_unescaped_not_truncated():
    folders = _catalog([b'(\\HasNoChildren) "/" "Foo \\"Bar\\" Baz"'])
    assert [f.remote_id for f in folders if f.remote_id != "INBOX"] == ['Foo "Bar" Baz']


def test_list_quoted_name_trailing_space_is_preserved():
    folders = _catalog([b'(\\HasNoChildren) "/" "Folder "'])
    assert "Folder " in [f.remote_id for f in folders]


def test_list_name_with_escaped_backslash():
    folders = _catalog([b'(\\HasNoChildren) "/" "A\\\\B"'])
    assert "A\\B" in [f.remote_id for f in folders]


def test_list_plain_names_unchanged():
    folders = _catalog(
        [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Sent Items"',
            b"(\\HasNoChildren) / PlainBox",
        ]
    )
    ids = [f.remote_id for f in folders]
    assert "INBOX" in ids
    assert "Sent Items" in ids
    assert "PlainBox" in ids
