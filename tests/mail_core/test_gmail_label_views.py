"""Gmail label ingestion and derived view projections (t086)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import list_folder_stats_for_account, unified_inbox
from mail_core.mail.domain.enums import FolderRemoteState
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
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        important = Folder(
            account_id=account.id,
            remote_id="[Gmail]/Important",
            name="重要邮件",
            role="important",
            kind=VIEW,
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        all_mail = Folder(
            account_id=account.id,
            remote_id="[Gmail]/All Mail",
            name="所有邮件",
            role="all",
            kind=VIEW,
            remote_state=FolderRemoteState.ACTIVE.value,
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
    """t092: 0004 迁移依赖已被 0007 移除的 folders.sync_status 列；在隔离的 0004 临时库验证幂等性。"""
    import importlib
    import os
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    migration = importlib.import_module(
        "mail_core.db.alembic.versions.20261123_0004_gmail_label_views"
    )
    root = Path(__file__).resolve().parents[2]
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_mig0004_{uuid.uuid4().hex[:16]}"
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    temp_url = parsed.set(database=db_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target = create_engine(temp_url, poolclass=NullPool)
    cfg = Config(str(root / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/mail_core/db/alembic"))
    cfg.set_main_option("sqlalchemy.url", temp_url.replace("%", "%%"))

    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        command.upgrade(cfg, "20261123_0004")

        gmail_id = uuid.uuid4()
        other_id = uuid.uuid4()
        gmail_folder_id = uuid.uuid4()
        other_folder_id = uuid.uuid4()
        with target.begin() as conn:
            conn.execute(
                text("INSERT INTO accounts (id, email, provider) VALUES (:id, :email, 'imap')"),
                [
                    {"id": gmail_id, "email": f"mig-gmail-{uuid.uuid4().hex[:8]}@gmail.com"},
                    {"id": other_id, "email": f"mig-other-{uuid.uuid4().hex[:8]}@example.com"},
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO folders (id, account_id, remote_id, name, role, kind, sync_status) "
                    "VALUES (:id, :aid, :rid, :name, :role, :kind, :status)"
                ),
                [
                    {
                        "id": gmail_folder_id,
                        "aid": gmail_id,
                        "rid": "[Gmail]/All Mail",
                        "name": "All Mail",
                        "role": "all",
                        "kind": CONTAINER,
                        "status": "paused",
                    },
                    {
                        "id": other_folder_id,
                        "aid": other_id,
                        "rid": "custom-all",
                        "name": "All",
                        "role": "all",
                        "kind": CONTAINER,
                        "status": "paused",
                    },
                ],
            )
            conn.execute(migration.view_update_statement("view", "idle"))
            conn.execute(migration.view_update_statement("view", "idle"))

            gmail_row = (
                conn.execute(
                    text("SELECT kind, sync_status FROM folders WHERE id = :id"),
                    {"id": gmail_folder_id},
                )
                .mappings()
                .one()
            )
            other_row = (
                conn.execute(
                    text("SELECT kind, sync_status FROM folders WHERE id = :id"),
                    {"id": other_folder_id},
                )
                .mappings()
                .one()
            )
            assert gmail_row["kind"] == VIEW
            assert gmail_row["sync_status"] == "idle"
            assert other_row["kind"] == CONTAINER
            assert other_row["sync_status"] == "paused"
            assert conn.execute(text("SELECT count(*) FROM messages")).scalar_one() == 0
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


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
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(all_mail)
        session.flush()
        stats = {item["role"]: item for item in list_folder_stats_for_account(session, account.id)}
        assert stats["all"]["total_count"] == 0
        assert stats["all"]["unread_count"] == 0
