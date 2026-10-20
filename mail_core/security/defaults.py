"""Hard defaults for mail-core clients (architecture M5).

Flask SPA MessageReader keeps its existing remote-image CSP when not using
mail-core; mail-core readers MUST pass loadRemoteImages=false unless the user
explicitly opts in.
"""

from __future__ import annotations

# Architecture §11 / M5: remote images default OFF for mail-core.
REMOTE_IMAGES_DEFAULT_ON = False

ENCRYPTED_VOLUME_REQUIREMENT = (
    "Production MUST place PostgreSQL data and the blob tree on an encrypted "
    "volume (OS disk encryption / LUKS / FileVault / BitLocker). Docker named "
    "volumes alone do NOT satisfy this. See docs/mail-core-architecture.md §11."
)


def require_encrypted_volume_docs() -> str:
    """Return the encryption-volume requirement text for ops docs / ready checks."""
    return ENCRYPTED_VOLUME_REQUIREMENT
