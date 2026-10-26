"""R12: cross-volume-safe blob restore (repair design section 8).

Restore must stage *inside* the target blob root, publish blobs fully
(renames only ever inside the target root), and only then commit the
database with ``pg_restore --single-transaction``.  A database failure
keeps the published blobs plus the operation log so ``resume`` can reuse
them after identity / package-digest / file-checksum verification; an
uncertain commit leaves the operation in ``needs_verification``.

The cross-filesystem boundary is exercised two ways:

* a monkeypatched ``Path.replace`` that raises ``EXDEV`` for any rename
  crossing between two simulated volumes (the restore flow must never
  attempt one), and
* when available, a real second mount (``/dev/shm``, tmpfs) for the
  package while the target lives under ``tmp_path`` — different
  ``st_dev`` values, so a cross-volume rename would really fail.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
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
    return json.loads((target / backup_package._RESTORE_OPERATION_LOG_FILENAME).read_text())


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


# --- Cross-volume publish ---------------------------------------------------


def test_restore_never_renames_across_volumes(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "vol-package")
    target = tmp_path / "vol-target" / "restored-blobs"

    volumes = [ (tmp_path / "vol-package").resolve(), (tmp_path / "vol-target").resolve() ]

    def volume_of(path: Path):
        resolved = path.resolve(strict=False)
        for idx, vol in enumerate(volumes):
            if resolved == vol or vol in resolved.parents:
                return idx
        return None

    cross_attempts: list[tuple[str, str]] = []
    real_replace = Path.replace

    def guarded_replace(self, dest):
        src_vol, dst_vol = volume_of(self), volume_of(Path(dest))
        if src_vol is not None and dst_vol is not None and src_vol != dst_vol:
            cross_attempts.append((str(self), str(dest)))
            raise OSError(errno.EXDEV, "Invalid cross-device link (simulated)")
        return real_replace(self, dest)

    monkeypatch.setattr(Path, "replace", guarded_replace)

    publish_renames: list[tuple[Path, Path]] = []
    real_publish = backup_package._publish_rename

    def recording_publish(src, dst, root):
        publish_renames.append((Path(src), Path(dst)))
        return real_publish(src, dst, root)

    monkeypatch.setattr(backup_package, "_publish_rename", recording_publish)
    fake = _FakePgRestore(0).install(monkeypatch)

    result = _restore(pkg_dir, target)

    assert result.ok
    assert result.database_restored
    assert cross_attempts == [], "restore attempted a cross-volume rename"
    assert publish_renames, "expected publish renames to be exercised"
    target_resolved = target.resolve()
    for src, dst in publish_renames:
        assert target_resolved in src.resolve().parents or src.resolve().parent == target_resolved
        assert target_resolved in dst.resolve(strict=False).parents
    assert _published_files(target) == PAYLOADS
    assert len(fake.calls) == 1
    assert _read_log(target)["stage"] == "complete"
    # Operation log contains only the five allowed categories of data.
    log = _read_log(target)
    assert set(log) == {
        "operation_id",
        "package_digest",
        "target_paths",
        "database_identity",
        "stage",
    }
    assert "pw" not in json.dumps(log)
    # Staging inside the target root is gone once published.
    assert not list(target.glob(".restore_staging_*"))


def test_restore_across_real_filesystems(tmp_path):
    shm = Path("/dev/shm")
    if not shm.is_dir() or not os.access(shm, os.W_OK):
        pytest.skip("/dev/shm not writable in this environment")
    if os.stat(shm).st_dev == os.stat(tmp_path).st_dev:
        pytest.skip("/dev/shm and tmp_path are the same filesystem here")
    # What was used: package on /dev/shm (tmpfs), target under tmp_path.
    base = shm / f"kkmail-r12-{uuid.uuid4().hex}"
    base.mkdir()
    try:
        pkg_dir = _make_package(base)
        target = tmp_path / "restored-blobs"
        # Fake only the DB step; all file I/O is real across the two mounts.
        import unittest.mock as _mock  # local alias to keep monkeypatch simple

        with _mock.patch.object(
            backup_package.shutil, "which", lambda name: "/fake/pg_restore"
        ), _mock.patch.object(
            backup_package.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b""),
        ):
            result = _restore(pkg_dir, target)
        assert result.ok
        assert _published_files(target) == PAYLOADS
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --- Failure injection at the staging / publish stages -----------------------


@pytest.mark.parametrize("fail_on_call", [1, 2])
def test_publish_failure_keeps_staging_and_never_touches_db(
    tmp_path, monkeypatch, fail_on_call
):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(0).install(monkeypatch)

    real_publish = backup_package._publish_rename
    calls = {"n": 0}

    def flaky_publish(src, dst, root):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise OSError("injected publish failure")
        return real_publish(src, dst, root)

    monkeypatch.setattr(backup_package, "_publish_rename", flaky_publish)

    with pytest.raises(OSError, match="injected publish failure"):
        _restore(pkg_dir, target)

    # Publish happens before the DB: pg_restore must not have run at all.
    assert fake.calls == []
    log = _read_log(target)
    assert log["stage"] == "staging"
    assert log["operation_id"]
    # Whatever was already published stays; the rest stays in staging.
    published = _published_files(target)
    assert len(published) == fail_on_call - 1
    staging_dirs = list(target.glob(".restore_staging_*"))
    assert len(staging_dirs) == 1
    staged = {
        p.relative_to(staging_dirs[0]).as_posix()
        for p in staging_dirs[0].rglob("*")
        if p.is_file()
    }
    assert staged == set(PAYLOADS) - set(published)

    # Resume continues the same operation and completes it.
    monkeypatch.setattr(backup_package, "_publish_rename", real_publish)
    result = _resume(pkg_dir, target, log["operation_id"])
    assert result.ok
    assert len(fake.calls) == 1
    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "complete"
    assert not list(target.glob(".restore_staging_*"))


def test_extraction_failure_keeps_db_untouched_and_resume_recovers(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(0).install(monkeypatch)

    real_replace = Path.replace
    state = {"failed": False}

    def flaky_replace(self, dest):
        if not state["failed"] and ".restore-" in self.name:
            state["failed"] = True
            raise OSError("injected extraction failure")
        return real_replace(self, dest)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    with pytest.raises(OSError, match="injected extraction failure"):
        _restore(pkg_dir, target)

    assert state["failed"]
    assert fake.calls == []
    assert _read_log(target)["stage"] == "staging"
    assert _published_files(target) == {}

    monkeypatch.setattr(Path, "replace", real_replace)
    result = _resume(pkg_dir, target, _read_log(target)["operation_id"])
    assert result.ok
    assert _published_files(target) == PAYLOADS
    assert len(fake.calls) == 1


# --- DB failure: published blobs retained, strict resume ---------------------


def _db_failed_operation(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(1).install(monkeypatch)
    with pytest.raises(RuntimeError, match=r"pg_restore failed \(1\)"):
        _restore(pkg_dir, target)
    return pkg_dir, target, fake


def test_db_failure_retains_published_blobs_and_log_then_resume_succeeds(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _db_failed_operation(tmp_path, monkeypatch)

    assert _published_files(target) == PAYLOADS
    log = _read_log(target)
    assert log["stage"] == "db_failed"
    assert not list(target.glob(".restore_staging_*"))

    fake.returncode = 0
    result = _resume(pkg_dir, target, log["operation_id"])
    assert result.ok
    assert result.database_restored
    assert len(fake.calls) == 2  # the failed attempt plus the resume
    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "complete"

    # Resuming a completed operation is a no-op (no second pg_restore).
    again = _resume(pkg_dir, target, log["operation_id"])
    assert again.ok
    assert len(fake.calls) == 2


def test_resume_rejects_wrong_operation_id_and_mismatched_package(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _db_failed_operation(tmp_path, monkeypatch)
    log = _read_log(target)
    calls_before = len(fake.calls)

    with pytest.raises(RuntimeError, match="operation"):
        _resume(pkg_dir, target, "0" * 32)
    assert len(fake.calls) == calls_before
    assert _published_files(target) == PAYLOADS

    other_pkg = _make_package(
        tmp_path / "other", {"aa/bb/first.blob": b"different payload"}
    )
    with pytest.raises(RuntimeError, match="package digest"):
        _resume(other_pkg, target, log["operation_id"])
    assert len(fake.calls) == calls_before
    assert _published_files(target) == PAYLOADS


def test_resume_rejects_mismatched_database_identity_and_foreign_files(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _db_failed_operation(tmp_path, monkeypatch)
    log = _read_log(target)
    calls_before = len(fake.calls)

    with pytest.raises(RuntimeError, match="database identity"):
        resume_restore_backup_package(
            pkg_dir,
            operation_id=log["operation_id"],
            target_database_url="postgresql://restore:pw@127.0.0.1:5432/other_db",
            target_blobs_dir=target,
            source_database_url=SOURCE_URL,
            allow_stub=True,
        )
    assert len(fake.calls) == calls_before

    foreign = target / "zz" / "foreign.blob"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"not from the backup")
    with pytest.raises(RuntimeError, match="checksum|unexpected|foreign"):
        _resume(pkg_dir, target, log["operation_id"])
    assert len(fake.calls) == calls_before
    # The foreign file is never overwritten or removed by a refused resume.
    assert foreign.read_bytes() == b"not from the backup"
    assert _published_files(target)["aa/bb/first.blob"] == PAYLOADS["aa/bb/first.blob"]


def test_cleanup_requires_matching_operation_id(tmp_path, monkeypatch):
    pkg_dir, target, _fake = _db_failed_operation(tmp_path, monkeypatch)
    log = _read_log(target)

    with pytest.raises(RuntimeError, match="operation"):
        cleanup_restore_operation(target, operation_id="f" * 32)
    assert _published_files(target) == PAYLOADS  # nothing deleted

    removed = cleanup_restore_operation(target, operation_id=log["operation_id"])
    assert removed >= len(PAYLOADS)
    assert list(target.iterdir()) == []


def _manual_operation_at_stage(target: Path, stage: str) -> dict:
    """Build a target blob root whose operation log sits at ``stage``."""
    resolved = backup_package._resolve_restore_target(target)
    for rel, data in PAYLOADS.items():
        path = resolved / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    payload = backup_package._operation_log_payload(
        operation_id="c1eanup0peration000000000000001",
        package_digest="manual-digest",
        target_blobs=resolved,
        target_database_url=TARGET_URL,
        target_ident=None,
        stage=stage,
    )
    return backup_package._write_restore_operation_log(
        resolved, payload, stage=stage
    )


def test_cleanup_refuses_needs_verification_and_keeps_all_files(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "needs_verification")

    with pytest.raises(RuntimeError, match="needs_verification"):
        cleanup_restore_operation(target, operation_id=log["operation_id"])

    # Commit outcome is unknown: the blobs may be the live restored data.
    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "needs_verification"


def test_cleanup_refuses_blobs_published_and_keeps_all_files(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "blobs_published")

    with pytest.raises(RuntimeError, match="blobs_published"):
        cleanup_restore_operation(target, operation_id=log["operation_id"])

    # A log stuck at blobs_published is ambiguous (see the fresh-restore
    # path, which upgrades it to needs_verification): nothing is deleted.
    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "blobs_published"


def test_cleanup_rechecks_stage_under_lock_when_operation_completes(
    tmp_path, monkeypatch
):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "staging")

    real_lock = backup_package._backup_destination_lock

    @contextlib.contextmanager
    def completing_lock(dest):
        with real_lock(dest):
            # The operation completes while cleanup is acquiring the lock:
            # the log on disk at lock entry says ``complete`` even though
            # the pre-lock read saw the eligible ``staging`` stage.
            current = backup_package._read_restore_operation_log(dest)
            backup_package._write_restore_operation_log(
                dest, current, stage="complete"
            )
            yield

    monkeypatch.setattr(backup_package, "_backup_destination_lock", completing_lock)

    with pytest.raises(RuntimeError, match="complete"):
        cleanup_restore_operation(target, operation_id=log["operation_id"])

    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "complete"


def test_cleanup_staging_operation_still_removes_files(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "staging")

    removed = cleanup_restore_operation(target, operation_id=log["operation_id"])

    # ``staging`` provably precedes any DB commit, so cleanup stays allowed.
    assert removed >= len(PAYLOADS)
    assert list(target.iterdir()) == []


# --- Uncertain commit: needs_verification ------------------------------------


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


def test_post_commit_interruption_enters_needs_verification(tmp_path, monkeypatch):
    pkg_dir, target, fake = _needs_verification_operation(tmp_path, monkeypatch)

    assert _published_files(target) == PAYLOADS  # blobs are kept
    assert _read_log(target)["stage"] == "needs_verification"
    assert len(fake.calls) == 1

    # Resume must never auto-replay a restore whose commit is uncertain.
    with pytest.raises(RuntimeError, match="needs_verification"):
        _resume(pkg_dir, target, _read_log(target)["operation_id"])
    assert len(fake.calls) == 1

    # A fresh restore attempt also refuses (and deletes nothing).
    with pytest.raises(RuntimeError):
        _restore(pkg_dir, target)
    assert len(fake.calls) == 1
    assert _published_files(target) == PAYLOADS


def test_verify_operation_finalizes_nonempty_database(tmp_path, monkeypatch):
    pkg_dir, target, fake = _needs_verification_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]

    monkeypatch.setattr(
        backup_package,
        "_read_database_identity",
        lambda url: backup_package.DatabaseIdentity("999999", 42, "target"),
    )

    def assert_nonempty(_url):
        raise RuntimeError("refusing to restore into non-empty target database")

    monkeypatch.setattr(
        backup_package, "_assert_target_database_is_empty", assert_nonempty
    )

    result = verify_restore_operation(
        pkg_dir,
        operation_id=operation_id,
        target_database_url=TARGET_URL,
        target_blobs_dir=target,
        source_database_url=SOURCE_URL,
        allow_stub=True,
    )
    assert result.ok
    assert result.database_restored
    assert _read_log(target)["stage"] == "complete"
    assert len(fake.calls) == 1  # verification never replays pg_restore


def test_verify_operation_with_still_empty_database_allows_retry(
    tmp_path, monkeypatch
):
    pkg_dir, target, fake = _needs_verification_operation(tmp_path, monkeypatch)
    operation_id = _read_log(target)["operation_id"]

    monkeypatch.setattr(
        backup_package,
        "_read_database_identity",
        lambda url: backup_package.DatabaseIdentity("999999", 42, "target"),
    )
    monkeypatch.setattr(
        backup_package, "_assert_target_database_is_empty", lambda _url: None
    )

    result = verify_restore_operation(
        pkg_dir,
        operation_id=operation_id,
        target_database_url=TARGET_URL,
        target_blobs_dir=target,
        source_database_url=SOURCE_URL,
        allow_stub=True,
    )
    assert not result.ok
    assert result.stage == "blobs_published"
    assert _read_log(target)["stage"] == "blobs_published"

    # DB verified empty -> resume may retry the restore exactly once.
    resumed = _resume(pkg_dir, target, operation_id)
    assert resumed.ok
    assert len(fake.calls) == 2
    assert _read_log(target)["stage"] == "complete"


def test_pg_restore_timeout_enters_needs_verification(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    monkeypatch.setattr(
        backup_package.shutil,
        "which",
        lambda name: "/fake/pg_restore" if name == "pg_restore" else None,
    )

    def timed_out(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(backup_package.subprocess, "run", timed_out)

    with pytest.raises(RuntimeError, match="needs_verification"):
        _restore(pkg_dir, target)

    # Outcome unknown: blobs stay published, nothing is replayed or deleted.
    assert _published_files(target) == PAYLOADS
    assert _read_log(target)["stage"] == "needs_verification"


# --- Wrong key / invalid tar members still rejected ---------------------------


def test_restore_wrong_backup_key_publishes_nothing(tmp_path, monkeypatch):
    backup_key = os.urandom(32)
    monkeypatch.setenv(
        "MAIL_CORE_BACKUP_KEY", base64.b64encode(backup_key).decode()
    )
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    src_blobs = tmp_path / "src-blobs"
    (src_blobs / "aa").mkdir(parents=True)
    (src_blobs / "aa" / "x.blob").write_bytes(b"payload")
    pkg_dir = tmp_path / "sealed-package"
    create_backup_package(
        pkg_dir,
        include_blobs=True,
        database_url_override=SOURCE_URL,
        blobs_dir=src_blobs,
        encrypt=True,
        allow_dump_stub=True,
    )
    fake = _FakePgRestore(0).install(monkeypatch)
    target = tmp_path / "restored-blobs"

    with pytest.raises(Exception):
        restore_backup_package(
            pkg_dir,
            target_database_url=TARGET_URL,
            target_blobs_dir=target,
            keyring={1: os.urandom(32)},
            source_database_url=SOURCE_URL,
            allow_stub=True,
        )
    assert fake.calls == []
    assert not target.exists() or _published_files(target) == {}


def test_restore_invalid_tar_member_publishes_nothing(tmp_path, monkeypatch):
    pkg_dir = _make_package(tmp_path / "case")
    # Rebuild blobs.tar with a traversal member and fix the manifest checksums.
    evil_tar = tmp_path / "evil.tar"
    with tarfile.open(evil_tar, "w") as tar:
        info = tarfile.TarInfo("blobs/../../escape.blob")
        data = b"escaped"
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))
    shutil.copyfile(evil_tar, pkg_dir / "blobs.tar")
    man_path = pkg_dir / "MANIFEST.json"
    man = json.loads(man_path.read_text())
    blob = (pkg_dir / "blobs.tar").read_bytes()
    man["members"]["blobs.tar"] = {
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size": len(blob),
    }
    man_path.write_text(json.dumps(man, indent=2) + "\n")
    (pkg_dir / "MANIFEST.sha256").write_text(
        f"{hashlib.sha256(man_path.read_bytes()).hexdigest()}  MANIFEST.json\n"
    )

    fake = _FakePgRestore(0).install(monkeypatch)
    target = tmp_path / "restored-blobs"
    with pytest.raises(RuntimeError, match="traversal|unsafe|disallowed"):
        _restore(pkg_dir, target)
    assert fake.calls == []
    assert _published_files(target) == {}
    assert not (tmp_path / "escape.blob").exists()
    assert not (target.parent / "escape.blob").exists()
