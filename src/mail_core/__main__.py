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
    """Startup migration entry: a thin adapter over the shared executor.

    All check / connection-release / write orchestration lives in
    ``mail_core.db.baseline.execute_migration`` — the same executor the
    offline tool uses — so startup, ``--migrate-only`` and
    ``--check-migrations`` cannot diverge from it. This entry only resolves
    the database URL (the Alembic tree location and revision context come
    from the single source in baseline, which resolves via the
    ``mail_core.db`` package, so it works from source and from a PyInstaller
    bundle) and selects the startup policy and mode. The executor closes the
    read-only check transaction and disposes its engine before opening any
    DDL/DML migration connection, so inspection locks (e.g. AccessShareLock
    on sync_checkpoints) never collide with ALTER TABLE.
    """
    from mail_core.db import baseline
    from mail_core.db.session import database_url

    cfg = baseline.alembic_config()
    db_url = cfg.get_main_option("sqlalchemy.url") or database_url()
    baseline.execute_migration(
        db_url,
        mode=(
            baseline.MigrationMode.CHECK_ONLY
            if check_only
            else baseline.MigrationMode.WRITE
        ),
        policy=baseline.STARTUP_POLICY,
    )


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


def _run_label_backfill(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    import uuid

    from sqlalchemy import select

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.folder_views import is_gmail_account
    from mail_core.mail.storage.models import Account
    from mail_core.sync.label_backfill import backfill_account

    requested = None
    if args.account_id:
        try:
            requested = uuid.UUID(args.account_id)
        except ValueError:
            parser.error(f"invalid --account-id: {args.account_id}")
    Session = get_session_factory()
    with Session() as session:
        if requested is not None:
            accounts = [session.get(Account, requested)]
        else:
            accounts = list(session.scalars(select(Account)).all())
        targets = [
            account
            for account in accounts
            if account is not None
            and is_gmail_account(account)
            and (args.force or account.label_backfill_completed_at is None)
        ]
    failures = 0
    for account in targets:
        result = backfill_account(Session, account.id, force=args.force)
        print(
            f"label_backfill account={account.id} status={result.status} "
            f"folders={result.folders} upserted={result.upserted}"
        )
        if result.status in ("failed", "account_not_found", "lease_busy"):
            failures += 1
    if requested is not None and not targets:
        with Session() as session:
            exists = session.get(Account, requested) is not None
        print(
            f"label_backfill account={requested} "
            f"status={'skipped' if exists else 'account_not_found'}"
        )
        return 0 if exists else 1
    return 1 if failures else 0


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
    gate.add_argument(
        "--backfill-gmail-labels",
        action="store_true",
        help="One-shot backfill of historical Gmail Important label membership, then exit.",
    )
    parser.add_argument("--account-id", help="Limit label backfill to this account UUID.")
    parser.add_argument("--force", action="store_true", help="Re-run label backfill even for completed accounts.")
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
    if args.backfill_gmail_labels:
        return _run_label_backfill(args, parser)
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
