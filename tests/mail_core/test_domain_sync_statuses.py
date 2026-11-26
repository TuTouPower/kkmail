from mail_core.mail.domain import FolderRemoteState, FolderRole, SyncRunStatus
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    SyncActivity,
)


# t092: 旧 SyncStatus 枚举与 Folder.sync_status 列已被正交模型替换并移除；
# 原 test_sync_status_values_match_persisted_folder_states 整体删除，新增
# test_folder_role_and_remote_state_enums 覆盖新的域枚举与向后清理契约。
def test_folder_role_and_remote_state_enums():
    import mail_core.mail.domain as domain_pkg
    import mail_core.mail.domain.enums as domain_enums

    assert not hasattr(domain_pkg, "SyncStatus")
    assert not hasattr(domain_enums, "SyncStatus")
    assert {state.value for state in FolderRemoteState} == {"active", "missing"}
    assert {role.value for role in FolderRole} == {
        "inbox",
        "junk",
        "trash",
        "sent",
        "drafts",
        "archive",
        "all",
        "flagged",
        "important",
        "other",
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
