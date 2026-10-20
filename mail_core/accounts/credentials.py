"""Resolve opaque credential_ref values. Never log secrets."""

from __future__ import annotations

import os
from typing import Protocol


class CredentialStore(Protocol):
    def get_secret(self, credential_ref: str) -> str: ...


class EnvCredentialStore:
    """Refs shaped as ``env:VAR_NAME`` read from the process environment."""

    def get_secret(self, credential_ref: str) -> str:
        if not credential_ref.startswith("env:"):
            raise ValueError(f"unsupported credential_ref scheme: {credential_ref!r}")
        var = credential_ref[4:]
        val = os.environ.get(var)
        if val is None:
            raise KeyError(f"environment variable {var!r} missing for credential_ref")
        return val


class DictCredentialStore:
    """In-memory store for unit/integration tests."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = dict(mapping or {})

    def put(self, credential_ref: str, secret: str) -> None:
        self._mapping[credential_ref] = secret

    def get_secret(self, credential_ref: str) -> str:
        try:
            return self._mapping[credential_ref]
        except KeyError as exc:
            raise KeyError(f"unknown credential_ref {credential_ref!r}") from exc


_default_store: CredentialStore | None = None


def get_credential_store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = EnvCredentialStore()
    return _default_store


def set_credential_store(store: CredentialStore | None) -> None:
    global _default_store
    _default_store = store
