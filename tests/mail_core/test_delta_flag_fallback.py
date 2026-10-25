from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.sync import delta as delta_module


def test_flag_patch_applies_read_and_flag_values_from_meta(monkeypatch):
    from mail_core.sync.delta import _apply_flag_patches

    monkeypatch.setattr(
        "mail_core.sync.remote_push.get_unconverged_field_intents",
        lambda *_args, **_kwargs: {},
    )
    message = SimpleNamespace(
        remote_id="remote-1",
        id=uuid.uuid4(),
        is_read=False,
        is_flagged=False,
        updated_at=None,
    )

    class Session:
        def scalars(self, _statement):
            return [message]

        def flush(self):
            pass

    meta = RemoteMessageMeta(
        remote_id="remote-1",
        subject="",
        from_address="",
        from_name=None,
        sort_time=None,
        is_read=True,
        has_attachments=None,
        is_flagged=True,
    )

    changed, touched = _apply_flag_patches(
        Session(),
        account_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        changes=[DeltaChange(kind="flag", remote_id="remote-1", meta=meta)],
    )

    assert changed == 1
    assert touched == [message.id]
    assert message.is_read is True
    assert message.is_flagged is True


def test_delta_coalescer_keeps_flag_only_meta_changes(monkeypatch):
    received_changes = []
    monkeypatch.setattr(delta_module, "assert_fencing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta_module, "upsert_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        delta_module,
        "_apply_flag_patches",
        lambda _session, **kwargs: (received_changes.extend(kwargs["changes"]) or 0, []),
    )
    monkeypatch.setattr(delta_module, "commit_checkpoint", lambda *_args, **_kwargs: None)

    meta = RemoteMessageMeta(
        remote_id="remote:flagged",
        subject="",
        from_address="",
        from_name=None,
        sort_time=None,
        is_read=None,
        has_attachments=None,
        is_flagged=True,
    )
    delta_module.apply_delta_page(
        MagicMock(),
        account_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        fencing_token=1,
        page=DeltaPage(
            changes=[DeltaChange(kind="flag", remote_id=meta.remote_id, meta=meta)],
            next_cursor={"historyId": "2"},
            exhausted=True,
        ),
    )

    assert len(received_changes) == 1
    assert received_changes[0].remote_id == "remote:flagged"
    assert received_changes[0].flags == {"is_flagged": True}
