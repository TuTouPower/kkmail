"""A288: remaining-old-version count must not re-scan the whole blob tree."""

from __future__ import annotations

import os
from pathlib import Path

import mail_core.blobs.rotate as rotate
from mail_core.blobs.crypto import Keyring, wrap


def _keyring() -> Keyring:
    return Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)


def _write_old(tmp_path: Path, keyring: Keyring, letter: str) -> Path:
    path = tmp_path / (letter * 64 + ".blob")
    path.write_bytes(wrap(letter.encode(), keyring=keyring, key_version=1))
    return path


def _counting_rglob(monkeypatch) -> list[str]:
    calls: list[str] = []
    real_rglob = Path.rglob

    def counting(self, pattern, *args, **kwargs):
        calls.append(str(pattern))
        return real_rglob(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", counting)
    return calls


def test_remaining_count_uses_single_tree_scan(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    keyring = _keyring()
    for letter in ("a", "b", "c"):
        _write_old(tmp_path, keyring, letter)
    rglob_calls = _counting_rglob(monkeypatch)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring)

    assert result.rewritten == 3
    assert result.remaining_old_version_blobs == 0
    assert result.errors == []
    # Initial discovery is the only full-tree rglob; the tail count must be
    # derived from scan-time tallies plus rechecks of failed/unknown files.
    assert rglob_calls == ["*.blob"]


def test_failed_and_unreadable_files_are_rechecked_for_remaining_count(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    keyring = _keyring()
    ok_path = _write_old(tmp_path, keyring, "a")
    fail_path = _write_old(tmp_path, keyring, "b")
    corrupt_path = tmp_path / ("c" * 64 + ".blob")
    corrupt_path.write_bytes(b"not-a-blob")

    real_rewrap = rotate.rewrap_blob_file

    def flaky_rewrap(path, **kwargs):
        if path == fail_path:
            raise RuntimeError("simulated rewrite failure")
        return real_rewrap(path, **kwargs)

    monkeypatch.setattr(rotate, "rewrap_blob_file", flaky_rewrap)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring)

    assert ok_path != fail_path
    assert result.rewritten == 1
    # Only the file whose rewrite failed still holds the old version; the
    # corrupt file stays uncounted (existing semantics: verify error only).
    assert result.remaining_old_version_blobs == 1
    assert any("simulated rewrite failure" in e for e in result.errors)
    assert any(corrupt_path.name in e for e in result.errors)


def test_limited_run_remaining_includes_truncated_files_without_rescan(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    keyring = _keyring()
    for letter in ("a", "b", "c"):
        _write_old(tmp_path, keyring, letter)
    rglob_calls = _counting_rglob(monkeypatch)

    result = rotate.rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)

    assert result.rewritten == 1
    assert result.remaining_old_version_blobs == 2
    assert rglob_calls == ["*.blob"]
