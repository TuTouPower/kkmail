from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from mail_core.backup.crypto import MAGIC, BackupCryptoError, load_backup_key
from mail_core.backup.package import create_backup_package, verify_backup_package


def test_create_backup_package_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    blobs = tmp_path / "blobs"
    (blobs / "aa" / "bb").mkdir(parents=True)
    (blobs / "aa" / "bb" / "file.blob").write_bytes(b"cipher")

    out = tmp_path / "backup"
    create_backup_package(
        out,
        include_blobs=True,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        blobs_dir=blobs,
        encrypt=False,
        allow_dump_stub=True,
    )
    assert (out / "postgres.dump").exists()
    assert (out / "blobs.tar").exists()
    man = json.loads((out / "MANIFEST.json").read_text())
    assert "postgres.dump" in man["members"]
    assert man["members"]["postgres.dump"]["method"] == "sql_stub"
    assert "***" in man["database_url_redacted"]
    # Stub dumps must not verify as restoreable by default.
    result = verify_backup_package(out)
    assert result.ok is False
    assert any("sql_stub" in e for e in result.errors)
    ok_stub = verify_backup_package(out, allow_stub=True)
    assert ok_stub.ok
    assert ok_stub.members_checked >= 2


def test_encrypted_backup_roundtrip_verify(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY_VERSION", "1")
    blobs = tmp_path / "blobs"
    (blobs / "x").mkdir(parents=True)
    (blobs / "x" / "a.blob").write_bytes(b"data")

    out = tmp_path / "enc-backup"
    create_backup_package(
        out,
        include_blobs=True,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        blobs_dir=blobs,
        encrypt=True,
        allow_dump_stub=True,
    )
    kkbak = out / "backup.kkbak"
    assert kkbak.is_file()
    assert kkbak.read_bytes()[:4] == MAGIC
    assert not (out / "plain").exists()
    man = json.loads((out / "MANIFEST.json").read_text())
    assert man["encrypted"] is True
    assert man["backup_key_version"] == 1

    # Default verify rejects sql_stub; crypto round-trip uses allow_stub.
    rejected = verify_backup_package(out)
    assert rejected.ok is False
    ok = verify_backup_package(out, allow_stub=True)
    assert ok.ok, ok.errors
    assert ok.backup_key_version == 1
    assert ok.members_checked >= 2

    # Wrong key fails
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(os.urandom(32)).decode())
    bad = verify_backup_package(out)
    assert bad.ok is False
    assert bad.errors


def test_backup_key_required_when_encrypt_forced(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    with pytest.raises(BackupCryptoError):
        load_backup_key({})
    with pytest.raises(BackupCryptoError):
        create_backup_package(
            tmp_path / "x",
            encrypt=True,
            database_url_override="postgresql://u:p@127.0.0.1:1/db",
            blobs_dir=tmp_path / "b",
            allow_dump_stub=True,
        )


def test_pg_dump_failure_raises_without_stub(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="pg_dump"):
        create_backup_package(
            tmp_path / "bak",
            include_blobs=False,
            database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
            encrypt=False,
            allow_dump_stub=False,
        )
