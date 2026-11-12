"""A214 / t076: Account model column layout.

账号同步状态写入函数及其死代码测试已删除；对应生产函数已删除，
改由 health 状态机测试覆盖（test_account_health_state_machine.py）。
``last_synced_at`` 仍只存在于 config["last_synced_at"]，不是列属性；
``Account.sync_status`` 列已被三个正交健康列替换。
"""

from __future__ import annotations


def test_account_model_has_no_last_synced_at_column():
    from mail_core.mail.storage.models import Account

    assert "last_synced_at" not in Account.__table__.columns


def test_account_model_replaces_sync_status_with_health_columns():
    from mail_core.mail.storage.models import Account

    columns = Account.__table__.columns
    assert "sync_status" not in columns
    assert "credential_state" in columns
    assert "connectivity_state" in columns
    assert "sync_activity" in columns
