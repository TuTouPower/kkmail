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


def _meta(remote_id: str) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=remote_id,
        subject="subject",
        from_address="sender@example.test",
        from_name=None,
        sort_time=None,
        is_read=False,
        has_attachments=False,
    )


def test_metadata_paging_anchors_on_remote_id_not_offset():
    # A370: offset paging skips/repeats entries when the list mutates
    # mid-scan. Paging must anchor on the last returned remote_id so a
    # deletion/insertion before the scan position cannot shift the window.
    provider = MemoryProvider(page_size=2)
    provider.seed("INBOX", [_meta(f"m{i}") for i in range(1, 6)])

    page1 = provider.fetch_metadata_page("INBOX", None)
    assert [m.remote_id for m in page1.items] == ["m1", "m2"]
    assert page1.exhausted is False

    # Deleting an already-returned entry shifts an offset window left,
    # which would skip m3 — anchored paging must not.
    provider.remove_message("INBOX", "m1")

    page2 = provider.fetch_metadata_page("INBOX", page1.next_cursor)
    assert [m.remote_id for m in page2.items] == ["m3", "m4"]

    page3 = provider.fetch_metadata_page("INBOX", page2.next_cursor)
    assert [m.remote_id for m in page3.items] == ["m5"]
    assert page3.exhausted is True

    seen = [m.remote_id for m in page1.items + page2.items + page3.items]
    assert sorted(seen) == ["m1", "m2", "m3", "m4", "m5"]
    assert len(seen) == len(set(seen))


def test_metadata_paging_does_not_repeat_after_insert_before_cursor():
    # Inserting before the scan position shifts an offset window right,
    # which would repeat m2 — anchored paging must not.
    provider = MemoryProvider(page_size=2)
    provider.seed("INBOX", [_meta(f"m{i}") for i in range(1, 6)])

    page1 = provider.fetch_metadata_page("INBOX", None)
    assert [m.remote_id for m in page1.items] == ["m1", "m2"]
    provider.messages["INBOX"].insert(0, _meta("m0"))

    page2 = provider.fetch_metadata_page("INBOX", page1.next_cursor)
    assert [m.remote_id for m in page2.items] == ["m3", "m4"]


def test_metadata_paging_survives_anchor_deletion():
    # If the anchor entry itself is deleted mid-scan, paging must still
    # terminate and must not repeat already-returned entries.
    provider = MemoryProvider(page_size=2)
    provider.seed("INBOX", [_meta(f"m{i}") for i in range(1, 6)])

    page1 = provider.fetch_metadata_page("INBOX", None)
    provider.remove_message("INBOX", "m2")  # the anchor itself

    seen = [m.remote_id for m in page1.items]
    cursor = page1.next_cursor
    for _ in range(10):
        page = provider.fetch_metadata_page("INBOX", cursor)
        seen.extend(m.remote_id for m in page.items)
        cursor = page.next_cursor
        if page.exhausted:
            break
    else:  # pragma: no cover - loop must terminate via exhausted
        raise AssertionError("paging did not terminate")
    assert len(seen) == len(set(seen))
    assert set(seen) <= {"m1", "m2", "m3", "m4", "m5"}
