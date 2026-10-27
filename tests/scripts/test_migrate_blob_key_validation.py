"""A340: MAIL_CORE_BLOB_KEY_V1 must be validated before any migration writes."""

from __future__ import annotations

import base64

import pytest

from scripts import migrate_from_legacy_db
from scripts.migrate_from_legacy_db import _load_blob_keyring


def test_valid_32_byte_key_builds_keyring():
    raw = bytes(range(32))

    keyring = _load_blob_keyring(base64.b64encode(raw).decode())

    assert keyring.keys == {1: raw}
    assert keyring.active_version == 1


@pytest.mark.parametrize("bad", ["not!base64!", "aGVsbG8\x00d29ybGQ=", "####"])
def test_invalid_base64_is_rejected_with_operator_message(bad):
    with pytest.raises(ValueError, match="MAIL_CORE_BLOB_KEY_V1.*base64"):
        _load_blob_keyring(bad)


@pytest.mark.parametrize("size", [0, 16, 31, 33, 64])
def test_non_32_byte_key_is_rejected_with_operator_message(size):
    encoded = base64.b64encode(b"x" * size).decode()

    with pytest.raises(ValueError, match="MAIL_CORE_BLOB_KEY_V1.*32"):
        _load_blob_keyring(encoded)


def test_migrate_exits_before_touching_databases_on_invalid_blob_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEGACY_SECRET_KEY", "legacy-secret")
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_V1", base64.b64encode(b"short").decode())

    with pytest.raises(SystemExit) as exc_info:
        migrate_from_legacy_db.migrate(tmp_path / "missing.sqlite", "postgresql://unused")

    assert exc_info.value.code == 1
    assert "MAIL_CORE_BLOB_KEY_V1" in capsys.readouterr().err
