from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from mail_core.mail.storage.models import Account
from mail_core.sync import engine
from mail_core.sync.leases import FencingMismatch


def test_folder_listing_failure_releases_lease_once_without_touching_account_health(monkeypatch):
    # t076: 账号健康状态写入已从 sync engine 移到 worker 层 health 状态机
    # (handle_job._apply_account_health / accounts.health)；engine 失败仅释放
    # lease 并上抛。旧断言 account.sync_status == "failed" 与
    # account.config["last_sync_error"] 整体删除，账号级状态改由
    # test_account_health_state_machine.py 覆盖。
    account = SimpleNamespace(
        id=uuid.uuid4(),
        email="sync-failure@example.test",
        provider="memory",
        credential_ref=None,
        config={},
        sync_enabled=True,
        credential_state="valid",
        connectivity_state="connected",
        sync_activity="idle",
    )
    sessions = []

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, _account_id):
            return account

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    def session_factory():
        session = Session()
        sessions.append(session)
        return session

    class BrokenProvider:
        def list_folders(self):
            raise ValueError("folder listing failed")

    release_calls = []

    def release_once(_session, **_kwargs):
        release_calls.append(True)
        if len(release_calls) > 1:
            raise FencingMismatch("lease already released")

    monkeypatch.setattr(engine, "_session_factory", lambda: session_factory)
    monkeypatch.setattr(engine, "acquire_lease", lambda *_args, **_kwargs: SimpleNamespace(fencing_token=7))
    monkeypatch.setattr(engine, "build_provider", lambda *_args, **_kwargs: BrokenProvider())
    monkeypatch.setattr(engine, "release_lease", release_once)

    with pytest.raises(ValueError, match="folder listing failed"):
        engine.sync_account_folders(account.id, worker_id="worker-a139", store=object())

    assert len(sessions) == 2
    assert [session.commits for session in sessions] == [1, 1]
    assert release_calls == [True]
    assert account.credential_state == "valid" and account.connectivity_state == "connected"
    assert account.connectivity_state == "connected"
    assert account.sync_activity == "idle"
