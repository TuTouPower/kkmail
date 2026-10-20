"""Encrypted backup create + verify drill.

Does **not** run live ``pg_restore`` — only package create + checksum verify
(with optional stub dump). Rename from restore_drill to avoid implying a DB restore.
"""

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
        allow_dump_stub=True,
    )
    assert path.exists()
    rejected = verify_backup_package(path)
    assert rejected.ok is False
    assert any("sql_stub" in e for e in rejected.errors)
    vr = verify_backup_package(path, allow_stub=True)
    assert vr.ok, vr.errors
    assert vr.members_checked >= 1
