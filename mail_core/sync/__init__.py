"""Sync engine: jobs, leases, metadata/delta apply, reconcile, remote push.

Exports resolve lazily (PEP 562) so importing a submodule never drags in
the whole package graph (avoids import cycles between accounts/sync/providers).
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "DeltaApplyResult": "mail_core.sync.delta",
    "FencingMismatch": "mail_core.sync.leases",
    "LeaseBusy": "mail_core.sync.leases",
    "LeaseHandle": "mail_core.sync.leases",
    "MetadataApplyResult": "mail_core.sync.metadata",
    "acquire_lease": "mail_core.sync.leases",
    "apply_delta_page": "mail_core.sync.delta",
    "apply_metadata_page": "mail_core.sync.metadata",
    "assert_fencing": "mail_core.sync.leases",
    "claim_jobs": "mail_core.sync.jobs",
    "commit_checkpoint": "mail_core.sync.checkpoints",
    "invalidate_checkpoint_for_rebuild": "mail_core.sync.checkpoints",
    "JobOwnershipError": "mail_core.sync.jobs",
    "complete_job": "mail_core.sync.jobs",
    "enqueue_job": "mail_core.sync.jobs",
    "fail_job": "mail_core.sync.jobs",
    "heartbeat_lease": "mail_core.sync.leases",
    "push_remote_operations": "mail_core.sync.remote_push",
    "prune_completed_jobs": "mail_core.sync.jobs",
    "reclaim_stale_claims": "mail_core.sync.jobs",
    "reconcile_folder": "mail_core.sync.reconcile",
    "release_lease": "mail_core.sync.leases",
    "sync_account_folders": "mail_core.sync.engine",
    "sync_folder_delta": "mail_core.sync.delta",
    "sync_folder_metadata": "mail_core.sync.engine",
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
