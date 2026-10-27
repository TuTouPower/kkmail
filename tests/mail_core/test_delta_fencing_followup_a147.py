"""A147: a fencing_mismatch exit from sync_folder_delta must reschedule a
delayed delta followup under the same dedupe key.

The periodic poll chain only continues when a run enqueues its successor;
before this fix every fencing_mismatch return silently ended the chain, so
a folder whose lease was lost once (e.g. a long provider call outliving
the lease) was never polled again.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint
from mail_core.sync import delta as delta_mod
from mail_core.sync.leases import FencingMismatch


class _Harness:
    def __init__(self):
        self.account_id = uuid.uuid4()
        self.folder_id = uuid.uuid4()
        self.account = SimpleNamespace(
            id=self.account_id,
            email="user@example.test",
            provider="imap",
            credential_ref="ref",
            config={},
            sync_enabled=True,
        )
        self.folder = SimpleNamespace(
            id=self.folder_id,
            remote_id="INBOX",
            sync_status=SyncStatus.IDLE.value,
        )
        self.checkpoint = SimpleNamespace(
            full_scan_complete=True,
            cursor={},
            modseq=None,
            history_id=None,
            delta_link=None,
            uidvalidity=None,
            scan_generation=None,
        )
        self.enqueued = []

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
                    return harness.checkpoint
                return None

            def add(self, _obj):
                return None

            def commit(self):
                return None

            def rollback(self):
                return None

        return _Session()


def _wire(monkeypatch, harness, *, apply_delta_page):
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: harness.session)
    monkeypatch.setattr(
        delta_mod, "acquire_lease", lambda *_a, **_k: SimpleNamespace(fencing_token=7)
    )
    monkeypatch.setattr(delta_mod, "release_lease", lambda *_a, **_k: None)
    provider = SimpleNamespace(delta_changes=lambda _r, _c: SimpleNamespace())
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)
    monkeypatch.setattr(delta_mod, "apply_delta_page", apply_delta_page)

    def _enqueue(_session, **kwargs):
        harness.enqueued.append(kwargs)
        return SimpleNamespace(status="pending")

    monkeypatch.setattr(delta_mod, "enqueue_job", _enqueue)


def _assert_delayed_delta_followup(harness):
    assert len(harness.enqueued) == 1
    followup = harness.enqueued[0]
    assert followup["job_type"] == JobType.SYNC_FOLDER_DELTA.value
    assert followup["dedupe_key"] == f"delta:{harness.account_id}:{harness.folder_id}"
    assert followup["payload"] == {"folder_id": str(harness.folder_id)}
    run_after = followup["run_after"]
    assert run_after > datetime.now(timezone.utc) + timedelta(seconds=1)


def test_apply_stage_fencing_mismatch_reschedules_delta(monkeypatch):
    harness = _Harness()

    def _apply(*_a, **_k):
        raise FencingMismatch("lease taken over during apply")

    _wire(monkeypatch, harness, apply_delta_page=_apply)
    result = delta_mod.sync_folder_delta(
        harness.account_id, harness.folder_id, worker_id="w-a147", store=object()
    )
    assert result["status"] == "fencing_mismatch"
    assert result["followup_scheduled"] is True
    _assert_delayed_delta_followup(harness)


def test_final_fencing_check_mismatch_reschedules_delta(monkeypatch):
    harness = _Harness()

    def _apply(*_a, **_k):
        return SimpleNamespace(upserted=0, deleted=0, flagged=0, cursor={}, exhausted=True)

    _wire(monkeypatch, harness, apply_delta_page=_apply)
    monkeypatch.setattr(delta_mod, "heartbeat_lease", lambda *_a, **_k: None)

    def _assert_fencing(*_a, **_k):
        raise FencingMismatch("lease lost before final release")

    monkeypatch.setattr(delta_mod, "assert_fencing", _assert_fencing)
    result = delta_mod.sync_folder_delta(
        harness.account_id, harness.folder_id, worker_id="w-a147", store=object()
    )
    assert result["status"] == "fencing_mismatch"
    assert result["followup_scheduled"] is True
    _assert_delayed_delta_followup(harness)
