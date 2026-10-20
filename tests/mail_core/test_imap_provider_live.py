from __future__ import annotations

import os
import socket

import pytest

from mail_core.providers.imap import ImapProvider

HOST = os.environ.get("MAIL_CORE_IMAP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAIL_CORE_IMAP_PORT", "1143"))
USER = os.environ.get("MAIL_CORE_IMAP_USER", "alice@kkmail.test")
PASS = os.environ.get("MAIL_CORE_IMAP_PASS", "alice-imap-pass")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(HOST, PORT), reason="local IMAP not available")


def test_imap_list_and_metadata_page():
    p = ImapProvider(host=HOST, port=PORT, username=USER, password=PASS, use_ssl=False)
    folders = p.list_folders()
    assert any(f.remote_id.upper() == "INBOX" for f in folders)
    page = p.fetch_metadata_page("INBOX", {"page_size": 10})
    assert page.exhausted or page.next_cursor is not None
    # seeded fixture mailbox should have at least one message
    assert len(page.items) >= 1
    assert page.items[0].remote_id
