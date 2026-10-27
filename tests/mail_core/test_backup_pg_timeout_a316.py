from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mail_core.backup import package as pkg


def _fake_dump_run(seen: dict):
    def fake_run(argv, check=True, capture_output=True, env=None, timeout=None, **kwargs):
        seen["timeout"] = timeout
        Path(argv[argv.index("--file") + 1]).write_bytes(b"PGDUMP")
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    return fake_run


@pytest.mark.parametrize("raw", ["not-a-number", "", "0", "-5", "nan", "inf"])
def test_pg_dump_malformed_timeout_falls_back_to_default(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("MAIL_CORE_PG_DUMP_TIMEOUT", raw)
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/fake/pg_dump")
    seen: dict = {}
    monkeypatch.setattr(pkg.subprocess, "run", _fake_dump_run(seen))

    result = pkg._pg_dump_to(
        tmp_path / "postgres.dump",
        "postgresql://u:p@127.0.0.1:5432/db",
    )

    assert result == "custom"
    assert seen["timeout"] == 300.0


def test_pg_dump_valid_timeout_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_PG_DUMP_TIMEOUT", "12.5")
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/fake/pg_dump")
    seen: dict = {}
    monkeypatch.setattr(pkg.subprocess, "run", _fake_dump_run(seen))

    assert (
        pkg._pg_dump_to(tmp_path / "postgres.dump", "postgresql://u:p@127.0.0.1:5432/db")
        == "custom"
    )
    assert seen["timeout"] == 12.5


@pytest.mark.parametrize("raw", ["bogus", "0", "-1", "nan"])
def test_pg_restore_malformed_timeout_falls_back_to_default(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("MAIL_CORE_PG_RESTORE_TIMEOUT", raw)
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/fake/pg_restore")
    seen: dict = {}

    def fake_run(argv, capture_output=True, env=None, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pkg.subprocess, "run", fake_run)
    dump_file = tmp_path / "postgres.dump"
    dump_file.write_bytes(b"PGDUMP")

    # Must not raise ValueError from float() parsing.
    pkg._run_pg_restore(dump_file, "postgresql://u:p@127.0.0.1:5432/db")
    assert seen["timeout"] == 300.0


def test_pg_restore_valid_timeout_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_PG_RESTORE_TIMEOUT", "45")
    monkeypatch.setattr(pkg.shutil, "which", lambda name: "/fake/pg_restore")
    seen: dict = {}

    def fake_run(argv, capture_output=True, env=None, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pkg.subprocess, "run", fake_run)
    dump_file = tmp_path / "postgres.dump"
    dump_file.write_bytes(b"PGDUMP")

    pkg._run_pg_restore(dump_file, "postgresql://u:p@127.0.0.1:5432/db")
    assert seen["timeout"] == 45.0
