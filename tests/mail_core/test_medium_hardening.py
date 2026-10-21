"""Medium-finding hardening: GC dry_run, IMAP repr, dispatcher drop, URLError, archive reclaim."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from mail_core.blobs.gc import run_gc_blobs
from mail_core.providers.http import ProviderHttpError
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import urllib_json_request
from mail_core.realtime.dispatcher import OutboxDispatcher

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_imap_provider_repr_redacts_password():
    p = ImapProvider(host="imap.example.com", port=993, username="u", password="s3cret-pass")
    r = repr(p)
    assert "s3cret-pass" not in r
    assert "password=***" in r
    assert "imap.example.com" in r


def test_urllib_json_request_wraps_urlerror(monkeypatch):
    import urllib.error
    import urllib.request

    def boom(*_a, **_k):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(ProviderHttpError) as ei:
        urllib_json_request("GET", "https://example.invalid/x")
    assert ei.value.status is None
    assert "timed out" in str(ei.value)


@pytestmark_db
def test_gc_dry_run_reports_would_delete_not_deleted(tmp_path, monkeypatch):
    from sqlalchemy import select

    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage import MessageBlob

    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    Session = get_session_factory()
    digest = "b" * 64
    rel = f"bb/bb/{digest}.blob"
    (tmp_path / "bb" / "bb").mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"x")
    with Session() as session:
        session.add(
            MessageBlob(
                content_sha256=digest,
                key_version=1,
                size_bytes=1,
                storage_path=rel,
                ref_count=0,
                gc_eligible_at=datetime.now(timezone.utc) - timedelta(hours=48),
            )
        )
        session.commit()

    out = run_gc_blobs(cool_off_hours=24.0, dry_run=True)
    assert out["dry_run"] is True
    assert out["deleted"] == 0
    assert out["would_delete"] >= 1
    assert out["unlinked"] == 0

    with Session() as session:
        assert session.scalar(select(MessageBlob).where(MessageBlob.content_sha256 == digest)) is not None
        assert (tmp_path / rel).exists()


def test_dispatch_queue_full_does_not_mark_and_sends_resync_hint():
    """Slow SSE consumer: drop must not mark_dispatched; client gets resync_hint."""

    class _FakeSession:
        def __init__(self):
            self.committed = False
            self.marked = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            self.committed = True

    class _Row:
        def __init__(self, eid):
            self.id = eid
            self.event_type = "sync.progress"
            self.account_id = None
            self.payload = {"n": 1}
            self.created_at = datetime.now(timezone.utc)

    fake = _FakeSession()
    row = _Row(42)
    marked_ids = []

    def fake_factory():
        return lambda: fake

    dispatcher = OutboxDispatcher()

    async def _setup_and_dispatch():
        q = dispatcher.subscribe()
        # Fill the queue so the next put hits QueueFull (maxsize=256).
        for i in range(256):
            q.put_nowait({"id": i, "event": "pad", "data": {}, "account_id": None, "created_at": ""})
        with (
            patch("mail_core.db.session.get_session_factory", fake_factory),
            patch("mail_core.realtime.dispatcher.fetch_undispatched", return_value=[row]),
            patch("mail_core.realtime.dispatcher.mark_dispatched", side_effect=lambda s, ids: marked_ids.extend(ids)),
            patch("mail_core.realtime.dispatcher.to_item") as ti,
        ):
            from mail_core.realtime.outbox import OutboxItem

            ti.return_value = OutboxItem(
                id=42,
                event_type="sync.progress",
                account_id=None,
                payload={"n": 1},
                created_at=row.created_at,
            )
            n = dispatcher.dispatch_once()
        dispatcher.unsubscribe(q)
        # Drain: expect a resync_hint somewhere after pads.
        hints = []
        while not q.empty():
            ev = q.get_nowait()
            if ev.get("event") == "client.resync_hint":
                hints.append(ev)
        return n, hints, marked_ids

    n, hints, marked = asyncio.run(_setup_and_dispatch())
    assert n == 0
    assert marked == []
    assert hints and hints[0]["data"]["reason"] == "sse_queue_full"


@pytestmark_db
def test_reclaim_stale_archive_claims():
    from mail_core.accounts import create_account
    from mail_core.blobs.archive import reclaim_stale_archive_claims
    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ArchiveState
    from mail_core.mail.storage.models import Message, MessageArchiveState

    Session = get_session_factory()
    with Session() as session:
        acc = create_account(session, email=f"arch-{uuid.uuid4().hex[:8]}@ex.com", provider="stub")
        m = Message(
            account_id=acc.id,
            remote_id="1",
            subject="x",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(m)
        session.flush()
        st = MessageArchiveState(
            message_id=m.id,
            state=ArchiveState.ARCHIVE_IN_PROGRESS.value,
            priority=1,
            claimed_by="dead-worker",
            claimed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        session.add(st)
        session.commit()
        mid = m.id

    with Session() as session:
        n = reclaim_stale_archive_claims(session, older_than=timedelta(minutes=15))
        session.commit()
        assert n >= 1
        st = session.get(MessageArchiveState, mid)
        assert st.state == ArchiveState.ARCHIVE_PENDING.value
        assert st.claimed_by is None
