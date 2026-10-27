"""R4 adoption P10 (backup domain): A6/A15/A26/A44/A56/A67/A78/A79.

Each test targets one adoption item in
``docs/reviews/review_20261027_021416/adoption_decision.md`` and the
corresponding code in ``src/mail_core/backup/package.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
import sys
import tarfile
import types
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


# --- A26: resume must not replay pg_restore when DB emptiness is unknown ---


def test_a26_resume_unknown_empty_state_enters_needs_verification(
    tmp_path, monkeypatch
):
    pkg_dir = _make_package(tmp_path / "case")
    target = tmp_path / "restored-blobs"
    fake = _FakePgRestore(1).install(monkeypatch)
    with pytest.raises(RuntimeError, match=r"pg_restore failed \(1\)"):
        _restore(pkg_dir, target)
    operation_id = _read_log(target)["operation_id"]
    assert _read_log(target)["stage"] == "db_failed"
    assert len(fake.calls) == 1

    # Target DB is reachable (identity readable) but its empty state
    # cannot be determined (None): resume must fail closed instead of
    # replaying pg_restore on a maybe-committed database.
    fake.returncode = 0
    monkeypatch.setattr(
        backup_package,
        "_read_database_identity",
        lambda url: backup_package.DatabaseIdentity("999999", 42, "target"),
    )
    monkeypatch.setattr(backup_package, "_database_is_empty", lambda _url: None)

    with pytest.raises(RuntimeError, match="could not be determined"):
        _resume(pkg_dir, target, operation_id)

    assert len(fake.calls) == 1  # pg_restore was NOT replayed
    assert _read_log(target)["stage"] == "needs_verification"
    assert _published_files(target) == PAYLOADS


# --- A15: cleanup must only remove this operation's own files --------------


def _manual_operation_at_stage(target: Path, stage: str) -> dict:
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


def test_a15_cleanup_refuses_foreign_file_and_deletes_nothing(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "staging")
    foreign = target / "zz" / "keep.txt"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_bytes(b"not part of the restore operation")

    with pytest.raises(RuntimeError, match="foreign"):
        cleanup_restore_operation(target, operation_id=log["operation_id"])

    # Nothing at all was deleted: published blobs, log and foreign file.
    assert _published_files(target) == {**PAYLOADS, "zz/keep.txt": b"not part of the restore operation"}
    assert _read_log(target)["stage"] == "staging"


def test_a15_cleanup_refuses_other_operations_staging_dir(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "staging")
    other_staging = target / ".restore_staging_otheroperation00000000001"
    other_staging.mkdir(parents=True)
    (other_staging / "partial.blob").write_bytes(b"someone else's staging")

    with pytest.raises(RuntimeError, match="foreign"):
        cleanup_restore_operation(target, operation_id=log["operation_id"])

    assert _published_files(target) == PAYLOADS
    assert (other_staging / "partial.blob").read_bytes() == b"someone else's staging"
    assert _read_log(target)["stage"] == "staging"


def test_a15_cleanup_removes_only_own_artifacts_including_staging(tmp_path):
    target = tmp_path / "restored-blobs"
    log = _manual_operation_at_stage(target, "staging")
    own_staging = target / f".restore_staging_{log['operation_id']}"
    own_staging.mkdir(parents=True)
    (own_staging / "aa" / "bb").mkdir(parents=True)
    (own_staging / "aa" / "bb" / "first.blob").write_bytes(PAYLOADS["aa/bb/first.blob"])

    removed = cleanup_restore_operation(target, operation_id=log["operation_id"])

    assert removed >= len(PAYLOADS)
    assert list(target.iterdir()) == []


# --- A67: _verify_restored_state must not trust DB storage_path ------------


class _FakeCursor:
    def __init__(self, storage_paths):
        self._storage_paths = storage_paths
        self._sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql):
        self._sql = sql

    def fetchall(self):
        if "information_schema.tables" in self._sql:
            return [(t,) for t in sorted(backup_package._RESTORE_REQUIRED_TABLES)]
        if "storage_path" in self._sql:
            return [(p,) for p in self._storage_paths]
        return []

    def fetchone(self):
        return (0,)


class _FakeConn:
    def __init__(self, storage_paths):
        self._storage_paths = storage_paths

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return _FakeCursor(self._storage_paths)


def _install_fake_psycopg(monkeypatch, storage_paths):
    fake = types.SimpleNamespace(
        connect=lambda dsn, **kwargs: _FakeConn(storage_paths)
    )
    monkeypatch.setitem(sys.modules, "psycopg", fake)


@pytest.mark.parametrize(
    "evil_path_kind", ["dotdot", "absolute"], ids=["dotdot", "absolute"]
)
def test_a67_verify_restored_state_rejects_escaping_storage_path(
    tmp_path, monkeypatch, evil_path_kind
):
    target = tmp_path / "restored-blobs"
    target.mkdir()
    outside = tmp_path / "escape.blob"
    outside.write_bytes(b"outside the blob root")
    evil = "../escape.blob" if evil_path_kind == "dotdot" else str(outside)
    _install_fake_psycopg(monkeypatch, [evil])

    with pytest.raises(RuntimeError, match="storage_path|escapes"):
        backup_package._verify_restored_state(
            TARGET_URL, target, {}, db_reachable=True
        )


def test_a67_verify_restored_state_accepts_in_root_storage_path(
    tmp_path, monkeypatch
):
    target = tmp_path / "restored-blobs"
    blob = target / "aa" / "bb" / "first.blob"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"plain blob content")
    inventory = {"aa/bb/first.blob": hashlib.sha256(b"plain blob content").hexdigest()}
    _install_fake_psycopg(monkeypatch, ["aa/bb/first.blob"])

    # In-root path: verification completes without raising.
    backup_package._verify_restored_state(
        TARGET_URL, target, inventory, db_reachable=True
    )


# --- A44: create must write source_database_identity into the manifest -----


def test_a44_manifest_records_source_database_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        backup_package,
        "_read_database_identity",
        lambda url: backup_package.DatabaseIdentity("424242", 1234, "source"),
    )
    pkg_dir = _make_package(tmp_path / "case")

    man = json.loads((pkg_dir / "MANIFEST.json").read_text())
    assert man["source_database_identity"] == {
        "system_identifier": "424242",
        "database_oid": 1234,
        "database_name": "source",
    }


def test_a44_manifest_identity_null_when_source_unreachable(tmp_path):
    # No identity reader patched: the source DB is unreachable in unit
    # mode, so the manifest records null and package creation still works.
    pkg_dir = _make_package(tmp_path / "case")

    man = json.loads((pkg_dir / "MANIFEST.json").read_text())
    assert man["source_database_identity"] is None
    assert (pkg_dir / "postgres.dump").is_file()


def test_a44_restore_refuses_when_manifest_identity_matches_target(
    tmp_path, monkeypatch
):
    shared = backup_package.DatabaseIdentity("777777", 42, "target")

    def selective_identity(url):
        if "target" in url:
            return shared
        if "source" in url:
            # At backup-creation time the source identity is read and
            # recorded; at restore time the source is offline, so the
            # manifest copy is the only source identity available.
            if selective_identity.phase == "create":
                return shared
            raise RuntimeError("source database unreachable at restore time")
        raise RuntimeError("unexpected url")

    selective_identity.phase = "create"
    monkeypatch.setattr(
        backup_package, "_read_database_identity", selective_identity
    )
    pkg_dir = _make_package(tmp_path / "case")
    man = json.loads((pkg_dir / "MANIFEST.json").read_text())
    assert man["source_database_identity"]["system_identifier"] == "777777"

    selective_identity.phase = "restore"
    # Target DB is reachable and empty (its identity reads fine above);
    # only the source is offline at restore time.
    monkeypatch.setattr(
        backup_package, "_assert_target_database_is_empty", lambda _url: None
    )
    fake = _FakePgRestore(0).install(monkeypatch)
    target = tmp_path / "restored-blobs"
    with pytest.raises(RuntimeError, match="refusing to restore onto source database"):
        _restore(pkg_dir, target)
    assert fake.calls == []
