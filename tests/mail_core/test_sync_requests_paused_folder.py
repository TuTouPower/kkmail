"""p060: an explicit folder_id pointing at a non-selectable (PAUSED)
folder must resolve to an empty target set, not raise folder_not_selectable.

Gmail virtual labels (role=all / role=important) and \\Noselect structure
nodes are PAUSED by design (spec AC-T56-001 / AC-034): role resolution
excludes them silently and the execution layer completes their jobs as
"skipped". The explicit-folder branch was the one place that hard-failed
with a 422, which the UI's routine navigation sync surfaced as a raw
error code above the message list of a first-class folder view.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``
(accounts/folders/sync_requests with real JSONB defaults and FK constraints).
"""

from __future__ import annotations

import os
import uuid

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request, resolve_sync_targets
from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import Account, Folder

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed(Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One Gmail account with an IDLE inbox and a PAUSED virtual folder."""
    account_id = uuid.uuid4()
    inbox_id = uuid.uuid4()
    important_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(id=account_id, email="virtuals@example.test", provider="imap", sync_enabled=True)
        )
        session.add_all(
            [
                Folder(
                    id=inbox_id,
                    account_id=account_id,
                    remote_id="INBOX",
                    name="INBOX",
                    role="inbox",
                    sync_status=SyncStatus.IDLE.value,
                ),
                Folder(
                    id=important_id,
                    account_id=account_id,
                    remote_id="[Gmail]/Important",
                    name="Important",
                    role="important",
                    sync_status=SyncStatus.PAUSED.value,
                ),
            ]
        )
        session.commit()
    return account_id, inbox_id, important_id


def test_explicit_paused_virtual_folder_resolves_to_no_targets():
    Session = get_session_factory()
    account_id, _inbox_id, important_id = _seed(Session)
    with Session() as session:
        targets = resolve_sync_targets(
            session, account_id=account_id, folder_id=important_id, folder_role="important"
        )
    assert targets == []


def test_explicit_idle_folder_still_resolves_to_single_target():
    Session = get_session_factory()
    account_id, inbox_id, _important_id = _seed(Session)
    with Session() as session:
        targets = resolve_sync_targets(session, account_id=account_id, folder_id=inbox_id)
    assert len(targets) == 1
    assert targets[0].account_id == account_id
    assert targets[0].folder_id == inbox_id


def test_explicit_folder_outside_account_scope_still_404():
    Session = get_session_factory()
    account_id, _inbox_id, _important_id = _seed(Session)
    other_account_id = uuid.uuid4()
    foreign_folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(id=other_account_id, email="other@example.test", provider="imap", sync_enabled=True)
        )
        session.add(
            Folder(
                id=foreign_folder_id,
                account_id=other_account_id,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
                sync_status=SyncStatus.IDLE.value,
            )
        )
        session.commit()
    with Session() as session:
        with pytest.raises(LookupError):
            resolve_sync_targets(session, account_id=account_id, folder_id=foreign_folder_id)
        with pytest.raises(LookupError):
            resolve_sync_targets(session, account_id=account_id, folder_id=uuid.uuid4())


def test_sync_request_for_paused_virtual_folder_completes_with_zero_targets():
    Session = get_session_factory()
    account_id, _inbox_id, important_id = _seed(Session)
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id="p060-paused-virtual",
            mode="full",
            trigger="navigation",
            scope={"account_id": str(account_id), "folder_id": str(important_id)},
            account_id=account_id,
            folder_id=important_id,
            folder_role="important",
        )
        session.commit()
        assert created is True
        assert req.state == "complete"
        assert req.finished_at is not None
