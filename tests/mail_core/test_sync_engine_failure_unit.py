from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from mail_core.mail.storage.models import Account
from mail_core.sync import engine
from mail_core.sync.leases import FencingMismatch


def test_folder_listing_failure_updates_status_and_releases_lease_once(monkeypatch):
    account = SimpleNamespace(
        id=uuid.uuid4(),
        email="sync-failure@example.test",
        provider="memory",
        credential_ref=None,
        config={},
        sync_enabled=True,
        sync_status="idle",
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
    assert account.sync_status == "failed"
    assert account.config["last_sync_error"] == "ValueError"
