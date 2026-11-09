"""Regression tests for unified sidecar detection and migration startup guards."""

from __future__ import annotations

import json
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


def _fake_script(heads, revisions):
    revs = [SimpleNamespace(revision=r) for r in revisions]
    return SimpleNamespace(
        get_heads=lambda: list(heads),
        walk_revisions=lambda: iter(revs),
    )


def test_single_alembic_revision_accepts_zero_or_one_row():
    assert main_module._single_alembic_revision([]) is None
    assert main_module._single_alembic_revision(["20261107_0001"]) == "20261107_0001"


def test_single_alembic_revision_rejects_multiple_rows():
    with pytest.raises(RuntimeError, match="alembic_version") as excinfo:
        main_module._single_alembic_revision(["20261107_0001", "20261108_0002"])
    message = str(excinfo.value)
    assert "2 rows" in message
    assert "20261107_0001" in message and "20261108_0002" in message


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
    monkeypatch.setattr(
        sqlalchemy,
        "inspect",
        lambda conn: SimpleNamespace(get_table_names=lambda: ["alembic_version"]),
    )
    monkeypatch.setattr(
        "mail_core.db.session.database_url", lambda: "postgresql://unused-for-test"
    )
    with pytest.raises(RuntimeError, match="alembic_version"):
        main_module.run_migrations()


def test_legacy_guard_distinguishes_revision_cases():
    script = _fake_script(["20261108_0002"], ["20261108_0002", "20261107_0001"])
    assert main_module._legacy_revision_error("20261107_0001", script) is None

    newer = main_module._legacy_revision_error("20261109_0001", script)
    older = main_module._legacy_revision_error("20261021_0003", script)
    unknown = main_module._legacy_revision_error("f5f312751c77", script)

    assert newer and "version mismatch" in newer and "20261108_0002" in newer
    assert older and "migrate_to_unified_baseline.py" in older and "20261108_0002" in older
    assert unknown and "legacy" in unknown and "backup" in unknown and "20261108_0002" in unknown
    assert len({newer, older, unknown}) == 3
