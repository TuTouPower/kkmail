"""A280: API readiness failure must echo api/worker log tails (or at least
the log paths) so diagnosis does not require hunting files by hand.
"""

from contextlib import contextmanager
import importlib.util
import logging
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy


def _load_runner():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/run_full_stack_e2e.py"
    spec = importlib.util.spec_from_file_location("run_full_stack_e2e_log_tail", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_log_tail_returns_last_n_lines(tmp_path):
    module = _load_runner()
    log_file = tmp_path / "x.log"
    log_file.write_text(
        "".join(f"line{i}\n" for i in range(1, 31)), encoding="utf-8"
    )
    tail = module._read_log_tail(log_file, lines=20)
    lines = tail.splitlines()
    assert len(lines) == 20
    assert lines[0] == "line11"
    assert lines[-1] == "line30"


def test_read_log_tail_missing_and_empty(tmp_path):
    module = _load_runner()
    assert module._read_log_tail(tmp_path / "nope.log") == "(unavailable)"
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    assert module._read_log_tail(empty) == "(empty)"


def test_readiness_failure_echoes_log_tails_and_paths(tmp_path, monkeypatch, caplog):
    module = _load_runner()
    module.ROOT = tmp_path
    monkeypatch.setattr(module, "load_env_test", lambda: None)
    monkeypatch.setattr(module, "API_READY_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(module, "API_READY_POLL_SECONDS", 0.01)

    class ConnectedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        module.socket, "create_connection", lambda *_a, **_k: ConnectedSocket()
    )
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", secrets.token_urlsafe(32))

    class FakeConnection:
        def execute(self, _statement):
            return None

    class FakeEngine:
        disposed = False

        @contextmanager
        def connect(self):
            yield FakeConnection()

        def dispose(self):
            self.disposed = True

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_a, **_k: FakeEngine())
    monkeypatch.setattr(module, "run_cmd", lambda *_a, **_k: "")
    ports = iter([11111, 22222])
    monkeypatch.setattr(module, "find_free_port", lambda: next(ports))

    class FakeProc:
        def __init__(self, args, **kwargs):
            self.args = [str(a) for a in args]
            out = kwargs.get("stdout")
            if out is not None:
                if "uvicorn" in self.args:
                    out.write("API-BOOM-LINE\n")
                else:
                    out.write("WORKER-BOOM-LINE\n")
                out.flush()

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(module.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0)
    )

    def never_ready(url, timeout=None):
        raise OSError("not ready")

    monkeypatch.setattr("urllib.request.urlopen", never_ready)

    with caplog.at_level(logging.INFO, logger="full_stack_e2e"):
        with pytest.raises(RuntimeError) as excinfo:
            module.main()

    # Exception names both log paths; log output carries both tails.
    assert "api_" in str(excinfo.value) and ".log" in str(excinfo.value)
    assert "worker_" in str(excinfo.value)
    assert "API-BOOM-LINE" in caplog.text
    assert "WORKER-BOOM-LINE" in caplog.text
