from dataclasses import replace

import pytest

import mail_core.providers.stub_memory as memory_module
from mail_core.providers.base import RemoteMessageMeta
from mail_core.providers.http import CursorInvalidError
from mail_core.providers.stub_memory import MemoryProvider


def test_flag_message_preserves_every_metadata_field():
    original = RemoteMessageMeta(
        remote_id="message-1",
        subject="Threaded message",
        from_address="sender@example.test",
        from_name="Sender",
        sort_time=None,
        is_read=False,
        has_attachments=True,
        is_flagged=True,
        internet_message_id="<message-1@example.test>",
        snippet="snippet",
        provider_thread_key="provider-thread-1",
        uid=17,
        size_bytes=123,
        to_addresses=("to@example.test",),
        cc_addresses=("cc@example.test",),
        in_reply_to="<parent@example.test>",
        references="<root@example.test> <parent@example.test>",
        supplied_fields=frozenset({"is_read", "in_reply_to", "references"}),
    )
    provider = MemoryProvider(messages={"INBOX": [original]})

    provider.flag_message("INBOX", original.remote_id, is_read=True)

    expected = replace(original, is_read=True)
    assert provider.messages["INBOX"][0] == expected
    assert provider.change_log["INBOX"][-1][1].meta == expected


def test_change_log_is_bounded_and_stale_cursors_request_rebuild(monkeypatch):
    monkeypatch.setattr(memory_module, "_MAX_CHANGE_LOG_ENTRIES", 2)
    provider = MemoryProvider()
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta(
                remote_id=f"message-{index}",
                subject="subject",
                from_address="sender@example.test",
                from_name=None,
                sort_time=None,
                is_read=False,
                has_attachments=False,
            )
            for index in range(3)
        ],
    )

    assert [modseq for modseq, _ in provider.change_log["INBOX"]] == [2, 3]
    assert provider.change_log_pruned_through["INBOX"] == 1
    with pytest.raises(CursorInvalidError, match="predates retained change history"):
        provider.delta_changes("INBOX", {"modseq": 0})

    page = provider.delta_changes("INBOX", {"modseq": 1})
    assert [change.remote_id for change in page.changes] == ["message-1", "message-2"]
