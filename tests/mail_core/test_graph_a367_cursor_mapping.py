"""A367: _raise_mapped must not turn an ordinary 404 into CursorInvalid
just because the error body happens to contain the words "delta"/"sync".

CursorInvalid is reserved for: HTTP 410, explicit Graph error codes
(syncStateNotFound / resyncRequired), or a 404 from a delta/sync-cursor
endpoint (per oauth._url_is_sync_cursor_endpoint).
"""

from __future__ import annotations

import pytest

from mail_core.providers.graph import GraphProvider
from mail_core.providers.http import CursorInvalidError, ProviderHttpError


def _provider_raising(exc: ProviderHttpError) -> GraphProvider:
    def transport(method, path, params):
        raise exc

    return GraphProvider(credential_ref="x", transport=transport)


def test_a367_plain_404_with_delta_sync_words_in_body_stays_http_error():
    exc = ProviderHttpError(
        "not found", status=404, body="The delta sync folder could not be found"
    )
    provider = _provider_raising(exc)
    with pytest.raises(ProviderHttpError) as caught:
        provider.fetch_metadata_page("folder-1", None)
    assert not isinstance(caught.value, CursorInvalidError)
    assert caught.value.status == 404


def test_a367_404_from_delta_endpoint_is_cursor_invalid():
    exc = ProviderHttpError("not found", status=404, body="resource missing")
    provider = _provider_raising(exc)
    with pytest.raises(CursorInvalidError):
        provider.delta_changes("folder-1", {})


def test_a367_410_is_cursor_invalid_regardless_of_endpoint():
    exc = ProviderHttpError("gone", status=410, body="gone")
    provider = _provider_raising(exc)
    with pytest.raises(CursorInvalidError):
        provider.fetch_metadata_page("folder-1", None)


@pytest.mark.parametrize("code", ["syncStateNotFound", "resyncRequired"])
def test_a367_explicit_error_code_is_cursor_invalid(code):
    exc = ProviderHttpError(
        "bad request", status=400, body=f'{{"error": {{"code": "{code}"}}}}'
    )
    provider = _provider_raising(exc)
    with pytest.raises(CursorInvalidError):
        provider.fetch_metadata_page("folder-1", None)
