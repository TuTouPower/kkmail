"""A318: rewrap_blob_file temp file permissions + parent dir fsync."""

from __future__ import annotations

import os
import stat

import mail_core.blobs.rotate as rotate
from mail_core.blobs.crypto import Keyring, unwrap, wrap


def _make_old_blob(tmp_path):
    keyring = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
    path = tmp_path / ("a" * 64 + ".blob")
    path.write_bytes(wrap(b"a318-payload", keyring=keyring, key_version=1))
    return keyring, path


def test_rewrap_replaced_file_has_0600_permissions(tmp_path):
    keyring, path = _make_old_blob(tmp_path)

    changed, ver = rotate.rewrap_blob_file(path, keyring=keyring)

    assert changed and ver == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert unwrap(path.read_bytes(), keyring=keyring) == (b"a318-payload", 2)


def test_rewrap_fsyncs_parent_directory_after_replace(tmp_path, monkeypatch):
    keyring, path = _make_old_blob(tmp_path)
    real_fsync = os.fsync
    fsynced_fds: list[int] = []

    def tracking_fsync(fd):
        fsynced_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(rotate.os, "fsync", tracking_fsync)

    changed, _ver = rotate.rewrap_blob_file(path, keyring=keyring)

    assert changed
    # One fsync for the temp file payload, plus one for the parent directory
    # so the rename itself is durable.
    assert len(fsynced_fds) >= 2
