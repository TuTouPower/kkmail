"""Gmail label ingestion and derived view projections (t086)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import list_folder_stats_for_account, unified_inbox
from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.domain.folder_views import CONTAINER, VIEW
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync import acquire_lease, apply_metadata_page

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _meta(remote_id: str, uid: int, labels: tuple[str, ...], is_read: bool) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=remote_id,
        subject=f"subject-{uid}",
        from_address="sender@example.test",
        from_name="Sender",
        sort_time=datetime.now(timezone.utc),
        is_read=is_read,
        has_attachments=False,
        uid=uid,
        labels=labels,
    )


def test_label_membership_becomes_location_and_views_return_real_counts():
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"labels-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap")
        session.add(account)
        session.flush()
        inbox = Folder(
            account_id=account.id,
            remote_id="INBOX",
            name="INBOX",
            role="inbox",
            kind=CONTAINER,
            sync_status=SyncStatus.IDLE.value,
        )
        important = Folder(
            account_id=account.id,
            remote_id="[Gmail]/Important",
            name="重要邮件",
            role="important",
            kind=VIEW,
            sync_status=SyncStatus.IDLE.value,
        )
        all_mail = Folder(
            account_id=account.id,
            remote_id="[Gmail]/All Mail",
            name="所有邮件",
            role="all",
            kind=VIEW,
            sync_status=SyncStatus.IDLE.value,
        )
        session.add_all([inbox, important, all_mail])
        session.flush()
        lease = acquire_lease(session, account_id=account.id, owner_id="w-t086", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                _meta("uid-1", 1, ("\\Important",), False),
                _meta("uid-2", 2, (), True),
            ],
            next_cursor=None,
            exhausted=True,
        )
        apply_metadata_page(
            session,
            account_id=account.id,
            folder_id=inbox.id,
            fencing_token=lease.fencing_token,
            page=page,
            label_view_folders={"\\Important": important.id},
        )
        session.flush()

        assert len(session.scalars(select(Message)).all()) == 2
        locations = list(session.scalars(select(MessageLocation)).all())
        assert len(locations) == 3
        important_locations = [loc for loc in locations if loc.folder_id == important.id]
        assert len(important_locations) == 1

        stats = {item["role"]: item for item in list_folder_stats_for_account(session, account.id)}
        assert stats["important"]["total_count"] == 1
        assert stats["important"]["unread_count"] == 1
        assert stats["all"]["total_count"] == 2
        assert stats["all"]["unread_count"] == 1

        important_page = unified_inbox(session, folder_id=important.id, limit=50)
        assert [item.subject for item in important_page.items] == ["subject-1"]
        all_page = unified_inbox(session, folder_id=all_mail.id, limit=50)
        assert sorted(item.subject for item in all_page.items) == ["subject-1", "subject-2"]


def test_view_labels_only_migrate_for_gmail_accounts_and_are_idempotent():
    import importlib

    migration = importlib.import_module(
        "mail_core.db.alembic.versions.20261123_0004_gmail_label_views"
    )
    Session = get_session_factory()
    with Session() as session:
        gmail = Account(email=f"mig-gmail-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap")
        other = Account(email=f"mig-other-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add_all([gmail, other])
        session.flush()
        gmail_folder = Folder(
            account_id=gmail.id,
            remote_id="[Gmail]/All Mail",
            name="All Mail",
            role="all",
            kind=CONTAINER,
            sync_status=SyncStatus.PAUSED.value,
        )
        other_folder = Folder(
            account_id=other.id,
            remote_id="custom-all",
            name="All",
            role="all",
            kind=CONTAINER,
            sync_status=SyncStatus.PAUSED.value,
        )
        session.add_all([gmail_folder, other_folder])
        session.flush()
        before = len(session.scalars(select(Message)).all())

        session.execute(migration.view_update_statement("view", "idle"))
        session.execute(migration.view_update_statement("view", "idle"))
        session.flush()
        session.expire_all()

        assert session.get(Folder, gmail_folder.id).kind == VIEW
        assert session.get(Folder, gmail_folder.id).sync_status == SyncStatus.IDLE.value
        assert session.get(Folder, other_folder.id).kind == CONTAINER
        assert session.get(Folder, other_folder.id).sync_status == SyncStatus.PAUSED.value
        assert len(session.scalars(select(Message)).all()) == before


def test_label_mapping_is_derived_from_db_when_not_supplied():
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"derive-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap")
        session.add(account)
        session.flush()
        inbox = Folder(
            account_id=account.id,
            remote_id="INBOX",
            name="INBOX",
            role="inbox",
            kind=CONTAINER,
        )
        important = Folder(
            account_id=account.id,
            remote_id="[Gmail]/Important",
            name="Important",
            role="important",
            kind=VIEW,
        )
        session.add_all([inbox, important])
        session.flush()
        lease = acquire_lease(session, account_id=account.id, owner_id="w-derive", ttl=timedelta(minutes=5))
        apply_metadata_page(
            session,
            account_id=account.id,
            folder_id=inbox.id,
            fencing_token=lease.fencing_token,
            page=MetadataPage(items=[_meta("derived-1", 1, ("\\Important",), False)], next_cursor=None, exhausted=True),
        )
        assert any(
            loc.folder_id == important.id for loc in session.scalars(select(MessageLocation)).all()
        )


def test_empty_view_reports_real_zero_counts():
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"empty-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap")
        session.add(account)
        session.flush()
        all_mail = Folder(
            account_id=account.id,
            remote_id="[Gmail]/All Mail",
            name="All Mail",
            role="all",
            kind=VIEW,
            sync_status=SyncStatus.IDLE.value,
        )
        session.add(all_mail)
        session.flush()
        stats = {item["role"]: item for item in list_folder_stats_for_account(session, account.id)}
        assert stats["all"]["total_count"] == 0
        assert stats["all"]["unread_count"] == 0
