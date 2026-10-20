"""DbCredentialStore: durable, encrypted at rest, shared across processes."""

from __future__ import annotations

import base64
import os
import uuid

import pytest
from cryptography.exceptions import InvalidTag

from mail_core.accounts import CompositeCredentialStore, DbCredentialStore
from mail_core.blobs.crypto import Keyring
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import CredentialSecret

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _ring(version: int = 1) -> Keyring:
    return Keyring(keys={1: b"\x01" * 32, 2: b"\x02" * 32}, active_version=version)


def test_roundtrip_is_encrypted_and_durable():
    ref = f"account:{uuid.uuid4().hex}@ex.com"
    secret = '{"refresh_token": "rt-very-secret"}'
    DbCredentialStore(keyring=_ring()).put_secret(ref, secret)

    # A fresh store instance (≈ another process) reads it back.
    assert DbCredentialStore(keyring=_ring()).get_secret(ref) == secret
    with get_session_factory()() as session:
        row = session.get(CredentialSecret, ref)
        assert row.key_version == 1
        assert b"rt-very-secret" not in row.ciphertext

    # Rotation: re-put under v2; old version still decryptable via keyring.
    DbCredentialStore(keyring=_ring(2)).put_secret(ref, secret)
    assert DbCredentialStore(keyring=_ring(1)).get_secret(ref) == secret

    DbCredentialStore(keyring=_ring()).delete_secret(ref)
    with pytest.raises(KeyError):
        DbCredentialStore(keyring=_ring()).get_secret(ref)


def test_ciphertext_bound_to_ref():
    a, b = f"account:a-{uuid.uuid4().hex}", f"account:b-{uuid.uuid4().hex}"
    store = DbCredentialStore(keyring=_ring())
    store.put_secret(a, "alpha")
    store.put_secret(b, "beta")
    with get_session_factory()() as session:
        ra, rb = session.get(CredentialSecret, a), session.get(CredentialSecret, b)
        rb.nonce, rb.ciphertext = ra.nonce, ra.ciphertext  # swap a's ciphertext under b
        session.commit()
    with pytest.raises(InvalidTag):
        store.get_secret(b)


def test_composite_routes_plain_refs_to_db(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_V1", base64.b64encode(b"\x03" * 32).decode())
    store = CompositeCredentialStore()
    ref = f"account:{uuid.uuid4().hex}"
    store.put_secret(ref, "x")
    assert DbCredentialStore().get_secret(ref) == "x"
    store.delete_secret(ref)
