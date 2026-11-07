"""Test typing annotation resolution for A1 modules."""

from __future__ import annotations

import typing
from typing import Any, Sequence

import mail_core.providers.remote_writeback as remote_writeback
import mail_core.search.index as search_index
import mail_core.worker.main as worker_main


def test_remote_writeback_type_hints():
    hints_compress = typing.get_type_hints(remote_writeback.compress_uids)
    assert hints_compress["uids"] == Sequence[int]

    hints_chunked = typing.get_type_hints(remote_writeback.compress_uids_chunked)
    assert hints_chunked["uids"] == Sequence[int]


def test_worker_main_getattr_type_hints():
    hints_getattr = typing.get_type_hints(worker_main.__getattr__)
    assert hints_getattr["return"] is Any


def test_search_index_format_recipient_text_type_hints():
    hints_recipient = typing.get_type_hints(search_index._format_recipient_text)
    assert hints_recipient["addresses"] == (Sequence[Any] | None)
