"""Healthcheck CLI command for container probes."""

from __future__ import annotations

import os
import sys

from mail_core.db.session import get_session_factory
from mail_core.worker.heartbeat import get_worker_heartbeats


def main() -> int:
    worker_id = os.environ.get("MAIL_CORE_WORKER_ID")
    stale_threshold = float(os.environ.get("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", "60.0"))

    try:
        Session = get_session_factory()
        with Session() as session:
            is_healthy, lag, workers = get_worker_heartbeats(
                session, stale_after_seconds=stale_threshold
            )
            if worker_id:
                matching = [w for w in workers if w.get("worker_id") == worker_id and w.get("active")]
                if not matching:
                    print(f"worker {worker_id} heartbeat missing or stale", file=sys.stderr)
                    return 1
                print(f"worker {worker_id} healthy (lag={matching[0].get('lag_seconds')}s)")
                return 0

            if not is_healthy:
                print("no active worker heartbeats found", file=sys.stderr)
                return 1

            print(f"workers healthy (min_lag={lag}s, count={len(workers)})")
            return 0
    except Exception as exc:
        print(f"worker healthcheck error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
