"""Healthcheck CLI command for container probes (t095 AC-005).

Liveness is verified from the worker's filesystem stamp alone: no Python
interpreter cold-start into SQLAlchemy, no DB connection, no ROLLBACK. The
stamp's mtime proves the main loop refreshed it recently; its progress counter
is carried for diagnostics. Database readiness stays the API's ``/ready``
concern.
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

from mail_core.liveness import read_liveness_stamp, stamp_path


def main() -> int:
    try:
        max_lag = float(os.environ.get("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", "60.0"))
        if not math.isfinite(max_lag) or max_lag <= 0:
            raise ValueError("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG must be finite > 0")

        path: Path = stamp_path()
        stamp = read_liveness_stamp(path)
        if stamp is None:
            print("worker liveness stamp missing", file=sys.stderr)
            return 1
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            print("worker liveness stamp unreadable", file=sys.stderr)
            return 1
        if age > max_lag:
            print(f"worker liveness stamp stale ({age:.1f}s)", file=sys.stderr)
            return 1
        print(
            f"worker alive (stamp_age={age:.1f}s, progress={stamp.get('progress')}, "
            f"worker_id={stamp.get('worker_id')})"
        )
        return 0
    except Exception as exc:
        print(f"worker healthcheck error: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
