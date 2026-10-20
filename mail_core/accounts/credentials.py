"""Resolve opaque credential_ref values. Never log secrets."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol


class CredentialStore(Protocol):
    def get_secret(self, credential_ref: str) -> str: ...

    def put_secret(self, credential_ref: str, secret: str) -> None: ...


class EnvCredentialStore:
    """Refs shaped as ``env:VAR_NAME`` read from the process environment.

    ``put_secret`` updates ``os.environ`` (process-local; for refresh token
    rotation in long-lived workers). Prefer KeyringCredentialStore for durable writes.
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
        if not credential_ref.startswith("env:"):
            raise ValueError(f"unsupported credential_ref scheme: {credential_ref!r}")
        os.environ[credential_ref[4:]] = secret


class DictCredentialStore:
    """In-memory store for unit/integration tests."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = dict(mapping or {})

    def put(self, credential_ref: str, secret: str) -> None:
        self.put_secret(credential_ref, secret)

    def put_secret(self, credential_ref: str, secret: str) -> None:
        self._mapping[credential_ref] = secret

    def get_secret(self, credential_ref: str) -> str:
        try:
            return self._mapping[credential_ref]
        except KeyError as exc:
            raise KeyError(f"unknown credential_ref {credential_ref!r}") from exc


class KeyringCredentialStore:
    """OS keyring stub. Uses the ``keyring`` package when installed; otherwise
    falls back to an in-memory map (tests / boxes without keyring).

    Refs: ``keyring:service/user`` or bare ``keyring:name`` (service=kkmail).
    """

    def __init__(self, *, service: str = "kkmail", fallback: dict[str, str] | None = None) -> None:
        self.service = service
        self._fallback = dict(fallback or {})
        self._backend: Any | None
        try:
            import keyring  # type: ignore

            self._backend = keyring
        except ImportError:
            self._backend = None

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
        if self._backend is not None:
            val = self._backend.get_password(svc, user)
            if val is not None:
                return val
        if credential_ref in self._fallback:
            return self._fallback[credential_ref]
        raise KeyError(f"keyring secret missing for {credential_ref!r}")

    def put_secret(self, credential_ref: str, secret: str) -> None:
        svc, user = self._parse(credential_ref)
        if self._backend is not None:
            self._backend.set_password(svc, user, secret)
        self._fallback[credential_ref] = secret


class CompositeCredentialStore:
    """Dispatch by ref scheme: env: / keyring: / everything else → dict."""

    def __init__(
        self,
        *,
        env: EnvCredentialStore | None = None,
        keyring: KeyringCredentialStore | None = None,
        mapping: dict[str, str] | None = None,
    ) -> None:
        self.env = env or EnvCredentialStore()
        self.keyring = keyring or KeyringCredentialStore()
        self.dict = DictCredentialStore(mapping)

    def get_secret(self, credential_ref: str) -> str:
        if credential_ref.startswith("env:"):
            return self.env.get_secret(credential_ref)
        if credential_ref.startswith("keyring:"):
            return self.keyring.get_secret(credential_ref)
        return self.dict.get_secret(credential_ref)

    def put_secret(self, credential_ref: str, secret: str) -> None:
        if credential_ref.startswith("env:"):
            self.env.put_secret(credential_ref, secret)
        elif credential_ref.startswith("keyring:"):
            self.keyring.put_secret(credential_ref, secret)
        else:
            self.dict.put_secret(credential_ref, secret)


def load_json_secret(store: CredentialStore, credential_ref: str) -> dict[str, Any]:
    raw = store.get_secret(credential_ref)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("credential secret must be a JSON object")
    return data


def save_json_secret(store: CredentialStore, credential_ref: str, data: dict[str, Any]) -> None:
    store.put_secret(credential_ref, json.dumps(data))


_default_store: CredentialStore | None = None


def get_credential_store() -> CredentialStore:
    global _default_store
    if _default_store is None:
        _default_store = CompositeCredentialStore()
    return _default_store


def set_credential_store(store: CredentialStore | None) -> None:
    global _default_store
    _default_store = store
