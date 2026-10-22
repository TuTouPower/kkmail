"""Per-test cleanup for real commits, threads and process-local backend state."""

from contextlib import contextmanager
import os
import threading

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import close_all_sessions


def clear_database():
    if not os.environ.get("MAIL_CORE_DATABASE_URL"):
        return
    from scripts.test_pg_runtime import checked_url, engine, guard_database
    from mail_core.db.base import Base

    guard_database()
    target = engine(checked_url(os.environ["MAIL_CORE_DATABASE_URL"]))
    try:
        tables = ", ".join(target.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables)
        with target.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    finally:
        target.dispose()


@contextmanager
def isolated_runtime(monkeypatch, tmp_path, session):
    from mail_core.accounts.credentials import set_credential_store
    from mail_core.api.app import _code_schema_head
    from mail_core.api import sse
    from mail_core.db import session as db
    from mail_core.realtime import dispatcher, listener
    from mail_core.security.auth import reset_auth_caches
    from mail_core.security.ratelimit import login_limiter
    from mail_core.worker import main as worker
    import mail_core.sync.delta as delta
    import mail_core.sync.engine as sync_engine
    import mail_core.sync.reconcile as reconcile
    import mail_core.sync.remote_push as remote_push

    providers = {module: module.build_provider for module in (delta, sync_engine, reconcile, remote_push)}
    listeners = []
    workers = []
    connections = []
    original_init = listener.OutboxListenThread.__init__
    original_start = listener.OutboxListenThread.start
    original_run = worker.run

    def listener_init(self, *args, **kwargs):
        kwargs.setdefault("idle_timeout_s", 0.1)
        kwargs.setdefault("reconnect_s", 0.1)
        original_init(self, *args, **kwargs)

    def listener_start(self):
        if self not in listeners:
            listeners.append(self)
        return original_start(self)

    def worker_run(*args, **kwargs):
        thread = threading.current_thread()
        workers.append(thread)
        return original_run(*args, **kwargs)

    def reset_state():
        close_all_sessions()
        for connection in connections:
            if not connection.closed:
                connection.close()
        for target in {connection.engine for connection in connections}:
            target.dispose()
        connections.clear()
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        db._SessionLocal = None
        set_credential_store(None)
        listener._listener = None
        dispatcher._dispatcher = None
        worker._stop = False
        sse._sse_active = 0
        reset_auth_caches()
        login_limiter.reset()
        _code_schema_head.cache_clear()
        for module, provider in providers.items():
            module.build_provider = provider

    try:
        reset_state()
        clear_database()
    except Exception as exc:
        message = f"backend isolation setup cleanup failed ({type(exc).__name__})"
        session.shouldstop = message
        pytest.fail(message, pytrace=False)
    for key, directory in (("MAIL_CORE_BLOB_ROOT", "blobs"), ("MAIL_CORE_BACKUP_DIR", "backups"), ("MAIL_CORE_DATA_DIR", "data")):
        monkeypatch.setenv(key, str(tmp_path / directory))
    monkeypatch.setattr(listener.OutboxListenThread, "__init__", listener_init)
    monkeypatch.setattr(listener.OutboxListenThread, "start", listener_start)
    monkeypatch.setattr(worker, "run", worker_run)
    def track_connection(connection):
        connections.append(connection)

    event.listen(Engine, "engine_connect", track_connection)
    try:
        yield
    finally:
        # Restore test overrides before calling real teardown functions. This
        # also restores the guarded DB URL when a test exercises missing config.
        monkeypatch.undo()
        try:
            worker.request_stop()
            for thread in workers:
                if thread is not threading.current_thread():
                    thread.join(timeout=2)
                    if thread.is_alive():
                        raise RuntimeError("test Worker did not stop")
            for item in listeners:
                item.stop(timeout=2)
                if item.is_alive:
                    raise RuntimeError("test LISTEN thread did not stop")
            event.remove(Engine, "engine_connect", track_connection)
            reset_state()
            clear_database()
        except Exception as exc:
            # A failed reset must stop the suite, never contaminate later tests.
            message = f"backend isolation cleanup failed ({type(exc).__name__})"
            session.shouldstop = message
            pytest.fail(message, pytrace=False)
        finally:
            if event.contains(Engine, "engine_connect", track_connection):
                event.remove(Engine, "engine_connect", track_connection)
