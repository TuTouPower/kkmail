"""A85: apply-stage exits must release the account lease (quietly, only
while fencing still belongs to this worker) instead of leaking it until
the TTL expires:
- engine.sync_folder_metadata: ScanGenerationMismatch from apply_metadata_page
- delta.sync_folder_delta: uncaught exceptions from apply_delta_page
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint
from mail_core.sync import delta as delta_mod
from mail_core.sync import engine
from mail_core.sync.checkpoints import ScanGenerationMismatch


def _make_session(harness):
    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, model, _key):
            if model is Account:
                return harness.account
            if model is Folder:
                return harness.folder
            if model is SyncCheckpoint:
                return harness.checkpoint
            return None

        def add(self, _obj):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    return _Session()


class _Harness:
    def __init__(self, *, checkpoint):
        self.account_id = uuid.uuid4()
        self.folder_id = uuid.uuid4()
        self.account = SimpleNamespace(
            id=self.account_id,
            email="user@example.test",
            provider="imap",
            credential_ref="ref",
            config={},
            sync_enabled=True,
            sync_status="idle",
        )
        self.folder = SimpleNamespace(
            id=self.folder_id,
            remote_id="INBOX",
            sync_status=SyncStatus.IDLE.value,
        )
        self.checkpoint = checkpoint
        self.released = 0

    def session(self):
        return _make_session(self)


def test_engine_scan_generation_mismatch_releases_lease(monkeypatch):
    harness = _Harness(checkpoint=None)
    monkeypatch.setattr(engine, "_session_factory", lambda: harness.session)
    monkeypatch.setattr(
        engine, "acquire_lease", lambda *_a, **_k: SimpleNamespace(fencing_token=7)
    )
    monkeypatch.setattr(engine, "heartbeat_lease", lambda *_a, **_k: None)

    def _release(_session, **_kwargs):
        harness.released += 1

    monkeypatch.setattr(engine, "release_lease", _release)
    provider = SimpleNamespace(fetch_metadata_page=lambda _r, _c: object())
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: provider)

    def _apply(*_a, **_k):
        raise ScanGenerationMismatch("newer generation owns the checkpoint")

    monkeypatch.setattr(engine, "apply_metadata_page", _apply)

    result = engine.sync_folder_metadata(
        harness.account_id, harness.folder_id, worker_id="w-a85", store=object()
    )
    assert result["status"] == "scan_generation_mismatch"
    assert harness.released == 1


def test_delta_apply_unexpected_error_releases_lease_and_reraises(monkeypatch):
    checkpoint = SimpleNamespace(
        full_scan_complete=True,
        cursor={},
        modseq=None,
        history_id=None,
        delta_link=None,
        uidvalidity=None,
    )
    harness = _Harness(checkpoint=checkpoint)
    monkeypatch.setattr(
        "mail_core.db.session.get_session_factory", lambda: harness.session
    )
    monkeypatch.setattr(
        delta_mod, "acquire_lease", lambda *_a, **_k: SimpleNamespace(fencing_token=7)
    )

    def _release(_session, **_kwargs):
        harness.released += 1

    monkeypatch.setattr(delta_mod, "release_lease", _release)
    provider = SimpleNamespace(delta_changes=lambda _r, _c: object())
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)

    def _apply(*_a, **_k):
        raise RuntimeError("db exploded during apply")

    monkeypatch.setattr(delta_mod, "apply_delta_page", _apply)

    with pytest.raises(RuntimeError, match="db exploded"):
        delta_mod.sync_folder_delta(
            harness.account_id, harness.folder_id, worker_id="w-a85", store=object()
        )
    assert harness.released == 1
