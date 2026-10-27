"""A271: a session stream whose epoch already changed must fail fast.

Pre-fix, the epoch check ran inside the stream generator after the
StreamingResponse was already committed: a revoked session received
a 200 with an empty body instead of an auth error. The endpoint now
verifies the epoch before returning the response and raises 401 on
mismatch, without consuming an SSE slot.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from mail_core.api import sse as sse_module
from mail_core.security.auth import AuthPrincipal


def _session_principal(epoch: int) -> AuthPrincipal:
    return AuthPrincipal(via="session", csrf_token="csrf", session_epoch=epoch)


def test_stale_epoch_raises_401_before_streaming(monkeypatch):
    monkeypatch.setattr(sse_module, "_get_session_epoch", lambda _force_refresh=False: 11)
    acquired = []
    monkeypatch.setattr(sse_module, "_acquire_sse_slot", lambda: acquired.append(True) or True)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            sse_module.stream_events(
                SimpleNamespace(),
                last_event_id=None,
                after=None,
                account_id=None,
                principal=_session_principal(10),
            )
        )
    assert excinfo.value.status_code == 401
    # The stale stream must not consume a connection slot.
    assert acquired == []


def test_current_epoch_passes_precheck_and_streams(monkeypatch):
    monkeypatch.setattr(sse_module, "_get_session_epoch", lambda _force_refresh=False: 10)
    monkeypatch.setattr(sse_module, "_acquire_sse_slot", lambda: True)
    released = []
    monkeypatch.setattr(sse_module, "_release_sse_slot", lambda: released.append(True))

    response = asyncio.run(
        sse_module.stream_events(
            SimpleNamespace(),
            last_event_id=None,
            after=None,
            account_id=None,
            principal=_session_principal(10),
        )
    )
    assert isinstance(response, StreamingResponse)
    asyncio.run(response.background())
    assert released == [True]


def test_api_key_principal_skips_epoch_precheck(monkeypatch):
    def _boom(_force_refresh=False):
        raise AssertionError("epoch lookup must not run for api_key principals")

    monkeypatch.setattr(sse_module, "_get_session_epoch", _boom)
    monkeypatch.setattr(sse_module, "_acquire_sse_slot", lambda: True)
    monkeypatch.setattr(sse_module, "_release_sse_slot", lambda: None)

    response = asyncio.run(
        sse_module.stream_events(
            SimpleNamespace(),
            last_event_id=None,
            after=None,
            account_id=None,
            principal=AuthPrincipal(via="api_key"),
        )
    )
    assert isinstance(response, StreamingResponse)
