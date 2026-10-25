from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mail_core.realtime.listener import OutboxListenThread, _dsn_from_settings, _normalize_listen_dsn


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://db.example/mail",
        "postgresql+psycopg://db.example/mail",
        "postgresql+psycopg2://db.example/mail",
    ],
)
def test_normalize_listen_dsn_accepts_supported_postgresql_schemes(url):
    assert _normalize_listen_dsn(url) == "postgresql://db.example/mail"


def test_dsn_from_settings_rejects_unsupported_scheme(monkeypatch):
    monkeypatch.setattr(
        "mail_core.db.session.database_url",
        lambda: "postgresql+asyncpg://user:password@db.example/mail",
    )

    with pytest.raises(ValueError, match="scheme is unsupported for LISTEN") as error:
        _dsn_from_settings()

    assert "password" not in str(error.value)


def test_listen_connection_uses_five_second_connect_timeout(monkeypatch):
    connect_args = {}
    connection = SimpleNamespace(
        execute=lambda _query: None,
        close=lambda: None,
    )
    listener = OutboxListenThread(
        SimpleNamespace(dispatch_once=lambda **_kwargs: None),
        dsn="postgresql://db.example/mail",
    )

    def connect(dsn, **kwargs):
        connect_args.update(dsn=dsn, **kwargs)
        listener._stop.set()
        return connection

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    listener._run()

    assert connect_args == {
        "dsn": "postgresql://db.example/mail",
        "autocommit": True,
        "connect_timeout": 5,
    }
