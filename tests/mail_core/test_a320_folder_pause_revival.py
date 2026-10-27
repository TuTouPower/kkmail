"""A320: a folder paused by the system (remote disappearance / \\Noselect)
must revive to IDLE and be re-enqueued for metadata when it reappears
remotely and is selectable again. All PAUSED assignments in the codebase
are system-driven (there is no manual folder pause), so re-deriving the
status from the current remote state on each discovery is the correct
distinction."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import Account, Folder
from mail_core.providers.base import RemoteFolder
from mail_core.sync import engine


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Harness:
    def __init__(self, account, existing_folders, remote_folders):
        self.account = account
        self.folders = list(existing_folders)
        self.remote_folders = remote_folders
        self.enqueued: list[dict] = []

    def session(self):
        harness = self

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get(self, model, _key):
                if model is Account:
                    return harness.account
                return None

            def scalars(self, _stmt):
                return _Scalars(harness.folders)

            def add(self, obj):
                if isinstance(obj, Folder) and obj not in harness.folders:
                    harness.folders.append(obj)

            def flush(self):
                return None

            def commit(self):
                return None

            def rollback(self):
                return None

        return _Session()


def _run(monkeypatch, harness):
    monkeypatch.setattr(engine, "_session_factory", lambda: harness.session)
    monkeypatch.setattr(
        engine, "acquire_lease", lambda *_a, **_k: SimpleNamespace(fencing_token=7)
    )
    monkeypatch.setattr(engine, "assert_fencing", lambda *_a, **_k: None)
    monkeypatch.setattr(engine, "fail_open_targets", lambda *_a, **_k: None)
    monkeypatch.setattr(engine, "release_lease", lambda *_a, **_k: None)
    provider = SimpleNamespace(list_folders=lambda: harness.remote_folders)
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: provider)

    def _enqueue(_session, **kwargs):
        harness.enqueued.append(kwargs)
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(engine, "enqueue_job", _enqueue)
    return engine.sync_account_folders(
        harness.account.id, worker_id="w-a320", store=object()
    )


def _account():
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="user@example.test",
        provider="imap",
        credential_ref="ref",
        config={},
        sync_enabled=True,
        sync_status="idle",
    )


def _existing(account_id, remote_id, status):
    return Folder(
        account_id=account_id,
        remote_id=remote_id,
        name=remote_id,
        role="inbox" if remote_id == "INBOX" else "other",
        sync_status=status,
    )


def test_paused_folder_revives_when_selectable_again(monkeypatch):
    account = _account()
    existing = _existing(account.id, "INBOX", SyncStatus.PAUSED.value)
    remote = [RemoteFolder("INBOX", "INBOX", role="inbox", selectable=True)]
    harness = _Harness(account, [existing], remote)
    result = _run(monkeypatch, harness)
    assert result["status"] == "ok"
    assert existing.sync_status == SyncStatus.IDLE.value
    enqueued_ids = {str(j["payload"]["folder_id"]) for j in harness.enqueued}
    assert str(existing.id) in enqueued_ids


def test_paused_folder_stays_paused_when_still_not_selectable(monkeypatch):
    account = _account()
    existing = _existing(account.id, "Archive", SyncStatus.PAUSED.value)
    remote = [RemoteFolder("Archive", "Archive", role="other", selectable=False)]
    harness = _Harness(account, [existing], remote)
    result = _run(monkeypatch, harness)
    assert result["status"] == "ok"
    assert existing.sync_status == SyncStatus.PAUSED.value
    assert harness.enqueued == []
