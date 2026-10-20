from unittest.mock import patch

import web_outlook_app as appmod


def test_sidecar_mode_flag(monkeypatch):
    for value, expected in (("1", True), ("true", True), ("", False), ("0", False)):
        monkeypatch.setenv("KKMAIL_SIDECAR", value)
        assert appmod.is_sidecar_mode() is expected


def test_frozen_sidecar_skips_tray_and_browser(monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "1")
    monkeypatch.setenv("PORT", "5999")
    with patch.object(appmod, "is_frozen", return_value=True), \
            patch.object(appmod, "run_desktop_app") as desktop, \
            patch.object(appmod.webbrowser, "open") as browser, \
            patch.object(appmod.threading, "Timer") as timer, \
            patch.object(appmod, "init_scheduler"), \
            patch.object(appmod.app, "run") as run:
        appmod.main()
    desktop.assert_not_called()
    browser.assert_not_called()
    timer.assert_not_called()
    run.assert_called_once()


def test_frozen_without_sidecar_opens_browser_on_linux(monkeypatch):
    monkeypatch.setenv("KKMAIL_SIDECAR", "0")
    with patch.object(appmod, "is_frozen", return_value=True), \
            patch.object(appmod.os, "name", "posix"), \
            patch.object(appmod.sys, "platform", "linux"), \
            patch.object(appmod.threading, "Timer") as timer, \
            patch.object(appmod, "init_scheduler"), \
            patch.object(appmod.app, "run"):
        appmod.main()
    timer.assert_called_once()
