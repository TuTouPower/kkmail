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
from mail_core.realtime.dispatcher import OutboxDispatcher, SSE_STREAM_CLOSE

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
    """Slow SSE consumer: drop must not advance dispatch; client gets resync_hint.

    Whole-test replacement (design §9.2 / §11): the G-part-2 outbox
    rewrite removed fetch_undispatched/mark_dispatched/dispatched_at —
    the dispatcher now commits publication_seq before broadcast and
    "marked dispatched" is the local _last_dispatched_seq cursor. The
    behaviour contract is preserved: a queue-full event is not counted
    as dispatched, the local cursor does not advance past it, and the
    isolated consumer receives a resync hint plus the close sentinel.
    """
    from types import SimpleNamespace

    epoch = str(uuid.uuid4())

    class _FakeSession:
        def __init__(self):
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def commit(self):
            self.committed = True

    fake = _FakeSession()
    row = SimpleNamespace(
        id=10042,
        publication_seq=42,
        event_type="sync.progress",
        account_id=None,
        payload={"n": 1},
        created_at=datetime.now(timezone.utc),
    )

    def fake_factory():
        return lambda: fake

    dispatcher = OutboxDispatcher()
    dispatcher._last_dispatched_seq = 41
    dispatcher._baseline_established = True  # R08: a bare cursor no longer implies an established baseline

    async def _setup_and_dispatch():
        q = dispatcher.subscribe()
        # Fill the queue so the next put hits QueueFull (maxsize=256).
        for i in range(256):
            q.put_nowait({"id": i, "event": "pad", "data": {}, "account_id": None, "created_at": ""})
        with (
            patch("mail_core.db.session.get_session_factory", fake_factory),
            patch(
                "mail_core.realtime.publication.publish_committed_batch",
                return_value=SimpleNamespace(count=0, first_seq=None, last_seq=None),
            ),
            patch("mail_core.realtime.outbox.publication_head", return_value=(epoch, 42)),
            patch("mail_core.realtime.outbox.pruned_through_seq", return_value=0),
            patch(
                "mail_core.realtime.outbox.fetch_published_since",
                return_value=[row],
            ),
        ):
            n = dispatcher.dispatch_once()
        # Isolation replaces stale queued events with a hint followed by a close sentinel.
        hints = []
        sentinels = 0
        queued_events = []
        while not q.empty():
            ev = q.get_nowait()
            if ev is SSE_STREAM_CLOSE:
                sentinels += 1
            else:
                queued_events.append(ev)
            if isinstance(ev, dict) and ev.get("event") == "client.resync_hint":
                hints.append(ev)
        return n, hints, sentinels, queued_events

    n, hints, sentinels, queued_events = asyncio.run(_setup_and_dispatch())
    assert fake.committed is True  # publication is committed before broadcast
    assert n == 0
    assert dispatcher._last_dispatched_seq == 41  # not marked dispatched
    assert hints and hints[0]["data"]["reason"] == "sse_queue_full"
    assert sentinels == 1
    assert queued_events == hints


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
