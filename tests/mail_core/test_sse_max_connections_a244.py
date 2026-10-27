"""A244: the SSE connection cap must track MAIL_CORE_SSE_MAX_CONNECTIONS.

Pre-fix, ``_max_sse_connections`` cached the first parsed value for
the whole process lifetime, so changing the env var (config reload,
tests, ops tuning) silently had no effect until a restart. The cache
now records the raw env value it was parsed from and re-parses when
the current raw value differs.
"""

from __future__ import annotations

import pytest

from mail_core.api import sse as sse_mod


@pytest.fixture(autouse=True)
def _reset_cap_cache(monkeypatch):
    monkeypatch.setattr(sse_mod, "_sse_max_connections_cache", None)
    yield
    monkeypatch.setattr(sse_mod, "_sse_max_connections_cache", None)


def test_env_change_is_picked_up_without_process_restart(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SSE_MAX_CONNECTIONS", "64")
    assert sse_mod._max_sse_connections() == 64
    monkeypatch.setenv("MAIL_CORE_SSE_MAX_CONNECTIONS", "32")
    assert sse_mod._max_sse_connections() == 32
    monkeypatch.delenv("MAIL_CORE_SSE_MAX_CONNECTIONS")
    assert sse_mod._max_sse_connections() == 128


def test_invalid_value_after_valid_one_falls_back_and_warns(monkeypatch, caplog):
    monkeypatch.setenv("MAIL_CORE_SSE_MAX_CONNECTIONS", "64")
    assert sse_mod._max_sse_connections() == 64
    monkeypatch.setenv("MAIL_CORE_SSE_MAX_CONNECTIONS", "bogus")
    with caplog.at_level("WARNING", logger="mail_core.api.sse"):
        assert sse_mod._max_sse_connections() == 128
        # Same raw value: cached, no second warning.
        assert sse_mod._max_sse_connections() == 128
    assert caplog.text.count("invalid MAIL_CORE_SSE_MAX_CONNECTIONS") == 1
