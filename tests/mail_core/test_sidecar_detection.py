"""Regression tests for unified sidecar detection and migration startup guards."""

from __future__ import annotations

import json
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from mail_core import __main__ as main_module
from mail_core.accounts.oauth_flow import get_oauth_metadata
from mail_core.config import ConfigError, load_config, reset_config
from mail_core.config.loader import is_sidecar_enabled


@pytest.fixture(autouse=True)
def _clean_config():
    reset_config()
    yield
    reset_config()


TRUE_VALUES = ("1", "true", "TRUE", "True", "yes", "YES", "on", " true ")
FALSE_VALUES = (None, "", "0", "false", "no", "off", "garbage", "  ")


@pytest.mark.parametrize("value", TRUE_VALUES)
def test_is_sidecar_enabled_accepts_every_truthy_spelling(value):
    assert is_sidecar_enabled({"KKMAIL_SIDECAR": value}) is True


@pytest.mark.parametrize("value", FALSE_VALUES)
def test_is_sidecar_enabled_rejects_false_and_unknown(value):
    env = {} if value is None else {"KKMAIL_SIDECAR": value}
    assert is_sidecar_enabled(env) is False


def test_is_sidecar_enabled_reads_process_env_by_default(monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "yes")
    assert is_sidecar_enabled() is True
    monkeypatch.delenv("KKMAIL_SIDECAR")
    assert is_sidecar_enabled() is False


@pytest.mark.parametrize("value", ("1", "true", "yes", "on", "TRUE"))
def test_oauth_metadata_uses_unified_sidecar_detection(monkeypatch, value):
    monkeypatch.setenv("KKMAIL_SIDECAR", value)
    monkeypatch.setenv("MAIL_CORE_PORT", "29654")
    meta = get_oauth_metadata("microsoft")
    assert meta["runtime_mode"] == "desktop"
    assert meta["redirect_uri"] == (
        "http://localhost:29654/api/accounts/oauth/callback/microsoft"
    )


def test_oauth_metadata_is_web_without_sidecar(monkeypatch):
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.delenv("MAIL_CORE_PUBLIC_ORIGIN", raising=False)
    meta = get_oauth_metadata("microsoft")
    assert meta["runtime_mode"] == "web"
    assert meta["redirect_uri"] is None


@pytest.mark.parametrize("value", ("1", "true", "yes", "on"))
def test_port_zero_allowed_for_every_sidecar_truthy_value(value):
    cfg = load_config({"MAIL_CORE_PORT": "0", "KKMAIL_SIDECAR": value})
    assert cfg.port == 0
    assert cfg.sidecar is True


def test_port_zero_rejected_without_sidecar():
    with pytest.raises(ConfigError, match="sidecar"):
        load_config({"MAIL_CORE_PORT": "0"})


@pytest.mark.parametrize("value", ("1", "true", "yes", "on"))
def test_main_sidecar_branch_for_every_truthy_value(monkeypatch, capsys, value):
    monkeypatch.setenv("KKMAIL_SIDECAR", value)
    monkeypatch.setenv("MAIL_CORE_PORT", "29654")
    fake_app = ModuleType("mail_core.api.app")
    fake_app.app = object()
    monkeypatch.setitem(sys.modules, "mail_core.api.app", fake_app)
    import uvicorn

    web_calls = []
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: web_calls.append(kw))

    captured = {}

    class FakeServer:
        def __init__(self, config):
            self.config = config

        def run(self, sockets=None):
            captured["sockets"] = sockets
            captured["port"] = self.config.port

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    main_module.main(["--skip-migrations", "--no-worker"])
    out = capsys.readouterr().out
    assert "KKMAIL_SIDECAR_READY:" in out
    data = json.loads(out.split("KKMAIL_SIDECAR_READY:")[1].strip())
    assert data["port"] == 29654
    assert captured["sockets"] and captured["port"] == 29654
    assert web_calls == []


# Retired (A13 follow-up): _is_dated_revision / _single_alembic_revision /
# _legacy_revision_error were dead helpers in mail_core.__main__ and are now
# removed. Database-state classification is unified in
# mail_core.db.baseline.plan_migration, which run_migrations() and the offline
# migration tool both call. The tests that invoked those three private helpers
# directly (test_single_alembic_revision_* here, test_legacy_guard_* here and
# in test_runtime_adopt_regression.py) merely endorsed dead code, so they are
# deleted wholesale rather than rewritten in place. The live-path test below
# (test_run_migrations_refuses_multiple_alembic_version_rows) is unrelated and
# kept unchanged.


def test_run_migrations_refuses_multiple_alembic_version_rows(monkeypatch):
    import sqlalchemy

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return ["20261107_0001", "20261108_0002"]

    class FakeConn:
        def execute(self, statement):
            return FakeResult()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConn()

        def dispose(self):
            pass

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url: FakeEngine())
    # A2 follow-up: state reading moved into baseline.read_database_state, so
    # the inspector fake must patch the reference that function actually
    # uses (mail_core.db.baseline.inspect), not sqlalchemy.inspect.
    monkeypatch.setattr(
        "mail_core.db.baseline.inspect",
        lambda conn: SimpleNamespace(get_table_names=lambda: ["alembic_version"]),
    )
    monkeypatch.setattr(
        "mail_core.db.session.database_url", lambda: "postgresql://unused-for-test"
    )
    with pytest.raises(RuntimeError, match="alembic_version"):
        main_module.run_migrations()


# test_legacy_guard_distinguishes_revision_cases was here; retired together
# with the three dead __main__ helpers (see the note above).


def test_port_zero_startup_normalizes_sidecar_into_env(monkeypatch, capsys):
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.delenv("MAIL_CORE_PORT", raising=False)
    monkeypatch.delenv("MAIL_CORE_HOST", raising=False)
    fake_app = ModuleType("mail_core.api.app")
    fake_app.app = object()
    monkeypatch.setitem(sys.modules, "mail_core.api.app", fake_app)
    import uvicorn

    captured = {}

    class FakeServer:
        def __init__(self, config):
            self.config = config

        def run(self, sockets=None):
            captured["sockets"] = sockets
            captured["port"] = self.config.port

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(uvicorn, "run", lambda _app, **kw: None)

    main_module.main(["--port", "0", "--skip-migrations", "--no-worker"])

    out = capsys.readouterr().out
    assert "KKMAIL_SIDECAR_READY:" in out
    assert os.environ["KKMAIL_SIDECAR"] == "1"
    assert is_sidecar_enabled() is True
    assert is_sidecar_enabled(os.environ) is True

    meta = get_oauth_metadata("microsoft")
    assert meta["runtime_mode"] == "desktop"
    assert meta["redirect_uri"] is not None
    assert meta["redirect_uri"].startswith("http://localhost:")
