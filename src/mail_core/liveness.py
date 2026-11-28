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


def explicit_stamp_path() -> Path | None:
    """The explicitly configured stamp path (``MAIL_CORE_LIVENESS_STAMP``), if any."""
    explicit = (os.environ.get("MAIL_CORE_LIVENESS_STAMP") or "").strip()
    return Path(explicit) if explicit else None


def stamp_path() -> Path:
    """Effective stamp path — the single resolution rule for writer and readers (t098).

    Priority: explicit ``MAIL_CORE_LIVENESS_STAMP`` > ``MAIL_CORE_DATA_DIR`` /
    ``worker-liveness.json`` > the process default path. The worker writer,
    the API readiness check and the worker healthcheck all resolve through
    here, so they can never disagree about which file carries liveness.
    """
    explicit = explicit_stamp_path()
    if explicit is not None:
        return explicit
    data_dir = (os.environ.get("MAIL_CORE_DATA_DIR") or "").strip()
    if data_dir:
        return Path(data_dir) / "worker-liveness.json"
    return Path(DEFAULT_STAMP_PATH)


def stamp_required(*, embedded_worker: bool) -> bool:
    """Whether a local stamp gates readiness (t098).

    A stamp is required when this process runs an embedded worker (its own
    loop must be refreshing the stamp) or when a stamp path is explicitly
    configured (a standalone worker's liveness is being probed through it).
    A distributed API with neither must not be gated by a stray local file.
    """
    return embedded_worker or explicit_stamp_path() is not None


def write_liveness_stamp(path: Path | None = None, *, progress: int, worker_id: str) -> None:
    """Atomically refresh the liveness stamp (tmpfs-backed in containers)."""
    target = path or stamp_path()
    target.parent.mkdir(parents=True, exist_ok=True)
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
