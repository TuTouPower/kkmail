"""Blob key rotation re-wrap."""

from __future__ import annotations

import base64
import os

from mail_core.blobs.crypto import load_keyring_from_env, unwrap
from mail_core.blobs.rotate import rewrap_all_blobs, rewrap_blob_file
from mail_core.blobs.store import BlobStore


def test_rewrap_moves_to_new_key_version(tmp_path, monkeypatch):
    k1 = base64.b64encode(os.urandom(32)).decode()
    k2 = base64.b64encode(os.urandom(32)).decode()
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
