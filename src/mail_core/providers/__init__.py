"""Mail providers (IMAP / Graph / memory) and the provider contract.

Exports resolve lazily (PEP 562) so importing a submodule never drags in
the whole package graph (avoids import cycles between accounts/sync/providers).
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "CursorInvalidError": "mail_core.providers.http",
    "AmbiguousOutcomeError": "mail_core.providers.http",
    "ProviderHttpError": "mail_core.providers.http",
    "RateLimitedError": "mail_core.providers.http",
    "DeltaChange": "mail_core.providers.base",
    "DeltaPage": "mail_core.providers.base",
    "GraphProvider": "mail_core.providers.graph",
    "ImapProvider": "mail_core.providers.imap",
    "MailProvider": "mail_core.providers.base",
    "MemoryProvider": "mail_core.providers.stub_memory",
    "MetadataPage": "mail_core.providers.base",
    "RateLimitHint": "mail_core.providers.base",
    "ReconcileAction": "mail_core.providers.base",
    "RemoteFolder": "mail_core.providers.base",
    "RemoteMessageMeta": "mail_core.providers.base",
    "RemoteOperationResult": "mail_core.providers.base",
    "StubProvider": "mail_core.providers.base",
    "build_provider": "mail_core.providers.factory",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
