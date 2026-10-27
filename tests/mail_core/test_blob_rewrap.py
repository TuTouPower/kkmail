"""Blob key rotation re-wrap."""

from __future__ import annotations

import base64
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import mail_core.blobs.rotate as rotate
from mail_core.blobs.crypto import Keyring, load_keyring_from_env, unwrap, wrap
from mail_core.blobs.rotate import RewrapResult, rewrap_all_blobs, rewrap_blob_file
from mail_core.blobs.store import BlobStore


def test_concurrent_rewrap_uses_distinct_temp_files(tmp_path, monkeypatch):
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    path = tmp_path / "blob.blob"
    path.write_bytes(wrap(b"concurrent-rewrap", keyring=keyring, key_version=1))

    both_waiting = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    call_count = 0
    original_iter_wrap = rotate.iter_wrap

    def synchronized_iter_wrap(chunks, *, keyring, key_version=None):
        nonlocal call_count
        with lock:
            call_count += 1
            if call_count == 2:
                both_waiting.set()
        if not release.wait(timeout=5):
            raise TimeoutError("concurrent rewrap barrier timed out")
        yield from original_iter_wrap(chunks, keyring=keyring, key_version=key_version)

    monkeypatch.setattr(rotate, "iter_wrap", synchronized_iter_wrap)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(rewrap_blob_file, path, keyring=keyring)
            for _ in range(2)
        ]
        try:
            assert both_waiting.wait(timeout=5)
            assert len(list(tmp_path.glob("*.rewrap*"))) == 2
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == [(True, 2), (True, 2)]

    assert unwrap(path.read_bytes(), keyring=keyring) == (b"concurrent-rewrap", 2)
    assert not list(tmp_path.glob("*.rewrap*"))


def test_rewrap_moves_to_new_key_version(tmp_path, monkeypatch):
    k1 = base64.b64encode(os.urandom(32)).decode()
    k2 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.delenv("MAIL_CORE_BLOB_KEY_V1", raising=False)
    monkeypatch.setenv("MAIL_CORE_BLOB_KEYS", f'{{"1": "{k1}", "2": "{k2}"}}')
    monkeypatch.setenv("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")
    store = BlobStore(tmp_path)
    data = b"rotate-me-mime"
    put = store.put(data)
    assert put.key_version == 1
    path = store.path_for(put.content_sha256)

    monkeypatch.setenv("MAIL_CORE_BLOB_ACTIVE_VERSION", "2")
    keyring = load_keyring_from_env()
    assert keyring.active_version == 2
    changed, ver = rewrap_blob_file(path, keyring=keyring)
    assert changed and ver == 2
    pt, new_ver = unwrap(path.read_bytes(), keyring=keyring)
    assert pt == data and new_ver == 2

    # second pass is no-op
    changed2, ver2 = rewrap_blob_file(path, keyring=keyring)
    assert not changed2 and ver2 == 2

    result = rewrap_all_blobs(root=tmp_path, keyring=keyring)
    assert result.scanned >= 1
    assert result.already_current >= 1
    assert result.errors == []


def test_rewrap_all_blobs_migrates_credentials_last_and_reports_retirement_gate(tmp_path, monkeypatch):
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    paths = [tmp_path / (letter * 64 + ".blob") for letter in ("a", "b")]
    for index, path in enumerate(paths):
        path.write_bytes(wrap(f"blob-{index}".encode(), keyring=keyring, key_version=1))

    events = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            events.append("commit")

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://test/db")
    monkeypatch.setattr(rotate, "get_session_factory", lambda: lambda: Session())
    original_rewrap = rotate.rewrap_blob_file

    def tracked_rewrap(path, **kwargs):
        events.append(f"blob:{path.name}")
        return original_rewrap(path, **kwargs)

    monkeypatch.setattr(rotate, "rewrap_blob_file", tracked_rewrap)
    monkeypatch.setattr(rotate, "_sync_key_version", lambda *_args: events.append("blob_metadata"))
    monkeypatch.setattr(
        rotate,
        "_rewrap_credential_secrets",
        lambda *_args: events.append("credential_secrets") or 2,
    )
    monkeypatch.setattr(rotate, "_count_old_credential_secrets", lambda *_args: 0)

    result = rewrap_all_blobs(root=tmp_path, keyring=keyring)

    last_blob_index = max(index for index, event in enumerate(events) if event.startswith("blob:"))
    assert events.index("credential_secrets") > last_blob_index
    assert result.remaining_old_version_blobs == 0
    assert result.remaining_old_version_credentials == 0
    assert result.credential_secrets_rewrapped == 2
    assert result.credential_secrets_committed is True
    assert result.safe_to_retire_old_keys is True


def test_partial_blob_rewrap_keeps_credentials_and_old_keys_unretirable(tmp_path, monkeypatch):
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    paths = [tmp_path / (letter * 64 + ".blob") for letter in ("a", "b")]
    for index, path in enumerate(paths):
        path.write_bytes(wrap(f"blob-{index}".encode(), keyring=keyring, key_version=1))

    credentials_rewrapped = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            pass

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://test/db")
    monkeypatch.setattr(rotate, "get_session_factory", lambda: lambda: Session())
    monkeypatch.setattr(rotate, "_sync_key_version", lambda *_args: None)
    monkeypatch.setattr(
        rotate,
        "_rewrap_credential_secrets",
        lambda *_args: credentials_rewrapped.append(True) or 1,
    )
    monkeypatch.setattr(rotate, "_count_old_credential_secrets", lambda *_args: 0)

    result = rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)

    # A82 semantics: scanned is the true scan total (2 files discovered);
    # the file skipped by limit=1 is reported via truncated instead.
    assert result.scanned == 2
    assert result.truncated == 1
    assert result.errors == []
    assert result.remaining_old_version_blobs == 1
    assert result.remaining_old_version_credentials == 0
    assert credentials_rewrapped == []
    assert result.safe_to_retire_old_keys is False


def test_limited_blob_rewrap_skips_current_files_and_progresses(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    versions = {"a": 2, "b": 2, "c": 1, "d": 1}
    for name, version in versions.items():
        path = tmp_path / (name * 64 + ".blob")
        path.write_bytes(wrap(name.encode(), keyring=keyring, key_version=version))

    first = rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)
    assert first.rewritten == 1
    assert first.already_current == 2
    assert first.remaining_old_version_blobs == 1

    second = rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)
    assert second.rewritten == 1
    assert second.remaining_old_version_blobs == 0

    third = rewrap_all_blobs(root=tmp_path, keyring=keyring, limit=1)
    assert third.rewritten == 0
    assert third.already_current == 4
    assert third.remaining_old_version_blobs == 0


def test_limited_blob_rewrap_repairs_metadata_for_current_files(tmp_path, monkeypatch):
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    digest = "a" * 64
    (tmp_path / f"{digest}.blob").write_bytes(wrap(b"already-current", keyring=keyring, key_version=2))
    synced = []
    monkeypatch.setattr(rotate, "_sync_key_version", lambda _session, key, version: synced.append((key, version)))
    monkeypatch.setattr(rotate, "_rewrap_credential_secrets", lambda *_args: 0)
    monkeypatch.setattr(rotate, "_count_old_credential_secrets", lambda *_args: 0)

    result = rewrap_all_blobs(root=tmp_path, keyring=keyring, session=object(), limit=1)

    assert result.already_current == 1
    assert synced == [(digest, 2)]


def test_run_rewrap_exposes_old_key_retirement_gate(monkeypatch):
    result = RewrapResult(
        scanned=1,
        rewritten=1,
        already_current=0,
        errors=[],
        remaining_old_version_blobs=0,
        remaining_old_version_credentials=0,
        credential_secrets_rewrapped=2,
        credential_secrets_committed=True,
    )
    monkeypatch.setattr(rotate, "rewrap_all_blobs", lambda **_kwargs: result)

    output = rotate.run_rewrap()

    assert output["safe_to_retire_old_keys"] is True
    assert output["remaining_old_version_blobs"] == 0
    assert output["remaining_old_version_credentials"] == 0
