"""A145: a single failed FETCH inside the no-CONDSTORE flag sweep must not
poison the whole folder delta.

Pre-fix, ``_sweep_existing_flags`` let ``_ImapFlagFetchError`` propagate, so
delta_changes raised before fetching new mail and the same poisoned window
was retried forever. The sweep must instead skip this round (same semantics
as its SEARCH-failure path) and let new-mail paging proceed.
"""

from __future__ import annotations

from mail_core.providers.base import MetadataPage
from mail_core.providers.imap import ImapProvider

_UV = 777


class _PoisonedFetchClient:
    """SEARCH works, but the FLAGS FETCH returns a response without FLAGS."""

    def select(self, mailbox, readonly=False):
        return "OK", [b"3"]

    def status(self, mailbox, items):
        return "OK", [f"INBOX (UIDVALIDITY {_UV})".encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"1 2 3"]
        if command == "FETCH":
            uids = [int(x) for x in str(args[0]).split(",") if x]
            # Missing FLAGS on every blob -> abort_on_missing_flags raises.
            return "OK", [(f"{u} (UID {u})".encode(), b"") for u in uids]
        return "NO", []

    def logout(self):
        return "BYE", [b"bye"]


def _provider(client) -> ImapProvider:
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    provider.fetch_metadata_page = lambda folder, cursor: MetadataPage(
        items=(), next_cursor={"uid_next": 4, "uidvalidity": _UV}, exhausted=True
    )
    return provider


def test_sweep_fetch_failure_skips_sweep_and_preserves_progress():
    client = _PoisonedFetchClient()
    provider = _provider(client)
    changes, complete, after = provider._sweep_existing_flags(
        client, "INBOX", _UV, {"uid_next": 4, "flag_scan_after": 1}
    )
    assert changes == []
    assert complete is True
    assert after == 1


def test_delta_survives_sweep_fetch_failure_and_still_pages_new_mail():
    client = _PoisonedFetchClient()
    provider = _provider(client)
    page = provider.delta_changes("INBOX", {"uidvalidity": _UV, "uid_next": 4})
    assert [c for c in page.changes if c.kind == "flag"] == []
    assert page.exhausted is True
    assert (page.next_cursor or {}).get("uid_next") == 4
