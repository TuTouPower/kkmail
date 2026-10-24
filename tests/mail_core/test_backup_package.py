from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from mail_core.backup.crypto import MAGIC, BackupCryptoError, load_backup_key
from mail_core.backup import package as backup_package
from mail_core.backup.package import (
    create_backup_package,
    restore_backup_package,
    verify_backup_package,
)


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
    assert man["members"]["postgres.dump"]["method"] == backup_package._SQL_STUB_METHOD
    assert "***" in man["database_url_redacted"]
    # Stub dumps must not verify as restoreable by default.
    result = verify_backup_package(out)
    assert result.ok is False
    assert any("sql_stub" in e for e in result.errors)
    ok_stub = verify_backup_package(out, allow_stub=True)
    assert ok_stub.ok
    assert ok_stub.members_checked >= 2


def test_restore_rejects_sql_stub_when_verification_is_bypassed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_package.shutil, "which", lambda _name: None)
    package_dir = tmp_path / "stub-backup"
    create_backup_package(
        package_dir,
        include_blobs=False,
        database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
        blobs_dir=tmp_path / "source-blobs",
        encrypt=False,
        allow_dump_stub=True,
    )
    monkeypatch.setattr(
        backup_package,
        "verify_backup_package",
        lambda *_args, **_kwargs: backup_package.RestoreVerifyResult(True, 1, []),
    )

    with pytest.raises(RuntimeError, match="refusing to restore stub backup"):
        restore_backup_package(
            package_dir,
            target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
            target_blobs_dir=tmp_path / "restored-blobs",
            source_database_url="postgresql://backup:pw@127.0.0.1:5432/source",
        )


def test_create_backup_rejects_key_equal_to_blob_key(tmp_path, monkeypatch):
    shared_key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", shared_key)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY_VERSION", raising=False)
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_V1", shared_key)
    monkeypatch.delenv("MAIL_CORE_BLOB_KEYS", raising=False)
    monkeypatch.delenv("MAIL_CORE_BLOB_KEY_VERSION", raising=False)
    monkeypatch.delenv("MAIL_CORE_BLOB_ACTIVE_VERSION", raising=False)

    with pytest.raises(BackupCryptoError, match="backup key must differ from blob keys"):
        create_backup_package(
            tmp_path / "same-key-backup",
            include_blobs=False,
            database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
            blobs_dir=tmp_path / "blobs",
            encrypt=True,
            allow_dump_stub=True,
        )

    assert not (tmp_path / "same-key-backup").exists()


def test_restore_plain_backup_uses_package_directory_as_restore_tree(tmp_path, monkeypatch):
    blobs = tmp_path / "source-blobs"
    blob = blobs / "aa" / "bb" / "message.blob"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"encrypted blob payload")

    package_dir = tmp_path / "plain-backup"
    create_backup_package(
        package_dir,
        include_blobs=True,
        database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
        blobs_dir=blobs,
        encrypt=False,
        allow_dump_stub=True,
    )
    assert (package_dir / "postgres.dump").is_file()
    assert (package_dir / "blobs.tar").is_file()
    assert not (package_dir / "backup.kkbak").exists()

    monkeypatch.setattr(backup_package.shutil, "which", lambda name: "/fake/pg_restore" if name == "pg_restore" else None)
    monkeypatch.setattr(
        backup_package.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b""),
    )
    target_blobs = tmp_path / "restored-blobs"
    result = restore_backup_package(
        package_dir,
        target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
        target_blobs_dir=target_blobs,
        source_database_url="postgresql://backup:pw@127.0.0.1:5432/source",
        allow_stub=True,
    )

    assert result.database_restored
    assert result.blobs_restored == 1
    assert (target_blobs / "aa" / "bb" / "message.blob").read_bytes() == b"encrypted blob payload"
    assert package_dir.is_dir(), "restore must preserve the source plain package"


def test_restore_sealed_backup_reads_manifest_filename_case(tmp_path, monkeypatch):
    assert backup_package._MANIFEST_FILENAME == "MANIFEST.json"

    backup_key = os.urandom(32)
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(backup_key).decode())
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)

    package_dir = tmp_path / "sealed-backup"
    create_backup_package(
        package_dir,
        include_blobs=False,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        encrypt=True,
        allow_dump_stub=True,
    )
    monkeypatch.setattr(backup_package.shutil, "which", lambda name: "/fake/pg_restore")
    monkeypatch.setattr(
        backup_package.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b"", stderr=b""),
    )

    result = restore_backup_package(
        package_dir,
        target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
        target_blobs_dir=tmp_path / "restored-blobs",
        keyring={1: backup_key},
        allow_stub=True,
        source_database_url="postgresql://backup-source:pw@127.0.0.1:5432/source",
    )

    assert result.ok
    assert result.database_restored


@pytest.mark.parametrize("encrypt", [False, True], ids=["plain", "sealed"])
def test_restore_backup_package_succeeds_offline_with_fake_postgres_tools(
    tmp_path, monkeypatch, encrypt
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    restore_record = tmp_path / "pg_restore_args.json"

    pg_dump = fake_bin / "pg_dump"
    pg_dump.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "Path(args[args.index('--file') + 1]).write_bytes(b'offline custom dump')\n",
        encoding="utf-8",
    )
    pg_dump.chmod(0o755)

    pg_restore = fake_bin / "pg_restore"
    pg_restore.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "Path(os.environ['FAKE_PG_RESTORE_RECORD']).write_text(json.dumps(args))\n"
        "if not Path(args[-1]).is_file():\n"
        "    sys.exit(2)\n",
        encoding="utf-8",
    )
    pg_restore.chmod(0o755)
    monkeypatch.setenv(
        "PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    monkeypatch.setenv("FAKE_PG_RESTORE_RECORD", str(restore_record))

    for name in (
        "MAIL_CORE_BACKUP_KEYS",
        "MAIL_CORE_BACKUP_KEY_VERSION",
        "MAIL_CORE_BLOB_KEY_V1",
        "MAIL_CORE_BLOB_KEYS",
        "MAIL_CORE_BLOB_KEY_VERSION",
        "MAIL_CORE_BLOB_ACTIVE_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)

    backup_key = os.urandom(32)
    if encrypt:
        monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(backup_key).decode())
    else:
        monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)

    source_blobs = tmp_path / "source-blobs"
    source_blob = source_blobs / "aa" / "bb" / "message.blob"
    source_blob.parent.mkdir(parents=True)
    source_blob.write_bytes(b"offline blob payload")
    package_dir = tmp_path / ("sealed-backup" if encrypt else "plain-backup")
    create_backup_package(
        package_dir,
        include_blobs=True,
        database_url_override="postgresql://backup:source-pw@127.0.0.1:5432/source",
        blobs_dir=source_blobs,
        encrypt=encrypt,
    )

    manifest = json.loads((package_dir / "MANIFEST.json").read_text())
    dump_meta = manifest["members"].get("plain/postgres.dump") or manifest["members"]["postgres.dump"]
    assert dump_meta["method"] == "custom"
    assert verify_backup_package(package_dir).ok

    target_blobs = tmp_path / "restored-blobs"
    result = restore_backup_package(
        package_dir,
        target_database_url="postgresql://restore:target-pw@127.0.0.1:5432/target",
        target_blobs_dir=target_blobs,
        keyring={1: backup_key} if encrypt else None,
        source_database_url="postgresql://backup:source-pw@127.0.0.1:5432/source",
    )

    assert result.ok
    assert result.database_restored
    assert result.blobs_restored == 1
    assert (target_blobs / "aa" / "bb" / "message.blob").read_bytes() == b"offline blob payload"
    restore_args = json.loads(restore_record.read_text())
    assert restore_args[:5] == ["--clean", "--if-exists", "--no-owner", "--no-privileges", "--dbname"]
    assert "target-pw" not in " ".join(restore_args)


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (1, b""),
        (1, b"pg_restore: warning: could not execute query"),
        (2, b""),
    ],
)
def test_restore_fails_on_any_nonzero_pg_restore_exit(tmp_path, monkeypatch, returncode, stderr):
    backup_key = os.urandom(32)
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(backup_key).decode())
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    package_dir = tmp_path / "sealed-backup"
    create_backup_package(
        package_dir,
        include_blobs=False,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        encrypt=True,
        allow_dump_stub=True,
    )
    monkeypatch.setattr(backup_package.shutil, "which", lambda name: "/fake/pg_restore")
    monkeypatch.setattr(
        backup_package.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], returncode, stdout=b"", stderr=stderr
        ),
    )

    with pytest.raises(RuntimeError, match=rf"pg_restore failed \({returncode}\)"):
        restore_backup_package(
            package_dir,
            target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
            target_blobs_dir=tmp_path / "restored-blobs",
            keyring={1: backup_key},
            allow_stub=True,
            source_database_url="postgresql://backup-source:pw@127.0.0.1:5432/source",
        )

    assert package_dir.is_dir()
    assert list(tmp_path.glob(".restore_staging_*")) == []


@pytest.mark.parametrize(
    ("source_url", "target_url"),
    [
        (
            "postgresql://restore:source-pw@DB.Example/source%20db?sslmode=require",
            "postgresql+psycopg://restore:target-pw@db.example:5432/source%20db?sslmode=disable",
        ),
        (
            "postgres://restore:source-pw@[2001:db8::1]/same_db",
            "postgresql+psycopg://restore:target-pw@[2001:0db8::1]:5432/same_db",
        ),
    ],
)
def test_restore_refuses_normalized_same_source_database(tmp_path, source_url, target_url):
    package_dir = tmp_path / "empty-package"
    package_dir.mkdir()

    with pytest.raises(RuntimeError, match="refusing to restore onto source database"):
        restore_backup_package(
            package_dir,
            target_database_url=target_url,
            target_blobs_dir=tmp_path / "restored-blobs",
            source_database_url=source_url,
        )


@pytest.mark.parametrize(
    "target_url",
    [
        "postgresql+psycopg://restore:pw@db.example:5432/target_db",
        "postgresql+psycopg://restore:pw@other.example:5432/source_db",
    ],
)
def test_restore_allows_different_database_or_host(tmp_path, target_url):
    package_dir = tmp_path / "empty-package"
    package_dir.mkdir()

    with pytest.raises(RuntimeError, match="backup package verification failed"):
        restore_backup_package(
            package_dir,
            target_database_url=target_url,
            target_blobs_dir=tmp_path / "restored-blobs",
            source_database_url="postgresql://restore:pw@DB.Example/source_db",
        )


def test_restore_rejects_identity_changing_url_query(tmp_path):
    package_dir = tmp_path / "empty-package"
    package_dir.mkdir()

    with pytest.raises(RuntimeError, match="identity-changing URL query"):
        restore_backup_package(
            package_dir,
            target_database_url="postgresql://restore:pw@db.example/source_db?HOST=other.example",
            target_blobs_dir=tmp_path / "restored-blobs",
            source_database_url="postgresql://restore:pw@db.example/source_db",
        )


def test_restore_requires_source_database_url(tmp_path):
    with pytest.raises(TypeError, match="source_database_url"):
        restore_backup_package(
            tmp_path / "missing-package",
            target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
            target_blobs_dir=tmp_path / "restored-blobs",
        )


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

