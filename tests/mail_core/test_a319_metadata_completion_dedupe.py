"""A319: the metadata completion branch must dedupe the non-full reconcile
enqueue and the per-account archive batch enqueue, like the full path and
the archive scheduler already do."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint
from mail_core.sync import engine


class _Harness:
    def __init__(self, account, folder):
        self.account = account
        self.folder = folder
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
                if model is Folder:
                    return harness.folder
                if model is SyncCheckpoint:
                    return None
                return None

            def add(self, _obj):
                return None

            def commit(self):
                return None

            def rollback(self):
                return None

        return _Session()


def test_metadata_completion_enqueues_carry_dedupe_keys(monkeypatch):
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    account = SimpleNamespace(
        id=account_id,
        email="user@example.test",
        provider="imap",
        credential_ref="ref",
        config={},
        sync_enabled=True,
        sync_status="idle",
    )
    folder = SimpleNamespace(
        id=folder_id,
        remote_id="INBOX",
        sync_status=SyncStatus.IDLE.value,
    )
    harness = _Harness(account, folder)

    monkeypatch.setattr(engine, "_session_factory", lambda: harness.session)
    monkeypatch.setattr(
        engine, "acquire_lease", lambda *_a, **_k: SimpleNamespace(fencing_token=7)
    )
    monkeypatch.setattr(engine, "assert_fencing", lambda *_a, **_k: None)
    monkeypatch.setattr(engine, "heartbeat_lease", lambda *_a, **_k: None)

    def _release(_session, **_kwargs):
        harness.released += 1

    monkeypatch.setattr(engine, "release_lease", _release)
    provider = SimpleNamespace(
        fetch_metadata_page=lambda _remote_id, _cursor: object()
    )
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: provider)
    monkeypatch.setattr(
        engine,
        "apply_metadata_page",
        lambda *_a, **_k: SimpleNamespace(upserted=3, exhausted=True, cursor={}),
    )

    def _enqueue(_session, **kwargs):
        harness.enqueued.append(kwargs)
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(engine, "enqueue_job", _enqueue)

    result = engine.sync_folder_metadata(
        account_id, folder_id, worker_id="w-a319", store=object()
    )
    assert result["status"] == "ok"
    assert result["exhausted"] is True

    by_type = {j["job_type"]: j for j in harness.enqueued}
    assert by_type[JobType.RECONCILE_FOLDER.value]["dedupe_key"] == (
        f"reconcile:{account_id}:{folder_id}"
    )
    assert by_type[JobType.ARCHIVE_MIME_BATCH.value]["dedupe_key"] == (
        f"archive_mime_batch:{account_id}"
    )
    assert by_type[JobType.SYNC_FOLDER_DELTA.value]["dedupe_key"] == (
        f"delta:{account_id}:{folder_id}"
    )
