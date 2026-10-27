"""R4 adoption P10 (backup domain): A6/A15/A26/A44/A56/A67/A78/A79.

Each test targets one adoption item in
``docs/reviews/review_20261027_021416/adoption_decision.md`` and the
corresponding code in ``src/mail_core/backup/package.py``.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from mail_core.backup import package as backup_package
from mail_core.backup.package import (
    cleanup_restore_operation,
    create_backup_package,
    restore_backup_package,
    resume_restore_backup_package,
    verify_restore_operation,
)

SOURCE_URL = "postgresql://backup:pw@127.0.0.1:5432/source"
TARGET_URL = "postgresql://restore:pw@127.0.0.1:5432/target"

PAYLOADS = {
    "aa/bb/first.blob": b"first blob payload",
    "cc/dd/second.blob": b"second blob payload",
}


def _make_package(base: Path, payloads: dict[str, bytes] | None = None) -> Path:
    payloads = PAYLOADS if payloads is None else payloads
    src_blobs = base / "src-blobs"
    for rel, data in payloads.items():
        path = src_blobs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    pkg_dir = base / "package"
    create_backup_package(
        pkg_dir,
        include_blobs=True,
        database_url_override=SOURCE_URL,
        blobs_dir=src_blobs,
        encrypt=False,
        allow_dump_stub=True,
    )
    return pkg_dir


class _FakePgRestore:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def install(self, monkeypatch) -> "_FakePgRestore":
        monkeypatch.setattr(
            backup_package.shutil,
            "which",
            lambda name: "/fake/pg_restore" if name == "pg_restore" else None,
        )

        def run(cmd, **_kwargs):
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(
                cmd,
                self.returncode,
                stdout=b"",
                stderr=b"simulated pg_restore failure" if self.returncode else b"",
            )

        monkeypatch.setattr(backup_package.subprocess, "run", run)
        return self


def _read_log(target: Path) -> dict:
    return json.loads(
        (target / backup_package._RESTORE_OPERATION_LOG_FILENAME).read_text()
    )


def _restore(pkg_dir: Path, target: Path, **kwargs):
    return restore_backup_package(
        pkg_dir,
        target_database_url=TARGET_URL,
        target_blobs_dir=target,
        source_database_url=SOURCE_URL,
        allow_stub=True,
        **kwargs,
    )


def _resume(pkg_dir: Path, target: Path, operation_id: str, **kwargs):
    return resume_restore_backup_package(
        pkg_dir,
        operation_id=operation_id,
        target_database_url=TARGET_URL,
        target_blobs_dir=target,
        source_database_url=SOURCE_URL,
        allow_stub=True,
        **kwargs,
    )


def _verify(pkg_dir: Path, target: Path, operation_id: str, **kwargs):
    return verify_restore_operation(
        pkg_dir,
        operation_id=operation_id,
        target_database_url=TARGET_URL,
        target_blobs_dir=target,
        source_database_url=SOURCE_URL,
        allow_stub=True,
        **kwargs,
    )


def _published_files(target: Path) -> dict[str, bytes]:
    out = {}
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if rel == backup_package._RESTORE_OPERATION_LOG_FILENAME:
            continue
        if rel.startswith(".restore_staging_"):
            continue
        out[rel] = path.read_bytes()
    return out


def _needs_verification_operation(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(0).install(monkeypatch)

    def interrupted_verify(*_args, **_kwargs):
        raise RuntimeError("simulated interruption after DB commit")

    monkeypatch.setattr(backup_package, "_verify_restored_state", interrupted_verify)
    with pytest.raises(RuntimeError, match="needs_verification"):
        _restore(pkg_dir, target)
    monkeypatch.setattr(
        backup_package, "_verify_restored_state", lambda *a, **k: None
    )
    return pkg_dir, target, fake


# --- A6: verify must re-read the operation log under the lock --------------


def test_a6_verify_rechecks_stage_under_lock_when_operation_completes(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _needs_verification_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]
    assert _read_log(target)["stage"] == "needs_verification"

    real_lock = backup_package._backup_destination_lock

    @contextlib.contextmanager
    def completing_lock(dest):
        with real_lock(dest):
            # Another operation completes this restore while verify is
            # acquiring the lock: at lock entry the log says ``complete``
            # even though the pre-lock read saw ``needs_verification``.
            current = backup_package._read_restore_operation_log(dest)
            backup_package._write_restore_operation_log(
                dest, current, stage="complete"
            )
            yield

    monkeypatch.setattr(backup_package, "_backup_destination_lock", completing_lock)

    result = _verify(pkg_dir, target, operation_id)

    # The in-lock stage (complete) must drive the outcome: no regression
    # to blobs_published and no needs_verification error from stale state.
    assert result.ok
    assert result.stage == "complete"
    assert _read_log(target)["stage"] == "complete"
    assert _published_files(target) == PAYLOADS
    assert len(fake.calls) == 1  # verify never replays pg_restore


# --- A56: verify of a complete operation must still validate the package ---


def _completed_operation(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(0).install(monkeypatch)
    result = _restore(pkg_dir, target)
    assert result.ok
    assert _read_log(target)["stage"] == "complete"
    return pkg_dir, target, fake


def test_a56_verify_complete_operation_validates_package(tmp_path, monkeypatch):
    pkg_dir, target, fake = _completed_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]

    result = _verify(pkg_dir, target, operation_id)

    assert result.ok
    assert result.stage == "complete"
    # The package was actually validated: its size is reported, not 0.
    assert result.package_size_bytes > 0
    assert result.blobs_restored == len(PAYLOADS)
    assert len(fake.calls) == 1


def test_a56_verify_complete_operation_rejects_mismatched_package(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _completed_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]
    other_pkg = _make_package(
        tmp_path / "other", {"aa/bb/first.blob": b"different payload"}
    )

    with pytest.raises(RuntimeError, match="package digest"):
        _verify(other_pkg, target, operation_id)
    assert _read_log(target)["stage"] == "complete"
    assert _published_files(target) == PAYLOADS


def test_a56_verify_complete_operation_rejects_tampered_published_blob(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _completed_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]
    victim = target / "aa" / "bb" / "first.blob"
    victim.write_bytes(b"tampered after completion")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _verify(pkg_dir, target, operation_id)
    assert _read_log(target)["stage"] == "complete"
