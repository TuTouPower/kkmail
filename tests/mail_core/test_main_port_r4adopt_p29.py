"""A216: an invalid MAIL_CORE_PORT must fail as an argparse error
(SystemExit with a usage message), not as a bare ValueError traceback
from ``int()`` evaluated while the parser is being built. The env value
and the ``--port`` flag share one validation callable.
"""

from __future__ import annotations

import pytest

from mail_core import __main__ as main_module


def test_invalid_env_port_is_argparse_error(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_PORT", "not-a-port")
    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["--skip-migrations", "--no-worker"])
    assert excinfo.value.code == 2


def test_invalid_cli_port_is_argparse_error(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_PORT", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["--port", "eighty", "--skip-migrations", "--no-worker"])
    assert excinfo.value.code == 2


def test_valid_env_port_still_parses(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_PORT", "8123")
    captured = {}

    import sys
    from types import ModuleType

    fake_app_module = ModuleType("mail_core.api.app")
    fake_app_module.app = object()
    monkeypatch.setitem(sys.modules, "mail_core.api.app", fake_app_module)
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda _app, **kwargs: captured.update(kwargs))
    main_module.main(["--skip-migrations", "--no-worker"])
    assert captured["port"] == 8123
