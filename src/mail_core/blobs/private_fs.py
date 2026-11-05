"""Low-level private-directory helpers shared by blob storage, rotation and restore.

The application-private storage contract is directory mode ``0700``.  These
helpers never follow a symlink and make the umask irrelevant.  They are kept
free of service dependencies so both the runtime and maintenance paths can
import them.
"""

from __future__ import annotations

import os
from pathlib import Path


class PrivatePathError(RuntimeError):
    """A path cannot be made application-private without following a link."""


def make_private_dir(path: Path, *, strict: bool = False) -> Path:
    """Create or tighten one directory to ``0700``, refusing symlinks.

    ``strict`` makes an unrepresentable chmod failure fatal; callers that are
    merely reinforcing a best-effort runtime path may keep the default.
    """
    if path.is_symlink():
        raise PrivatePathError(f"refusing symlink directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        if strict:
            raise
    return path


def make_private_chain(path: Path, root: Path, *, strict: bool = False) -> Path:
    """Tighten ``path`` and every directory between it and ``root`` inclusive."""
    root_abs = Path(os.path.abspath(root))
    current = Path(os.path.abspath(path))
    if current != root_abs and root_abs not in current.parents:
        raise PrivatePathError(f"path is outside private root: {path}")
    current.mkdir(parents=True, exist_ok=True)
    while True:
        make_private_dir(current, strict=strict)
        if current == root_abs:
            return path
        current = current.parent
