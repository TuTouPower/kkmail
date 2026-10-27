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


def test_restore_uses_the_package_snapshot_it_verified(tmp_path, monkeypatch):
    import mail_core.backup.package as pkg

    package_dir = tmp_path / "mutable-package"
    expected_dump = b"verified postgres dump"
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")

    def fake_dump(dest, _url, allow_stub=False):
        dest.write_bytes(expected_dump)
        return "custom"

    monkeypatch.setattr(pkg, "_pg_dump_to", fake_dump)
    create_backup_package(
        package_dir,
        include_blobs=False,
        database_url_override="postgresql://backup:pw@127.0.0.1:1/source",
        encrypt=False,
        allow_dump_stub=True,
    )
    original_verify = pkg.verify_backup_package
    verified_snapshots = []

    def verify_then_mutate_original(snapshot_dir, **kwargs):
        snapshot = Path(snapshot_dir)
        assert snapshot != package_dir
        result = original_verify(snapshot, **kwargs)
        verified_snapshots.append(snapshot)
        (package_dir / "postgres.dump").write_bytes(b"tampered after verification")
        return result

    restored_dumps = []

    def fake_run(argv, **_kwargs):
        restored_dumps.append(Path(argv[-1]).read_bytes())
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pkg, "verify_backup_package", verify_then_mutate_original)
    monkeypatch.setattr(pkg.shutil, "which", lambda _name: "/fake/pg_restore")
    monkeypatch.setattr(pkg.subprocess, "run", fake_run)

    result = restore_backup_package(
        package_dir,
        target_database_url="postgresql://restore:pw@127.0.0.1:1/target",
        target_blobs_dir=tmp_path / "restored-blobs",
        allow_stub=True,
        source_database_url="postgresql://backup:pw@127.0.0.1:1/source",
    )

    assert result.ok
    assert len(verified_snapshots) == 1
    assert restored_dumps == [expected_dump]
    assert (package_dir / "postgres.dump").read_bytes() == b"tampered after verification"
    assert list(tmp_path.glob(".restore_staging_*")) == []


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


def test_restore_blob_copy_failure_preserves_existing_file(tmp_path, monkeypatch):
    source_blobs = tmp_path / "source-blobs"
    source_blob = source_blobs / "aa" / "bb" / "message.blob"
    source_blob.parent.mkdir(parents=True)
    source_blob.write_bytes(b"replacement blob payload")
    package_dir = tmp_path / "plain-backup"
    create_backup_package(
        package_dir,
        include_blobs=True,
        database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
        blobs_dir=source_blobs,
        encrypt=False,
        allow_dump_stub=True,
    )
    monkeypatch.setattr(
        backup_package,
        "verify_backup_package",
        lambda *_args, **_kwargs: backup_package.RestoreVerifyResult(True, 1, []),
    )

    target_blobs = tmp_path / "restored-blobs"
    dest_file = target_blobs / "aa" / "bb" / "message.blob"
    dest_file.parent.mkdir(parents=True)
    dest_file.write_bytes(b"existing blob")

    # Upgraded per D02: non-empty destination is rejected upfront to prevent overwrite
    with pytest.raises(RuntimeError, match="non-empty target blobs dir"):
        restore_backup_package(
            package_dir,
            target_database_url="postgresql://restore:pw@127.0.0.1:5432/target",
            target_blobs_dir=target_blobs,
            source_database_url="postgresql://backup:pw@127.0.0.1:5432/source",
            allow_stub=True,
        )

    assert dest_file.read_bytes() == b"existing blob"
    assert not list(target_blobs.rglob("*.restore-*"))


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
    # Upgraded per D02: remove --clean/--if-exists, enforce --exit-on-error --single-transaction
    assert restore_args[:5] == [
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        "--dbname",
    ]
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


def test_create_backup_requires_key_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY_VERSION", raising=False)
    out = tmp_path / "backup"

    with pytest.raises(BackupCryptoError, match="required to encrypt backups"):
        create_backup_package(
            out,
            include_blobs=False,
            database_url_override="postgresql://u:p@127.0.0.1:1/db",
            blobs_dir=tmp_path / "blobs",
            allow_dump_stub=True,
        )

    assert not out.exists()


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


@pytest.mark.parametrize("existing_output", [False, True])
def test_failed_plain_backup_dump_keeps_partial_file_in_staging_only(
    tmp_path, monkeypatch, existing_output
):
    out = tmp_path / "plain-backup"
    if existing_output:
        out.mkdir()
        (out / "keep.txt").write_text("previous package", encoding="utf-8")

    monkeypatch.setattr(
        backup_package.shutil,
        "which",
        lambda name: "/fake/pg_dump" if name == "pg_dump" else None,
    )

    def fail_after_partial_dump(command, **_kwargs):
        dump_path = Path(command[command.index("--file") + 1])
        dump_path.write_bytes(b"partial dump")
        raise subprocess.CalledProcessError(1, command, stderr=b"simulated pg_dump failure")

    monkeypatch.setattr(backup_package.subprocess, "run", fail_after_partial_dump)
    with pytest.raises(backup_package.PgDumpError, match="pg_dump failed"):
        create_backup_package(
            out,
            include_blobs=False,
            database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
            encrypt=False,
            allow_dump_stub=False,
        )

    if existing_output:
        assert (out / "keep.txt").read_text(encoding="utf-8") == "previous package"
        assert not (out / "postgres.dump").exists()
    else:
        assert not out.exists()
    assert not list(tmp_path.glob(".staging_plain_*"))


def test_missing_pg_dump_raises_a_dump_specific_error(tmp_path, monkeypatch):
    from mail_core.backup.package import PgDumpError, _pg_dump_to

    monkeypatch.setattr("mail_core.backup.package.shutil.which", lambda _name: None)

    with pytest.raises(PgDumpError, match="pg_dump binary not found on PATH"):
        _pg_dump_to(
            tmp_path / "postgres.dump",
            "postgresql://nobody:nope@127.0.0.1:1/none",
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


@pytest.mark.parametrize("existing_output", [False, True])
def test_backup_build_failure_publishes_nothing(tmp_path, monkeypatch, existing_output):
    # A80 (replaces test_backup_build_failure_cleans_plain_staging): the
    # encrypted path used to assemble the package in place inside the target
    # directory, so a mid-build failure left a partial package behind and the
    # old test only asserted the staging subdirs were cleaned from it. With
    # atomic staging+rename publication, a failed build must leave a
    # pre-existing package untouched (or no package at all) and no staging
    # remnants anywhere.
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "fail_enc_pkg"
    if existing_output:
        out.mkdir()
        (out / "keep.txt").write_text("previous package", encoding="utf-8")

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

    if existing_output:
        assert (out / "keep.txt").read_text(encoding="utf-8") == "previous package"
        assert not (out / "backup.kkbak").exists()
    else:
        assert not out.exists()
    assert not list(tmp_path.glob(".staging_enc_*"))
    assert not list(tmp_path.glob(".old_*"))


def test_encrypted_backup_replaces_existing_package_atomically(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "enc_pkg"
    out.mkdir()
    (out / "stale.txt").write_text("previous package", encoding="utf-8")

    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )

    assert (out / "backup.kkbak").is_file()
    assert not (out / "stale.txt").exists()
    assert verify_backup_package(out, allow_stub=True).ok
    assert not list(tmp_path.glob(".staging_enc_*"))
    assert not list(tmp_path.glob(".old_*"))


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


def test_run_backup_serializes_same_destination(tmp_path, monkeypatch):
    import threading

    import mail_core.backup.package as pkg

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
    first_dump_started = threading.Event()
    second_dump_started = threading.Event()
    second_lock_attempting = threading.Event()
    release_first = threading.Event()
    call_lock = threading.Lock()
    calls = 0
    results = []
    errors = []
    dest = tmp_path / "shared-backup"
    original_lock = pkg._backup_destination_lock

    def observed_lock(path):
        if threading.current_thread().name == "backup-second":
            second_lock_attempting.set()
        return original_lock(path)

    def fake_dump(dump_path, _url, allow_stub=False):
        nonlocal calls
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_dump_started.set()
            if not release_first.wait(timeout=5):
                raise RuntimeError("test did not release first dump")
        else:
            second_dump_started.set()
        dump_path.write_bytes(f"dump-{call_number}".encode())
        return "custom"

    def run_backup():
        try:
            results.append(pkg.run_backup(output_dir=str(dest), encrypt=False))
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(pkg, "_backup_destination_lock", observed_lock)
    monkeypatch.setattr(pkg, "_pg_dump_to", fake_dump)
    first = threading.Thread(target=run_backup, name="backup-first")
    second = threading.Thread(target=run_backup, name="backup-second")
    first.start()
    assert first_dump_started.wait(timeout=2)
    second.start()
    assert second_lock_attempting.wait(timeout=2)
    try:
        assert not second_dump_started.wait(timeout=0.05)
    finally:
        release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert [result["status"] for result in results] == ["ok", "ok"]


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


def test_validate_blob_members_matrix(tmp_path):
    import io
    import tarfile
    from mail_core.backup.package import _validate_blob_members

    def create_tar_with_member(name: str, member_type: bytes = tarfile.REGTYPE, linkname: str = "") -> io.BytesIO:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            ti = tarfile.TarInfo(name=name)
            ti.type = member_type
            ti.linkname = linkname
            if member_type == tarfile.REGTYPE:
                data = b"blob-content"
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
            else:
                t.addfile(ti)
        buf.seek(0)
        return buf

    # 1. Traversal member
    with tarfile.open(fileobj=create_tar_with_member("blobs/../../etc/passwd"), mode="r") as t:
        with pytest.raises(RuntimeError, match="path traversal|disallowed"):
            _validate_blob_members(t)

    # 2. Symlink member
    with tarfile.open(fileobj=create_tar_with_member("blobs/link", member_type=tarfile.SYMTYPE, linkname="/etc/passwd"), mode="r") as t:
        with pytest.raises(RuntimeError, match="unsafe member type"):
            _validate_blob_members(t)

    # 3. Absolute path
    with tarfile.open(fileobj=create_tar_with_member("/blobs/file.blob"), mode="r") as t:
        with pytest.raises(RuntimeError, match="unsafe absolute path"):
            _validate_blob_members(t)

    # 4. Windows drive
    with tarfile.open(fileobj=create_tar_with_member("C:/blobs/file.blob"), mode="r") as t:
        with pytest.raises(RuntimeError, match="unsafe drive"):
            _validate_blob_members(t)

    # 5. Invalid character backslash
    with tarfile.open(fileobj=create_tar_with_member("blobs\\sub\\file.blob"), mode="r") as t:
        with pytest.raises(RuntimeError, match="invalid characters"):
            _validate_blob_members(t)


def test_validate_restore_destination_matrix(tmp_path):
    from mail_core.backup.package import _validate_restore_destination

    # 1. Non-empty destination
    non_empty = tmp_path / "non_empty_blobs"
    non_empty.mkdir()
    (non_empty / "existing.blob").write_bytes(b"data")
    with pytest.raises(RuntimeError, match="non-empty target blobs dir"):
        _validate_restore_destination(non_empty)

    # 2. Symlink destination
    symlink_dest = tmp_path / "symlink_blobs"
    target_real = tmp_path / "real_dir"
    target_real.mkdir()
    symlink_dest.symlink_to(target_real)
    with pytest.raises(RuntimeError, match="refusing target blobs dir as symlink"):
        _validate_restore_destination(symlink_dest)

    # 3. Traversal destination
    with pytest.raises(RuntimeError, match="path traversal detected"):
        _validate_restore_destination(tmp_path / ".." / "outside")

    # 4. Valid empty directory
    valid_empty = tmp_path / "empty_blobs"
    valid_empty.mkdir()
    assert _validate_restore_destination(valid_empty) == valid_empty.resolve()


def test_backup_destination_lock_times_out_when_held(tmp_path, monkeypatch, caplog):
    import logging
    import time

    import mail_core.backup.package as pkg

    monkeypatch.setenv("MAIL_CORE_BACKUP_LOCK_TIMEOUT", "0.3")
    dest = tmp_path / "locked-backup"
    held = pkg._backup_destination_lock(dest)
    held.__enter__()
    try:
        started = time.monotonic()
        with caplog.at_level(logging.INFO, logger="mail_core.backup"):
            with pytest.raises(RuntimeError, match="timed out.*backup destination lock"):
                with pkg._backup_destination_lock(dest):
                    pass
        assert time.monotonic() - started < 5
        # While waiting, the contention must be observable in the log.
        assert any(
            "backup destination lock" in record.getMessage()
            for record in caplog.records
        )
    finally:
        held.__exit__(None, None, None)


def test_backup_destination_lock_acquires_after_release_within_timeout(
    tmp_path, monkeypatch
):
    import threading

    import mail_core.backup.package as pkg

    monkeypatch.setenv("MAIL_CORE_BACKUP_LOCK_TIMEOUT", "5")
    dest = tmp_path / "contended-backup"
    held = pkg._backup_destination_lock(dest)
    held.__enter__()
    acquired = threading.Event()
    errors: list[BaseException] = []

    def contender():
        try:
            with pkg._backup_destination_lock(dest):
                acquired.set()
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    thread = threading.Thread(target=contender)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.2)
    finally:
        held.__exit__(None, None, None)
    assert acquired.wait(timeout=3)
    thread.join(timeout=3)
    assert errors == []


def test_run_backup_logs_warning_when_last_success_write_fails(
    tmp_path, monkeypatch, caplog
):
    import logging

    import mail_core.db.session as db_session
    import mail_core.backup.package as pkg

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")

    def fake_dump(dest, _url, allow_stub=False):
        dest.write_bytes(b"valid pg dump data")
        return "custom"

    def failing_factory():
        raise RuntimeError("session factory unavailable for test")

    monkeypatch.setattr(pkg, "_pg_dump_to", fake_dump)
    monkeypatch.setattr(db_session, "get_session_factory", failing_factory)

    dest = tmp_path / "backup-out"
    with caplog.at_level(logging.WARNING, logger="mail_core.backup"):
        result = pkg.run_backup(output_dir=str(dest), encrypt=False)

    # The backup itself succeeded; the bookkeeping failure must be visible
    # in the log instead of being silently swallowed.
    assert result["status"] == "ok"
    assert any(
        "backup:last_success" in record.getMessage()
        and "session factory unavailable" in record.getMessage()
        for record in caplog.records
    )


def _install_fake_psycopg(monkeypatch, row, executed: list[str]):
    import sys
    import types

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            executed.append(sql)

        def fetchone(self):
            return row

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return FakeCursor()

    fake = types.ModuleType("psycopg")
    fake.connect = lambda _dsn, **_kw: FakeConn()
    monkeypatch.setitem(sys.modules, "psycopg", fake)


def test_assert_target_database_is_empty_accepts_truly_empty_db(monkeypatch):
    executed: list[str] = []
    _install_fake_psycopg(monkeypatch, (0, 0, 0), executed)
    backup_package._assert_target_database_is_empty(
        "postgresql://u:p@127.0.0.1:5432/target"
    )
    # The check must look beyond tables: views/sequences live in pg_class,
    # functions in pg_proc and extensions in pg_extension.
    joined = " ".join(executed)
    assert "pg_proc" in joined
    assert "pg_extension" in joined


@pytest.mark.parametrize("row", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (3, 2, 1)])
def test_assert_target_database_is_empty_rejects_any_user_objects(monkeypatch, row):
    # A database with zero tables but e.g. only a function, a sequence or an
    # extension installed is not an empty restore target.
    executed: list[str] = []
    _install_fake_psycopg(monkeypatch, row, executed)
    with pytest.raises(RuntimeError, match="non-empty target database"):
        backup_package._assert_target_database_is_empty(
            "postgresql://u:p@127.0.0.1:5432/target"
        )


def _rewrite_manifest(package_dir: Path, manifest) -> None:
    import hashlib

    man_path = package_dir / "MANIFEST.json"
    man_path.write_text(json.dumps(manifest), encoding="utf-8")
    (package_dir / "MANIFEST.sha256").write_text(
        f"{hashlib.sha256(man_path.read_bytes()).hexdigest()}  MANIFEST.json\n",
        encoding="utf-8",
    )


def _make_plain_package(tmp_path: Path) -> Path:
    out = tmp_path / "plain-pkg"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=False,
        allow_dump_stub=True,
    )
    return out


@pytest.mark.parametrize("bad_members", [["postgres.dump"], "postgres.dump", 42])
def test_verify_rejects_non_dict_members_without_raising(tmp_path, bad_members):
    out = _make_plain_package(tmp_path)
    man = json.loads((out / "MANIFEST.json").read_text())
    man["members"] = bad_members
    _rewrite_manifest(out, man)

    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert result.errors


def test_verify_rejects_non_dict_member_metadata_without_raising(tmp_path):
    out = _make_plain_package(tmp_path)
    man = json.loads((out / "MANIFEST.json").read_text())
    man["members"] = {"postgres.dump": "not-a-dict"}
    _rewrite_manifest(out, man)

    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert any("postgres.dump" in e for e in result.errors)


def test_verify_rejects_non_dict_manifest_without_raising(tmp_path):
    out = _make_plain_package(tmp_path)
    _rewrite_manifest(out, ["not", "a", "manifest"])

    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert result.errors


def test_verify_sealed_rejects_non_dict_outer_members_without_raising(
    tmp_path, monkeypatch
):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", key)
    out = tmp_path / "sealed-pkg"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override="postgresql://u:p@127.0.0.1:1/db",
        encrypt=True,
        allow_dump_stub=True,
    )
    man = json.loads((out / "MANIFEST.json").read_text())
    man["members"] = ["backup.kkbak"]
    _rewrite_manifest(out, man)

    result = verify_backup_package(out, allow_stub=True)
    assert result.ok is False
    assert result.errors


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:userpw@127.0.0.1:5432/db?password=querypw&sslpassword=sslpw&sslmode=require",
        "postgresql://u:userpw@127.0.0.1:5432/db?token=tok123&x=1",
    ],
)
def test_redact_url_masks_query_credentials(url):
    from mail_core.backup.package import _redact_url

    redacted = _redact_url(url)
    for secret in ("userpw", "querypw", "sslpw", "tok123"):
        assert secret not in redacted
    assert "***" in redacted


def test_package_module_has_no_unused_crypto_or_fsync_helpers():
    # A192: package.py imported encrypt_bytes/decrypt_bytes without using them
    # and defined _fsync_file with zero callers; both mislead readers about
    # which crypto/fsync paths the restore chain actually uses.
    assert not hasattr(backup_package, "encrypt_bytes")
    assert not hasattr(backup_package, "decrypt_bytes")
    assert not hasattr(backup_package, "_fsync_file")


def test_restore_database_identity_ignores_username_and_normalizes_aliases():
    from mail_core.backup.package import _restore_database_identity

    id1 = _restore_database_identity("postgresql://user_alice:pass1@localhost:5432/kkmail_db")
    id2 = _restore_database_identity("postgresql+psycopg://user_bob:pass2@127.0.0.1:5432/kkmail_db")
    id3 = _restore_database_identity("postgresql://postgres:admin@[::1]:5432/kkmail_db")

    assert id1 == id2
    assert id2 == id3
    assert id1 == ("postgresql", "127.0.0.1", 5432, "kkmail_db")

