"""A323: metadata page_size taken from the persisted cursor must be bounded.

Pre-fix ``batch_size = int(cursor.get("page_size") or 50)`` accepted a huge
value (one FETCH for the whole mailbox), a negative value (broken slicing)
and crashed on a non-numeric value; the value was also written back into
the next cursor verbatim, perpetuating itself.
"""

from __future__ import annotations

from mail_core.providers.imap import ImapProvider

_MAX_UID = 600


class _FakeBigClient:
    def select(self, *_args, **_kwargs):
        return "OK", [b"1"]

    def status(self, *_args, **_kwargs):
        return "OK", [b"INBOX (UIDVALIDITY 7)"]

    def logout(self):
        return "OK", []

    def uid(self, command, *args):
        if command == "SEARCH":
            start = int(str(args[-1]).split()[1].split(":")[0])
            return "OK", [b" ".join(str(u).encode() for u in range(start, _MAX_UID + 1))]
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


def _page(page_size):
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (_FakeBigClient(), None)
    return provider.fetch_metadata_page(
        "INBOX", {"uid_next": 1, "uidvalidity": 7, "page_size": page_size}
    )


def test_page_size_clamped_to_500():
    page = _page(100000)
    assert len(page.items) == 500
    assert page.exhausted is False
    assert (page.next_cursor or {}).get("page_size") == 500
    assert (page.next_cursor or {}).get("uid_next") == 501


def test_non_numeric_page_size_falls_back_to_50():
    page = _page("bogus")
    assert len(page.items) == 50
    assert (page.next_cursor or {}).get("page_size") == 50


def test_non_positive_page_size_falls_back_to_50():
    page = _page(-5)
    assert len(page.items) == 50
    assert (page.next_cursor or {}).get("page_size") == 50


def test_normal_page_size_unchanged():
    page = _page(3)
    assert len(page.items) == 3
    assert (page.next_cursor or {}).get("page_size") == 3
