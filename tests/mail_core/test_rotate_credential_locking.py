"""R03 regression: key rotation must not overwrite concurrently refreshed secrets.

_rewrap_credential_secrets used to snapshot CredentialSecret rows without
any lock and later write back re-encrypted *old* plaintext. A token refresh
(or password edit) committing between the snapshot and the write-back was
silently reverted to the old secret. Rotation now joins the credential_edit
lock protocol: per-ref advisory lock (credential_lock_key) + FOR UPDATE
re-read with populate_existing, in ref order.
"""

from __future__ import annotations

import os
import threading
import time

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.blobs.crypto import Keyring
from mail_core.blobs.rotate import _cred_key, _rewrap_credential_secrets
from mail_core.mail.storage.models import CredentialSecret

_KEYRING = Keyring(keys={1: os.urandom(32), 2: os.urandom(32)}, active_version=2)
_REF = "acct-r03"


def _encrypt(keyring: Keyring, version: int, ref: str, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ct = AESGCM(_cred_key(keyring, version)).encrypt(nonce, plaintext, ref.encode())
    return nonce, ct


def _decrypt_row(session: Session, keyring: Keyring, ref: str) -> bytes:
    row = session.scalars(
        select(CredentialSecret)
        .where(CredentialSecret.ref == ref)
        .execution_options(populate_existing=True)
    ).first()
    assert row is not None
    return AESGCM(_cred_key(keyring, row.key_version)).decrypt(
        row.nonce, row.ciphertext, ref.encode()
    )


def test_rewrap_roundtrip_sqlite(tmp_path):
    """Non-gated smoke: a v1 row is rewrapped to v2 and still decrypts."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    CredentialSecret.__table__.create(engine)
    nonce, ct = _encrypt(_KEYRING, 1, _REF, b'{"refresh_token": "tok"}')
    with Session(engine) as session:
        session.add(CredentialSecret(ref=_REF, key_version=1, nonce=nonce, ciphertext=ct))
        session.commit()
    with Session(engine) as session:
        assert _rewrap_credential_secrets(session, _KEYRING, 2) == 1
        session.commit()
    with Session(engine) as session:
        assert _decrypt_row(session, _KEYRING, _REF) == b'{"refresh_token": "tok"}'


DATABASE_URL = os.environ.get("MAIL_CORE_DATABASE_URL")
pg_only = pytest.mark.skipif(not DATABASE_URL, reason="MAIL_CORE_DATABASE_URL not set")


@pg_only
def test_rotation_does_not_overwrite_concurrent_refresh():
    from sqlalchemy import func

    from mail_core.accounts.credentials import credential_lock_key
    from mail_core.db.session import get_session_factory

    SessionFactory = get_session_factory()
    old_pt = b'{"refresh_token": "old-token"}'
    new_pt = b'{"refresh_token": "new-token"}'

    with SessionFactory() as session:
        existing = session.scalars(
            select(CredentialSecret).where(CredentialSecret.ref == _REF)
        ).first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        nonce, ct = _encrypt(_KEYRING, 1, _REF, old_pt)
        session.add(CredentialSecret(ref=_REF, key_version=1, nonce=nonce, ciphertext=ct))
        session.commit()

    edit_holding = threading.Event()
    edit_release = threading.Event()
    errors: list[BaseException] = []

    def simulated_credential_edit():
        """Mimic credential_edit: advisory lock + row lock, rewrite, commit."""
        try:
            with SessionFactory() as session:
                session.execute(
                    select(func.pg_advisory_xact_lock(credential_lock_key(_REF)))
                )
                row = session.scalars(
                    select(CredentialSecret)
                    .where(CredentialSecret.ref == _REF)
                    .with_for_update()
                ).first()
                nonce, ct = _encrypt(_KEYRING, 1, _REF, new_pt)
                row.nonce, row.ciphertext = nonce, ct
                session.flush()
                edit_holding.set()
                assert edit_release.wait(timeout=30)
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    def rotation():
        try:
            with SessionFactory() as session:
                _rewrap_credential_secrets(session, _KEYRING, 2)
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    t_edit = threading.Thread(target=simulated_credential_edit)
    t_edit.start()
    assert edit_holding.wait(timeout=30)
    t_rotate = threading.Thread(target=rotation)
    t_rotate.start()
    # Let rotation reach its lock/read point, then let the edit commit.
    time.sleep(0.5)
    edit_release.set()
    t_edit.join(timeout=30)
    t_rotate.join(timeout=30)
    assert not t_edit.is_alive() and not t_rotate.is_alive()
    assert not errors, f"concurrent rotation raised: {errors!r}"

    with SessionFactory() as session:
        assert _decrypt_row(session, _KEYRING, _REF) == new_pt
        row = session.scalars(
            select(CredentialSecret).where(CredentialSecret.ref == _REF)
        ).first()
        assert row.key_version == 2
        session.delete(row)
        session.commit()
