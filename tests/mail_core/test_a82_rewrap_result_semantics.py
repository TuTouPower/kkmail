"""A82: RewrapResult scanned/truncated truth + external-session retire gate."""

from __future__ import annotations

import os
from pathlib import Path

import mail_core.blobs.rotate as rotate
from mail_core.blobs.crypto import Keyring, wrap


def _keyring() -> Keyring:
    return Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)


def _write(tmp_path: Path, keyring: Keyring, letter: str, version: int) -> Path:
    path = tmp_path / (letter * 64 + ".blob")
    path.write_bytes(wrap(letter.encode(), keyring=keyring, key_version=version))
    return path


def test_scanned_reports_true_total_and_truncated_under_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    keyring = _keyring()
    for letter in ("a", "b", "c"):
        _write(tmp_path, keyring, letter, 1)
    _write(tmp_path, keyring, "d", 2)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)

    assert result.scanned == 4
    assert result.truncated == 2
    assert result.rewritten == 1
    assert result.already_current == 1
    assert result.remaining_old_version_blobs == 2


def _stub_external_session(monkeypatch):
    monkeypatch.setattr(rotate, "_sync_key_version", lambda *_args: None)
    monkeypatch.setattr(rotate, "_rewrap_credential_secrets", lambda *_args: 2)
    monkeypatch.setattr(rotate, "_count_old_credential_secrets", lambda *_args: 0)


def test_external_session_marks_credentials_pending_commit_not_committed(tmp_path, monkeypatch):
    keyring = _keyring()
    _write(tmp_path, keyring, "a", 1)
    _stub_external_session(monkeypatch)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring, session=object())

    assert result.remaining_old_version_blobs == 0
    assert result.remaining_old_version_credentials == 0
    assert result.credential_secrets_rewrapped == 2
    # Nothing is committed by rewrap_all_blobs on the external-session path:
    assert result.credential_secrets_committed is False
    assert result.safe_to_retire_old_keys is False
    # ...but the result must expose the pending state so the caller can judge
    # retirement safety after it commits.
    assert result.credential_secrets_pending_commit is True
    assert result.safe_to_retire_after_caller_commit is True


def test_external_session_with_remaining_old_blobs_is_not_pending(tmp_path, monkeypatch):
    keyring = _keyring()
    _write(tmp_path, keyring, "a", 1)
    _write(tmp_path, keyring, "b", 1)
    _stub_external_session(monkeypatch)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring, session=object(), limit=1)

    assert result.remaining_old_version_blobs == 1
    assert result.credential_secrets_pending_commit is False
    assert result.safe_to_retire_after_caller_commit is False


def test_run_rewrap_exposes_truncated_and_pending_state(monkeypatch):
    result = rotate.RewrapResult(
        scanned=4,
        rewritten=1,
        already_current=1,
        errors=[],
        remaining_old_version_blobs=0,
        remaining_old_version_credentials=0,
        credential_secrets_rewrapped=2,
        credential_secrets_committed=False,
        truncated=2,
        credential_secrets_pending_commit=True,
    )
    monkeypatch.setattr(rotate, "rewrap_all_blobs", lambda **_kwargs: result)

    output = rotate.run_rewrap()

    assert output["scanned"] == 4
    assert output["truncated"] == 2
    assert output["credential_secrets_pending_commit"] is True
    assert output["safe_to_retire_old_keys"] is False
    assert output["safe_to_retire_after_caller_commit"] is True
