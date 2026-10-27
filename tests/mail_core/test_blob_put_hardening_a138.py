"""A138: BlobStore.put hardening.

Three defects in the original ``put``:
- check-then-write race: the exists/verify step and the ``os.replace``
  were not serialised per digest, so concurrent puts of the same
  content could interleave verification and replacement;
- inconsistent error classification: an existing blob whose key
  version is unknown raises plain ``BlobCryptoError`` (not the
  ``BlobIntegrityError`` subclass), which escaped the rewrite branch
  and aborted the put instead of rewriting the blob;
- no parent-directory fsync after ``os.replace``, so a crash could
  lose a file that committed references already point at.
"""

from __future__ import annotations

import base64
import os
import threading

import pytest

from mail_core.blobs.crypto import Keyring, wrap
from mail_core.blobs.store import BlobStore


def test_put_rewrites_existing_blob_with_unknown_key_version(tmp_path):
    store = BlobStore(tmp_path)
    data = b"payload whose on-disk copy uses an unknown key version"
    digest = store.hash_plaintext(data)
    path = store.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Wrap the same plaintext under a key version the store's keyring
    # does not know: read_key_version succeeds, decryption raises
    # BlobCryptoError("unknown blob key version 99").
    foreign_keyring = Keyring(keys={99: os.urandom(32)}, active_version=99)
    path.write_bytes(wrap(data, keyring=foreign_keyring, key_version=99))

    result = store.put(data)

    assert result.content_sha256 == digest
    assert store.get(digest) == data


def test_put_concurrent_same_digest_all_succeed(tmp_path):
    store = BlobStore(tmp_path)
    data = os.urandom(128 * 1024)
    results: list = []
    errors: list = []

    def _put():
        try:
            results.append(store.put(data))
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            errors.append(exc)

    threads = [threading.Thread(target=_put) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert len(results) == 8
    assert all(r.content_sha256 == results[0].content_sha256 for r in results)
    assert store.get(results[0].content_sha256) == data


def test_put_fsyncs_parent_directory_after_replace(tmp_path, monkeypatch):
    store = BlobStore(tmp_path)
    fsynced_fds: list[int] = []
    real_fsync = os.fsync
    real_open = os.open

    def _tracking_fsync(fd):
        fsynced_fds.append(fd)
        return real_fsync(fd)

    dir_fds: set[int] = set()

    def _tracking_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        # Directory opens are the ones whose path is an existing dir.
        try:
            if os.path.isdir(path):
                dir_fds.add(fd)
        except Exception:
            pass
        return fd

    monkeypatch.setattr(os, "fsync", _tracking_fsync)
    monkeypatch.setattr(os, "open", _tracking_open)
    store.put(b"fsync me")
    assert dir_fds & set(fsynced_fds), "put must fsync the destination directory after replace"


def test_put_uses_per_digest_lock(tmp_path):
    store = BlobStore(tmp_path)
    digest = store.hash_plaintext(b"lock check")
    lock = store._lock_for_digest(digest)
    assert lock is store._lock_for_digest(digest), "same digest must share one lock"
    other = store._lock_for_digest(store.hash_plaintext(b"different"))
    assert other is not lock, "different digests must not share the put lock"
    # The lock is a real context manager usable for serialisation.
    with lock:
        pass
