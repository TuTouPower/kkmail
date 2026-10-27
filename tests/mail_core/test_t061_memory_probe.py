"""t061 f007 residue: MemoryProvider.probe_folder_status + patrol
default provider factory.

The patrol's stub-account production path goes through
``_default_provider_factory`` -> ``build_provider`` -> MemoryProvider;
these tests pin that adapter's probe semantics (unread counting,
modseq normalisation, unknown folder -> None) and the factory wiring.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from mail_core.mail.storage.models import Account
from mail_core.providers.base import FolderStatus, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync.patrol import _default_provider_factory


def _meta(remote_id: str, *, is_read: bool | None) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=remote_id,
        subject="s",
        from_address="a@example.com",
        from_name=None,
        sort_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_read=is_read,
        has_attachments=False,
    )


def test_memory_probe_counts_messages_and_unread():
    provider = MemoryProvider(
        messages={
            "Sent": [
                _meta("m1", is_read=True),
                _meta("m2", is_read=False),
                _meta("m3", is_read=False),
                _meta("m4", is_read=None),
            ]
        },
        modseq={"Sent": 9},
    )
    assert provider.probe_folder_status("Sent") == FolderStatus(
        messages=4, uidnext=None, unseen=2, highestmodseq=9
    )


def test_memory_probe_zero_modseq_normalises_to_none():
    provider = MemoryProvider(messages={"Sent": []}, modseq={"Sent": 0})
    status = provider.probe_folder_status("Sent")
    assert status is not None
    assert status.messages == 0
    assert status.highestmodseq is None


def test_memory_probe_unknown_folder_returns_none():
    provider = MemoryProvider(messages={})
    assert provider.probe_folder_status("Nope") is None


def test_default_factory_builds_memory_provider_for_stub_accounts():
    account = Account(
        id=uuid.uuid4(),
        email="stub@example.com",
        provider="stub",
        credential_ref="ref",
        config={"folders": [{"remote_id": "INBOX", "name": "INBOX", "role": "inbox"}]},
    )
    provider = _default_provider_factory(account)
    assert isinstance(provider, MemoryProvider)
    # The factory-built provider answers probes (unseeded folder -> None,
    # which the patrol treats as a failed probe, never as "no change").
    assert provider.probe_folder_status("INBOX") is None
