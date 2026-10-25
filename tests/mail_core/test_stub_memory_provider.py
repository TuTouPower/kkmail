from dataclasses import replace

from mail_core.providers.base import RemoteMessageMeta
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
