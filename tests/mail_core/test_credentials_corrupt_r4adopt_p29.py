"""A374: DbCredentialStore.get_secret decode failures.

A corrupted / wrongly-keyed row used to escape get_secret as a raw
cryptography InvalidTag (or UnicodeDecodeError for non-UTF-8
plaintext), bypassing every caller that handles a missing secret via
KeyError. Pinned: both failure modes surface as CredentialCorruptError,
a KeyError subclass, so existing KeyError handling applies and callers
may also catch the specific type.
"""

from __future__ import annotations

import pytest

import uuid as _uuid
from types import SimpleNamespace as _SimpleNamespace

from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM

from mail_core.accounts.credentials import CredentialCorruptError, DbCredentialStore
from mail_core.blobs.crypto import Keyring as _Keyring


class _FakeSession:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, _model, _ref):
        return self._row


def _db_store_for_row(row) -> DbCredentialStore:
    ring = _Keyring(keys={1: b"\x01" * 32}, active_version=1)
    return DbCredentialStore(keyring=ring, session_factory=lambda: _FakeSession(row))


def test_get_secret_normalizes_invalid_tag_to_credential_corrupt_error():
    row = _SimpleNamespace(key_version=1, nonce=b"\x00" * 12, ciphertext=b"not-a-valid-ciphertext")
    store = _db_store_for_row(row)
    with pytest.raises(CredentialCorruptError):
        store.get_secret("account:corrupt")
    # ... and as a KeyError, so missing-secret handling catches it.
    with pytest.raises(KeyError):
        store.get_secret("account:corrupt")


def test_get_secret_normalizes_non_utf8_plaintext_to_credential_corrupt_error():
    ref = f"account:{_uuid.uuid4().hex}"
    store = _db_store_for_row(None)
    nonce = b"\x02" * 12
    ciphertext = _AESGCM(store._key(1)).encrypt(nonce, b"\xff\xfe not utf-8", ref.encode())
    store = _db_store_for_row(_SimpleNamespace(key_version=1, nonce=nonce, ciphertext=ciphertext))
    with pytest.raises(CredentialCorruptError):
        store.get_secret(ref)


def test_get_secret_missing_row_still_raises_plain_keyerror():
    store = _db_store_for_row(None)
    with pytest.raises(KeyError) as excinfo:
        store.get_secret("account:missing")
    assert not isinstance(excinfo.value, CredentialCorruptError)
