"""t096 unit tests: runtime budget derivation, liveness isolation, readiness mode boundary, clean imports."""

from __future__ import annotations

import ast
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from mail_core import liveness, runtime_budget
from mail_core.config.loader import load_config
from mail_core.readiness import read_worker_active_via_core
from mail_core.sync.idle_policy import IdleWatcherConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ac004_load_config_and_idle_watcher_config_derive_all_budget_defaults():
    """AC-004: production load_config({}) and IdleWatcherConfig() derive strictly from runtime_budget."""
    cfg = load_config({})
    assert cfg.db_pool_size == runtime_budget.DEFAULT_DB_POOL_SIZE
    assert cfg.db_max_overflow == runtime_budget.DEFAULT_DB_MAX_OVERFLOW
    assert cfg.total_slots == runtime_budget.DEFAULT_TOTAL_SLOTS
    assert cfg.background_start_slot == runtime_budget.DEFAULT_BACKGROUND_START_SLOT
    assert cfg.idle_quota == runtime_budget.DEFAULT_IDLE_QUOTA
    assert IdleWatcherConfig().quota == runtime_budget.DEFAULT_IDLE_QUOTA

    # Guard against literal duplication in loader.py (e.g. hardcoded 8 / 2 matching runtime_budget).
    loader_src = (REPO_ROOT / "src/mail_core/config/loader.py").read_text()
    tree = ast.parse(loader_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in (
            "db_pool_size",
            "db_max_overflow",
            "total_slots",
            "background_start_slot",
            "idle_quota",
        ):
            assert isinstance(node.value, ast.Call)
            # Second positional arg to _parse_int must be an Attribute on runtime_budget.
            default_arg = node.value.args[1]
            assert isinstance(default_arg, ast.Attribute), (
                f"{node.arg} default in loader.py must come from runtime_budget, got {ast.dump(default_arg)}"
            )
            assert isinstance(default_arg.value, ast.Name) and default_arg.value.id == "runtime_budget"


def test_ac005_liveness_stamp_isolates_under_data_dir(monkeypatch, tmp_path):
    """AC-005: when MAIL_CORE_DATA_DIR is set and MAIL_CORE_LIVENESS_STAMP is unset, stamp lives in data_dir."""
    data_dir = tmp_path / "nested" / "data_dir"
    monkeypatch.delenv("MAIL_CORE_LIVENESS_STAMP", raising=False)
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", str(data_dir))

    resolved = liveness.stamp_path()
    assert resolved == data_dir / "worker-liveness.json"

    # write_liveness_stamp creates missing parent directory and writes atomically.
    liveness.write_liveness_stamp(progress=7, worker_id="sidecar-1")
    loaded = liveness.read_liveness_stamp()
    assert loaded == {"progress": 7, "worker_id": "sidecar-1", "v": 1}


def _fake_engine_with_fresh_heartbeat():
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = f'{{"worker_id": "w1", "updated_at": "{now_iso}", "active_jobs": 0}}'

    class _Scalars:
        def all(self):
            return [payload]

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execution_options(self, **_kwargs):
            return self

        def execute(self, *_args, **_kwargs):
            return _Result()

    class _Engine:
        def connect(self):
            return _Conn()

    return _Engine()


def test_ac005_distributed_readiness_ignores_stray_default_tmp_stamp(monkeypatch, tmp_path):
    """AC-005: distributed API (MAIL_CORE_EMBEDDED_WORKER=0, unset stamp env) ignores stale local default stamp."""
    stray = tmp_path / "stray-liveness.json"
    liveness.write_liveness_stamp(stray, progress=1, worker_id="old-local")
    stale_time = time.time() - 3600.0
    os.utime(stray, (stale_time, stale_time))

    monkeypatch.setattr(liveness, "DEFAULT_STAMP_PATH", str(stray))
    monkeypatch.delenv("MAIL_CORE_LIVENESS_STAMP", raising=False)
    monkeypatch.delenv("MAIL_CORE_DATA_DIR", raising=False)
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")

    active, lag = read_worker_active_via_core(_fake_engine_with_fresh_heartbeat())
    assert active is True
    assert lag is not None

    # In embedded mode (MAIL_CORE_EMBEDDED_WORKER=1), the stale stamp MUST fail readiness.
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    active_embedded, _ = read_worker_active_via_core(_fake_engine_with_fresh_heartbeat())
    assert active_embedded is False


def test_ac003_patrol_and_readiness_avoid_runtime_dunder_import():
    """AC-003: patrol.py and readiness.py use normal imports instead of __import__."""
    for rel in ("src/mail_core/sync/patrol.py", "src/mail_core/readiness.py"):
        src = (REPO_ROOT / rel).read_text()
        assert "__import__" not in src, f"{rel} still contains __import__"
