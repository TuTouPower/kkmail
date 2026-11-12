from mail_core.mail.domain import SyncRunStatus, SyncStatus
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    SyncActivity,
)


def test_sync_status_values_match_persisted_folder_states():
    # t076: SyncStatus 枚举仍存在，但仅用于 folders.sync_status；
    # 账号健康已改由三个正交枚举表达（见下方新断言）。
    assert {status.value for status in SyncStatus} == {
        "idle",
        "running",
        "paused",
        "failed",
        "auth_failed",
    }


def test_sync_run_status_values_match_persisted_run_states():
    assert {status.value for status in SyncRunStatus} == {"running", "done"}


def test_account_health_enums_match_persisted_account_states():
    # t076: 替代已移除 Account.sync_status 单列的三个正交枚举。
    assert {state.value for state in CredentialState} == {"valid", "invalid"}
    assert {state.value for state in ConnectivityState} == {
        "connected",
        "degraded",
        "unreachable",
    }
    assert {state.value for state in SyncActivity} == {"idle", "syncing"}
