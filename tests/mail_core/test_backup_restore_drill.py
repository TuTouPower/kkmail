"""Encrypted backup create + verify drill (no live pg_restore)."""

from __future__ import annotations

import base64
import os

from mail_core.backup.package import create_backup_package, verify_backup_package


def test_encrypted_backup_verify_drill(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(os.urandom(32)).decode())
    blobs = tmp_path / "blobs"
    (blobs / "aa" / "bb").mkdir(parents=True)
    (blobs / "aa" / "bb" / ("c" * 64 + ".blob")).write_bytes(b"KKMBcipher")
    out = tmp_path / "bak"
    path = create_backup_package(
        out,
        include_blobs=True,
        encrypt=True,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        blobs_dir=blobs,
    )
    assert path.exists()
    vr = verify_backup_package(path)
    assert vr.ok, vr.errors
    assert vr.members_checked >= 1
