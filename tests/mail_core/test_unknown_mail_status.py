"""Unknown provider state stays unknown through persistence and read models."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import query_global_inbox_stats, unified_inbox
from mail_core.mail.storage.models import Account, Folder, FolderStats, Message
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync import acquire_lease, apply_metadata_page

pytestmark = pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")


def test_unknown_status_insert_and_stats_remain_unknown_until_provider_supplies_values():
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"unknown-{uuid.uuid4().hex[:8]}@example.com", provider="graph")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=account.id, owner_id="unknown-status", ttl=timedelta(minutes=5))

        def apply(read, flagged, attachments):
            apply_metadata_page(
                session, account_id=account.id, folder_id=folder.id, fencing_token=lease.fencing_token,
                page=MetadataPage(items=[RemoteMessageMeta(
                    remote_id="unknown", subject="Unknown", from_address="a@example.com", from_name=None,
                    sort_time=None, is_read=read, is_flagged=flagged, has_attachments=attachments,
                )], next_cursor={}, exhausted=True),
            )
            session.commit()

        apply(None, None, None)
        message = session.scalar(select(Message).where(Message.account_id == account.id))
        assert (message.is_read, message.is_flagged, message.has_attachments) == (None, None, None)
        stats = session.get(FolderStats, folder.id)
        assert stats.total_count == 1
        assert stats.unread_count is None
        global_stats = query_global_inbox_stats(session)
        assert global_stats.total_unread is None
        assert global_stats.accounts[0].total_count == 1
        page = unified_inbox(session, account_ids=[account.id])
        assert (page.items[0].is_read, page.items[0].is_flagged, page.items[0].has_attachments) == (None, None, None)

        apply(False, False, False)
        session.refresh(message)
        assert (message.is_read, message.is_flagged, message.has_attachments) == (False, False, False)
        assert session.get(FolderStats, folder.id).unread_count == 1
        apply(None, None, None)
        session.refresh(message)
        assert (message.is_read, message.is_flagged, message.has_attachments) == (False, False, False)
