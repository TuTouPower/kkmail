"""A172: coalescing repeated upserts in one delta page must not let a
later partial projection erase facts an earlier change already supplied.

The merge claimed "unknown parsed values never erase earlier known
facts" but only protected sort_time/is_read/is_flagged/has_attachments;
every other field (snippet, from_name, uid, thread key, ...) was wiped
when the newer projection carried None for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import mail_core.sync.delta as delta
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta


def test_newer_none_values_never_erase_earlier_known_facts(monkeypatch):
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
    monkeypatch.setattr(
        delta,
        "assign_thread_for_message",
        lambda *_a, **_k: SimpleNamespace(thread_id=None),
    )

    class Session:
        def add(self, _value):
            pass

        def flush(self):
            pass

        def scalars(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [])

        def scalar(self, *_args, **_kwargs):
            return None

    now = datetime.now(timezone.utc)
    older = RemoteMessageMeta(
        remote_id="r1",
        subject="Old subject",
        from_address="sender@example.test",
        from_name="Alice",
        sort_time=now,
        is_read=True,
        has_attachments=True,
        is_flagged=False,
        internet_message_id="<m1@example.test>",
        snippet="known snippet",
        provider_thread_key="thread-1",
        uid=42,
        size_bytes=1234,
    )
    newer = RemoteMessageMeta(
        remote_id="r1",
        subject="New subject",
        from_address="sender@example.test",
        from_name=None,
        sort_time=None,
        is_read=None,
        has_attachments=None,
        is_flagged=None,
        internet_message_id=None,
        snippet=None,
        provider_thread_key=None,
        uid=None,
        size_bytes=None,
        supplied_fields=frozenset(
            {
                "subject",
                "from_name",
                "sort_time",
                "is_read",
                "has_attachments",
                "is_flagged",
                "internet_message_id",
                "snippet",
                "provider_thread_key",
                "uid",
                "size_bytes",
            }
        ),
    )
    page = DeltaPage(
        changes=[
            DeltaChange(kind="upsert", remote_id="r1", meta=older),
            DeltaChange(kind="upsert", remote_id="r1", meta=newer),
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
    # Known newer facts still win.
    assert merged.subject == "New subject"
    # Unknown (None) newer values must not erase any earlier known fact —
    # not only the four previously protected fields.
    assert merged.from_name == "Alice"
    assert merged.sort_time == now
    assert merged.is_read is True
    assert merged.has_attachments is True
    assert merged.is_flagged is False
    assert merged.internet_message_id == "<m1@example.test>"
    assert merged.snippet == "known snippet"
    assert merged.provider_thread_key == "thread-1"
    assert merged.uid == 42
    assert merged.size_bytes == 1234
