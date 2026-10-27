"""A31: IMAP SEARCH responses may arrive in multiple data chunks.

Reading only ``data[0]`` drops UIDs: reconcile then treats the dropped UIDs
as remotely deleted, MODSEQ/flag-sweep miss flag changes. All SEARCH
consumers must parse every chunk via ``_search_uids``.
"""

from __future__ import annotations

from mail_core.providers.base import MetadataPage
from mail_core.providers.imap import ImapProvider, _search_uids, format_imap_remote_id

_UV = 777


def test_search_uids_parses_all_chunks():
    assert _search_uids([b"1 2", b"3", "4 5", None, b""]) == [1, 2, 3, 4, 5]
    assert _search_uids([]) == []
    assert _search_uids(None) == []
    assert _search_uids([b""]) == []


class _ReconcileClient:
    def select(self, mailbox, readonly=False):
        return "OK", [b"4"]

    def status(self, mailbox, items):
        return "OK", [f"INBOX (UIDVALIDITY {_UV})".encode()]

    def uid(self, command, *args):
        assert command == "SEARCH"
        return "OK", [b"1 2", b"3 4"]

    def logout(self):
        return "BYE", [b"bye"]


def test_reconcile_uses_all_search_chunks():
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (_ReconcileClient(), None)
    locals_ = [format_imap_remote_id("INBOX", _UV, u) for u in range(1, 6)]
    actions = provider.reconcile("INBOX", locals_)
    assert [(a.kind, a.remote_id) for a in actions] == [
        ("delete", format_imap_remote_id("INBOX", _UV, 5))
    ]


class _ModseqClient:
    def select(self, mailbox, readonly=False):
        return "OK", [b"2"]

    def status(self, mailbox, items):
        return "OK", [f"INBOX (UIDVALIDITY {_UV} HIGHESTMODSEQ 50)".encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"5", b"6"]
        if command == "FETCH":
            uids = [int(x) for x in str(args[0]).split(",") if x]
            return "OK", [(f"{u} (UID {u} FLAGS (\\Seen))".encode(), b"") for u in uids]
        return "NO", []

    def logout(self):
        return "BYE", [b"bye"]


def test_modseq_search_uses_all_chunks():
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (_ModseqClient(), None)
    page = provider.delta_changes("INBOX", {"modseq": 40, "uidvalidity": _UV, "uid_next": 10})
    flag_ids = {c.remote_id for c in page.changes if c.kind == "flag"}
    assert flag_ids == {
        format_imap_remote_id("INBOX", _UV, 5),
        format_imap_remote_id("INBOX", _UV, 6),
    }


class _SweepClient:
    def __init__(self):
        self._flags = {1: "\\Seen", 2: "", 3: "\\Flagged"}

    def select(self, mailbox, readonly=False):
        return "OK", [b"3"]

    def status(self, mailbox, items):
        return "OK", [f"INBOX (UIDVALIDITY {_UV})".encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"1 2", b"3"]
        if command == "FETCH":
            uids = [int(x) for x in str(args[0]).split(",") if x]
            blobs = [f"{u} (UID {u} FLAGS ({self._flags[u]}))".encode() for u in uids]
            blobs.append(b")")
            return "OK", blobs
        return "NO", []

    def logout(self):
        return "BYE", [b"bye"]


def test_flag_sweep_search_uses_all_chunks():
    client = _SweepClient()
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    provider.fetch_metadata_page = lambda folder, cursor: MetadataPage(
        items=(), next_cursor={"uid_next": 4, "uidvalidity": _UV}, exhausted=True
    )
    page = provider.delta_changes("INBOX", {"uidvalidity": _UV, "uid_next": 4})
    flag_ids = {c.remote_id for c in page.changes if c.kind == "flag"}
    assert flag_ids == {format_imap_remote_id("INBOX", _UV, u) for u in (1, 2, 3)}
