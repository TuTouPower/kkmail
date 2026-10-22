"""High-priority sync hardening: heartbeat, lease release, remote_push isolation, oauth mapping."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage import Folder, RemoteOperation
from mail_core.mail.storage.models import AccountSyncLease
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.gmail import gmail_label_role
from mail_core.providers.graph import graph_folder_role
from mail_core.providers.http import CursorInvalidError, ProviderHttpError
from mail_core.providers.oauth import _url_is_sync_cursor_endpoint, urllib_json_request
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import push_remote_operations, reconcile_folder, sync_folder_delta, sync_folder_metadata
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
import mail_core.sync.reconcile as reconcile_mod
import mail_core.sync.remote_push as push_mod

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_url_is_sync_cursor_endpoint():
    assert _url_is_sync_cursor_endpoint("https://gmail.googleapis.com/gmail/v1/users/me/history")
    assert _url_is_sync_cursor_endpoint(
        "https://graph.microsoft.com/v1.0/me/mailFolders/aa/messages/delta?$deltatoken=x"
    )
    assert not _url_is_sync_cursor_endpoint("https://gmail.googleapis.com/gmail/v1/users/me/labels")
    assert not _url_is_sync_cursor_endpoint("https://graph.microsoft.com/v1.0/me/messages/abc/$value")


def test_urllib_json_request_404_mapping(monkeypatch):
    import urllib.error
    import io

    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self, code, url):
            self.code = code
            self.url = url
            self.headers = {}
            # HTTPError requires fp
            super().__init__(url, code, "x", hdrs={}, fp=io.BytesIO(b'{"error":"x"}'))

        def read(self):
            return b'{"error":"x"}'

    def boom_history(req, timeout=60):
        raise FakeHTTPError(404, "https://gmail.googleapis.com/gmail/v1/users/me/history")

    def boom_labels(req, timeout=60):
        raise FakeHTTPError(404, "https://gmail.googleapis.com/gmail/v1/users/me/labels")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", boom_history)
    with pytest.raises(CursorInvalidError):
        urllib_json_request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/history")

    monkeypatch.setattr(urllib.request, "urlopen", boom_labels)
    with pytest.raises(ProviderHttpError) as ei:
        urllib_json_request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/labels")
    assert not isinstance(ei.value, CursorInvalidError)
    assert ei.value.status == 404


def test_gmail_and_graph_folder_roles():
    assert gmail_label_role("INBOX", "INBOX") == "inbox"
    assert gmail_label_role("SENT", "SENT") == "sent"
    assert gmail_label_role("DRAFT", "DRAFT") == "drafts"
    assert gmail_label_role("TRASH", "TRASH") == "trash"
    assert gmail_label_role("SPAM", "SPAM") == "junk"
    assert gmail_label_role("Label_1", "Work") == "other"
    assert graph_folder_role({"id": "1", "wellKnownName": "sentitems"}) == "sent"
    assert graph_folder_role({"id": "2", "wellKnownName": "junkemail"}) == "junk"
    assert graph_folder_role({"id": "3", "role": "archive"}) == "archive"
    assert graph_folder_role({"id": "4", "displayName": "Custom"}) == "other"


def _patch_all(provider):
    originals = {
        "engine": engine_mod.build_provider,
        "delta": delta_mod.build_provider,
        "reconcile": reconcile_mod.build_provider,
        "push": push_mod.build_provider,
    }

    def _build(account, store=None):
        return provider

    engine_mod.build_provider = _build
    delta_mod.build_provider = _build
    reconcile_mod.build_provider = _build
    push_mod.build_provider = _build
    return originals


def _restore(originals):
    engine_mod.build_provider = originals["engine"]
    delta_mod.build_provider = originals["delta"]
    reconcile_mod.build_provider = originals["reconcile"]
    push_mod.build_provider = originals["push"]


@_requires_db
def test_metadata_provider_error_releases_lease():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)

    class Boom(MemoryProvider):
        def fetch_metadata_page(self, folder_remote_id, cursor):
            raise RuntimeError("network down")

    provider = Boom(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    originals = _patch_all(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session, email=f"hb-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r"
            )
            folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.commit()
            account_id, folder_id = acc.id, folder.id

        with pytest.raises(RuntimeError, match="network down"):
            sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease is not None
            # Lease must be expired / releasable (not held for long TTL).
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        _restore(originals)
        set_credential_store(None)


@_requires_db
def test_delta_provider_error_releases_and_returns_status():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)])

    originals = _patch_all(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session, email=f"de-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r"
            )
            session.commit()
            account_id = acc.id
        from mail_core.sync import sync_account_folders

        assert sync_account_folders(account_id, worker_id="w", store=store)["status"] == "ok"
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        assert sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)["exhausted"]

        def boom(folder_remote_id, cursor):
            raise ConnectionError("delta boom")

        provider.delta_changes = boom  # type: ignore[method-assign]
        out = sync_folder_delta(account_id, folder_id, worker_id="w", store=store)
        assert out["status"] == "provider_error"
        assert "ConnectionError" in out["error"]

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        _restore(originals)
        set_credential_store(None)


@_requires_db
def test_remote_push_isolates_per_op_errors():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)

    class Flaky(MemoryProvider):
        def apply_remote_operation(self, op_type, desired_state):
            rid = desired_state.get("remote_id")
            if rid == "bad":
                raise RuntimeError("provider crash")
            return super().apply_remote_operation(op_type, desired_state)

    provider = Flaky(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta("good", "G", "a@b.c", "A", now, False, False, uid=1),
            RemoteMessageMeta("bad", "B", "a@b.c", "A", now, False, False, uid=2),
        ],
    )
    originals = _patch_all(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session, email=f"rp-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r"
            )
            session.commit()
            account_id = acc.id
        from mail_core.sync import sync_account_folders

        assert sync_account_folders(account_id, worker_id="w", store=store)["status"] == "ok"
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        with Session() as session:
            enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:bad",
                op_type="mark_read",
                desired_state={"remote_id": "bad", "folder_remote_id": "INBOX", "is_read": True},
            )
            enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:good",
                op_type="mark_read",
                desired_state={"remote_id": "good", "folder_remote_id": "INBOX", "is_read": True},
            )
            session.commit()

        result = push_remote_operations(account_id, worker_id="w", store=store)
        assert result["status"] == "ok"
        assert result["failed"] == 1
        assert result["pushed"] == 1

        with Session() as session:
            ops = list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == account_id)).all())
            by_key = {o.entity_key: o for o in ops}
            assert by_key["msg:bad"].status == RemoteOperationStatus.FAILED.value
            assert "RuntimeError" in (by_key["msg:bad"].last_error or by_key["msg:bad"].error or "")
            assert by_key["msg:good"].status == RemoteOperationStatus.DONE.value
    finally:
        _restore(originals)
        set_credential_store(None)


@_requires_db
def test_reconcile_provider_error_releases_lease():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)])
    originals = _patch_all(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session, email=f"rc-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r"
            )
            session.commit()
            account_id = acc.id
        from mail_core.sync import sync_account_folders

        sync_account_folders(account_id, worker_id="w", store=store)
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        def boom(folder_remote_id, local_ids):
            raise RuntimeError("reconcile boom")

        provider.reconcile = boom  # type: ignore[method-assign]
        out = reconcile_folder(account_id, folder_id, worker_id="w", store=store)
        assert out["status"] == "provider_error"
        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        _restore(originals)
        set_credential_store(None)


@_requires_db
def test_metadata_heartbeats_between_pages(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    heartbeats = {"n": 0}
    real_hb = engine_mod.heartbeat_lease

    def counting_hb(*args, **kwargs):
        heartbeats["n"] += 1
        return real_hb(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "heartbeat_lease", counting_hb)

    class Paged(MemoryProvider):
        def __init__(self):
            super().__init__(folders=[RemoteFolder("INBOX", "INBOX", "inbox")], page_size=1)
            self.seed(
                "INBOX",
                [
                    RemoteMessageMeta("1", "A", "a@b.c", "A", now, False, False, uid=1),
                    RemoteMessageMeta("2", "B", "a@b.c", "A", now, False, False, uid=2),
                ],
            )

    provider = Paged()
    originals = _patch_all(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session, email=f"pg-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r"
            )
            folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.commit()
            account_id, folder_id = acc.id, folder.id
        out = sync_folder_metadata(account_id, folder_id, worker_id="w", store=store, max_pages=5)
        assert out["status"] == "ok"
        assert out["pages"] >= 2
        assert heartbeats["n"] >= 2
    finally:
        _restore(originals)
        set_credential_store(None)
