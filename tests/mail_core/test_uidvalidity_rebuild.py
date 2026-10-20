"""UIDVALIDITY mismatch → CursorInvalidError + controlled metadata rebuild."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder, SyncCheckpoint
from mail_core.providers.base import MetadataPage, RemoteFolder, RemoteMessageMeta
from mail_core.providers.http import CursorInvalidError
from mail_core.providers.imap import _check_uidvalidity
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import sync_folder_metadata
from mail_core.sync.leases import acquire_lease
import mail_core.sync.engine as engine_mod

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_check_uidvalidity_ok_and_mismatch():
    _check_uidvalidity(None, 9)
    _check_uidvalidity({}, 9)
    _check_uidvalidity({"uidvalidity": 9}, 9)
    with pytest.raises(CursorInvalidError, match="UIDVALIDITY changed"):
        _check_uidvalidity({"uidvalidity": 1}, 2)


def test_imap_fetch_metadata_page_raises_on_uidvalidity_change(monkeypatch):
    from mail_core.providers import imap as imap_mod

    class FakeIMAP:
        def select(self, *a, **k):
            return ("OK", [b"1"])

        def status(self, folder, items):
            return ("OK", [b'"INBOX" (UIDVALIDITY 99)'])

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return ("OK", [b"1"])
            return ("OK", [None])

        def logout(self):
            return ("OK", [])

        def login(self, *a):
            return ("OK", [])

    prov = imap_mod.ImapProvider("h", 993, "u", "p", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAP())
    with pytest.raises(CursorInvalidError, match="UIDVALIDITY changed"):
        prov.fetch_metadata_page("INBOX", {"uid_next": 1, "uidvalidity": 1})


def test_imap_fetch_mime_and_writeback_uidvalidity_mismatch(monkeypatch):
    from mail_core.providers import imap as imap_mod

    class FakeIMAP:
        def select(self, *a, **k):
            return ("OK", [b"1"])

        def status(self, folder, items):
            return ("OK", [b'"INBOX" (UIDVALIDITY 99)'])

        def uid(self, *a, **k):
            return ("OK", [(b"flags", b"headers")])

        def logout(self):
            return ("OK", [])

    prov = imap_mod.ImapProvider("h", 993, "u", "p", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAP())

    # Namespaced remote_id with UIDVALIDITY 1 differs from server's 99
    rid = imap_mod.format_imap_remote_id("INBOX", 1, 100)

    # fetch_mime should raise on mismatch
    with pytest.raises(RuntimeError, match="UIDVALIDITY mismatch"):
        prov.fetch_mime(rid)

    # apply_remote_operation should return failure on mismatch
    res = prov.apply_remote_operation("mark_read", {"remote_id": rid, "is_read": True})
    assert not res.success
    assert "UIDVALIDITY mismatch" in (res.error or "")


@pytestmark_db
def test_sync_folder_metadata_rebuilds_on_cursor_invalid():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)

    class BoomProvider(MemoryProvider):
        def fetch_metadata_page(self, folder_remote_id, cursor):
            raise CursorInvalidError("UIDVALIDITY changed: was 1, now 2")

    provider = BoomProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    originals = engine_mod.build_provider

    def _build(account, store=None):
        return provider

    engine_mod.build_provider = _build
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"uv-{uuid.uuid4().hex[:8]}@ex.com",
                provider="memory",
                credential_ref="r",
            )
            folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.flush()
            lease = acquire_lease(session, account_id=acc.id, owner_id="seed", ttl=__import__("datetime").timedelta(seconds=5))
            session.flush()
            # Seed a checkpoint that looks like a mid-sync IMAP folder.
            from mail_core.sync.checkpoints import commit_checkpoint

            commit_checkpoint(
                session,
                account_id=acc.id,
                folder_id=folder.id,
                fencing_token=lease.fencing_token,
                cursor={"uid_next": 10, "uidvalidity": 1},
                uidvalidity=1,
                full_scan_complete=False,
            )
            # Expire seed lease so sync can acquire.
            from mail_core.mail.storage.models import AccountSyncLease
            from datetime import datetime as dt, timezone as tz, timedelta

            row = session.get(AccountSyncLease, acc.id)
            row.lease_expires_at = dt.now(tz.utc) - timedelta(seconds=1)
            session.commit()
            account_id, folder_id = acc.id, folder.id

        result = sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)
        assert result["status"] == "cursor_invalid"

        with Session() as session:
            cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
            assert cp is not None
            assert cp.full_scan_complete is False
            assert cp.uidvalidity is None
            assert cp.cursor == {}
            from mail_core.mail.storage.models import WorkerJob

            jobs = list(
                session.scalars(
                    select(WorkerJob).where(
                        WorkerJob.account_id == account_id,
                        WorkerJob.job_type == "sync_folder_metadata",
                    )
                ).all()
            )
            assert any((j.payload or {}).get("reason") == "cursor_invalid" for j in jobs)
    finally:
        engine_mod.build_provider = originals
        set_credential_store(None)
