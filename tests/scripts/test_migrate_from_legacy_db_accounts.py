import uuid
from types import SimpleNamespace

from scripts.migrate_from_legacy_db import _update_account_from_legacy


def test_existing_account_updates_legacy_owned_fields_and_preserves_runtime_state():
    # t076: 旧 Account.sync_status 单列已移除，账号运行时健康状态改由
    # credential_state/connectivity_state/sync_activity 三维 + config 诊断表达。
    # 迁移仍只收敛 legacy-owned 字段；旧断言
    # assert account.sync_status == "failed" 整体重写为四个健康字段保留断言，
    # 禁止把旧预期字符串就地改成新字段。
    group_id = uuid.uuid4()
    account = SimpleNamespace(
        provider="imap",
        credential_ref="account:old@example.com",
        display_name="Old name",
        config={"imap_host": "old.example.com"},
        group_id=None,
        sync_enabled=True,
        credential_state="invalid",
        connectivity_state="unreachable",
        sync_activity="syncing",
        last_connectivity_error=None,
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
    assert account.credential_state == "invalid"
    assert account.connectivity_state == "unreachable"
    assert account.sync_activity == "syncing"
    assert account.last_connectivity_error is None
    assert account.master_order == 7
    assert account.group_order == 3
