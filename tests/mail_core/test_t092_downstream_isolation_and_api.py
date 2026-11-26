"""Tests for t092 AC-004/AC-005 & HTTP API: downstream active/syncable isolation and view scoping."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.application.mutations import (
    UnaddressableMessageError,
    _resolve_imap_trash_folder,
    mark_all_messages_read,
    set_message_flagged,
    set_message_read,
    trash_message,
)
from mail_core.mail.application.queries import (
    query_global_inbox_stats,
    query_group_inbox_stats,
    unified_inbox,
    view_scope_folder_ids,
)
from mail_core.mail.storage.models import (
    Account,
    AccountGroup,
    Folder,
    FolderStats,
    Message,
    MessageLocation,
    RemoteOperation,
)
from mail_core.mail.domain.folder_views import CONTAINER, VIEW
from mail_core.providers.imap import format_imap_remote_id
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_ac004_view_isolation_stats_locations_and_writeback_priority():
    """AC-004: views, missing/unselectable folders, group stats, and writeback priority stay isolated."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        group = AccountGroup(name=f"t092-grp-{uuid.uuid4().hex[:8]}", sort_order=0, created_at=now)
        session.add(group)
        session.flush()
        acc = Account(email=f"iso-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap", config={"imap_host": "imap.gmail.com"}, sync_enabled=True, group_id=group.id)
        acc_other = Account(email=f"iso-b-{uuid.uuid4().hex[:8]}@ex.com", provider="imap", config={"imap_host": "imap.ex.com"}, sync_enabled=True, group_id=group.id)
        session.add_all([acc, acc_other])
        session.flush()

        f_inbox = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox", kind=CONTAINER, selectable=True, remote_state="active")
        f_ghost_inbox = Folder(account_id=acc.id, remote_id="OldInbox", name="OldInbox", role="inbox", kind=CONTAINER, selectable=True, remote_state="missing")
        f_archive = Folder(account_id=acc.id, remote_id="Archive", name="Archive", role="archive", kind=CONTAINER, selectable=True, remote_state="active")
        f_sent_active = Folder(account_id=acc.id, remote_id="Sent", name="Sent", role="sent", kind=CONTAINER, selectable=True, remote_state="active")
        f_sent_nosel = Folder(account_id=acc.id, remote_id="SentRoot", name="SentRoot", role="sent", kind=CONTAINER, selectable=False, remote_state="active")
        f_sent_other = Folder(account_id=acc_other.id, remote_id="Sent", name="Sent", role="sent", kind=CONTAINER, selectable=True, remote_state="active")
        f_imp = Folder(account_id=acc.id, remote_id="[Gmail]/Important", name="[Gmail]/Important", role="important", kind=VIEW, selectable=True, remote_state="active")
        f_all = Folder(account_id=acc.id, remote_id="[Gmail]/All Mail", name="[Gmail]/All Mail", role="all", kind=VIEW, selectable=True, remote_state="active")
        f_trash = Folder(account_id=acc.id, remote_id="Trash", name="Trash", role="trash", kind=CONTAINER, selectable=True, remote_state="active")
        f_ghost_only = Folder(account_id=acc.id, remote_id="VanishedOnly", name="VanishedOnly", role="other", kind=CONTAINER, selectable=True, remote_state="missing")
        session.add_all([f_inbox, f_ghost_inbox, f_archive, f_sent_active, f_sent_nosel, f_sent_other, f_imp, f_all, f_trash, f_ghost_only])
        session.flush()

        session.add_all([
            FolderStats(folder_id=f_inbox.id, total_count=2, unread_count=2),
            FolderStats(folder_id=f_sent_active.id, total_count=4, unread_count=2),
            FolderStats(folder_id=f_sent_other.id, total_count=5, unread_count=3),
        ])

        m_imp = Message(account_id=acc.id, remote_id=format_imap_remote_id("INBOX", 1, 1), subject="Imp", sort_time=now, is_read=False)
        m_plain = Message(account_id=acc.id, remote_id=format_imap_remote_id("INBOX", 1, 2), subject="Plain", sort_time=now, is_read=False)
        m_trash = Message(account_id=acc.id, remote_id=format_imap_remote_id("Trash", 2, 3), subject="Trashed", sort_time=now, is_read=False)
        m_ghost_only = Message(account_id=acc.id, remote_id=format_imap_remote_id("VanishedOnly", 3, 99), subject="Ghost", sort_time=now, is_read=False, is_flagged=False)
        m_ghost_batch = Message(account_id=acc.id, remote_id=format_imap_remote_id("VanishedOnly", 3, 100), subject="GhostBatch", sort_time=now, is_read=False, is_flagged=False)
        session.add_all([m_imp, m_plain, m_trash, m_ghost_only, m_ghost_batch])
        session.flush()

        session.add_all([
            MessageLocation(message_id=m_imp.id, folder_id=f_inbox.id, uid=1),
            MessageLocation(message_id=m_imp.id, folder_id=f_imp.id, uid=None),
            MessageLocation(message_id=m_imp.id, folder_id=f_ghost_inbox.id, uid=77),
            MessageLocation(message_id=m_plain.id, folder_id=f_inbox.id, uid=2),
            MessageLocation(message_id=m_plain.id, folder_id=f_archive.id, uid=20),
            MessageLocation(message_id=m_trash.id, folder_id=f_trash.id, uid=3),
            MessageLocation(message_id=m_ghost_only.id, folder_id=f_ghost_only.id, uid=99),
            MessageLocation(message_id=m_ghost_only.id, folder_id=f_imp.id, uid=None),
            MessageLocation(message_id=m_ghost_batch.id, folder_id=f_ghost_only.id, uid=100),
            MessageLocation(message_id=m_ghost_batch.id, folder_id=f_imp.id, uid=None),
        ])
        session.commit()

        # View isolation & locations active filter
        assert view_scope_folder_ids(session, f_imp) == [f_imp.id]
        imp_items = unified_inbox(session, folder_id=f_imp.id).items
        assert {i.id for i in imp_items} == {m_imp.id, m_ghost_only.id, m_ghost_batch.id}
        all_items = unified_inbox(session, folder_id=f_all.id).items
        assert {i.id for i in all_items} == {m_imp.id, m_plain.id}  # Excludes trash & vanished

        inbox_items = unified_inbox(session, account_ids=[acc.id], folder_role="inbox").items
        assert {i.id for i in inbox_items} == {m_imp.id, m_plain.id}
        imp_row = next(i for i in inbox_items if i.id == m_imp.id)
        assert f_ghost_inbox.id not in {loc.folder_id for loc in imp_row.locations}

        # Global & group stats ignore missing / selectable=False folders (including f_sent_nosel -> f011)
        gstats = query_global_inbox_stats(session)
        assert next(a for a in gstats.accounts if a.account_id == acc.id).unread_count == 2
        grp_sent = query_group_inbox_stats(session, group.id, folder_role="sent")
        assert grp_sent.total_unread == 5
        assert next(a for a in grp_sent.accounts if a.account_id == acc.id).unread_count == 2

        # Missing/view-only messages never enqueue RemoteOperation across all 4 mutation paths
        op_before = len(list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == acc.id)).all()))
        assert set_message_read(session, m_ghost_only.id, is_read=True).operation_id is None
        assert set_message_flagged(session, m_ghost_only.id, is_flagged=True).operation_id is None
        assert mark_all_messages_read(session, account_id=acc.id, folder_id=f_ghost_only.id).count == 1
        assert trash_message(session, m_ghost_only.id).operation_id is None
        assert len(list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == acc.id)).all())) == op_before

        # mark_all_messages_read(..., folder_role="inbox") touches only active inbox, leaves m_trash unread
        assert mark_all_messages_read(session, account_id=acc.id, folder_role="inbox").count == 2
        assert session.get(Message, m_trash.id).is_read is False

        # Cross-priority writeback: make f_inbox missing so m_plain falls back from missing INBOX to active Archive
        f_inbox.remote_state = "missing"
        session.flush()
        res_arch = set_message_read(session, m_plain.id, is_read=False)
        assert session.get(RemoteOperation, res_arch.operation_id).desired_state["folder_remote_id"] == "Archive"
        session.commit()


def test_ac004_resolve_imap_trash_folder_and_trash_message_real_pg():
    """AC-004: _resolve_imap_trash_folder & trash_message select only active selectable container trash."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = Account(email=f"trash-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap", config={"imap_host": "imap.gmail.com"}, sync_enabled=True)
        session.add(acc)
        session.flush()
        f_inbox = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox", kind=CONTAINER, selectable=True, remote_state="active")
        f_missing_trash = Folder(account_id=acc.id, remote_id="OldTrash", name="OldTrash", role="trash", kind=CONTAINER, selectable=True, remote_state="missing")
        f_nosel_trash = Folder(account_id=acc.id, remote_id="NoSelTrash", name="NoSelTrash", role="trash", kind=CONTAINER, selectable=False, remote_state="active")
        f_view_trash = Folder(account_id=acc.id, remote_id="[Gmail]/ViewTrash", name="[Gmail]/ViewTrash", role="trash", kind=VIEW, selectable=True, remote_state="active")
        f_active_trash = Folder(account_id=acc.id, remote_id="Deleted", name="Deleted", role="trash", kind=CONTAINER, selectable=True, remote_state="active")
        session.add_all([f_inbox, f_missing_trash, f_nosel_trash, f_view_trash, f_active_trash])
        session.flush()
        msg = Message(account_id=acc.id, remote_id=format_imap_remote_id("INBOX", 1, 5), subject="Delete me", sort_time=now, is_read=True)
        session.add(msg)
        session.flush()
        session.add(MessageLocation(message_id=msg.id, folder_id=f_inbox.id, uid=5))
        session.commit()

        assert _resolve_imap_trash_folder(session, acc.id) == "Deleted"
        res = trash_message(session, msg.id)
        op = session.get(RemoteOperation, res.operation_id)
        assert op is not None and op.desired_state["trash_folder_remote_id"] == "Deleted"

        f_active_trash.remote_state = "missing"
        session.commit()
        with pytest.raises(UnaddressableMessageError):
            _resolve_imap_trash_folder(session, acc.id)


def test_ac004_http_folder_stats_schema_excludes_sync_status():
    """AC-004: GET /api/mail/accounts/{id}/folder-stats exposes kind/selectable without sync_status."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"api-stats-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap", config={"imap_host": "imap.gmail.com"}, sync_enabled=True)
        session.add(acc)
        session.flush()
        f_inbox = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox", kind=CONTAINER, selectable=True, remote_state="active")
        f_root = Folder(account_id=acc.id, remote_id="[Gmail]", name="[Gmail]", role="other", kind=CONTAINER, selectable=False, remote_state="active")
        f_imp = Folder(account_id=acc.id, remote_id="[Gmail]/Important", name="[Gmail]/Important", role="important", kind=VIEW, selectable=True, remote_state="active")
        f_gone = Folder(account_id=acc.id, remote_id="Gone", name="Gone", role="other", kind=CONTAINER, selectable=True, remote_state="missing")
        session.add_all([f_inbox, f_root, f_imp, f_gone])
        session.flush()
        m1 = Message(account_id=acc.id, remote_id=format_imap_remote_id("INBOX", 1, 1), subject="One", is_read=False)
        session.add(m1)
        session.flush()
        session.add_all([
            MessageLocation(message_id=m1.id, folder_id=f_inbox.id, uid=1),
            MessageLocation(message_id=m1.id, folder_id=f_imp.id, uid=None),
        ])
        session.commit()
        account_id = acc.id

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    resp = client.get(f"/api/mail/accounts/{account_id}/folder-stats")
    assert resp.status_code == 200
    rows = resp.json()["folders"]
    by_rid = {row["remote_id"]: row for row in rows}
    assert "Gone" not in by_rid
    assert all("sync_status" not in row and "kind" in row and "selectable" in row for row in rows)
    assert by_rid["[Gmail]"]["selectable"] is False
    assert by_rid["[Gmail]"]["unread_count"] is None and by_rid["[Gmail]"]["total_count"] is None
    assert by_rid["[Gmail]/Important"]["kind"] == VIEW and by_rid["[Gmail]/Important"]["total_count"] == 1
