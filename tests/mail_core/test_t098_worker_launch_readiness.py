"""t098: unified worker launch mode and readiness configuration.

The startup boundary merges CLI and environment into one effective worker
mode shared by the worker-thread decision and the /ready probe; the liveness
stamp path resolves through a single rule for writer and readers. All tests
run without PostgreSQL: process entry, simulated DB heartbeat, real files
and /ready requests only.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core import liveness
from mail_core.api.app import _code_schema_head, app
from mail_core.config.loader import load_config, resolve_embedded_worker
from mail_core.readiness import ReadinessProbe, get_readiness_probe, read_worker_active_via_core
from mail_core.worker.healthcheck import main as healthcheck_main


# ---------------------------------------------------------------------------
# Fakes: simulated DB heartbeat + /ready engine
# ---------------------------------------------------------------------------


def _heartbeat_payload(*, stale: bool = False) -> str:
    updated = datetime.now(timezone.utc) - (timedelta(seconds=3600) if stale else timedelta(0))
    return f'{{"worker_id": "w1", "updated_at": "{updated.isoformat()}", "active_jobs": 0}}'


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, *, scalar_value=None, scalar_values=()):
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values

    def scalar(self):
        return self._scalar_value

    def scalars(self):
        return _Scalars(self._scalar_values)


class _Conn:
    def __init__(self, result):
        self._result = result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execution_options(self, **_kwargs):
        return self

    def execute(self, *_args, **_kwargs):
        return self._result


class _Engine:
    def __init__(self, result):
        self._result = result

    def connect(self):
        return _Conn(self._result)


def _heartbeat_engine(*, stale: bool = False) -> _Engine:
    return _Engine(_Result(scalar_values=[_heartbeat_payload(stale=stale)]))


def _ready_engine(*, stale_heartbeat: bool = False) -> _Engine:
    return _Engine(
        _Result(
            scalar_value=_code_schema_head(),
            scalar_values=[_heartbeat_payload(stale=stale_heartbeat)],
        )
    )


class _Listener:
    def __init__(self, listen_ready: bool):
        self.listen_ready = listen_ready


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_worker_env(monkeypatch, tmp_path):
    """Hermetic worker-mode env; the default stamp path points into tmp_path."""
    for name in (
        "MAIL_CORE_EMBEDDED_WORKER",
        "MAIL_CORE_LIVENESS_STAMP",
        "MAIL_CORE_DATA_DIR",
        "MAIL_CORE_REQUIRE_WORKER_READY",
        "KKMAIL_SIDECAR",
    ):
        monkeypatch.delenv(name, raising=False)
    default_stamp = tmp_path / "default" / "worker-liveness.json"
    monkeypatch.setattr(liveness, "DEFAULT_STAMP_PATH", str(default_stamp))
    get_readiness_probe().invalidate()
    yield default_stamp
    get_readiness_probe().invalidate()


def _write_stamp(path, *, stale: bool = False) -> None:
    liveness.write_liveness_stamp(path, progress=1, worker_id="w1")
    if stale:
        old = time.time() - 3600.0
        os.utime(path, (old, old))


def _patch_ready_seams(monkeypatch, engine, *, listener_ready: bool = True) -> None:
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda url=None: engine)
    monkeypatch.setattr(
        "mail_core.realtime.listener.get_outbox_listener",
        lambda: _Listener(listener_ready),
    )


# ---------------------------------------------------------------------------
# AC-001: CLI --no-worker and MAIL_CORE_EMBEDDED_WORKER=0 are equivalent
# ---------------------------------------------------------------------------


def test_ac001_resolve_embedded_worker_matrix():
    assert resolve_embedded_worker({}) is True
    assert resolve_embedded_worker({"MAIL_CORE_EMBEDDED_WORKER": "0"}) is False
    assert resolve_embedded_worker({"MAIL_CORE_EMBEDDED_WORKER": "1"}) is True
    # CLI wins over the environment in both directions it can express.
    assert resolve_embedded_worker({"MAIL_CORE_EMBEDDED_WORKER": "1"}, cli_no_worker=True) is False
    assert resolve_embedded_worker({"MAIL_CORE_EMBEDDED_WORKER": "0"}, cli_no_worker=True) is False
    # The loaded config derives from the same resolver.
    assert load_config({}).embedded_worker is True
    assert load_config({"MAIL_CORE_EMBEDDED_WORKER": "0"}).embedded_worker is False


def _run_main(monkeypatch, argv, *, env: dict[str, str] | None = None):
    """Run the real process entry with uvicorn and the worker loop stubbed out."""
    from mail_core.__main__ import main as mail_core_main

    started = threading.Event()
    monkeypatch.setattr("mail_core.worker.main.run", lambda *a, **k: started.set())
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    mail_core_main(["--skip-migrations", "--host", "127.0.0.1", "--port", "18123", *argv])
    return started


def test_ac001_main_no_worker_publishes_mode_and_starts_no_thread(monkeypatch, _clean_worker_env):
    default_stamp = _clean_worker_env
    _write_stamp(default_stamp, stale=True)  # residual stamp from an earlier run

    started = _run_main(monkeypatch, ["--no-worker"])
    assert not started.wait(timeout=0.5), "embedded worker thread must not start"
    assert os.environ["MAIL_CORE_EMBEDDED_WORKER"] == "0"

    # The probe now agrees with the thread decision: fresh DB heartbeat is
    # enough; the residual default stamp is ignored.
    active, lag = read_worker_active_via_core(_heartbeat_engine())
    assert active is True
    assert lag is not None


def test_ac001_main_env_zero_starts_no_thread(monkeypatch):
    started = _run_main(monkeypatch, [], env={"MAIL_CORE_EMBEDDED_WORKER": "0"})
    assert not started.wait(timeout=0.5)
    assert os.environ["MAIL_CORE_EMBEDDED_WORKER"] == "0"


def test_ac001_main_default_starts_embedded_thread_and_publishes_mode(monkeypatch):
    started = _run_main(monkeypatch, [])
    assert started.wait(timeout=5), "embedded worker thread must start by default"
    assert os.environ["MAIL_CORE_EMBEDDED_WORKER"] == "1"


def test_ac001_ready_200_end_to_end_after_cli_no_worker_launch(
    monkeypatch, _clean_worker_env
):
    """AC-001: a real --no-worker launch publishes the mode the /ready probe consumes."""
    default_stamp = _clean_worker_env
    _write_stamp(default_stamp, stale=True)
    started = _run_main(monkeypatch, ["--no-worker"])
    assert not started.wait(timeout=0.5)
    assert os.environ["MAIL_CORE_EMBEDDED_WORKER"] == "0"

    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    _patch_ready_seams(monkeypatch, _ready_engine())
    res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["worker"] is True


def test_ac001_ready_200_for_no_worker_modes_despite_residual_stamp(
    monkeypatch, _clean_worker_env
):
    default_stamp = _clean_worker_env
    _write_stamp(default_stamp, stale=True)
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    # Both launch modes converge on the published effective mode "0" (the
    # --no-worker case is covered end-to-end by the main() test above).
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    _patch_ready_seams(monkeypatch, _ready_engine())

    res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["worker"] is True


# ---------------------------------------------------------------------------
# AC-002: a required stamp gates readiness; DB heartbeat stays authoritative
# ---------------------------------------------------------------------------


def test_ac002_explicit_stamp_gates_readiness_in_standalone_mode(monkeypatch, tmp_path):
    stamp = tmp_path / "explicit.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp))

    # Missing stamp -> not ready even with a fresh DB heartbeat.
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is False

    # Corrupt stamp -> not ready.
    stamp.write_text("not json")
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is False

    # Unreadable stamp (a directory at the stamp path: the read fails with
    # OSError) -> not ready.
    stamp.unlink()
    stamp.mkdir()
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is False
    stamp.rmdir()

    # Stale stamp -> not ready.
    _write_stamp(stamp, stale=True)
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is False

    # Fresh stamp + fresh heartbeat -> ready.
    _write_stamp(stamp)
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is True

    # Fresh stamp cannot rescue a stale DB heartbeat.
    active, _ = read_worker_active_via_core(_heartbeat_engine(stale=True))
    assert active is False


def test_ac002_embedded_mode_requires_stamp(monkeypatch, _clean_worker_env):
    default_stamp = _clean_worker_env
    # Embedded by default: no stamp anywhere -> not ready.
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is False
    _write_stamp(default_stamp)
    active, _ = read_worker_active_via_core(_heartbeat_engine())
    assert active is True


def test_ac002_ready_503_when_required_stamp_stale(monkeypatch, tmp_path):
    stamp = tmp_path / "explicit.json"
    _write_stamp(stamp, stale=True)
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp))
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    _patch_ready_seams(monkeypatch, _ready_engine())

    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "worker_not_running"


# ---------------------------------------------------------------------------
# AC-003: one effective stamp path for writing and reading; test isolation
# ---------------------------------------------------------------------------


def test_ac003_stamp_path_priority(monkeypatch, tmp_path, _clean_worker_env):
    default_stamp = _clean_worker_env
    data_dir = tmp_path / "data"
    explicit = tmp_path / "elsewhere" / "stamp.json"

    # Process default when nothing is configured.
    assert liveness.stamp_path() == default_stamp

    # Data directory beats the default; the stamp sits directly inside it.
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", str(data_dir))
    resolved = liveness.stamp_path()
    assert resolved == data_dir / "worker-liveness.json"
    assert resolved.parent == data_dir

    # Explicit path beats the data directory.
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(explicit))
    assert liveness.stamp_path() == explicit


def test_ac003_write_and_read_share_effective_path_and_isolate_default(
    monkeypatch, tmp_path, _clean_worker_env
):
    default_stamp = _clean_worker_env
    data_dir = tmp_path / "data"
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", str(data_dir))

    liveness.write_liveness_stamp(progress=7, worker_id="sidecar-1")

    landed = data_dir / "worker-liveness.json"
    assert landed.exists()
    assert liveness.read_liveness_stamp() == {"progress": 7, "worker_id": "sidecar-1", "v": 1}
    # Isolation: the shared default path was never written.
    assert not default_stamp.exists()


def test_ac003_healthcheck_shares_stamp_resolution(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", str(data_dir))
    monkeypatch.delenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raising=False)

    liveness.write_liveness_stamp(progress=3, worker_id="w1")
    assert healthcheck_main() == 0

    stamp = data_dir / "worker-liveness.json"
    old = time.time() - 3600.0
    os.utime(stamp, (old, old))
    assert healthcheck_main() == 1


# ---------------------------------------------------------------------------
# AC-004: DB/schema/LISTEN re-read every call; worker signal short-TTL cached
# ---------------------------------------------------------------------------


def test_ac004_probe_caches_worker_signal_with_short_ttl_and_invalidate():
    probe = ReadinessProbe(ttl_s=60.0)
    first = probe.snapshot(
        schema_revision="head", listener_ready=True, worker_active=False
    )
    # Within the TTL the worker-derived result is served from cache.
    cached = probe.snapshot(
        schema_revision="head", listener_ready=True, worker_active=True
    )
    assert cached.worker_active is False
    assert cached is first
    # Invalidation (readiness failure / LISTEN drop) forces a fresh read.
    probe.invalidate()
    refreshed = probe.snapshot(
        schema_revision="head", listener_ready=True, worker_active=True
    )
    assert refreshed.worker_active is True


def test_ac004_ready_rereads_worker_signal_after_failure(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    _patch_ready_seams(monkeypatch, _ready_engine(stale_heartbeat=True))

    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "worker_not_running"

    # The worker recovers: the very next probe re-reads the signal instead of
    # serving the cached failure.
    _patch_ready_seams(monkeypatch, _ready_engine())
    res = TestClient(app).get("/ready")
    assert res.status_code == 200
    assert res.json()["worker"] is True


def test_ac004_ready_rereads_listener_state_every_call(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    _patch_ready_seams(monkeypatch, _ready_engine(), listener_ready=True)
    assert TestClient(app).get("/ready").status_code == 200

    # LISTEN drops: the next call sees it immediately (never cache-masked).
    _patch_ready_seams(monkeypatch, _ready_engine(), listener_ready=False)
    res = TestClient(app).get("/ready")
    assert res.status_code == 503
    assert res.json()["reason"] == "outbox_listener"
