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

    def fake_run(argv, check=True, capture_output=True, env=None, timeout=None, **kwargs):
        seen["argv"] = list(argv)
        seen["env_pw"] = (env or {}).get("PGPASSWORD")
        seen["timeout"] = timeout
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


def test_backup_workspace_permissions_and_staging_cleanup(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "enc_pkg"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )

    # 1. Staging directory and temporary archive must be fully removed
    remnants = [p.name for p in out.iterdir() if p.name.startswith(".")]
    assert not remnants, f"Found lingering temporary artifacts: {remnants}"

    # 2. Files written to package have 0600 permissions
    for f in (out / "backup.kkbak", out / "MANIFEST.json", out / "MANIFEST.sha256"):
        assert f.is_file()
        assert (f.stat().st_mode & 0o777) == 0o600

    # 3. Plaintext package files also have 0600 permissions
    plain_out = tmp_path / "plain_pkg"
    create_backup_package(
        plain_out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=False,
        allow_dump_stub=True,
    )
    for f in (plain_out / "postgres.dump", plain_out / "MANIFEST.json", plain_out / "MANIFEST.sha256"):
        assert f.is_file()
        assert (f.stat().st_mode & 0o777) == 0o600


def test_backup_build_failure_cleans_plain_staging(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "fail_enc_pkg"

    import mail_core.backup.package as pkg

    def fake_encrypt_file(*args, **kwargs):
        raise RuntimeError("simulated disk error during encryption")

    monkeypatch.setattr(pkg, "encrypt_file", fake_encrypt_file)

    with pytest.raises(RuntimeError, match="simulated disk error"):
        create_backup_package(
            out,
            include_blobs=False,
            database_url_override="postgresql://u:p@127.0.0.1:1/db",
            encrypt=True,
            allow_dump_stub=True,
        )

    # Ensure no plain staging directory or archive tar remains
    remnants = [p.name for p in out.iterdir()]
    assert not remnants, f"Staging cleanup failed on exception: {remnants}"


def test_verify_failure_cleans_extract_dir(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "verify_clean_pkg"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )

    # Tamper with kkbak payload so decrypt fails
    kkbak = out / "backup.kkbak"
    raw = bytearray(kkbak.read_bytes())
    raw[30] ^= 0xFF
    kkbak.write_bytes(raw)
    # Update outer manifest sha so it reaches decrypt phase
    man = json.loads((out / "MANIFEST.json").read_text())
    man["members"]["backup.kkbak"]["sha256"] = __import__("hashlib").sha256(raw).hexdigest()
    (out / "MANIFEST.json").write_text(json.dumps(man))
    (out / "MANIFEST.sha256").write_text(
        f"{__import__('hashlib').sha256((out / 'MANIFEST.json').read_bytes()).hexdigest()}  MANIFEST.json\n"
    )

    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert any("decrypt failed" in e for e in result.errors)

    # No verify directory should linger
    lingering = [p.name for p in out.iterdir() if p.name.startswith(".verify_")]
    assert not lingering, f"Lingering verify directories found: {lingering}"


def test_backup_refuses_symlink_staging(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)

    target_dir = tmp_path / "actual_target"
    target_dir.mkdir()
    symlink_out = tmp_path / "symlink_dest"
    symlink_out.symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(RuntimeError, match="refusing to use symlink as output directory"):
        create_backup_package(
            symlink_out,
            include_blobs=False,
            database_url_override="postgresql://u:p@127.0.0.1:1/db",
            encrypt=True,
            allow_dump_stub=True,
        )


def test_verify_tar_refuses_symlink(tmp_path, monkeypatch):
    import tarfile
    from mail_core.backup.crypto import encrypt_file

    key = os.urandom(32)
    key_b64 = base64.b64encode(key).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key_b64)

    out = tmp_path / "evil_pkg"
    out.mkdir()

    # Create a malicious tar containing a symlink
    tar_path = tmp_path / "evil.tar"
    with tarfile.open(tar_path, mode="w") as tar:
        # Add postgres.dump as normal file
        dummy = tmp_path / "postgres.dump"
        dummy.write_text("dummy dump")
        tar.add(dummy, arcname="postgres.dump")

        # Add evil symlink
        sym_info = tarfile.TarInfo(name="blobs.tar")
        sym_info.type = tarfile.SYMTYPE
        sym_info.linkname = "/etc/passwd"
        tar.addfile(sym_info)

    kkbak = out / "backup.kkbak"
    encrypt_file(tar_path, kkbak, key=key, key_version=1)

    # Outer manifest
    manifest = {
        "created_at": "2026-01-01T00:00:00Z",
        "database_url_redacted": "postgresql://...",
        "blob_root": "...",
        "members": {
            "backup.kkbak": {
                "sha256": __import__("hashlib").sha256(kkbak.read_bytes()).hexdigest(),
                "size": kkbak.stat().st_size,
            }
        },
        "encrypted": True,
        "backup_key_version": 1,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest))
    (out / "MANIFEST.sha256").write_text(
        f"{__import__('hashlib').sha256((out / 'MANIFEST.json').read_bytes()).hexdigest()}  MANIFEST.json\n"
    )

    res = verify_backup_package(out, allow_stub=True)
    assert res.ok is False
    assert any("unsafe symlink" in e for e in res.errors)

    # Ensure extract dir was cleaned up
    lingering = [p.name for p in out.iterdir() if p.name.startswith(".verify_")]
    assert not lingering


def test_run_backup_private_workspace_and_cleanup(tmp_path, monkeypatch):
    import mail_core.backup.package as pkg

    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")

    def fake_dump(dest, url, allow_stub=False):
        dest.write_bytes(b"valid pg dump data")
        return "custom"

    monkeypatch.setattr(pkg, "_pg_dump_to", fake_dump)

    dest = tmp_path / "final_backup"
    res = pkg.run_backup(output_dir=str(dest), encrypt=True)
    assert res["status"] == "ok"
    assert res["verify"]["ok"] is True
    assert dest.is_dir()
    # Check permissions
    assert (dest.stat().st_mode & 0o777) == 0o700
    for f in dest.iterdir():
        assert (f.stat().st_mode & 0o777) == 0o600

    # Check that dest.parent contains no leftover staging directories
    staging_dirs = [p.name for p in dest.parent.iterdir() if p.name.startswith(".staging_")]
    assert not staging_dirs

