"""Resolve opaque credential_ref values. Never log secrets."""

from __future__ import annotations

import copy
import json
import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Protocol


class CredentialStore(Protocol):
    def get_secret(self, credential_ref: str) -> str: ...

    def put_secret(self, credential_ref: str, secret: str) -> None: ...

    def delete_secret(self, credential_ref: str) -> None: ...


class ReadOnlyCredentialRef(ValueError):
    """The ref points at operator-managed configuration that the app must not rewrite."""


class EnvCredentialStore:
    """Refs shaped as ``env:VAR_NAME`` read from the process environment.

    Read-only: env refs are operator-managed. Writing (e.g. OAuth refresh-token
    rotation) raises ``ReadOnlyCredentialRef`` instead of silently mutating
    ``os.environ`` (which would be lost on restart and invisible to other processes).
    Use the default database-backed store for credentials the app must update.
    """

    def get_secret(self, credential_ref: str) -> str:
        if not credential_ref.startswith("env:"):
            raise ValueError(f"unsupported credential_ref scheme: {credential_ref!r}")
        var = credential_ref[4:]
        val = os.environ.get(var)
        if val is None:
            raise KeyError(f"environment variable {var!r} missing for credential_ref")
        return val

    def put_secret(self, credential_ref: str, secret: str) -> None:
        raise ReadOnlyCredentialRef(f"credential_ref {credential_ref!r} is read-only (env)")

    def delete_secret(self, credential_ref: str) -> None:
        raise ReadOnlyCredentialRef(f"credential_ref {credential_ref!r} is read-only (env)")


_CRED_HKDF_INFO = b"kkmail/credential-store/v1"


class DbCredentialStore:
    """Durable store in ``credential_secrets``; AES-256-GCM with a key derived from the blob keyring.

    Shared by API and worker processes. Each call uses its own short transaction.
    """

    def __init__(self, *, keyring=None, session_factory=None) -> None:  # noqa: ANN001 - lazy types
        self._keyring = keyring
        self._session_factory = session_factory

    def _ring(self):
        if self._keyring is None:
            from mail_core.blobs.crypto import load_keyring_from_env

            self._keyring = load_keyring_from_env()
        return self._keyring

    def _sessions(self):
        if self._session_factory is None:
            from mail_core.db.session import get_session_factory

            self._session_factory = get_session_factory()
        return self._session_factory

    def _key(self, version: int) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_CRED_HKDF_INFO).derive(
            self._ring().get(version)
        )

    def get_secret(self, credential_ref: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from mail_core.mail.storage.models import CredentialSecret

        with self._sessions()() as session:
            row = session.get(CredentialSecret, credential_ref)
            if row is None:
                raise KeyError(f"unknown credential_ref {credential_ref!r}")
            pt = AESGCM(self._key(row.key_version)).decrypt(row.nonce, row.ciphertext, credential_ref.encode())
            return pt.decode()

    def put_secret(self, credential_ref: str, secret: str, *, session: Any = None) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from mail_core.mail.storage.models import CredentialSecret

        version = self._ring().active_version
        nonce = os.urandom(12)
        ct = AESGCM(self._key(version)).encrypt(nonce, secret.encode(), credential_ref.encode())
        if session is not None:
            row = session.get(CredentialSecret, credential_ref)
            if row is None:
                row = CredentialSecret(ref=credential_ref, key_version=version, nonce=nonce, ciphertext=ct)
                session.add(row)
            else:
                row.key_version, row.nonce, row.ciphertext = version, nonce, ct
            session.flush()
            return

        with self._sessions()() as s:
            row = s.get(CredentialSecret, credential_ref)
            if row is None:
                row = CredentialSecret(ref=credential_ref, key_version=version, nonce=nonce, ciphertext=ct)
                s.add(row)
            else:
                row.key_version, row.nonce, row.ciphertext = version, nonce, ct
            s.commit()

    def delete_secret(self, credential_ref: str, *, session: Any = None) -> None:
        from mail_core.mail.storage.models import CredentialSecret

        if session is not None:
            row = session.get(CredentialSecret, credential_ref)
            if row is not None:
                session.delete(row)
                session.flush()
            return

        with self._sessions()() as s:
            row = s.get(CredentialSecret, credential_ref)
            if row is not None:
                s.delete(row)
                s.commit()


class DictCredentialStore:
    """In-memory store for unit/integration tests."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = dict(mapping or {})

    def put(self, credential_ref: str, secret: str) -> None:
        self.put_secret(credential_ref, secret)

    def put_secret(self, credential_ref: str, secret: str, *, session: Any = None) -> None:
        self._mapping[credential_ref] = secret

    def get_secret(self, credential_ref: str) -> str:
        try:
            return self._mapping[credential_ref]
        except KeyError as exc:
            raise KeyError(f"unknown credential_ref {credential_ref!r}") from exc

    def delete_secret(self, credential_ref: str, *, session: Any = None) -> None:
        self._mapping.pop(credential_ref, None)


class KeyringCredentialStore:
    """OS keyring via the optional ``keyring`` package (no in-memory fallback).

    Refs: ``keyring:service/user`` or bare ``keyring:name`` (service=kkmail).
    """

    def __init__(self, *, service: str = "kkmail") -> None:
        self.service = service

    @staticmethod
    def _backend():
        try:
            import keyring  # type: ignore
        except ImportError as exc:
            raise RuntimeError("keyring: credential refs need the 'keyring' package installed") from exc
        return keyring

    def _parse(self, credential_ref: str) -> tuple[str, str]:
        if not credential_ref.startswith("keyring:"):
            raise ValueError(f"unsupported credential_ref scheme: {credential_ref!r}")
        rest = credential_ref[len("keyring:") :]
        if "/" in rest:
            svc, user = rest.split("/", 1)
            return svc or self.service, user
        return self.service, rest

    def get_secret(self, credential_ref: str) -> str:
        svc, user = self._parse(credential_ref)
        val = self._backend().get_password(svc, user)
        if val is None:
            raise KeyError(f"keyring secret missing for {credential_ref!r}")
        return val

    def put_secret(self, credential_ref: str, secret: str) -> None:
        svc, user = self._parse(credential_ref)
        self._backend().set_password(svc, user, secret)

    def delete_secret(self, credential_ref: str) -> None:
        svc, user = self._parse(credential_ref)
        self._backend().delete_password(svc, user)


class CompositeCredentialStore:
    """Dispatch by ref scheme: ``env:`` (read-only) / ``keyring:`` / everything else → database."""

    def __init__(
        self,
        *,
        env: EnvCredentialStore | None = None,
        keyring: KeyringCredentialStore | None = None,
        db: CredentialStore | None = None,
    ) -> None:
        self.env = env or EnvCredentialStore()
        self.keyring = keyring or KeyringCredentialStore()
        self.db = db or DbCredentialStore()

    def _pick(self, credential_ref: str) -> CredentialStore:
        if credential_ref.startswith("env:"):
            return self.env
        if credential_ref.startswith("keyring:"):
            return self.keyring
        return self.db

    def get_secret(self, credential_ref: str) -> str:
        return self._pick(credential_ref).get_secret(credential_ref)

    def put_secret(self, credential_ref: str, secret: str, *, session: Any = None) -> None:
        target = self._pick(credential_ref)
        try:
            target.put_secret(credential_ref, secret, session=session)
        except TypeError:
            target.put_secret(credential_ref, secret)

    def delete_secret(self, credential_ref: str, *, session: Any = None) -> None:
        target = self._pick(credential_ref)
        try:
            target.delete_secret(credential_ref, session=session)
        except TypeError:
            target.delete_secret(credential_ref)


def load_json_secret(store: CredentialStore, credential_ref: str) -> dict[str, Any]:
    raw = store.get_secret(credential_ref)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("credential secret must be a JSON object")
    return data


def save_json_secret(
    store: CredentialStore,
    credential_ref: str,
    data: dict[str, Any],
    *,
    session: Any = None,
) -> None:
    try:
        store.put_secret(credential_ref, json.dumps(data), session=session)
    except TypeError:
        store.put_secret(credential_ref, json.dumps(data))


_default_store: CredentialStore | None = None
_non_db_lock = threading.RLock()


def get_credential_store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = CompositeCredentialStore()
    return _default_store


def set_credential_store(store: CredentialStore | None) -> None:
    global _default_store
    _default_store = store


@contextmanager
def credential_edit(store: CredentialStore, ref: str, *, session=None, allow_readonly: bool = False, readonly_cache: dict[str, Any] | None = None):
    """Serialize edits and token rotation on the same durable credential row."""
    target = store._pick(ref) if isinstance(store, CompositeCredentialStore) else store
    if isinstance(target, DbCredentialStore):
        from sqlalchemy import func, select
        from mail_core.mail.storage.models import CredentialSecret
        owned = session is None
        current = session if session is not None else target._sessions()()
        try:
            # A row lock alone cannot serialize creation of an absent OAuth code claim.
            lock_key = int.from_bytes(hashlib.sha256(ref.encode()).digest()[:8], 'big', signed=True)
            current.execute(select(func.pg_advisory_xact_lock(lock_key)))
            row = current.scalar(
                select(CredentialSecret)
                .where(CredentialSecret.ref == ref)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            data = json.loads(AESGCM(target._key(row.key_version)).decrypt(row.nonce, row.ciphertext, ref.encode()).decode()) if row else {}
            if not isinstance(data, dict):
                raise ValueError('credential secret must be a JSON object')
            original = copy.deepcopy(data)
            yield data
            if data != original:
                save_json_secret(target, ref, data, session=current)
            if owned:
                current.commit()
        except BaseException:
            if owned:
                current.rollback()
            raise
        finally:
            if owned:
                current.close()
    else:
        # Non-DB stores are used for operator-managed refs and isolated tests.
        with _non_db_lock:
            try:
                data = load_json_secret(store, ref)
            except KeyError:
                data = {}
            if isinstance(target, EnvCredentialStore) and readonly_cache:
                data = dict(readonly_cache)
            original = copy.deepcopy(data)
            yield data
            if data != original:
                try:
                    save_json_secret(store, ref, data, session=session)
                except ReadOnlyCredentialRef:
                    if not allow_readonly:
                        raise
                    logging.getLogger(__name__).warning('refreshed OAuth token cannot be persisted to an operator-managed read-only credential')
