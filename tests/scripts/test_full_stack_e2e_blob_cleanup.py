from contextlib import contextmanager
import importlib.util
import secrets
from pathlib import Path

import pytest
import sqlalchemy


def _load_runner():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/run_full_stack_e2e.py"
    spec = importlib.util.spec_from_file_location("run_full_stack_e2e_blob_cleanup", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blob_directory_is_cleaned_after_setup_failure(tmp_path, monkeypatch):
    module = _load_runner()
    module.ROOT = tmp_path
    monkeypatch.setattr(module, "load_env_test", lambda: None)

    class ConnectedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(module.socket, "create_connection", lambda *_args, **_kwargs: ConnectedSocket())
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

    engine = FakeEngine()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_args, **_kwargs: engine)

    def fail_migration(*_args, **_kwargs):
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(module, "run_cmd", fail_migration)

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        module.main()

    scratch = tmp_path / ".scratch"
    assert list(scratch.glob("e2e_blobs_*")) == []
    assert (scratch / "e2e_logs").is_dir()
    assert (scratch / "e2e_artifacts").is_dir()
    assert engine.disposed
