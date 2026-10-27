from __future__ import annotations

import base64
import json
import os

from mail_core.backup import package as backup_package
from mail_core.backup.package import create_backup_package

_SECRET_URL = "postgresql://alice_topology:s3cret@db.internal.example:6543/kkmail_prod"


def _assert_manifest_redacted(manifest_text: str, blob_root_path) -> dict:
    man = json.loads(manifest_text)
    # Absolute blob path and deployment topology must not leave with the package.
    assert str(blob_root_path) not in manifest_text
    assert "alice_topology" not in manifest_text
    assert "db.internal.example" not in manifest_text
    assert "6543" not in manifest_text
    assert "s3cret" not in manifest_text
    # Manifest records only the logical blob name, not an absolute path.
    assert man["blob_root"] == "blobs"
    # Database identifier keeps only the db name plus a fingerprint.
    redacted = man["database_url_redacted"]
    assert "kkmail_prod" in redacted
    assert "***" in redacted
    return man


def test_plain_manifest_does_not_leak_blob_path_or_db_topology(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    blobs = tmp_path / "secret-topology" / "blobs-store"
    (blobs / "aa").mkdir(parents=True)
    (blobs / "aa" / "file.blob").write_bytes(b"cipher")

    out = tmp_path / "backup"
    create_backup_package(
        out,
        include_blobs=True,
        database_url_override=_SECRET_URL,
        blobs_dir=blobs,
        encrypt=False,
        allow_dump_stub=True,
    )

    _assert_manifest_redacted((out / "MANIFEST.json").read_text(), blobs)
    # The stub dump is also part of the package and must not leak topology.
    dump_text = (out / "postgres.dump").read_text()
    assert "alice_topology" not in dump_text
    assert "db.internal.example" not in dump_text
    assert "s3cret" not in dump_text


def test_sealed_manifest_does_not_leak_blob_path_or_db_topology(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MAIL_CORE_BACKUP_KEY", base64.b64encode(os.urandom(32)).decode()
    )
    monkeypatch.delenv("MAIL_CORE_BACKUP_KEYS", raising=False)
    blobs = tmp_path / "secret-topology" / "blobs-store"
    blobs.mkdir(parents=True)

    out = tmp_path / "sealed-backup"
    create_backup_package(
        out,
        include_blobs=False,
        database_url_override=_SECRET_URL,
        blobs_dir=blobs,
        encrypt=True,
        allow_dump_stub=True,
    )

    _assert_manifest_redacted((out / "MANIFEST.json").read_text(), blobs)


def test_redacted_url_fingerprint_is_stable_and_distinguishing():
    first = backup_package._redact_url(_SECRET_URL)
    again = backup_package._redact_url(_SECRET_URL)
    other = backup_package._redact_url(
        "postgresql://alice_topology:s3cret@other.internal.example:6543/kkmail_prod"
    )
    assert first == again
    assert first != other
    for value in (first, other):
        assert "alice_topology" not in value
        assert "internal.example" not in value
        assert "s3cret" not in value
        assert "kkmail_prod" in value
