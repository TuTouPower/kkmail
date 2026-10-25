from __future__ import annotations

import os
import sys
from types import ModuleType

import uvicorn

from mail_core import __main__ as mail_core_main


def test_main_proxy_header_options_use_trusted_hosts_and_warn_without_them(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("MAIL_CORE_DATA_DIR", raising=False)
    warnings = []
    trusted_hosts_at_run = []
    fake_app_module = ModuleType("mail_core.api.app")
    fake_app_module.app = object()
    monkeypatch.setitem(sys.modules, "mail_core.api.app", fake_app_module)
    monkeypatch.setattr(mail_core_main.log, "warning", lambda message, *args: warnings.append(message % args))
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda _app, **_kwargs: trusted_hosts_at_run.append(os.environ.get("MAIL_CORE_FORWARDED_ALLOW_IPS")),
    )

    mail_core_main.main(["--skip-migrations", "--no-worker", "--proxy-headers"])
    assert trusted_hosts_at_run == [None]
    assert warnings == ["--proxy-headers requested without trusted proxy hosts; forwarded headers remain disabled"]

    warnings.clear()
    mail_core_main.main([
        "--skip-migrations",
        "--no-worker",
        "--proxy-headers",
        "--forwarded-allow-ips",
        "127.0.0.1",
    ])
    assert trusted_hosts_at_run[-1] == "127.0.0.1"
    assert warnings == []

    mail_core_main.main([
        "--skip-migrations",
        "--no-worker",
        "--forwarded-allow-ips",
        "192.0.2.10",
    ])
    assert trusted_hosts_at_run[-1] == "192.0.2.10"
