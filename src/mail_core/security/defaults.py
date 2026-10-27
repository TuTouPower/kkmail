"""Hard defaults for mail-core clients (architecture M5)."""

from __future__ import annotations

ENCRYPTED_VOLUME_REQUIREMENT = (
    "Production MUST place PostgreSQL data and the blob tree on an encrypted "
    "volume (OS disk encryption / LUKS / FileVault / BitLocker). Docker named "
    "volumes alone do NOT satisfy this. See docs/blueprint/architecture.md §11."
)


def require_encrypted_volume_docs() -> str:
    """Return the encryption-volume requirement text for ops docs / ready checks."""
    return ENCRYPTED_VOLUME_REQUIREMENT
