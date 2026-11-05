from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

import pytest

import mail_core.backup.export as backup_export
from mail_core.backup.export import BackupExportError, export_container_package
from mail_core.backup.package import create_backup_package, verify_backup_package


def _source_package(tmp_path, monkeypatch):
    backup_key = os.urandom(32)
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", base64.b64encode(backup_key).decode())
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    source = tmp_path / "container-package"
    create_backup_package(
        source,
        include_blobs=False,
        database_url_override="postgresql://backup:pw@127.0.0.1:5432/source",
        encrypt=True,
        allow_dump_stub=True,
    )
    return source


def _copy_package(source: Path):
    def copier(_source: str, destination: str) -> None:
        import shutil

        shutil.copytree(source, Path(destination), dirs_exist_ok=True)

    return copier


def test_export_publishes_private_operator_owned_package(tmp_path, monkeypatch):
    source = _source_package(tmp_path, monkeypatch)
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    staging.mkdir()
    staging.chmod(0o755)
    backup.mkdir(mode=0o700)

    destination = export_container_package(
        container="backup-container",
        staging_dir=staging,
        backup_dir=backup,
        allow_stub=True,
        docker_cp=_copy_package(source),
    )

    assert destination == backup / "package"
    assert destination.is_dir()
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700
    assert not (staging / "package").exists()
    assert verify_backup_package(destination, allow_stub=True).ok
    uid, gid = os.getuid(), os.getgid()
    for path in [destination, *destination.rglob("*")]:
        st = path.lstat()
        assert (st.st_uid, st.st_gid) == (uid, gid)
        expected = 0o700 if path.is_dir() else 0o600
        assert stat.S_IMODE(st.st_mode) == expected


def test_export_failure_does_not_publish_a_package(tmp_path, monkeypatch):
    source = _source_package(tmp_path, monkeypatch)
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    staging.mkdir(mode=0o700)
    backup.mkdir(mode=0o700)

    def corrupt_copy(_source: str, destination: str) -> None:
        dest = Path(destination)
        _copy_package(source)(_source, destination)
        (dest / "backup.kkbak").write_bytes(b"corrupted")

    with pytest.raises(BackupExportError, match="failed verification"):
        export_container_package(
            container="backup-container",
            staging_dir=staging,
            backup_dir=backup,
            allow_stub=True,
            docker_cp=corrupt_copy,
        )

    assert not (backup / "package").exists()
    assert not (staging / "package").exists()


def test_export_refuses_package_already_present(tmp_path, monkeypatch):
    source = _source_package(tmp_path, monkeypatch)
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    staging.mkdir(mode=0o700)
    backup.mkdir(mode=0o700)
    (backup / "package").mkdir()

    with pytest.raises(BackupExportError, match="refusing to overwrite"):
        export_container_package(
            container="backup-container",
            staging_dir=staging,
            backup_dir=backup,
            allow_stub=True,
            docker_cp=_copy_package(source),
        )


def test_export_cli_reports_docker_cp_failure_without_traceback(tmp_path, monkeypatch, capsys):
    def fail_cp(*_args, **_kwargs):
        raise __import__("subprocess").CalledProcessError(
            1, ["docker", "cp"], stderr="container not found"
        )

    monkeypatch.setattr(backup_export, "_docker_cp", fail_cp)
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    staging.mkdir()
    backup.mkdir()

    rc = backup_export.main(
        [
            "--container",
            "missing",
            "--staging-dir",
            str(staging),
            "--backup-dir",
            str(backup),
        ]
    )

    assert rc == 1
    stderr = capsys.readouterr().err
    assert "backup_export_failed: docker cp failed (1): container not found" in stderr
