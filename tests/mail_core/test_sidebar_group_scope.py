from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, AccountGroup, Folder, FolderStats, Message, MessageLocation, OutboxEvent, RemoteOperation
from mail_core.search.index import upsert_message_search
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")


def current_sidebar_revision(client: TestClient) -> str:
    response = client.get("/api/sidebar/layout")
    assert response.status_code == 200
    return response.json()["revision"]


def put_sidebar_layout(client: TestClient, layout: dict[str, object]):
    return client.put("/api/sidebar/layout", json={**layout, "expected_revision": current_sidebar_revision(client)})


def reset_sidebar_order(client: TestClient):
    return client.post("/api/sidebar/layout/default-order", json={"expected_revision": current_sidebar_revision(client)})


def test_group_scope_is_empty_safe_and_applies_to_search_stats_and_mark_all():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        group = AccountGroup(name=f"sidebar-{uuid.uuid4().hex}")
        other_group = AccountGroup(name=f"sidebar-other-{uuid.uuid4().hex}")
        session.add_all([group, other_group])
        session.flush()
        member = Account(email=f"member-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        outsider = Account(email=f"outsider-{uuid.uuid4().hex}@example.test", provider="imap", group_id=other_group.id)
        session.add_all([member, outsider])
        session.flush()
        inboxes = [
            Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            for acc in (member, outsider)
        ]
        session.add_all(inboxes)
        session.flush()
        messages = [
            Message(account_id=member.id, remote_id="member", subject="Group scoped lighthouse", from_address="a@example.test", sort_time=now, is_read=False),
            Message(account_id=outsider.id, remote_id="outsider", subject="Group scoped lighthouse", from_address="b@example.test", sort_time=now, is_read=False),
        ]
        session.add_all(messages)
        session.flush()
        for idx, (message, folder) in enumerate(zip(messages, inboxes, strict=True), 1):
            session.add(MessageLocation(message_id=message.id, folder_id=folder.id, uid=idx))
            session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=1))
            upsert_message_search(session, message_id=message.id, body_text="shared phrase")
        group_id = group.id
        empty_group = AccountGroup(name=f"sidebar-empty-{uuid.uuid4().hex}")
        session.add(empty_group)
        session.commit()
        empty_group_id = empty_group.id
        member_id = member.id
        member_message_id = messages[0].id
        member_folder_id = inboxes[0].id
        outsider_message_id = messages[1].id

    group_inbox = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert group_inbox.status_code == 200
    assert len(group_inbox.json()["items"]) == 1
    assert group_inbox.json()["items"][0]["account_id"] == str(member_id)

    group_search = client.get("/api/mail/search", params={"q": "lighthouse", "group_id": str(group_id)})
    assert group_search.status_code == 200
    assert group_search.json()["total"] == 1
    assert group_search.json()["items"][0]["account_id"] == str(member_id)
    folder_search = client.get("/api/mail/search", params={"q": "lighthouse", "folder_id": str(member_folder_id)})
    assert folder_search.status_code == 200
    assert folder_search.json()["total"] == 1
    assert folder_search.json()["items"][0]["account_id"] == str(member_id)

    group_stats = client.get("/api/mail/stats", params={"group_id": str(group_id)})
    assert group_stats.status_code == 200
    assert group_stats.json()["total_unread"] == 1
    assert group_stats.json()["accounts"][0]["account_id"] == str(member_id)

    empty_inbox = client.get("/api/mail/inbox", params={"group_id": str(empty_group_id)})
    assert empty_inbox.status_code == 200
    assert empty_inbox.json()["items"] == []
    empty_search = client.get("/api/mail/search", params={"q": "lighthouse", "group_id": str(empty_group_id)})
    assert empty_search.status_code == 200
    assert empty_search.json()["total"] == 0

    ambiguous = client.get("/api/mail/inbox", params={"group_id": str(group_id), "account_id": str(member_id)})
    assert ambiguous.status_code == 400
    invalid = client.get("/api/mail/search", params={"q": "x", "group_id": str(uuid.uuid4())})
    assert invalid.status_code == 404

    marked = client.post("/api/mail/mark-all-read", json={"group_id": str(group_id), "folder_role": "inbox"})
    assert marked.status_code == 200
    assert marked.json()["count"] == 1
    with Session() as session:
        assert session.get(Message, member_message_id).is_read is True
        assert session.get(Message, outsider_message_id).is_read is False
        assert session.scalar(select(RemoteOperation.id).where(RemoteOperation.account_id == member_id)) is not None
        assert session.scalar(select(OutboxEvent.id).where(OutboxEvent.account_id == member_id, OutboxEvent.event_type == "message.upserted")) is not None
    folder_ambiguous = client.post("/api/mail/mark-all-read", json={
        "group_id": str(group_id),
        "folder_id": str(member_folder_id),
    })
    assert folder_ambiguous.status_code == 400
    empty_stats = client.get("/api/mail/stats", params={"group_id": str(empty_group_id)})
    assert empty_stats.status_code == 200
    assert empty_stats.json()["total_unread"] == 0
    empty_marked = client.post("/api/mail/mark-all-read", json={"group_id": str(empty_group_id)})
    assert empty_marked.status_code == 200 and empty_marked.json()["count"] == 0


def test_disabled_accounts_are_excluded_from_aggregate_scopes_but_remain_directly_addressable():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    phrase = f"disabled-scope-{uuid.uuid4().hex}"
    with Session() as session:
        group = AccountGroup(name=f"disabled-scope-{uuid.uuid4().hex}")
        disabled_only_group = AccountGroup(name=f"disabled-only-{uuid.uuid4().hex}")
        session.add_all([group, disabled_only_group])
        session.flush()
        enabled = Account(email=f"enabled-{uuid.uuid4().hex}@example.test", provider="memory", group_id=group.id)
        disabled = Account(
            email=f"disabled-{uuid.uuid4().hex}@example.test",
            provider="memory",
            group_id=group.id,
            sync_enabled=False,
        )
        disabled_only = Account(
            email=f"disabled-only-{uuid.uuid4().hex}@example.test",
            provider="memory",
            group_id=disabled_only_group.id,
            sync_enabled=False,
        )
        session.add_all([enabled, disabled, disabled_only])
        session.flush()
        accounts = (enabled, disabled, disabled_only)
        folders = [Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox") for account in accounts]
        session.add_all(folders)
        session.flush()
        messages = [
            Message(
                account_id=account.id,
                remote_id=f"{phrase}-{index}",
                subject=phrase,
                from_address="sender@example.test",
                sort_time=now,
                is_read=False,
            )
            for index, account in enumerate(accounts)
        ]
        session.add_all(messages)
        session.flush()
        for index, (message, folder) in enumerate(zip(messages, folders, strict=True), 1):
            session.add(MessageLocation(message_id=message.id, folder_id=folder.id, uid=index))
            session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=1))
            upsert_message_search(session, message_id=message.id, body_text=phrase)
        group_id = group.id
        disabled_only_group_id = disabled_only_group.id
        enabled_id, disabled_id, disabled_only_id = (account.id for account in accounts)
        enabled_message_id, disabled_message_id, disabled_only_message_id = (message.id for message in messages)
        disabled_folder_id = folders[1].id
        session.commit()

    group_inbox = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert group_inbox.status_code == 200
    assert [item["account_id"] for item in group_inbox.json()["items"]] == [str(enabled_id)]

    global_inbox = client.get("/api/mail/inbox")
    assert global_inbox.status_code == 200
    assert str(disabled_id) not in {item["account_id"] for item in global_inbox.json()["items"]}

    group_search = client.get("/api/mail/search", params={"q": phrase, "group_id": str(group_id)})
    assert group_search.status_code == 200
    assert group_search.json()["total"] == 1
    assert [item["account_id"] for item in group_search.json()["items"]] == [str(enabled_id)]

    global_search = client.get("/api/mail/search", params={"q": phrase})
    assert global_search.status_code == 200
    assert str(disabled_id) not in {item["account_id"] for item in global_search.json()["items"]}
    assert global_search.json()["total"] == 1

    group_stats = client.get("/api/mail/stats", params={"group_id": str(group_id)})
    assert group_stats.status_code == 200
    assert [item["account_id"] for item in group_stats.json()["accounts"]] == [str(enabled_id)]
    global_stats = client.get("/api/mail/stats")
    assert global_stats.status_code == 200
    assert global_stats.json()["total_unread"] == 1
    assert str(disabled_id) not in {item["account_id"] for item in global_stats.json()["accounts"]}

    disabled_only_inbox = client.get("/api/mail/inbox", params={"group_id": str(disabled_only_group_id)})
    assert disabled_only_inbox.status_code == 200 and disabled_only_inbox.json()["items"] == []
    disabled_only_search = client.get("/api/mail/search", params={"q": phrase, "group_id": str(disabled_only_group_id)})
    assert disabled_only_search.status_code == 200 and disabled_only_search.json()["total"] == 0
    disabled_only_stats = client.get("/api/mail/stats", params={"group_id": str(disabled_only_group_id)})
    assert disabled_only_stats.status_code == 200
    assert disabled_only_stats.json() == {"total_unread": 0, "accounts": []}

    direct_disabled = client.get("/api/mail/inbox", params={"account_id": str(disabled_id)})
    assert direct_disabled.status_code == 200
    assert [item["account_id"] for item in direct_disabled.json()["items"]] == [str(disabled_id)]
    direct_folder = client.get("/api/mail/inbox", params={"folder_id": str(disabled_folder_id)})
    assert direct_folder.status_code == 200
    assert [item["account_id"] for item in direct_folder.json()["items"]] == [str(disabled_id)]

    marked = client.post("/api/mail/mark-all-read", json={"group_id": str(group_id)})
    assert marked.status_code == 200 and marked.json()["count"] == 1
    disabled_only_marked = client.post("/api/mail/mark-all-read", json={"group_id": str(disabled_only_group_id)})
    assert disabled_only_marked.status_code == 200 and disabled_only_marked.json()["count"] == 0
    global_marked = client.post("/api/mail/mark-all-read", json={})
    assert global_marked.status_code == 200 and global_marked.json()["count"] == 0
    with Session() as session:
        assert session.get(Message, enabled_message_id).is_read is True
        assert session.get(Message, disabled_message_id).is_read is False
        assert session.get(Message, disabled_only_message_id).is_read is False
        assert session.get(Account, disabled_id).sync_enabled is False
        assert session.get(Account, disabled_only_id).sync_enabled is False

    layout_before_enable = client.get("/api/sidebar/layout").json()
    disabled_all_active = client.patch(f"/api/accounts/{enabled_id}", json={"sync_enabled": False})
    assert disabled_all_active.status_code == 200
    assert client.get("/api/mail/inbox").json()["items"] == []
    assert client.get("/api/mail/search", params={"q": phrase}).json()["total"] == 0
    global_stats_with_all_disabled = client.get("/api/mail/stats").json()
    assert global_stats_with_all_disabled == {"total_unread": 0, "accounts": []}

    no_op_update = client.patch(f"/api/accounts/{disabled_id}", json={"sync_enabled": False})
    assert no_op_update.status_code == 200
    with Session() as session:
        assert session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.account_id == disabled_id,
                OutboxEvent.event_type == "account.updated",
            )
        ) is None

    enabled_again = client.patch(f"/api/accounts/{disabled_id}", json={"sync_enabled": True})
    assert enabled_again.status_code == 200, enabled_again.text
    assert enabled_again.json()["sync_enabled"] is True
    still_disabled_group = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert {item["account_id"] for item in still_disabled_group.json()["items"]} == {str(disabled_id)}
    enabled_after_empty = client.patch(f"/api/accounts/{enabled_id}", json={"sync_enabled": True})
    assert enabled_after_empty.status_code == 200
    assert enabled_after_empty.json()["sync_enabled"] is True
    group_after_enable = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert {item["account_id"] for item in group_after_enable.json()["items"]} == {str(enabled_id), str(disabled_id)}

    disabled_again = client.patch(f"/api/accounts/{enabled_id}", json={"sync_enabled": False})
    assert disabled_again.status_code == 200 and disabled_again.json()["sync_enabled"] is False
    group_after_disable = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert {item["account_id"] for item in group_after_disable.json()["items"]} == {str(disabled_id)}
    enabled_once_more = client.patch(f"/api/accounts/{enabled_id}", json={"sync_enabled": True})
    assert enabled_once_more.status_code == 200 and enabled_once_more.json()["sync_enabled"] is True

    layout_after_enable = client.get("/api/sidebar/layout").json()
    assert layout_after_enable["master_account_ids"] == layout_before_enable["master_account_ids"]
    assert layout_after_enable["group_account_ids"] == layout_before_enable["group_account_ids"]
    with Session() as session:
        account_updates = list(session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.account_id == disabled_id,
                OutboxEvent.event_type == "account.updated",
            )
            .order_by(OutboxEvent.id)
        ))
        enabled_account_updates = list(session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.account_id == enabled_id,
                OutboxEvent.event_type == "account.updated",
            )
            .order_by(OutboxEvent.id)
        ))
        assert [event.payload for event in account_updates] == [{"sync_enabled": True}]
        assert [event.payload for event in enabled_account_updates] == [
            {"sync_enabled": False},
            {"sync_enabled": True},
            {"sync_enabled": False},
            {"sync_enabled": True},
        ]


def test_global_and_group_stats_keep_missing_folder_stats_unknown():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-unknown-stats-{uuid.uuid4().hex}")
        session.add(group)
        session.flush()
        known = Account(email=f"known-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        unknown = Account(email=f"unknown-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        session.add_all([known, unknown])
        session.flush()
        known_folder = Folder(account_id=known.id, remote_id="INBOX", name="INBOX", role="inbox")
        unknown_folder = Folder(account_id=unknown.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add_all([known_folder, unknown_folder])
        session.flush()
        session.add(FolderStats(folder_id=known_folder.id, total_count=0, unread_count=0))
        known_id, unknown_id, group_id = known.id, unknown.id, group.id
        session.commit()

    global_stats = client.get("/api/mail/stats").json()
    global_by_account = {item["account_id"]: item["unread_count"] for item in global_stats["accounts"]}
    assert global_by_account[str(known_id)] == 0
    assert global_by_account[str(unknown_id)] is None
    assert global_stats["total_unread"] is None

    group_stats = client.get("/api/mail/stats", params={"group_id": str(group_id)}).json()
    group_by_account = {item["account_id"]: item["unread_count"] for item in group_stats["accounts"]}
    assert group_by_account == {str(known_id): 0, str(unknown_id): None}
    assert group_stats["total_unread"] is None


def test_group_mark_all_read_honors_flag_filter_and_keeps_outsiders_unread():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-flag-filter-{uuid.uuid4().hex}")
        session.add(group)
        session.flush()
        member = Account(email=f"sidebar-flag-member-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        outsider = Account(email=f"sidebar-flag-outsider-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add_all([member, outsider])
        session.flush()
        member_folder = Folder(account_id=member.id, remote_id="INBOX", name="INBOX", role="inbox")
        outside_folder = Folder(account_id=outsider.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add_all([member_folder, outside_folder])
        session.flush()
        now = datetime.now(timezone.utc)
        flagged = Message(account_id=member.id, remote_id=f"flagged-{uuid.uuid4().hex}", subject="flagged", from_address="a@example.test", sort_time=now, is_read=False, is_flagged=True)
        unflagged = Message(account_id=member.id, remote_id=f"unflagged-{uuid.uuid4().hex}", subject="unflagged", from_address="a@example.test", sort_time=now, is_read=False, is_flagged=False)
        outside = Message(account_id=outsider.id, remote_id=f"outside-{uuid.uuid4().hex}", subject="outside", from_address="b@example.test", sort_time=now, is_read=False, is_flagged=True)
        session.add_all([flagged, unflagged, outside])
        session.flush()
        session.add_all([
            MessageLocation(message_id=flagged.id, folder_id=member_folder.id, uid=1),
            MessageLocation(message_id=unflagged.id, folder_id=member_folder.id, uid=2),
            MessageLocation(message_id=outside.id, folder_id=outside_folder.id, uid=1),
            FolderStats(folder_id=member_folder.id, total_count=2, unread_count=2),
            FolderStats(folder_id=outside_folder.id, total_count=1, unread_count=1),
        ])
        group_id, member_id = group.id, member.id
        flagged_id, unflagged_id, outside_id = flagged.id, unflagged.id, outside.id
        session.commit()

    result = client.post("/api/mail/mark-all-read", json={
        "group_id": str(group_id),
        "folder_role": "inbox",
        "is_flagged": True,
    })
    assert result.status_code == 200 and result.json()["count"] == 1
    with Session() as session:
        assert session.get(Message, flagged_id).is_read is True
        assert session.get(Message, unflagged_id).is_read is False
        assert session.get(Message, outside_id).is_read is False
        assert session.scalar(select(RemoteOperation.id).where(RemoteOperation.account_id == member_id)) is not None


def test_group_order_endpoint_persists_membership_and_independent_account_orders():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-order-{uuid.uuid4().hex}")
        first = Account(email=f"z-{uuid.uuid4().hex}@z.example", provider="imap", group_id=group.id)
        second = Account(email=f"a-{uuid.uuid4().hex}@a.example", provider="imap")
        session.add_all([group, first, second])
        session.commit()
        group_id, first_id, second_id = group.id, first.id, second.id

    response = put_sidebar_layout(client, {
        "group_ids": [str(group_id)],
        "master_account_ids": [str(first_id), str(second_id)],
        "ungrouped_account_ids": [str(second_id)],
        "group_account_ids": {str(group_id): [str(first_id)]},
    })
    assert response.status_code == 204
    with Session() as session:
        first = session.get(Account, first_id)
        second = session.get(Account, second_id)
        assert first.group_id == group_id
        assert second.group_id is None
        assert first.master_order == 0 and second.master_order == 1
        assert first.group_order == 0

    invalid = put_sidebar_layout(client, {
        "group_ids": [str(group_id)],
        "master_account_ids": [str(first_id), str(first_id)],
        "ungrouped_account_ids": [str(second_id)],
        "group_account_ids": {str(group_id): [str(first_id)]},
    })
    assert invalid.status_code == 400
    with Session() as session:
        assert session.get(Account, first_id).group_id == group_id
        assert session.get(Account, second_id).group_id is None


def test_nonexistent_group_is_not_treated_as_unscoped_for_inbox():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    response = client.get("/api/mail/inbox", params={"group_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_sidebar_account_orders_are_independent_and_reset_keeps_membership():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    with Session() as session:
        first_group = AccountGroup(name=f"sidebar-layout-a-{uuid.uuid4().hex}")
        second_group = AccountGroup(name=f"sidebar-layout-b-{uuid.uuid4().hex}")
        session.add_all([first_group, second_group])
        session.flush()
        z_account = Account(email=f"z-{uuid.uuid4().hex}@z.example", provider="imap", group_id=first_group.id)
        a_account = Account(email=f"a-{uuid.uuid4().hex}@a.example", provider="imap", group_id=first_group.id)
        m_account = Account(email=f"m-{uuid.uuid4().hex}@m.example", provider="imap", group_id=second_group.id)
        u_account = Account(email=f"u-{uuid.uuid4().hex}@u.example", provider="imap")
        session.add_all([z_account, a_account, m_account, u_account])
        session.commit()
        first_group_id, second_group_id = first_group.id, second_group.id
        z_id, a_id, m_id, u_id = z_account.id, a_account.id, m_account.id, u_account.id

    default_members = client.get("/api/accounts", params={"group_id": str(first_group_id)}).json()["accounts"]
    assert [item["id"] for item in default_members] == [str(a_id), str(z_id)]
    layout = {
        "group_ids": [str(second_group_id), str(first_group_id)],
        "master_account_ids": [str(u_id), str(m_id), str(z_id), str(a_id)],
        "ungrouped_account_ids": [str(u_id)],
        "group_account_ids": {
            str(first_group_id): [str(z_id), str(a_id)],
            str(second_group_id): [str(m_id)],
        },
    }
    assert put_sidebar_layout(client, layout).status_code == 204
    persisted_members = client.get("/api/accounts", params={"group_id": str(first_group_id)}).json()["accounts"]
    assert [item["id"] for item in persisted_members] == [str(z_id), str(a_id)]
    persisted_master = client.get("/api/accounts", params={"limit": 500}).json()["accounts"]
    target_order = [str(u_id), str(m_id), str(z_id), str(a_id)]
    current_order = [item["id"] for item in persisted_master]
    assert [item_id for item_id in current_order if item_id in target_order] == target_order

    layout["master_account_ids"] = [str(a_id), str(u_id), str(z_id), str(m_id)]
    assert put_sidebar_layout(client, layout).status_code == 204
    unchanged_members = client.get("/api/accounts", params={"group_id": str(first_group_id)}).json()["accounts"]
    assert [item["id"] for item in unchanged_members] == [str(z_id), str(a_id)]

    assert reset_sidebar_order(client).status_code == 204
    with Session() as session:
        assert session.get(Account, z_id).group_id == first_group_id
        assert session.get(Account, a_id).group_id == first_group_id
        assert session.get(Account, m_id).group_id == second_group_id
        assert session.get(Account, u_id).group_id is None
        assert all(session.get(Account, account_id).master_order is None for account_id in (z_id, a_id, m_id, u_id))
        assert all(session.get(Account, account_id).group_order is None for account_id in (z_id, a_id, m_id))
        assert session.get(AccountGroup, second_group_id).sort_order == 0
        assert session.get(AccountGroup, first_group_id).sort_order == 1
    reset_members = client.get("/api/accounts", params={"group_id": str(first_group_id)}).json()["accounts"]
    assert [item["id"] for item in reset_members] == [str(a_id), str(z_id)]


def test_invalid_complete_sidebar_layout_is_atomic():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-invalid-{uuid.uuid4().hex}")
        session.add(group)
        session.flush()
        member = Account(email=f"invalid-member-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        outsider = Account(email=f"invalid-outsider-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add_all([member, outsider])
        session.commit()
        group_id, member_id, outsider_id = group.id, member.id, outsider.id
    baseline = {
        "group_ids": [str(group_id)],
        "master_account_ids": [str(member_id), str(outsider_id)],
        "ungrouped_account_ids": [str(outsider_id)],
        "group_account_ids": {str(group_id): [str(member_id)]},
    }
    invalid_layouts = []
    missing_group = {**baseline, "group_account_ids": {}}
    invalid_layouts.append(missing_group)
    other_group_member = {**baseline, "group_account_ids": {str(group_id): [str(outsider_id)]}}
    invalid_layouts.append(other_group_member)
    overlapping = {**baseline, "ungrouped_account_ids": [str(member_id), str(outsider_id)]}
    invalid_layouts.append(overlapping)
    for payload in invalid_layouts:
        response = put_sidebar_layout(client, payload)
        assert response.status_code == 400
        with Session() as session:
            assert session.get(Account, member_id).group_id == group_id
            assert session.get(Account, outsider_id).group_id is None
            assert session.get(Account, member_id).master_order is None
            assert session.get(Account, outsider_id).master_order is None


def test_group_delete_and_layout_save_have_consistent_lock_order():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-race-{uuid.uuid4().hex}")
        session.add(group)
        session.flush()
        member = Account(email=f"sidebar-race-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        session.add(member)
        session.commit()
        group_id, account_id = group.id, member.id
    snapshot = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"}).get("/api/sidebar/layout").json()
    layout = {key: snapshot[key] for key in (
        "group_ids", "master_account_ids", "ungrouped_account_ids", "group_account_ids",
    )}
    layout["expected_revision"] = snapshot["revision"]
    barrier = Barrier(2)

    def save_layout():
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        barrier.wait(timeout=10)
        return client.put("/api/sidebar/layout", json=layout)

    def delete_group():
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        barrier.wait(timeout=10)
        return client.delete(f"/api/groups/{group_id}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        layout_result = pool.submit(save_layout)
        delete_result = pool.submit(delete_group)
        layout_response = layout_result.result(timeout=20)
        delete_response = delete_result.result(timeout=20)
    assert layout_response.status_code in {204, 409}
    assert delete_response.status_code == 204
    with Session() as session:
        assert session.get(AccountGroup, group_id) is None
        account = session.get(Account, account_id)
        assert account is not None and account.group_id is None


def test_concurrent_sidebar_layout_writes_reject_one_stale_full_snapshot():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    Session = get_session_factory()
    with Session() as session:
        groups = [AccountGroup(name=f"sidebar-revision-{uuid.uuid4().hex}") for _ in range(2)]
        session.add_all(groups)
        session.flush()
        accounts = [
            Account(email=f"sidebar-revision-{uuid.uuid4().hex}@example.test", provider="imap", group_id=groups[index].id)
            for index in range(2)
        ]
        session.add_all(accounts)
        session.commit()

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    snapshot = client.get("/api/sidebar/layout").json()
    base = {key: snapshot[key] for key in (
        "group_ids", "master_account_ids", "ungrouped_account_ids", "group_account_ids",
    )}
    first_layout = {
        **base,
        "group_ids": list(reversed(base["group_ids"])),
        "expected_revision": snapshot["revision"],
    }
    second_layout = {
        **base,
        "master_account_ids": list(reversed(base["master_account_ids"])),
        "expected_revision": snapshot["revision"],
    }
    barrier = Barrier(2)

    def save_layout(payload: dict[str, object]):
        request_client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        barrier.wait(timeout=10)
        return request_client.put("/api/sidebar/layout", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save_layout, first_layout)
        second = pool.submit(save_layout, second_layout)
        responses = [first.result(timeout=20), second.result(timeout=20)]

    assert sorted(response.status_code for response in responses) == [204, 409]
    winner = first_layout if responses[0].status_code == 204 else second_layout
    current = client.get("/api/sidebar/layout").json()
    assert current["group_ids"] == winner["group_ids"]
    assert current["master_account_ids"] == winner["master_account_ids"]
    assert current["ungrouped_account_ids"] == winner["ungrouped_account_ids"]
    assert current["group_account_ids"] == winner["group_account_ids"]


def test_moving_account_into_concurrently_deleted_group_returns_conflict_not_server_error():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"sidebar-move-delete-{uuid.uuid4().hex}")
        account = Account(email=f"sidebar-move-delete-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add_all([group, account])
        session.commit()
        group_id, account_id = group.id, account.id

    barrier = Barrier(2)

    def move_account():
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        barrier.wait(timeout=10)
        return client.patch(f"/api/accounts/{account_id}", json={"group_id": str(group_id)})

    def delete_group():
        client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        barrier.wait(timeout=10)
        return client.delete(f"/api/groups/{group_id}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        move_result = pool.submit(move_account)
        delete_result = pool.submit(delete_group)
        move_response = move_result.result(timeout=20)
        delete_response = delete_result.result(timeout=20)

    assert move_response.status_code in {200, 404}
    assert delete_response.status_code == 204
    with Session() as session:
        account = session.get(Account, account_id)
        assert account is not None and account.group_id is None


def test_group_scope_covers_roles_pagination_search_offsets_and_member_changes():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    Session = get_session_factory()
    timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with Session() as session:
        group = AccountGroup(name=f"sidebar-scope-{uuid.uuid4().hex}")
        other_group = AccountGroup(name=f"sidebar-scope-other-{uuid.uuid4().hex}")
        session.add_all([group, other_group])
        session.flush()
        first = Account(email=f"scope-a-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        second = Account(email=f"scope-b-{uuid.uuid4().hex}@example.test", provider="imap", group_id=group.id)
        outsider = Account(email=f"scope-out-{uuid.uuid4().hex}@example.test", provider="imap", group_id=other_group.id)
        session.add_all([first, second, outsider])
        session.flush()
        inbox_a = Folder(account_id=first.id, remote_id="INBOX", name="INBOX", role="inbox")
        inbox_a_duplicate = Folder(account_id=first.id, remote_id="INBOX-ALIAS", name="INBOX Alias", role="inbox")
        sent_a = Folder(account_id=first.id, remote_id="Sent", name="Sent", role="sent")
        inbox_b = Folder(account_id=second.id, remote_id="INBOX", name="INBOX", role="inbox")
        sent_b = Folder(account_id=second.id, remote_id="Sent", name="Sent", role="sent")
        inbox_out = Folder(account_id=outsider.id, remote_id="INBOX", name="INBOX", role="inbox")
        roles = ("drafts", "trash", "junk", "archive")
        extra_folders = {
            (role, owner): Folder(
                account_id=account.id,
                remote_id=f"{role}-{owner}",
                name=f"{role.title()} {owner}",
                role=role,
            )
            for role in roles
            for owner, account in (("a", first), ("b", second), ("out", outsider))
        }
        session.add_all([inbox_a, inbox_a_duplicate, sent_a, inbox_b, sent_b, inbox_out, *extra_folders.values()])
        session.flush()
        group_messages = [
            Message(account_id=first.id, remote_id=f"scope-a-{index}-{uuid.uuid4().hex}", subject="shared lighthouse", from_address="a@example.test", sort_time=timestamp, is_read=False)
            for index in range(2)
        ] + [
            Message(account_id=second.id, remote_id=f"scope-b-{uuid.uuid4().hex}", subject="shared lighthouse", from_address="b@example.test", sort_time=timestamp, is_read=False),
        ]
        sent_message = Message(account_id=first.id, remote_id=f"scope-sent-{uuid.uuid4().hex}", subject="sent lighthouse", from_address="a@example.test", sort_time=timestamp, is_read=True)
        outside_message = Message(account_id=outsider.id, remote_id=f"scope-out-{uuid.uuid4().hex}", subject="shared lighthouse", from_address="out@example.test", sort_time=timestamp, is_read=False)
        role_messages = {
            role: [
                Message(
                    account_id=account.id,
                    remote_id=f"scope-{role}-{owner}-{uuid.uuid4().hex}",
                    subject=f"{role} scoped message",
                    from_address=f"{owner}@example.test",
                    sort_time=timestamp,
                    is_read=False,
                )
                for owner, account in (("a", first), ("b", second), ("out", outsider))
            ]
            for role in roles
        }
        session.add_all([*group_messages, sent_message, outside_message, *(message for messages in role_messages.values() for message in messages)])
        session.flush()
        for message in group_messages[:2]:
            session.add(MessageLocation(message_id=message.id, folder_id=inbox_a.id))
        session.add(MessageLocation(message_id=group_messages[0].id, folder_id=inbox_a_duplicate.id))
        session.add(MessageLocation(message_id=group_messages[2].id, folder_id=inbox_b.id))
        session.add(MessageLocation(message_id=sent_message.id, folder_id=sent_a.id))
        session.add(MessageLocation(message_id=outside_message.id, folder_id=inbox_out.id))
        for role, messages in role_messages.items():
            for (owner, _account), message in zip((("a", first), ("b", second), ("out", outsider)), messages, strict=True):
                folder = extra_folders[(role, owner)]
                session.add(MessageLocation(message_id=message.id, folder_id=folder.id))
                session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=1))
        session.add_all([
            FolderStats(folder_id=inbox_a.id, total_count=2, unread_count=2),
            FolderStats(folder_id=inbox_b.id, total_count=1, unread_count=1),
            FolderStats(folder_id=sent_a.id, total_count=1, unread_count=0),
            FolderStats(folder_id=sent_b.id, total_count=0, unread_count=0),
        ])
        for message in [*group_messages, sent_message, outside_message]:
            upsert_message_search(session, message_id=message.id, body_text="indexed scoped lighthouse")
        group_id, other_group_id = group.id, other_group.id
        first_id, second_id = first.id, second.id
        inbox_folder_id = inbox_a.id
        group_message_ids = [message.id for message in group_messages]
        group_role_message_ids = {role: [messages[0].id, messages[1].id] for role, messages in role_messages.items()}
        sent_message_id = sent_message.id
        outside_message_id = outside_message.id
        session.commit()

    first_page = client.get("/api/mail/inbox", params={"group_id": str(group_id), "limit": 2})
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    assert first_page.json()["next_cursor"]
    second_page = client.get("/api/mail/inbox", params={"group_id": str(group_id), "limit": 2, "cursor": first_page.json()["next_cursor"]})
    page_ids = [item["id"] for item in first_page.json()["items"] + second_page.json()["items"]]
    assert len(page_ids) == 3 and set(page_ids) == {str(item_id) for item_id in group_message_ids}
    assert len(set(page_ids)) == len(page_ids)
    asc_first = client.get("/api/mail/inbox", params={"group_id": str(group_id), "limit": 2, "sort_order": "asc"})
    asc_second = client.get("/api/mail/inbox", params={"group_id": str(group_id), "limit": 2, "sort_order": "asc", "cursor": asc_first.json()["next_cursor"]})
    asc_ids = [item["id"] for item in asc_first.json()["items"] + asc_second.json()["items"]]
    assert len(asc_ids) == len(set(asc_ids)) == 3
    assert set(asc_ids) == {str(item_id) for item_id in group_message_ids}

    sent_page = client.get("/api/mail/inbox", params={"group_id": str(group_id), "folder_role": "sent"})
    assert [item["id"] for item in sent_page.json()["items"]] == [str(sent_message_id)]
    assert client.get("/api/mail/inbox", params={"group_id": str(group_id), "folder_id": str(inbox_folder_id)}).status_code == 400
    assert client.get("/api/mail/search", params={"q": "lighthouse", "group_id": str(group_id), "folder_id": str(inbox_folder_id)}).status_code == 400
    for role, expected_ids in group_role_message_ids.items():
        role_page = client.get("/api/mail/inbox", params={"group_id": str(group_id), "folder_role": role})
        assert role_page.status_code == 200
        assert {item["id"] for item in role_page.json()["items"]} == {str(item_id) for item_id in expected_ids}
        assert all(item["account_id"] in {str(first_id), str(second_id)} for item in role_page.json()["items"])
        role_stats = client.get("/api/mail/stats", params={"group_id": str(group_id), "folder_role": role})
        assert role_stats.json()["total_unread"] == 2
    stats = client.get("/api/mail/stats", params={"group_id": str(group_id)})
    assert stats.json()["total_unread"] is None
    sent_stats = client.get("/api/mail/stats", params={"group_id": str(group_id), "folder_role": "sent"})
    assert sent_stats.json()["total_unread"] == 0
    global_sent_stats = client.get("/api/mail/stats", params={"folder_role": "sent"})
    assert global_sent_stats.status_code == 200
    global_sent_by_account = {row["account_id"]: row for row in global_sent_stats.json()["accounts"]}
    assert global_sent_by_account[str(first_id)]["unread_count"] == 0
    assert global_sent_by_account[str(second_id)]["unread_count"] == 0

    search_first = client.get("/api/mail/search", params={"q": "indexed scoped lighthouse", "group_id": str(group_id), "limit": 2, "offset": 0})
    search_second = client.get("/api/mail/search", params={"q": "indexed scoped lighthouse", "group_id": str(group_id), "limit": 2, "offset": 2})
    assert search_first.json()["total"] == 4
    assert search_first.json()["next_offset"] == 2
    assert len(search_second.json()["items"]) == 2
    search_ids = [item["id"] for item in search_first.json()["items"] + search_second.json()["items"]]
    assert len(search_ids) == len(set(search_ids)) == 4
    assert set(search_ids) == {str(item_id) for item_id in [*group_message_ids, sent_message_id]}
    assert all(item["account_id"] in {str(first_id), str(second_id)} for item in search_first.json()["items"] + search_second.json()["items"])

    marked = client.post("/api/mail/mark-all-read", json={"group_id": str(group_id), "folder_role": "inbox"})
    assert marked.status_code == 200 and marked.json()["count"] == 3
    with Session() as session:
        assert all(session.get(Message, item_id).is_read for item_id in group_message_ids)
        assert session.get(Message, outside_message_id).is_read is False
        assert session.scalar(select(RemoteOperation.id).where(RemoteOperation.account_id == first_id)) is not None
        assert session.scalar(select(OutboxEvent.id).where(OutboxEvent.account_id == second_id, OutboxEvent.event_type == "message.upserted")) is not None
        member = session.get(Account, second_id)
        assert member is not None
        member.group_id = other_group_id
        session.commit()
    after_move = client.get("/api/mail/inbox", params={"group_id": str(group_id)})
    assert len(after_move.json()["items"]) == 2
    assert all(item["account_id"] == str(first_id) for item in after_move.json()["items"])
