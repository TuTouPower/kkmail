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


def test_libpq_dsn_strips_password_from_uri():
    from mail_core.backup.package import _libpq_dsn_and_password

    dsn, pw = _libpq_dsn_and_password("postgresql://alice:s3cret@127.0.0.1:5432/kkmail")
    assert pw == "s3cret"
    assert "s3cret" not in dsn
    assert dsn.startswith("postgresql://alice@127.0.0.1:5432/kkmail")

    dsn2, pw2 = _libpq_dsn_and_password(
        "postgresql+psycopg://bob:p%40ss@db.example/app"
    )
    assert pw2 == "p@ss"
    assert "p%40ss" not in dsn2 and "p@ss" not in dsn2
    assert "bob@" in dsn2


def test_pg_dump_uses_pgpassword_not_argv(tmp_path, monkeypatch):
    """Password must travel via PGPASSWORD, never on the pg_dump argv."""
    import mail_core.backup.package as pkg

    seen: dict = {}

    def fake_which(name):
        return "/usr/bin/pg_dump" if name == "pg_dump" else None

    def fake_run(argv, check=True, capture_output=True, env=None):
        seen["argv"] = list(argv)
        seen["env_pw"] = (env or {}).get("PGPASSWORD")
        class R:
            returncode = 0
        # Write a tiny custom-format-ish file so sha works
        Path(argv[argv.index("--file") + 1]).write_bytes(b"PGDUMP")
        return R()

    monkeypatch.setattr(pkg.shutil, "which", fake_which)
    monkeypatch.setattr(pkg.subprocess, "run", fake_run)

    out = tmp_path / "bak"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:secretPW@127.0.0.1:5432/db",
        encrypt=False,
        allow_dump_stub=False,
    )
    assert seen["env_pw"] == "secretPW"
    assert all("secretPW" not in str(a) for a in seen["argv"])
    joined = " ".join(seen["argv"])
    assert "postgresql://u@127.0.0.1:5432/db" in joined or "u@127.0.0.1" in joined
    man = json.loads((out / "MANIFEST.json").read_text())
    assert man["members"]["postgres.dump"]["method"] == "custom"
    assert verify_backup_package(out).ok


def test_verify_rejects_path_traversal_member(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    out = tmp_path / "bak"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=False,
        allow_dump_stub=True,
    )
    man = json.loads((out / "MANIFEST.json").read_text())
    # Inject a traversal member pointing at an outside file
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"owned")
    man["members"]["../outside.bin"] = {
        "sha256": __import__("hashlib").sha256(b"owned").hexdigest(),
        "size": 5,
    }
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=2) + "\n")
    (out / "MANIFEST.sha256").write_text(
        f"{__import__('hashlib').sha256((out / 'MANIFEST.json').read_bytes()).hexdigest()}  MANIFEST.json\n"
    )
    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert any("disallowed member" in e for e in result.errors)


def test_verify_checks_outer_kkbak_checksum(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "enc"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )
    # Tamper with sealed blob after manifest was written
    kkbak = out / "backup.kkbak"
    kkbak.write_bytes(kkbak.read_bytes() + b"x")
    bad = verify_backup_package(out, allow_stub=True)
    assert bad.ok is False
    assert any("backup.kkbak" in e for e in bad.errors)

    # Restore bytes but corrupt outer MANIFEST.sha256
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )
    (out / "MANIFEST.sha256").write_text("0" * 64 + "  MANIFEST.json\n")
    bad2 = verify_backup_package(out, allow_stub=True)
    assert bad2.ok is False
    assert any("MANIFEST.sha256" in e for e in bad2.errors)
