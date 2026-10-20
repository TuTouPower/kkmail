#!/usr/bin/env python3
"""Flask backend removed — mail-core is the sole backend.

Use:
  uvicorn mail_core.api.app:app --host 127.0.0.1 --port 8000
  python -m mail_core.worker.main

See docs/mail-core-architecture.md and docker-compose.mail-core.yml.
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "kkmail: Flask web_outlook_app has been removed.\n"
        "Start mail-core instead:\n"
        "  uvicorn mail_core.api.app:app --host 127.0.0.1 --port 8000\n"
        "  python -m mail_core.worker.main\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


# Importing this module no longer loads 12 exec segments.
app = None  # type: ignore
SEGMENT_FILES = ()


if __name__ == "__main__":
    main()
