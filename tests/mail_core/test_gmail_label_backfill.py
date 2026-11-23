"""Historical Gmail Important label backfill (t088)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import list_folder_stats_for_account, unified_inbox
from mail_core.mail.domain.folder_views import CONTAINER, VIEW
from mail_core.mail.storage.models import (
    Account,
    Folder,
    Message,
    MessageLocation,
    SyncCheckpoint,
)
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync.label_backfill import backfill_account

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class _FakeProvider:
    def __init__(self, labels: tuple[str, ...]):
        self.labels = labels
        self.calls = 0

    def fetch_metadata_page(self, _remote_id, _cursor):
        self.calls += 1
        return MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="hist-1",
                    subject="Historical",
                    from_address="sender@example.test",
                    from_name=None,
                    sort_time=datetime.now(timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    uid=1,
                    labels=self.labels,
                )
            ],
            next_cursor=None,
            exhausted=True,
        )


def _seed(Session, *, email: str, with_view: bool = True, historical: bool = True, important_role: str = "important"):
    with Session() as session:
        account = Account(email=email, provider="imap")
        session.add(account)
        session.flush()
        inbox = Folder(
            account_id=account.id,
            remote_id="INBOX",
            name="INBOX",
            role="inbox",
            kind=CONTAINER,
        )
        session.add(inbox)
        session.flush()
        all_mail = Folder(
            account_id=account.id,
            remote_id="[Gmail]/All Mail",
            name="All Mail",
            role="all",
            kind=VIEW,
        )
        session.add(all_mail)
        view = None
        if with_view:
            view = Folder(
                account_id=account.id,
                remote_id="[Gmail]/Important",
                name="Important",
                role=important_role,
                kind=VIEW,
            )
            session.add(view)
        if historical:
            message = Message(
                account_id=account.id,
                remote_id="hist-1",
                subject="Historical",
                from_address="sender@example.test",
                sort_time=datetime.now(timezone.utc),
                is_read=False,
            )
            session.add(message)
            session.flush()
            session.add(MessageLocation(message_id=message.id, folder_id=inbox.id))
        session.flush()
        checkpoint = SyncCheckpoint(
            account_id=account.id,
            folder_id=inbox.id,
            cursor={"uid_next": 9},
            full_scan_complete=True,
        )
        session.add(checkpoint)
        session.commit()
        return account.id, inbox.id, (view.id if view else None)


def test_backfill_writes_historical_label_location_and_marks_completion():
    Session = get_session_factory()
    account_id, folder_id, view_id = _seed(Session, email=f"backfill-{uuid.uuid4().hex[:8]}@gmail.com")
    with Session() as session:
        all_before = {item["role"]: item for item in list_folder_stats_for_account(session, account_id)}["all"]
    lease_checks: list[bool] = []

    class _LeaseAwareProvider:
        def fetch_metadata_page(self, *_args, **_kwargs):
            from mail_core.sync.leases import LeaseBusy, acquire_lease

            with Session() as probe:
                try:
                    acquire_lease(
                        probe, account_id=account_id, owner_id="another-worker"
                    )
                except LeaseBusy:
                    lease_checks.append(True)
                else:
                    lease_checks.append(False)
            return _FakeProvider(("\\Important",)).fetch_metadata_page(*_args, **_kwargs)

    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: _LeaseAwareProvider())
    assert result.status == "completed"
    assert result.upserted == 1
    with Session() as session:
        assert session.get(Account, account_id).label_backfill_completed_at is not None
        message_id = session.scalar(select(Message.id).where(Message.account_id == account_id))
        locs = list(session.scalars(select(MessageLocation)).all())
        assert {(loc.message_id, loc.folder_id) for loc in locs} == {
            (message_id, folder_id),
            (message_id, view_id),
        }
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        assert cp.cursor == {"uid_next": 9}
        assert cp.full_scan_complete is True
        stats = {item["role"]: item for item in list_folder_stats_for_account(session, account_id)}
        assert stats["important"]["total_count"] == 1
        assert stats["all"] == all_before
        assert [item.subject for item in unified_inbox(session, folder_id=view_id).items] == ["Historical"]
    assert lease_checks and all(lease_checks)


def test_backfill_is_idempotent_and_skips_completed_and_non_gmail():
    Session = get_session_factory()
    account_id, _folder_id, _view_id = _seed(Session, email=f"idem-{uuid.uuid4().hex[:8]}@gmail.com")
    other_id, _other_folder, _other_view = _seed(Session, email=f"other-{uuid.uuid4().hex[:8]}@example.com")
    provider = _FakeProvider(("\\Important",))
    first = backfill_account(Session, account_id, provider_factory=lambda *a, **k: provider)
    second = backfill_account(Session, account_id, provider_factory=lambda *a, **k: provider)
    assert first.status == "completed"
    assert second.status == "skipped_completed"
    assert backfill_account(
        Session, account_id, force=True, provider_factory=lambda *a, **k: provider
    ).status == "completed"
    assert backfill_account(
        Session, other_id, provider_factory=lambda *a, **k: provider
    ).status == "skipped_not_gmail"
    with Session() as session:
        assert len(session.scalars(select(Message).where(Message.account_id == account_id)).all()) == 1
        locations = list(
            session.scalars(
                select(MessageLocation).join(Message, Message.id == MessageLocation.message_id)
                .where(Message.account_id == account_id)
            ).all()
        )
        assert len(locations) == 2


def test_backfill_skips_account_without_important_view():
    Session = get_session_factory()
    account_id, _folder_id, view_id = _seed(
        Session, email=f"noview-{uuid.uuid4().hex[:8]}@gmail.com", with_view=False
    )
    assert view_id is None
    provider = _FakeProvider(("\\Important",))
    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: provider)
    assert result.status == "skipped_no_view"
    with Session() as session:
        assert session.get(Account, account_id).label_backfill_completed_at is None


def test_backfill_all_folders_failing_still_completes_with_count():
    Session = get_session_factory()
    account_id, _folder_id, _view_id = _seed(Session, email=f"retry-{uuid.uuid4().hex[:8]}@gmail.com")

    class _Broken:
        def fetch_metadata_page(self, *_args, **_kwargs):
            raise OSError("transient IMAP failure")

    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: _Broken())
    assert result.status == "completed"
    assert "failed_folders=1" in result.detail
    with Session() as session:
        assert session.get(Account, account_id).label_backfill_completed_at is not None


def test_backfill_finds_important_view_with_role_other():
    Session = get_session_factory()
    account_id, _folder_id, view_id = _seed(
        Session,
        email=f"roleother-{uuid.uuid4().hex[:8]}@gmail.com",
        important_role="other",
    )
    provider = _FakeProvider(("\\Important",))
    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: provider)
    assert result.status == "completed"
    with Session() as session:
        assert any(
            loc.folder_id == view_id for loc in session.scalars(select(MessageLocation)).all()
        )


def test_backfill_skips_unselectable_folder_and_still_completes():
    Session = get_session_factory()
    account_id, _folder_id, view_id = _seed(Session, email=f"badfolder-{uuid.uuid4().hex[:8]}@gmail.com")
    with Session() as session:
        session.add(
            Folder(
                account_id=account_id,
                remote_id="Broken",
                name="Broken",
                role="other",
                kind=CONTAINER,
            )
        )
        session.commit()

    class _PartialProvider:
        def fetch_metadata_page(self, remote_id, cursor):
            if remote_id == "Broken":
                raise OSError("select failed: NO")
            return _FakeProvider(("\\Important",)).fetch_metadata_page(remote_id, cursor)

    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: _PartialProvider())
    assert result.status == "completed"
    assert "failed_folders=1" in result.detail
    with Session() as session:
        assert session.get(Account, account_id).label_backfill_completed_at is not None
        assert any(
            loc.folder_id == view_id for loc in session.scalars(select(MessageLocation)).all()
        )


def test_backfill_retries_transient_fetch_failure(monkeypatch):
    import mail_core.sync.label_backfill as module

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    Session = get_session_factory()
    account_id, _folder_id, _view_id = _seed(Session, email=f"flaky-{uuid.uuid4().hex[:8]}@gmail.com")

    class _FlakyProvider:
        def __init__(self):
            self.calls = 0

        def fetch_metadata_page(self, remote_id, cursor):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("transient")
            return _FakeProvider(("\\Important",)).fetch_metadata_page(remote_id, cursor)

    provider = _FlakyProvider()
    result = backfill_account(Session, account_id, provider_factory=lambda *a, **k: provider)
    assert result.status == "completed"
    assert provider.calls == 2
