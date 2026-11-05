"""Real Docker integration: application-uid backup reads private 0600 blobs."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from mail_core.backup.export import export_container_package
from mail_core.backup.package import verify_backup_package

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:16.15"
BACKUP_IMAGE = f"kkmail-test-backup-permissions:{os.getpid()}"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True
    )


def _wait_for_postgres(name: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = _docker(
            "exec", name, "pg_isready", "-U", "kkmail", "-d", "kkmail_mail",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError(f"postgres container {name} did not become ready")


@pytest.fixture(scope="module")
def backup_image() -> str:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    if _docker("info", check=False).returncode != 0:
        pytest.skip("docker daemon is unavailable")
    build = _docker(
        "build",
        "-q",
        "-f",
        "Dockerfile.mail-core-backup",
        "-t",
        BACKUP_IMAGE,
        ".",
        check=False,
    )
    if build.returncode != 0:
        raise AssertionError(f"could not build backup image: {build.stderr}")
    yield BACKUP_IMAGE
    _docker("rmi", "-f", BACKUP_IMAGE, check=False)


@pytest.fixture()
def docker_stack(backup_image: str):
    token = uuid.uuid4().hex[:12]
    network = f"kkmail-t075-net-{token}"
    postgres = f"kkmail-t075-pg-{token}"
    backup = f"kkmail-t075-backup-{token}"
    volume = f"kkmail-t075-blobs-{token}"
    password = f"test_{token}"
    _docker("network", "create", network)
    _docker("volume", "create", volume)
    _docker(
        "run",
        "-d",
        "--name",
        postgres,
        "--network",
        network,
        "--network-alias",
        "postgres",
        "-e",
        "POSTGRES_USER=kkmail",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        "POSTGRES_DB=kkmail_mail",
        POSTGRES_IMAGE,
    )
    _docker(
        "run",
        "--rm",
        "--user",
        "0:0",
        "-v",
        f"{volume}:/b",
        "--entrypoint",
        "sh",
        backup_image,
        "-c",
        "mkdir -p /b/aa/bb && printf probe > /b/aa/bb/probe.blob "
        "&& chown -R 10001:999 /b && chmod 0700 /b/aa /b/aa/bb "
        "&& chmod 0600 /b/aa/bb/probe.blob",
    )
    try:
        _wait_for_postgres(postgres)
        yield {
            "network": network,
            "postgres": postgres,
            "backup": backup,
            "volume": volume,
            "password": password,
        }
    finally:
        _docker("rm", "-f", backup, check=False)
        _docker("rm", "-f", postgres, check=False)
        _docker("network", "rm", network, check=False)
        _docker("volume", "rm", "-f", volume, check=False)


def _blob_stat(backup_image: str, volume: str) -> str:
    return _docker(
        "run",
        "--rm",
        "-v",
        f"{volume}:/b:ro",
        "--entrypoint",
        "stat",
        backup_image,
        "-c",
        "%a %u %g",
        "/b/aa/bb/probe.blob",
    ).stdout.strip()


def test_backup_container_reads_private_blobs_and_exports_host_owned_package(
    tmp_path, monkeypatch, docker_stack
):
    stack = docker_stack
    blob_key = base64.b64encode(os.urandom(32)).decode()
    backup_key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", backup_key)
    before = _blob_stat(BACKUP_IMAGE, stack["volume"])
    assert before == "600 10001 999"
    uid_output = _docker("run", "--rm", "--entrypoint", "id", BACKUP_IMAGE, "-u")
    assert uid_output.stdout.strip() == "10001"

    env_args: list[str] = []
    env = {
        "MAIL_CORE_DATABASE_URL": (
            f"postgresql+psycopg://kkmail:{stack['password']}"
            "@postgres:5432/kkmail_mail"
        ),
        "MAIL_CORE_BLOB_KEY_V1": blob_key,
        "MAIL_CORE_BACKUP_KEY": backup_key,
        "MAIL_CORE_BLOB_ROOT": "/var/lib/kkmail/blobs",
        "MAIL_CORE_BACKUP_DIR": "/backup",
    }
    for key, value in env.items():
        env_args.extend(["-e", f"{key}={value}"])

    command = """import json
from mail_core.backup import run_backup
result = run_backup(output_dir="/backup/package")
verify = result.get("verify", {})
print(json.dumps({"status": result.get("status"), "verified": verify.get("ok")}))
raise SystemExit(0 if result.get("status") == "ok" and verify.get("ok") else 1)
"""
    run = _docker(
        "run",
        "--name",
        stack["backup"],
        "--network",
        stack["network"],
        "-v",
        f"{stack['volume']}:/var/lib/kkmail/blobs:ro",
        *env_args,
        BACKUP_IMAGE,
        "-c",
        command,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert '"verified": true' in run.stdout
    assert _blob_stat(BACKUP_IMAGE, stack["volume"]) == before

    staging = tmp_path / "staging"
    backup_dir = tmp_path / "backup"
    staging.mkdir(mode=0o700)
    backup_dir.mkdir(mode=0o700)
    destination = export_container_package(
        container=stack["backup"],
        staging_dir=staging,
        backup_dir=backup_dir,
    )
    assert verify_backup_package(destination).ok
    assert (destination / "backup.kkbak").is_file()
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(
        (path.stat().st_mode & 0o777) == (0o700 if path.is_dir() else 0o600)
        for path in [destination, *destination.rglob("*")]
    )

    for permission_test in ("-r", "-x"):
        traverse = _docker(
            "run",
            "--rm",
            "--user",
            "12345:12345",
            "-v",
            f"{stack['volume']}:/b:ro",
            "--entrypoint",
            "sh",
            BACKUP_IMAGE,
            "-c",
            f"test {permission_test} /b/aa",
            check=False,
        )
        assert traverse.returncode != 0

    _docker("rm", "-f", stack["backup"], check=False)
    normalized = _docker(
        "run",
        "--rm",
        "--user",
        "10001:999",
        "-v",
        f"{stack['volume']}:/b",
        "--entrypoint",
        "python3",
        BACKUP_IMAGE,
        "-m",
        "mail_core.blobs.permissions",
        "/b",
        check=False,
    )
    assert normalized.returncode == 0, normalized.stderr
    second_run = _docker(
        "run",
        "--name",
        stack["backup"],
        "--network",
        stack["network"],
        "-v",
        f"{stack['volume']}:/var/lib/kkmail/blobs:ro",
        *env_args,
        BACKUP_IMAGE,
        "-c",
        command,
        check=False,
    )
    assert second_run.returncode == 0, second_run.stderr
    assert '"verified": true' in second_run.stdout

    unrelated = _docker(
        "run",
        "--rm",
        "--user",
        "12345:12345",
        "-v",
        f"{stack['volume']}:/b:ro",
        "--entrypoint",
        "sh",
        BACKUP_IMAGE,
        "-c",
        "cat /b/aa/bb/probe.blob",
        check=False,
    )
    assert unrelated.returncode != 0


def test_owner_normalization_migrates_foreign_private_tree(backup_image):
    volume = f"kkmail-t075-owner-{uuid.uuid4().hex[:12]}"
    _docker("volume", "create", volume)
    try:
        _docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "-v",
            f"{volume}:/b",
            "--entrypoint",
            "sh",
            backup_image,
            "-c",
            "mkdir -p /b/aa && printf x > /b/aa/x.blob "
            "&& chown -R 0:0 /b && chmod 0700 /b /b/aa "
            "&& chmod 0600 /b/aa/x.blob",
        )
        result = _docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "FOWNER",
            "--cap-add",
            "DAC_OVERRIDE",
            "-v",
            f"{volume}:/b",
            "--entrypoint",
            "python3",
            backup_image,
            "-m",
            "mail_core.blobs.permissions",
            "/b",
            "--target-uid",
            "10001",
            "--target-gid",
            "999",
            check=False,
        )
        assert result.returncode == 0, result.stderr
        stat = _docker(
            "run",
            "--rm",
            "-v",
            f"{volume}:/b:ro",
            "--entrypoint",
            "stat",
            backup_image,
            "-c",
            "%a %u %g",
            "/b/aa/x.blob",
        ).stdout.strip()
        assert stat == "600 10001 999"
    finally:
        _docker("volume", "rm", "-f", volume, check=False)
