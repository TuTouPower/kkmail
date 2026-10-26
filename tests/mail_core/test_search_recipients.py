"""Verify recipient and alias search support across message_search and accounts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.accounts import list_accounts_app
from mail_core.mail.storage.models import Account, Folder, Message, MessageSearch
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.search.index import (
    search_messages,
    search_messages_with_total,
    upsert_message_search,
)
from mail_core.sync.leases import acquire_lease
from mail_core.sync.metadata import apply_metadata_page


def test_recipient_address_in_search_and_account():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"primary-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
            display_name="Primary User",
        )
        session.add(acc)
        session.flush()
        acc_id = acc.id

        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        # 1. Direct message search upsert includes to_addresses in to_text
        msg = Message(
            account_id=acc.id,
            remote_id="msg-alias-1",
            subject="Welcome to our service",
            from_address="service@platform.org",
            from_name="Platform Team",
            to_addresses=["f.eng@example.com", "zzz001@zzzkkkccc.site"],
            sort_time=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.flush()

        search_row = upsert_message_search(session, message_id=msg.id)
        assert "zzz001@zzzkkkccc.site" in search_row.to_text
        assert "f.eng@example.com" in search_row.to_text

        # Search by alias address finds the message
        hits = search_messages(session, account_ids=[acc.id], query="zzz001@zzzkkkccc.site")
        assert msg.id in hits

        hits_partial = search_messages(session, account_ids=[acc.id], query="zzz001")
        assert msg.id in hits_partial

        hits_alias = search_messages(session, account_ids=[acc.id], query="f.eng")
        assert msg.id in hits_alias

        page_ids, total = search_messages_with_total(session, account_ids=[acc.id], query="f.eng")
        assert msg.id in page_ids
        assert total >= 1

        # 2. Syncing metadata automatically populates account.recipient_addresses
        lease = acquire_lease(session, account_id=acc.id, owner_id="worker-test", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="msg-alias-2",
                    subject="Invoice #1024",
                    from_address="billing@vendor.com",
                    from_name="Billing",
                    is_read=False,
                    has_attachments=False,
                    to_addresses=("fe.ng@example.com", "billing-alias@custom.io"),
                    sort_time=datetime.now(timezone.utc),
                    uid=1024,
                ),
            ],
            next_cursor={"uid_next": 1025, "uidvalidity": 1},
            exhausted=False,
        )
        apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()

    with Session() as session:
        reloaded_acc = session.get(Account, acc_id)
        assert reloaded_acc is not None
        assert "fe.ng@example.com" in reloaded_acc.recipient_addresses
        assert "billing-alias@custom.io" in reloaded_acc.recipient_addresses

        # list_accounts_app DTO output carries recipient_addresses
        page_dto = list_accounts_app()
        target_dto = next((a for a in page_dto.accounts if a.id == str(acc_id)), None)
        assert target_dto is not None
        assert "fe.ng@example.com" in target_dto.recipient_addresses
        assert "billing-alias@custom.io" in target_dto.recipient_addresses
