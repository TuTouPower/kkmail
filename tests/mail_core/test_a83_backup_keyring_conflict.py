"""A83: MAIL_CORE_BACKUP_KEY conflicting with MAIL_CORE_BACKUP_KEYS v1 must
error (like the blob keyring) instead of being silently ignored via setdefault."""
import base64
import json
import os

import pytest

from mail_core.backup.crypto import BackupCryptoError, load_backup_keyring


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_conflicting_single_key_raises():
    key_a = os.urandom(32)
    key_b = os.urandom(32)
    env = {
        "MAIL_CORE_BACKUP_KEYS": json.dumps({"1": _b64(key_a)}),
        "MAIL_CORE_BACKUP_KEY": _b64(key_b),
    }
    with pytest.raises(BackupCryptoError, match="MAIL_CORE_BACKUP_KEY"):
        load_backup_keyring(env)


def test_identical_single_key_is_accepted():
    key = os.urandom(32)
    env = {
        "MAIL_CORE_BACKUP_KEYS": json.dumps({"1": _b64(key)}),
        "MAIL_CORE_BACKUP_KEY": _b64(key),
    }
    assert load_backup_keyring(env) == {1: key}


def test_single_key_fills_missing_v1():
    key_a = os.urandom(32)
    key_b = os.urandom(32)
    env = {
        "MAIL_CORE_BACKUP_KEYS": json.dumps({"2": _b64(key_a)}),
        "MAIL_CORE_BACKUP_KEY": _b64(key_b),
    }
    assert load_backup_keyring(env) == {2: key_a, 1: key_b}
