"""Filesystem liveness stamp for container probes (t095 AC-005).

The worker's main loop atomically refreshes a tmpfs stamp with each tick, so a
Docker healthcheck can verify liveness by checking stamp freshness alone —
without cold-starting a Python interpreter, importing SQLAlchemy, or querying
PostgreSQL. A monotonic progress counter distinguishes a live-but-stalled loop
from an actually progressing one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULT_STAMP_PATH = "/tmp/kkmail-worker-liveness.json"


def stamp_path() -> Path:
    return Path(os.environ.get("MAIL_CORE_LIVENESS_STAMP", DEFAULT_STAMP_PATH))


def write_liveness_stamp(path: Path | None = None, *, progress: int, worker_id: str) -> None:
    """Atomically refresh the liveness stamp (tmpfs-backed in containers)."""
    target = path or stamp_path()
    payload = json.dumps({"progress": progress, "worker_id": worker_id, "v": 1})
    fd, tmp_name = tempfile.mkstemp(prefix=".kkmail-liveness-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def read_liveness_stamp(path: Path | None = None) -> dict | None:
    target = path or stamp_path()
    try:
        return json.loads(target.read_text())
    except (OSError, ValueError):
        return None
