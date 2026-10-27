"""A321: Gmail virtual-folder detection must use only the exact remote_id
set or role (all/important) — a user label whose name merely *contains*
"重要"/"All Mail" etc. must not be paused."""

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
        self.released = 0

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

    def _release(_session, **_kwargs):
        harness.released += 1

    monkeypatch.setattr(engine, "release_lease", _release)

    provider = SimpleNamespace(list_folders=lambda: harness.remote_folders)
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: provider)

    def _enqueue(_session, **kwargs):
        harness.enqueued.append(kwargs)
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(engine, "enqueue_job", _enqueue)
    return engine.sync_account_folders(
        harness.account.id, worker_id="w-a321", store=object()
    )


def _gmail_account():
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="user@gmail.com",
        provider="imap",
        credential_ref="ref",
        config={"imap_host": "imap.gmail.com"},
        sync_enabled=True,
        sync_status="idle",
    )


def test_user_label_with_virtual_substring_is_not_paused(monkeypatch):
    account = _gmail_account()
    remote = [
        RemoteFolder("[Gmail]/重要客户", "[Gmail]/重要客户", role="other", selectable=True),
        RemoteFolder("[Gmail]/All Mail 备份", "[Gmail]/All Mail 备份", role="other", selectable=True),
    ]
    harness = _Harness(account, [], remote)
    result = _run(monkeypatch, harness)
    assert result["status"] == "ok"
    by_remote = {f.remote_id: f for f in harness.folders}
    assert by_remote["[Gmail]/重要客户"].sync_status == SyncStatus.IDLE.value
    assert by_remote["[Gmail]/All Mail 备份"].sync_status == SyncStatus.IDLE.value
    enqueued_ids = {str(j["payload"]["folder_id"]) for j in harness.enqueued}
    assert str(by_remote["[Gmail]/重要客户"].id) in enqueued_ids


def test_exact_virtual_folders_stay_paused(monkeypatch):
    account = _gmail_account()
    remote = [
        RemoteFolder("[Gmail]/All Mail", "[Gmail]/All Mail", role="other", selectable=True),
        RemoteFolder("[Gmail]/&YkBnCZCuTvY-", "[Gmail]/所有邮件", role="other", selectable=True),
        RemoteFolder("custom-all", "custom-all", role="all", selectable=True),
        RemoteFolder("custom-important", "custom-important", role="important", selectable=True),
    ]
    harness = _Harness(account, [], remote)
    result = _run(monkeypatch, harness)
    assert result["status"] == "ok"
    for folder in harness.folders:
        assert folder.sync_status == SyncStatus.PAUSED.value, folder.remote_id
    assert harness.enqueued == []
