"""Test recompute_folder_stats protects initial creation against race conditions (SEC-06).

Real-DB version (T4): the previous test mocked the session end-to-end
(hand-raised IntegrityError, scripted session.get), so the SAVEPOINT
recovery path was never executed by a real database. Here a competing
transaction inserts the FolderStats row first and holds it uncommitted;
the worker's INSERT then blocks on the primary-key speculative token
until the competitor commits, raises a genuine UniqueViolation inside
begin_nested, and must recover through the production retry path.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import Account, Folder, FolderStats, Message, MessageLocation

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set (PG-gated real-DB test)",
)


def test_recompute_folder_stats_handles_race_integrity_error():
    Session = get_session_factory()
    suffix = uuid.uuid4().hex[:8]
    with Session() as session:
        acc = Account(email=f"race-{suffix}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        folder_id = folder.id
        for i in range(5):
            msg = Message(
                account_id=acc.id,
                remote_id=f"race-msg-{i}",
                subject=f"Race {i}",
                from_address="a@b.c",
                sort_time=datetime.now(timezone.utc),
                is_read=i >= 2,  # 2 unread, 3 read
            )
            session.add(msg)
            session.flush()
            session.add(MessageLocation(message_id=msg.id, folder_id=folder.id, uid=i + 1))
        session.commit()

    # Competitor inserts the stats row and holds it uncommitted.
    competitor = Session()
    competitor.add(FolderStats(folder_id=folder_id, total_count=0, unread_count=0))
    competitor.flush()

    outcome: dict = {}

    def _worker() -> None:
        worker_session = Session()
        try:
            stats = recompute_folder_stats(worker_session, folder_id)
            outcome["total"] = stats.total_count
            outcome["unread"] = stats.unread_count
            worker_session.commit()
        except Exception as exc:  # surfaced by the assertions below
            outcome["error"] = exc
        finally:
            worker_session.close()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    try:
        # Wait until the worker's INSERT is really blocked on the
        # competitor's uncommitted primary key (speculative insertion).
        with Session() as probe:
            blocked = False
            for _ in range(100):
                blocked = bool(
                    probe.execute(
                        text(
                            "SELECT 1 FROM pg_stat_activity "
                            "WHERE wait_event_type = 'Lock' AND state = 'active' "
                            "AND pid <> pg_backend_pid()"
                        )
                    ).first()
                )
                probe.commit()
                if blocked:
                    break
                thread.join(timeout=0.05)
                if not thread.is_alive():
                    break
            assert blocked, "worker INSERT never blocked on the competing stats row"
    finally:
        competitor.commit()
        competitor.close()
    thread.join(timeout=15)
    assert not thread.is_alive(), "recompute_folder_stats did not finish after the competitor committed"
    assert "error" not in outcome, f"recompute raised instead of recovering: {outcome.get('error')!r}"
    assert outcome["total"] == 5
    assert outcome["unread"] == 2

    with Session() as session:
        final = session.get(FolderStats, folder_id)
        assert final is not None
        assert final.total_count == 5
        assert final.unread_count == 2
