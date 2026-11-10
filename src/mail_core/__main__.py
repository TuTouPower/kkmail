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
import json
import logging
import os
import socket
import threading

log = logging.getLogger("mail_core.main")


def _configure_proxy_headers(*, enabled: bool, forwarded_allow_ips: str | None) -> None:
    raw_allow_ips = (
        forwarded_allow_ips
        if forwarded_allow_ips is not None
        else os.environ.get("MAIL_CORE_FORWARDED_ALLOW_IPS")
    )
    trusted_hosts = (raw_allow_ips or "").strip()
    if trusted_hosts:
        os.environ["MAIL_CORE_FORWARDED_ALLOW_IPS"] = trusted_hosts
    else:
        os.environ.pop("MAIL_CORE_FORWARDED_ALLOW_IPS", None)
        if enabled:
            log.warning("--proxy-headers requested without trusted proxy hosts; forwarded headers remain disabled")


def run_migrations(*, check_only: bool = False) -> None:
    import sqlalchemy

    from mail_core.db import baseline
    from mail_core.db.session import database_url

    from alembic import command

    # Tree location and the revision context come from the single source in
    # baseline (resolves via the mail_core.db package, so it works from
    # source and from a PyInstaller bundle), shared with the offline tool.
    cfg = baseline.alembic_config()
    context = baseline.revision_context(cfg)

    db_url = cfg.get_main_option("sqlalchemy.url") or database_url()
    check_engine = sqlalchemy.create_engine(baseline.check_connect_url(db_url))
    try:
        with check_engine.connect() as conn:
            backend = baseline.make_url(db_url).get_backend_name()
            baseline.configure_read_only(conn, backend)
            state = baseline.read_database_state(conn)
            plan = baseline.plan_migration(state, context=context)

            if plan.action in (
                baseline.MigrationAction.NO_VERSION_WITH_BUSINESS_TABLES,
                baseline.MigrationAction.UNKNOWN_REVISION,
                baseline.MigrationAction.NEWER_THAN_CODE,
                baseline.MigrationAction.MULTIPLE_VERSIONS,
            ):
                raise RuntimeError(plan.message)

            if plan.action in (
                baseline.MigrationAction.EMPTY_DATABASE,
                baseline.MigrationAction.AT_BASELINE,
            ):
                if check_only:
                    return
                command.upgrade(cfg, "head")
                return

            errors = baseline.verify_narrow_legacy_schema(conn)
            if errors:
                detail = "\n  - ".join(errors)
                raise RuntimeError(
                    f"Automatic upgrade of this legacy database (revision '{plan.current_revision}') "
                    "to the unified baseline is not supported: the narrow conversion "
                    "path only handles the verified legacy shape.\n  - " + detail + "\n"
                    "The database was not modified. Restore the pre-upgrade sealed "
                    "backup into a deployment running the matching historical release "
                    "and resolve the schema there; do not re-run this migration "
                    "against the same database, it cannot reconstruct the missing schema."
                )
            if check_only:
                return
            try:
                outcome = baseline.apply_narrow_legacy_conversion(db_url)
            except baseline.SchemaValidationError as exc:
                raise RuntimeError(
                    f"Legacy conversion for revision '{plan.current_revision}' failed and was "
                    f"rolled back: {exc} The database was not modified."
                ) from exc
            log.info("Narrow legacy conversion %s for revision '%s'", outcome, plan.current_revision)
            command.upgrade(cfg, "head")
            return
    finally:
        check_engine.dispose()


def _sidecar_address_family(host: str) -> int:
    try:
        return socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)[0][0]
    except socket.gaierror:
        return socket.AF_INET


def _port_value(raw: str) -> int:
    """Shared validation for ``--port`` and the MAIL_CORE_PORT default."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid port value: {raw!r}") from None


def main(argv: list[str] | None = None) -> int | None:
    from mail_core.config import ConfigError, get_config, reset_config
    from mail_core.config.loader import is_sidecar_enabled

    parser = argparse.ArgumentParser(prog="python -m mail_core")
    try:
        default_port = _port_value(os.environ.get("MAIL_CORE_PORT") or "8000")
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    parser.add_argument("--host", default=os.environ.get("MAIL_CORE_HOST") or "127.0.0.1")
    parser.add_argument("--port", type=_port_value, default=default_port)
    parser.add_argument("--data-dir", default=os.environ.get("MAIL_CORE_DATA_DIR") or "")
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
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument(
        "--migrate-only",
        action="store_true",
        help="Run pending migrations, then exit without starting the API server or worker.",
    )
    gate.add_argument(
        "--check-migrations",
        action="store_true",
        help="Read-only migration check: exit 0 when the database can start, non-zero otherwise. Performs zero writes.",
    )
    args = parser.parse_args(argv)

    if args.migrate_only or args.check_migrations:
        # Gate flags run before get_config() and ignore MAIL_CORE_SKIP_MIGRATIONS.
        from mail_core.db.session import DatabaseConfigError

        try:
            run_migrations(check_only=args.check_migrations)
        except DatabaseConfigError as exc:
            parser.error(str(exc))
        return 0

    try:
        # Validate core configuration on first frame
        get_config()
    except ConfigError as exc:
        parser.error(str(exc))

    is_sidecar = is_sidecar_enabled() or args.port == 0
    if is_sidecar:
        os.environ["KKMAIL_SIDECAR"] = "1"
    reset_config()

    from mail_core.logging_config import configure_logging

    configure_logging(service_name="mail-core")
    if args.data_dir:
        from mail_core.runtime.bootstrap import bootstrap_data_dir

        os.environ["MAIL_CORE_DATA_DIR"] = args.data_dir
        bootstrap_data_dir(args.data_dir)
    _configure_proxy_headers(enabled=args.proxy_headers, forwarded_allow_ips=args.forwarded_allow_ips)
    if not args.skip_migrations:
        run_migrations()
    if not args.no_worker:
        from mail_core.worker import main as worker_main

        threading.Thread(target=worker_main.run, name="mail-core-worker", daemon=True).start()

    import uvicorn

    from mail_core.api.app import app

    if is_sidecar:
        sock = socket.socket(_sidecar_address_family(args.host), socket.SOCK_STREAM)
        sock.bind((args.host, args.port))
        sock.listen(128)
        bound_port = sock.getsockname()[1]
        os.environ["MAIL_CORE_PORT"] = str(bound_port)
        print(
            f"KKMAIL_SIDECAR_READY:{json.dumps({'status': 'ready', 'port': bound_port, 'host': args.host})}",
            flush=True,
        )
        config = uvicorn.Config(app, host=args.host, port=bound_port, log_level="info", proxy_headers=False)
        server = uvicorn.Server(config)
        try:
            server.run(sockets=[sock])
        finally:
            try:
                sock.close()
            except Exception:
                pass
    else:
        # Proxy headers handling is managed inside FastAPI via ProxyHeadersMiddleware when
        # MAIL_CORE_FORWARDED_ALLOW_IPS is explicitly configured, avoiding double parsing.
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
