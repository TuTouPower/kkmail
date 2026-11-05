#!/usr/bin/env python3
"""Normalize application-private data permissions (0700 directories / 0600 files).

Run inside the application-uid container for a Docker blob volume, or on the
host for a host-owned backup directory:

  docker compose -f docker-compose.mail-core.yml --profile distributed \\
    run --rm --no-deps --entrypoint python3 api \\
    -m mail_core.blobs.permissions /var/lib/kkmail/blobs

  .venv/bin/python scripts/normalize_mail_core_permissions.py .scratch/deploy_backup_...

The command always refuses symlinks. Without target ids it normalizes mode only
and refuses entries not owned by the current uid/gid; with both
``--target-uid/--target-gid`` it performs an explicit chown (requires
root plus CHOWN/FOWNER/DAC_OVERRIDE to traverse foreign 0700 trees).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mail_core.blobs.permissions import main


if __name__ == "__main__":
    raise SystemExit(main())
