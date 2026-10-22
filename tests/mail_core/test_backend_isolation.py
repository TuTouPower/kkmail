"""Committed data must not be visible to a later test, in any test order."""

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import func, select, text

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, AppSetting, AuthCredential, Message, OutboxEvent, WorkerJob

pytestmark = pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")


@pytest.mark.parametrize("iteration", [0, 1])
def test_committed_data_starts_empty(iteration):
    with get_session_factory()() as session:
        for model in (Account, AppSetting, AuthCredential, Message, OutboxEvent, WorkerJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        account = Account(email=f"isolation-{iteration}@example.test", provider="memory")
        session.add(account)
        session.flush()
        session.add_all([
            Message(account_id=account.id, remote_id="1", subject="隔离", sort_time=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            AppSetting(key="isolation", value=str(iteration)),
            AuthCredential(id="default"),
            OutboxEvent(event_type="sync.progress", account_id=account.id, payload={}),
            WorkerJob(job_type="sync_account_folders", account_id=account.id, payload={}),
        ])
        session.commit()
        # Keep A checked out while B observes the commit. Backend PIDs prove
        # the pool cannot quietly return the same physical connection.
        from mail_core.db.session import get_engine
        first_pid = session.connection().scalar(text("SELECT pg_backend_pid()"))
        with get_engine().connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) != first_pid
            assert connection.scalar(select(func.count()).select_from(Account)) == 1


@pytest.mark.parametrize("seed", [17, 41])
def test_factory_same_time_pagination_and_duplicate_message_ids(seed):
    from mail_core.blobs.store import BlobStore
    from mail_core.mail.application.queries import list_messages_keyset
    from mail_core.mail.storage.models import FolderStats
    from tests.mail_core.mailbox_factory import build_mailbox, fixture_id, mime_message

    assert mime_message(seed, 0, 0) == mime_message(seed, 0, 0)
    with get_session_factory()() as session:
        data = build_mailbox(session, os.environ["MAIL_CORE_BLOB_ROOT"], seed=seed)
        session.commit()
        assert data["accounts"][0] == fixture_id(seed, "account:0")
        for account, inbox, empty in zip(data["accounts"], data["inboxes"], data["empty_folders"]):
            seen = []
            cursor = None
            while True:
                page = list_messages_keyset(session, folder_ids=[inbox], limit=2, cursor=cursor)
                assert all(message.account_id == account for message in page.items)
                seen.extend(message.id for message in page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
            expected = session.scalars(select(Message.id).where(Message.account_id == account)).all()
            assert len(seen) == len(set(seen)) == 5
            assert set(seen) == set(expected)
            assert session.get(FolderStats, inbox).total_count == 5
            assert session.get(FolderStats, empty).total_count == 0
        duplicate_id = f"<fixture-{seed}-0@example.test>"
        assert session.scalar(select(func.count()).select_from(Message).where(Message.internet_message_id == duplicate_id)) == 2
    store = BlobStore(os.environ["MAIL_CORE_BLOB_ROOT"])
    for digest, expected in data["attachments"]:
        assert store.get(digest) == expected


@pytest.mark.parametrize("fail", [False, True])
def test_cleanup_restores_threads_providers_credentials_and_commits(tmp_path, fail, request):
    from contextlib import nullcontext
    from mail_core.accounts.credentials import DictCredentialStore, get_credential_store, set_credential_store
    from mail_core.realtime.dispatcher import OutboxDispatcher
    from mail_core.realtime.listener import OutboxListenThread
    from mail_core.db.session import get_engine
    from mail_core.worker import main as worker
    import threading
    import mail_core.sync.engine as sync_engine
    from tests.mail_core.runtime_isolation import isolated_runtime

    original_provider = sync_engine.build_provider
    test_patch = pytest.MonkeyPatch()
    expected = pytest.raises(AssertionError, match="intentional assertion") if fail else nullcontext()
    with expected:
        with isolated_runtime(test_patch, tmp_path / "nested", request.session):
            sync_engine.build_provider = lambda *_args, **_kwargs: None
            set_credential_store(DictCredentialStore({"leaked": "test-only"}))
            with get_session_factory()() as session:
                session.add(Account(email="nested@example.test", provider="memory"))
                session.commit()
            listener = OutboxListenThread(OutboxDispatcher())
            listener.start()
            assert listener.wait_started(5)
            raw_connection = get_engine().connect()
            raw_pid = raw_connection.scalar(text("SELECT pg_backend_pid()"))
            ticked = threading.Event()
            original_tick = worker._tick

            def observed_tick(*args, **kwargs):
                result = original_tick(*args, **kwargs)
                ticked.set()
                return result

            test_patch.setattr(worker, "_tick", observed_tick)
            worker_thread = threading.Thread(target=lambda: worker.run(poll_interval_s=0.05), daemon=True)
            worker_thread.start()
            assert ticked.wait(5)
            if fail:
                raise AssertionError("intentional assertion")
    assert not listener.is_alive
    assert not worker_thread.is_alive()
    assert raw_connection.closed
    assert sync_engine.build_provider is original_provider
    assert not isinstance(get_credential_store(), DictCredentialStore)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 0
        assert session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid=:pid"), {"pid": raw_pid}) == 0


def test_api_lifespan_stops_listener():
    from fastapi.testclient import TestClient
    from mail_core.api.app import app
    from mail_core.realtime.listener import get_outbox_listener

    with TestClient(app) as client:
        listener = get_outbox_listener()
        assert listener.listen_ready
        assert client.get("/health").status_code == 200
    assert not listener.is_alive


def test_notify_is_committed_and_received():
    import psycopg
    from mail_core.realtime.listener import _dsn_from_settings
    from mail_core.realtime.notify import CHANNEL, notify_outbox

    # Receive directly from PostgreSQL: no dispatcher idle polling can hide a
    # broken NOTIFY. Transactional delivery must wait until the writer commits.
    with psycopg.connect(_dsn_from_settings(), autocommit=True) as receiver:
        receiver.execute(f"LISTEN {CHANNEL}")
        with get_session_factory()() as writer:
            writer.add(OutboxEvent(event_type="sync.progress", payload={"notification_probe": True}))
            writer.flush()
            notify_outbox(writer)
            assert next(receiver.notifies(timeout=0.1, stop_after=1), None) is None
            writer.commit()
        notification = next(receiver.notifies(timeout=2, stop_after=1), None)
        assert notification is not None, "committed outbox notification not received"
        assert notification.channel == CHANNEL
