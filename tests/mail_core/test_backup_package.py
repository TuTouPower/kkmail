from __future__ import annotations

import json
from pathlib import Path

from mail_core.backup.package import create_backup_package


def test_create_backup_package_writes_manifest(tmp_path, monkeypatch):
    blobs = tmp_path / "blobs"
    (blobs / "aa" / "bb").mkdir(parents=True)
    (blobs / "aa" / "bb" / "file.blob").write_bytes(b"cipher")

    out = tmp_path / "backup"
    # Use unreachable DSN so we exercise sql_stub path unless pg_dump works against real URL
    create_backup_package(
        out,
        include_blobs=True,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        blobs_dir=blobs,
    )
    assert (out / "postgres.dump").exists()
    assert (out / "blobs.tar").exists()
    man = json.loads((out / "MANIFEST.json").read_text())
    assert "postgres.dump" in man["members"]
    assert "blobs.tar" in man["members"]
    assert (out / "MANIFEST.sha256").read_text().split()[0]
    # password redacted
    assert "***" in man["database_url_redacted"]
