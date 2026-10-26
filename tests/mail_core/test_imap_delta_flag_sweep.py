"""R06: IMAP delta without CONDSTORE must observe other clients' flag changes.

Pre-fix, when the server did not advertise HIGHESTMODSEQ, delta_changes
only paged new UIDs since ``uid_next`` — FLAGS of already-known messages
were never re-read, so read/flagged changes made by another client never
reached the local store (reconcile does not compare flags either).

The fix adds a bounded sweep of existing UIDs' FLAGS to the no-MODSEQ
path: at most 200 UIDs per delta call, progress persisted in the delta
cursor as ``flag_scan_after`` and wrapped away when a sweep completes.
"""

from __future__ import annotations

from mail_core.providers.base import MetadataPage
from mail_core.providers.imap import ImapProvider, format_imap_remote_id

_UV = 777


class _FakeDeltaClient:
    """No-CONDSTORE server: STATUS lacks HIGHESTMODSEQ."""

    def __init__(self, flags_by_uid: dict[int, str], *, with_modseq: bool = False):
        self._flags = flags_by_uid
        self._with_modseq = with_modseq
        self.searches: list[str] = []

    def select(self, mailbox, readonly=False):
        return "OK", [b"3"]

    def status(self, mailbox, items):
        if self._with_modseq:
            return "OK", [f"INBOX (UIDVALIDITY {_UV} HIGHESTMODSEQ 900)".encode()]
        return "OK", [f"INBOX (UIDVALIDITY {_UV})".encode()]

    def uid(self, command, charset, criteria, *rest):
        if command == "SEARCH":
            self.searches.append(str(criteria))
            if criteria == "MODSEQ":
                return "OK", [b""]
            assert criteria == "ALL"
            return "OK", [" ".join(str(u) for u in sorted(self._flags)).encode()]
        if command == "FETCH":
            spec = str(charset)
            uids = [int(x) for x in spec.split(",") if x]
            blobs = [
                f"{u} (UID {u} FLAGS ({self._flags[u]}))".encode() for u in uids
            ]
            blobs.append(b")")
            return "OK", blobs
        raise AssertionError(f"unexpected uid command {command}")

    def logout(self):
        return "BYE", [b"bye"]


def _provider(client) -> ImapProvider:
    provider = ImapProvider(host="imap.example.com", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    provider.fetch_metadata_page = lambda folder, cursor: MetadataPage(
        items=(), next_cursor={"uid_next": max(client._flags) + 1, "uidvalidity": _UV}, exhausted=True
    )
    return provider


def test_delta_without_modseq_reports_existing_uid_flag_changes():
    # Baseline complete (uid_next=4, UIDs 1-3 stored). Another client has
    # since marked UID 2 read+flagged and UID 1 read.
    client = _FakeDeltaClient({1: "\\Seen", 2: "\\Seen \\Flagged", 3: ""})
    provider = _provider(client)
    page = provider.delta_changes("INBOX", {"uidvalidity": _UV, "uid_next": 4})
    flags = {c.remote_id: c.flags for c in page.changes if c.kind == "flag"}
    assert flags == {
        format_imap_remote_id("INBOX", _UV, 1): {"is_read": True, "is_flagged": False},
        format_imap_remote_id("INBOX", _UV, 2): {"is_read": True, "is_flagged": True},
        format_imap_remote_id("INBOX", _UV, 3): {"is_read": False, "is_flagged": False},
    }
    assert page.exhausted is True
    assert "flag_scan_after" not in (page.next_cursor or {})


def test_delta_flag_sweep_is_windowed_and_resumes_from_cursor():
    client = _FakeDeltaClient({u: "" for u in range(1, 251)})
    provider = _provider(client)
    first = provider.delta_changes("INBOX", {"uidvalidity": _UV, "uid_next": 251})
    assert sum(1 for c in first.changes if c.kind == "flag") == 200
    assert first.exhausted is False
    assert (first.next_cursor or {}).get("flag_scan_after") == 200

    second = provider.delta_changes("INBOX", dict(first.next_cursor))
    assert sum(1 for c in second.changes if c.kind == "flag") == 50
    assert second.exhausted is True
    assert "flag_scan_after" not in (second.next_cursor or {})


def test_delta_with_modseq_does_not_run_flag_sweep():
    client = _FakeDeltaClient({1: "\\Seen"}, with_modseq=True)
    provider = _provider(client)
    page = provider.delta_changes(
        "INBOX", {"uidvalidity": _UV, "uid_next": 2, "modseq": 5}
    )
    assert page.exhausted is True
    assert "ALL" not in client.searches
