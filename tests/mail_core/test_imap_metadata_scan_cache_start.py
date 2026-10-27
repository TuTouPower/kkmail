"""A170: the cached UID scan must record its lower bound.

Pre-fix the cache was only ``(folder, uidvalidity, uids)``; a first scan
starting at UID 100 cached ``[100..]`` and a later call with a smaller
``start`` silently reused that truncated list, reporting the folder as
exhausted while UIDs below 100 were never scanned.
"""

from __future__ import annotations

from mail_core.providers.imap import ImapProvider


class _FakeScanClient:
    def __init__(self):
        self.search_queries: list[str] = []

    def select(self, *_args, **_kwargs):
        return "OK", [b"1"]

    def status(self, *_args, **_kwargs):
        return "OK", [b"INBOX (UIDVALIDITY 7)"]

    def logout(self):
        return "OK", []

    def uid(self, command, *args):
        if command == "SEARCH":
            query = str(args[-1])
            self.search_queries.append(query)
            start = int(query.split()[1].split(":")[0])
            return "OK", [b" ".join(str(u).encode() for u in range(start, 8))]
        if command == "FETCH":
            uids = [int(v) for v in str(args[0]).split(",")]
            return "OK", [
                (
                    f"{u} (UID {u} FLAGS () INTERNALDATE \"21-Oct-2026 10:00:00 +0000\")".encode(),
                    f"From: user@example.com\r\nSubject: Message {u}\r\n\r\n".encode(),
                )
                for u in uids
            ]
        return "NO", []


def _provider(client) -> ImapProvider:
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    return provider


def test_scan_cache_rebuilt_when_start_moves_backwards():
    client = _FakeScanClient()
    provider = _provider(client)

    first = provider.fetch_metadata_page(
        "INBOX", {"uid_next": 5, "uidvalidity": 7, "page_size": 2}
    )
    assert [m.uid for m in first.items] == [5, 6]
    assert first.exhausted is False

    # Start moves backwards (e.g. a fresh full scan reusing this provider
    # instance): the truncated cache must not be reused.
    second = provider.fetch_metadata_page(
        "INBOX", {"uid_next": 1, "uidvalidity": 7, "page_size": 50}
    )
    assert [m.uid for m in second.items] == [1, 2, 3, 4, 5, 6, 7]
    assert client.search_queries == ["UID 5:*", "UID 1:*"]


def test_scan_cache_still_reused_when_start_moves_forwards():
    client = _FakeScanClient()
    provider = _provider(client)

    provider.fetch_metadata_page("INBOX", {"uid_next": 3, "uidvalidity": 7, "page_size": 1})
    page = provider.fetch_metadata_page(
        "INBOX", {"uid_next": 4, "uidvalidity": 7, "page_size": 2}
    )
    assert [m.uid for m in page.items] == [4, 5]
    assert client.search_queries == ["UID 3:*"]
