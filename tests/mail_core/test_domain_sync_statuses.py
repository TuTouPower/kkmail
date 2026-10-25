from mail_core.mail.domain import SyncRunStatus, SyncStatus


def test_sync_status_values_match_persisted_account_and_folder_states():
    assert {status.value for status in SyncStatus} == {
        "idle",
        "running",
        "paused",
        "failed",
        "auth_failed",
    }


def test_sync_run_status_values_match_persisted_run_states():
    assert {status.value for status in SyncRunStatus} == {"running", "done"}
