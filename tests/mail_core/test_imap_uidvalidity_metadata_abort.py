"""A28: metadata/delta must not mint remote_ids with uv=0 when UIDVALIDITY
cannot be verified.

Reconcile already aborts in that situation (B1); fetch_metadata_page used to
fall back to ``int(uidvalidity or 0)`` and delta_changes to ``uv = 0``, so the
same messages were re-ingested under a ``0`` namespace once the server
recovered (and later deleted by reconcile as orphans).
"""

from __future__ import annotations

import pytest

from mail_core.providers.imap import ImapProvider


class _NoUidvalidityClient:
    """STATUS never yields UIDVALIDITY (configurable blob / failure)."""

    def __init__(self, status_result, *, with_modseq=False):
        self._status_result = status_result
        self._with_modseq = with_modseq
        self.fetched = False

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def status(self, mailbox, items):
        return self._status_result

    def list(self, ref, mailbox):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b"5"]
        if command == "FETCH":
            self.fetched = True
            return "OK", [
                (
                    b"5 (UID 5 FLAGS (\\Seen) INTERNALDATE \"21-Oct-2026 10:00:00 +0000\")",
                    b"From: a@b.c\r\nSubject: Hi\r\n\r\n",
                )
            ]
        return "NO", []

    def logout(self):
        return "BYE", [b"bye"]


def _provider(client) -> ImapProvider:
    provider = ImapProvider(host="imap.example.com", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    return provider


def test_fetch_metadata_page_aborts_when_status_blob_lacks_uidvalidity():
    client = _NoUidvalidityClient(("OK", [b"INBOX (MESSAGES 1)"]))
    provider = _provider(client)
    with pytest.raises(RuntimeError, match="UIDVALIDITY"):
        provider.fetch_metadata_page("INBOX", {"uid_next": 1})
    assert client.fetched is False


def test_fetch_metadata_page_aborts_when_status_fails():
    client = _NoUidvalidityClient(("NO", [b"status unavailable"]))
    provider = _provider(client)
    with pytest.raises(RuntimeError, match="UIDVALIDITY"):
        provider.fetch_metadata_page("INBOX", {"uid_next": 1})
    assert client.fetched is False


def test_delta_modseq_aborts_when_uidvalidity_unresolved():
    # HIGHESTMODSEQ present but no UIDVALIDITY anywhere (server or cursor):
    # flag changes must not be minted under uv=0.
    client = _NoUidvalidityClient(("OK", [b"INBOX (HIGHESTMODSEQ 50)"]), with_modseq=True)
    provider = _provider(client)
    with pytest.raises(RuntimeError, match="UIDVALIDITY"):
        provider.delta_changes("INBOX", {"modseq": 40, "uid_next": 10})
