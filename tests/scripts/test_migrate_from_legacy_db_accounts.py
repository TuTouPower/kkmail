import uuid
from types import SimpleNamespace

from scripts.migrate_from_legacy_db import _update_account_from_legacy


def test_existing_account_updates_legacy_owned_fields_and_preserves_runtime_state():
    group_id = uuid.uuid4()
    account = SimpleNamespace(
        provider="imap",
        credential_ref="account:old@example.com",
        display_name="Old name",
        config={"imap_host": "old.example.com"},
        group_id=None,
        sync_enabled=True,
        sync_status="failed",
        master_order=7,
        group_order=3,
    )
    config = {"imap_host": "imap.example.com", "imap_port": 993, "use_ssl": True}

    _update_account_from_legacy(
        account,
        provider="imap",
        credential_ref="account:new@example.com",
        display_name="New name",
        config=config,
        group_id=group_id,
        sync_enabled=False,
    )

    assert account.provider == "imap"
    assert account.credential_ref == "account:new@example.com"
    assert account.display_name == "New name"
    assert account.config == config
    assert account.group_id == group_id
    assert account.sync_enabled is False
    assert account.sync_status == "failed"
    assert account.master_order == 7
    assert account.group_order == 3
