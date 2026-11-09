"""Focused regression tests for adopted runtime review findings."""

from __future__ import annotations

import builtins
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mail_core import __main__ as main_module
from mail_core.config import ConfigError, load_config, reset_config
from mail_core.security import auth as auth_module

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(REPO_ROOT / "src")


@pytest.fixture(autouse=True)
def _clean_config():
    reset_config()
    yield
    reset_config()


def _install_fake_app_and_server(monkeypatch, captured):
    fake_app_module = ModuleType("mail_core.api.app")
    fake_app_module.app = object()
    monkeypatch.setitem(sys.modules, "mail_core.api.app", fake_app_module)
    import uvicorn

    class FakeServer:
        def __init__(self, config):
            self.config = config

        def run(self, sockets=None):
            captured["sockets"] = sockets
            captured["port"] = self.config.port

    monkeypatch.setattr(uvicorn, "Server", FakeServer)


def test_sidecar_writes_bound_port_back_to_env_for_oauth(monkeypatch, capsys):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("MAIL_CORE_PORT", "0")
    monkeypatch.delenv("MAIL_CORE_HOST", raising=False)
    captured = {}
    _install_fake_app_and_server(monkeypatch, captured)

    main_module.main(["--skip-migrations", "--no-worker"])

    out = capsys.readouterr().out
    data = json.loads(out.split("KKMAIL_SIDECAR_READY:")[1].strip())
    assert isinstance(data["port"], int) and data["port"] > 0
    assert os.environ["MAIL_CORE_PORT"] == str(data["port"])
    assert captured["port"] == data["port"]

    from mail_core.accounts.oauth_flow import get_oauth_metadata

    meta = get_oauth_metadata("microsoft")
    assert meta["runtime_mode"] == "desktop"
    assert meta["redirect_uri"] == (
        f"http://localhost:{data['port']}/api/accounts/oauth/callback/microsoft"
    )


def test_bootstrap_imports_without_fcntl_and_reaches_win32_lock():
    script = r"""
import sys
import types
import tempfile
from pathlib import Path

sys.modules["fcntl"] = None
sys.platform = "win32"
msvcrt = types.ModuleType("msvcrt")
msvcrt.LK_LOCK = 1
msvcrt.LK_UNLCK = 2
locked = []
msvcrt.locking = lambda fd, mode, n: locked.append(mode)
sys.modules["msvcrt"] = msvcrt

import mail_core.runtime.bootstrap as b
assert b.fcntl is None, "fcntl must be optional on win32"
d = Path(tempfile.mkdtemp())
with b._bootstrap_lock(d):
    pass
assert 1 in locked and 2 in locked, "win32/msvcrt lock branch must be reachable"
print("OK")
"""
    env = {**os.environ, "PYTHONPATH": SRC_DIR}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# Retired (A13 follow-up): these three tests called the now-removed dead
# helpers main_module._legacy_revision_error / _single_alembic_revision /
# _is_dated_revision directly. Database-state classification has been unified
# in mail_core.db.baseline.plan_migration (used by run_migrations() and the
# offline migration tool), so the helpers are gone and these tests, which only
# endorsed dead code, are deleted wholesale instead of being rewritten in
# place. _fake_script was their sole support and is removed with them.


def test_port_zero_requires_sidecar_flag():
    with pytest.raises(ConfigError, match="sidecar"):
        load_config({"MAIL_CORE_PORT": "0"})
    cfg = load_config({"MAIL_CORE_PORT": "0", "KKMAIL_SIDECAR": "1"})
    assert cfg.port == 0 and cfg.sidecar is True


def test_sidecar_socket_family_supports_ipv6_host():
    assert main_module._sidecar_address_family("127.0.0.1") == socket.AF_INET
    assert main_module._sidecar_address_family("::1") == socket.AF_INET6


def test_password_hash_write_fsyncs_parent_directory_after_replace(tmp_path, monkeypatch):
    fsynced = []
    real_fsync = os.fsync

    def tracking_fsync(fd):
        fsynced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)
    target = tmp_path / "nested" / "login-password.bcrypt"
    payload = b"$2b$" + b"x" * 56
    auth_module._write_password_hash_file(target, payload)
    assert len(fsynced) == 2
    assert target.read_bytes() == payload


def test_password_hash_write_closes_fd_and_removes_tmp_on_open_failure(tmp_path, monkeypatch):
    opened = {}
    closed = []
    real_os_open = os.open
    real_os_close = os.close

    def tracking_open(path, flags, *args, **kwargs):
        fd = real_os_open(path, flags, *args, **kwargs)
        opened["fd"] = fd
        return fd

    def tracking_close(fd):
        closed.append(fd)
        return real_os_close(fd)

    def fail_open(*args, **kwargs):
        raise OSError("simulated open(fd) failure")

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", tracking_close)
    monkeypatch.setattr(auth_module, "open", fail_open, raising=False)

    with pytest.raises(OSError, match="simulated open"):
        auth_module._write_password_hash_file(
            tmp_path / "login-password.bcrypt", b"hash"
        )

    assert opened.get("fd") is not None
    assert closed == [opened["fd"]]
    assert list(tmp_path.glob(".*tmp*")) == []
