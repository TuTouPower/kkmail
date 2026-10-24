import os
import uuid

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import Folder, Message, MessageLocation, RemoteOperation
from mail_core.providers.base import RemoteMessageMeta, RemoteOperationResult
from mail_core.sync.metadata import upsert_messages
import mail_core.sync.remote_push as remote_push

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class MoveProvider:
    def __init__(self, *, success: bool):
        self.success = success

    def apply_remote_operation(self, _op_type, _desired_state):
        return RemoteOperationResult(
            success=self.success,
            error=None if self.success else "provider rejected move",
            remote_state={"id": "new-remote-id", "folder_remote_id": "Archive"},
        )


def _seed_move_operation():
    Session = get_session_factory()
    store = DictCredentialStore({"move-ref": "secret"})
    with Session() as session:
        account = create_account(
            session,
            email=f"move-state-{uuid.uuid4().hex[:8]}@example.test",
            provider="memory",
            credential_ref="move-ref",
        )
        source = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        destination = Folder(account_id=account.id, remote_id="Archive", name="Archive", role="archive")
        session.add_all((source, destination))
        session.flush()
        message = Message(
            account_id=account.id,
            remote_id="old-remote-id",
            subject="Moved message",
            from_address="sender@example.test",
        )
        session.add(message)
        session.flush()
        source_location = MessageLocation(message_id=message.id, folder_id=source.id, uid=11)
        session.add(source_location)
        operation = enqueue_remote_operation(
            session,
            account_id=account.id,
            entity_key="msg:old-remote-id:move",
            op_type="move",
            desired_state={
                "remote_id": "old-remote-id",
                "folder_remote_id": "INBOX",
                "dest_folder_remote_id": "Archive",
            },
            idempotency_key=f"{message.id}:move",
        )
        session.commit()
        return account.id, message.id, source.id, destination.id, operation.id, store


def test_successful_move_persists_provider_remote_identity_and_location(monkeypatch):
    account_id, message_id, source_id, destination_id, operation_id, store = _seed_move_operation()
    monkeypatch.setattr(remote_push, "build_provider", lambda _account, _store=None: MoveProvider(success=True))

    result = remote_push.push_remote_operations(account_id, worker_id="move-test", store=store, limit=1)

    assert result["status"] == "ok"
    assert result["pushed"] == 1
    Session = get_session_factory()
    with Session() as session:
        message = session.get(Message, message_id)
        assert message is not None
        assert message.remote_id == "new-remote-id"
        locations = list(
            session.scalars(select(MessageLocation).where(MessageLocation.message_id == message_id))
        )
        assert [location.folder_id for location in locations] == [destination_id]
        assert session.get(RemoteOperation, operation_id).status == RemoteOperationStatus.DONE.value
        assert session.get(Folder, source_id) is not None

        synced = upsert_messages(
            session,
            account_id=account_id,
            folder_id=destination_id,
            metas=[
                RemoteMessageMeta(
                    remote_id="new-remote-id",
                    subject="Moved message",
                    from_address="sender@example.test",
                    from_name=None,
                    sort_time=None,
                    is_read=None,
                    has_attachments=None,
                )
            ],
        )
        assert len(synced) == 1
        assert synced[0].created is False
        assert synced[0].message.id == message_id


def test_failed_move_does_not_apply_provider_remote_state(monkeypatch):
    account_id, message_id, source_id, _destination_id, operation_id, store = _seed_move_operation()
    monkeypatch.setattr(remote_push, "build_provider", lambda _account, _store=None: MoveProvider(success=False))

    result = remote_push.push_remote_operations(account_id, worker_id="move-test", store=store, limit=1)

    assert result["status"] == "ok"
    assert result["failed"] == 1
    Session = get_session_factory()
    with Session() as session:
        message = session.get(Message, message_id)
        assert message is not None
        assert message.remote_id == "old-remote-id"
        locations = list(
            session.scalars(select(MessageLocation).where(MessageLocation.message_id == message_id))
        )
        assert [location.folder_id for location in locations] == [source_id]
        assert session.get(RemoteOperation, operation_id).status == RemoteOperationStatus.FAILED.value
