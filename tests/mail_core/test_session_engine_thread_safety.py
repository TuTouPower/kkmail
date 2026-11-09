"""Thread-safety of get_session_factory: concurrent calls resolve the engine once.

This is a pure unit test of the in-process double-checked lock; it does not
touch a database at all. A lightweight stub stands in for the SQLAlchemy
Engine so no SQLite/PG dialect, driver or connection is involved (retired
the old SQLite ``create_engine`` smoke engine).
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import mail_core.db.session as db_session


class _StubURL:
    def __init__(self, rendered: str) -> None:
        self._rendered = rendered

    def render_as_string(self, hide_password: bool = False) -> str:
        return self._rendered


class _StubEngine:
    def __init__(self, rendered: str) -> None:
        self.url = _StubURL(rendered)

    def dispose(self) -> None:
        pass


def test_concurrent_session_factory_resolves_engine_once(monkeypatch):
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_SessionLocal", None)
    create_entered = Event()
    duplicate_create_entered = Event()
    release_create = Event()
    count_lock = Lock()
    create_count = 0
    created_engines = []
    workers = 6
    start = Barrier(workers)
    url = "stub://session-factory"

    def slow_create_engine(*args, **kwargs):
        nonlocal create_count
        with count_lock:
            create_count += 1
            if create_count == 1:
                create_entered.set()
            else:
                duplicate_create_entered.set()
        if not release_create.wait(timeout=3):
            raise RuntimeError("test did not release engine creation")
        engine = _StubEngine(str(args[0]))
        created_engines.append(engine)
        return engine

    monkeypatch.setattr(db_session, "create_engine", slow_create_engine)

    def get_factory():
        start.wait(timeout=2)
        return db_session.get_session_factory(url)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(get_factory) for _ in range(workers)]
            assert create_entered.wait(timeout=2)
            assert not duplicate_create_entered.wait(timeout=0.05)
            release_create.set()
            factories = [future.result(timeout=3) for future in futures]

        assert create_count == 1
        assert all(factory is factories[0] for factory in factories)
        assert factories[0].kw["bind"] is created_engines[0]
    finally:
        release_create.set()
        for engine in created_engines:
            engine.dispose()
