"""A264: find_free_port TOCTOU — port allocation must be deferred to just
before API launch and retried once with a fresh port on readiness failure.
"""

from contextlib import contextmanager
import importlib.util
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy


def _load_runner():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/run_full_stack_e2e.py"
    spec = importlib.util.spec_from_file_location("run_full_stack_e2e_port_retry", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _OkResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _run_main_with_ports(tmp_path, monkeypatch, ports, ready_port):
    module = _load_runner()
    module.ROOT = tmp_path
    monkeypatch.setattr(module, "load_env_test", lambda: None)
    monkeypatch.setattr(module, "API_READY_TIMEOUT_SECONDS", 0.3)
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

    monkeypatch.setattr(
        sqlalchemy, "create_engine", lambda *_a, **_k: FakeEngine()
    )

    events = []

    def fake_run_cmd(cmd, **_kwargs):
        events.append("migrate")
        return ""

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    port_iter = iter(ports)

    def fake_find_free_port():
        events.append("alloc_port")
        return next(port_iter)

    monkeypatch.setattr(module, "find_free_port", fake_find_free_port)

    popen_calls = []

    class FakeProc:
        def __init__(self, args, **kwargs):
            self.args = [str(a) for a in args]
            self.terminated = False
            popen_calls.append(self)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(module.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0),
    )

    def fake_urlopen(url, timeout=None):
        if f":{ready_port}/" in url:
            return _OkResponse()
        raise OSError("not ready")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    module.main()
    api_ports = [
        int(p.args[p.args.index("--port") + 1])
        for p in popen_calls
        if "--port" in p.args
    ]
    return events, api_ports, popen_calls


def test_port_allocated_after_migrations_and_retried_once(tmp_path, monkeypatch):
    events, api_ports, popen_calls = _run_main_with_ports(
        tmp_path, monkeypatch, ports=[11111, 22222], ready_port=22222
    )
    # Allocation deferred until launch time (after migrations), and the
    # first (raced) port is abandoned for exactly one retry.
    assert events.index("alloc_port") > events.index("migrate")
    assert api_ports == [11111, 22222]
    api_procs = [p for p in popen_calls if "--port" in p.args]
    assert api_procs[0].terminated  # failed attempt cleaned up before retry


def test_first_port_success_means_no_retry(tmp_path, monkeypatch):
    _events, api_ports, _calls = _run_main_with_ports(
        tmp_path, monkeypatch, ports=[33333], ready_port=33333
    )
    assert api_ports == [33333]
