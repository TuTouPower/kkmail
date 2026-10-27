"""A289: list_folders well-known resolution must only swallow 404s.

Capacity / rate-limit failures are deferral signals, not "endpoint does
not exist": swallowing them produced wrong folder roles and wasted the
remaining well-known calls. Non-404 HTTP errors propagate likewise.
"""

from __future__ import annotations

import pytest

from mail_core.providers.connection_slots import ProviderCapacityUnavailable
from mail_core.providers.graph import GraphProvider
from mail_core.providers.http import ProviderHttpError, RateLimitedError

_WELL_KNOWN_IDS = {
    "inbox": "fid-inbox",
    "sentitems": "fid-sent",
    "deleteditems": "fid-trash",
    "drafts": "fid-drafts",
    "junkemail": "fid-junk",
    "archive": "fid-archive",
}


def _transport_with_failure(failing_name: str, exc: BaseException):
    def transport(method, path, params):
        for name, fid in _WELL_KNOWN_IDS.items():
            if path == f"/me/mailFolders/{name}":
                if name == failing_name:
                    raise exc
                return {"id": fid, "displayName": name, "childFolderCount": 0}
        if path == "/me/mailFolders":
            return {
                "value": [
                    {"id": fid, "displayName": name, "childFolderCount": 0}
                    for name, fid in _WELL_KNOWN_IDS.items()
                ]
            }
        return {}

    return transport


def test_a289_missing_well_known_endpoint_404_is_swallowed():
    transport = _transport_with_failure(
        "archive", ProviderHttpError("not found", status=404, body="missing")
    )
    folders = GraphProvider(credential_ref="x", transport=transport).list_folders()
    roles = {f.remote_id: f.role for f in folders}
    assert roles["fid-archive"] == "other"
    assert roles["fid-sent"] == "sent"


def test_a289_rate_limited_well_known_call_propagates():
    transport = _transport_with_failure("inbox", RateLimitedError("slow down"))
    with pytest.raises(RateLimitedError):
        GraphProvider(credential_ref="x", transport=transport).list_folders()


def test_a289_capacity_error_well_known_call_propagates():
    transport = _transport_with_failure(
        "inbox", ProviderCapacityUnavailable("connection budget saturated")
    )
    with pytest.raises(ProviderCapacityUnavailable):
        GraphProvider(credential_ref="x", transport=transport).list_folders()


def test_a289_non_404_http_error_well_known_call_propagates():
    transport = _transport_with_failure(
        "inbox", ProviderHttpError("server error", status=500, body="boom")
    )
    with pytest.raises(ProviderHttpError) as caught:
        GraphProvider(credential_ref="x", transport=transport).list_folders()
    assert caught.value.status == 500
