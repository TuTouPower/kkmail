"""``python -m mail_core`` — run migrations, API, and an embedded worker thread.

Used by the desktop sidecar and single-host installs. Container deployments
run API and worker as separate processes (see docker-compose.mail-core.yml).

Options (env):
  MAIL_CORE_HOST / MAIL_CORE_PORT     bind (default 127.0.0.1:8000)
  MAIL_CORE_DATA_DIR                  per-install secrets/blobs (optional)
  MAIL_CORE_EMBEDDED_WORKER=0         disable the in-process worker thread
  MAIL_CORE_SKIP_MIGRATIONS=1         skip ``alembic upgrade head``
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("mail_core.main")


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    import mail_core.db as db_pkg

    # Resolve via the package (works from source and from a PyInstaller bundle).
    here = Path(db_pkg.__file__).resolve().parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m mail_core")
    parser.add_argument("--host", default=os.environ.get("MAIL_CORE_HOST") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MAIL_CORE_PORT") or 8000))
    parser.add_argument("--data-dir", default=os.environ.get("MAIL_CORE_DATA_DIR") or "")
    parser.add_argument("--instance-token", default=os.environ.get("KKMAIL_INSTANCE_TOKEN") or "")
    parser.add_argument("--no-worker", action="store_true", default=os.environ.get("MAIL_CORE_EMBEDDED_WORKER") == "0")
    parser.add_argument("--skip-migrations", action="store_true", default=os.environ.get("MAIL_CORE_SKIP_MIGRATIONS") == "1")
    parser.add_argument(
        "--proxy-headers",
        action="store_true",
        default=os.environ.get("MAIL_CORE_PROXY_HEADERS", "0").strip().lower() in ("1", "true", "yes", "on"),
        help="Enable proxy headers parsing",
    )
    parser.add_argument(
        "--forwarded-allow-ips",
        default=os.environ.get("MAIL_CORE_FORWARDED_ALLOW_IPS") or None,
        help="Comma-separated list of IPs/CIDRs to trust for proxy headers",
    )
    args = parser.parse_args(argv)

    from mail_core.logging_config import configure_logging

    configure_logging(service_name="mail-core")
    if args.instance_token:
        os.environ["KKMAIL_INSTANCE_TOKEN"] = args.instance_token
    if args.data_dir:
        from mail_core.runtime.bootstrap import bootstrap_data_dir

        os.environ["MAIL_CORE_DATA_DIR"] = args.data_dir
        bootstrap_data_dir(args.data_dir)
    if args.forwarded_allow_ips:
        os.environ["MAIL_CORE_FORWARDED_ALLOW_IPS"] = args.forwarded_allow_ips
    if not args.skip_migrations:
        run_migrations()
    if not args.no_worker:
        from mail_core.worker import main as worker_main

        threading.Thread(target=worker_main.run, name="mail-core-worker", daemon=True).start()

    import uvicorn

    from mail_core.api.app import app

    # Proxy headers handling is managed inside FastAPI via ProxyHeadersMiddleware when
    # MAIL_CORE_FORWARDED_ALLOW_IPS is explicitly configured, avoiding double parsing.
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
