"""A369: apply_remote_operation must not AttributeError on non-dict
transport responses; they are normalized to {} (branch fallbacks apply)
so the RemoteOperationResult channel is preserved.
"""

from __future__ import annotations

import pytest

from mail_core.providers.graph import GraphProvider


def _provider_returning(payload) -> GraphProvider:
    def transport(method, path, params):
        return payload

    return GraphProvider(credential_ref="x", transport=transport)


@pytest.mark.parametrize("payload", [["not-a-dict"], "plain-string", None, 42])
def test_a369_mark_read_non_dict_response_succeeds_with_requested_state(payload):
    provider = _provider_returning(payload)
    result = provider.apply_remote_operation(
        "mark_read", {"remote_id": "m1", "is_read": False}
    )
    assert result.success is True
    assert result.remote_state == {"is_read": False}


def test_a369_move_non_dict_response_falls_back_to_destination():
    provider = _provider_returning(["moved"])
    result = provider.apply_remote_operation(
        "move", {"remote_id": "m1", "dest_folder_remote_id": "dest-1"}
    )
    assert result.success is True
    assert result.remote_state == {"folder_remote_id": "dest-1", "id": "m1"}


def test_a369_set_flag_non_dict_response_succeeds():
    provider = _provider_returning("ok")
    result = provider.apply_remote_operation(
        "set_flag", {"remote_id": "m1", "is_flagged": True}
    )
    assert result.success is True
    assert result.remote_state == {"is_flagged": True, "flag": None}


def test_a369_dict_response_still_uses_server_state():
    provider = _provider_returning({"isRead": True})
    result = provider.apply_remote_operation(
        "mark_read", {"remote_id": "m1", "is_read": True}
    )
    assert result.success is True
    assert result.remote_state == {"is_read": True}
