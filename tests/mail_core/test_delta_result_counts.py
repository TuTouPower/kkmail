from __future__ import annotations

import uuid
from types import SimpleNamespace

import mail_core.sync.delta as delta
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta


def test_delta_apply_counts_only_changed_upserts(monkeypatch):
    outcomes = [
        SimpleNamespace(changed=True, created=True, message=SimpleNamespace(id=uuid.uuid4(), thread_id=None)),
        SimpleNamespace(changed=False, created=False, message=SimpleNamespace(id=uuid.uuid4(), thread_id=None)),
    ]
    monkeypatch.setattr(delta, "assert_fencing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "upsert_messages", lambda *_args, **_kwargs: outcomes)
    monkeypatch.setattr(delta, "upsert_message_search", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "_apply_flag_patches", lambda *_args, **_kwargs: (0, []))
    monkeypatch.setattr(delta, "messages_upserted_event", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(delta, "recompute_folder_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "commit_checkpoint", lambda *_args, **_kwargs: None)

    class Session:
        # Package C test-contract adaptation: apply_delta_page legitimately
        # queries shared folders via session.scalars(...).all(); the fake
        # models "no shared folders" instead of lacking the method.
        def add(self, _value):
            pass

        def flush(self):
            pass

        def scalars(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [])

        def scalar(self, *_args, **_kwargs):
            return None

    metas = [
        RemoteMessageMeta(
            remote_id=f"remote-{index}",
            subject="subject",
            from_address="sender@example.test",
            from_name=None,
            sort_time=None,
            is_read=None,
            has_attachments=None,
        )
        for index in range(2)
    ]
    page = DeltaPage(
        changes=[DeltaChange(kind="upsert", remote_id=meta.remote_id, meta=meta) for meta in metas],
        next_cursor={"historyId": "next"},
        exhausted=False,
    )

    result = delta.apply_delta_page(
        Session(),
        account_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        fencing_token=1,
        page=page,
    )

    assert result.upserted == 1
