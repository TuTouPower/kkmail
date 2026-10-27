"""A366: DeltaChange.kind must be validated, and flag patches must only
carry is_read / is_flagged.

Before the fix an unknown kind was silently ignored by apply_delta_page
(a provider bug became a silent sync hole), and a flag patch containing
an arbitrary key flowed into ``replace(older, **flags)`` during page
coalescing, raising TypeError and killing the whole delta page.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import mail_core.sync.delta as delta
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.sync.delta import _flag_patch_values


def test_unknown_delta_change_kind_is_rejected_at_construction():
    with pytest.raises(ValueError, match="kind"):
        DeltaChange(kind="teleport", remote_id="r1")
    for kind in ("upsert", "delete", "flag"):
        assert DeltaChange(kind=kind, remote_id="r1").kind == kind


def test_flag_patch_values_keep_only_read_and_flagged_keys():
    change = DeltaChange(
        kind="flag",
        remote_id="r1",
        flags={"is_read": True, "is_flagged": False, "subject": "boom", "evil": 1},
    )
    assert _flag_patch_values(change) == {"is_read": True, "is_flagged": False}


def test_arbitrary_flag_key_does_not_crash_page_coalescing(monkeypatch):
    captured = {}

    def _upsert(_session, **kwargs):
        captured["metas"] = kwargs["metas"]
        return [
            SimpleNamespace(
                changed=False,
                created=False,
                message=SimpleNamespace(id=uuid.uuid4(), thread_id=None),
            )
            for _ in kwargs["metas"]
        ]

    monkeypatch.setattr(delta, "assert_fencing", lambda *_a, **_k: None)
    monkeypatch.setattr(delta, "upsert_messages", _upsert)
    monkeypatch.setattr(delta, "upsert_message_search", lambda *_a, **_k: None)
    monkeypatch.setattr(delta, "_apply_flag_patches", lambda *_a, **_k: (0, []))
    monkeypatch.setattr(delta, "commit_checkpoint", lambda *_a, **_k: None)

    class Session:
        def add(self, _value):
            pass

        def flush(self):
            pass

        def scalars(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [])

        def scalar(self, *_args, **_kwargs):
            return None

    first = RemoteMessageMeta(
        remote_id="r1",
        subject="One",
        from_address="sender@example.test",
        from_name=None,
        sort_time=None,
        is_read=True,
        has_attachments=False,
    )
    second = RemoteMessageMeta(
        remote_id="r1",
        subject="Two",
        from_address="sender@example.test",
        from_name=None,
        sort_time=None,
        is_read=None,
        has_attachments=None,
        supplied_fields=frozenset({"subject"}),
    )
    page = DeltaPage(
        changes=[
            DeltaChange(kind="upsert", remote_id="r1", meta=first),
            DeltaChange(
                kind="flag",
                remote_id="r1",
                flags={"not_a_meta_field": 123, "is_read": False},
            ),
            DeltaChange(kind="upsert", remote_id="r1", meta=second),
        ],
        next_cursor={"historyId": "next"},
        exhausted=True,
    )

    delta.apply_delta_page(
        Session(),
        account_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        fencing_token=1,
        page=page,
    )

    (merged,) = captured["metas"]
    assert merged.subject == "Two"
    assert merged.is_read is False
