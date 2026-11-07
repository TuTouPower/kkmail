# bundle_local_docs_archive_tasks_b

## responsibilities

- 归档并保存 t027 至 t075 演进期任务的背景需求、契约区、行为 AC、实现进度及收尾验收回执
- 记录账号分组拖拽、按需正文归档、IMAP IDLE 实时监听与巡检、高并发执行器、写回管道等重大重构的验证事实
- 留存各 task 独立的 review_code.md / review_test.md / review_general.md 复审凭据

## interfaces

- task.md：契约区范围、非范围与细化 AC
- handoff.json：包含 git hash、验证命令与最终 status 的执行回执
- review_code.md / review_test.md：多视角复核记录与 diff anchor

## dependencies

- src/mail_core/、src/frontend/、src/desktop/ 源码演进历史
- .repo_template/ 工作流管理与模板契约

## flows

- 复杂特性通过 task 分解与 TDD 落地，完成复审后由工具链归档至 docs/archive/tasks/

## constraints

- 归档文件只追加不修改原则（隐私安全修复除外）
- 公开仓绝对禁止写入开发机私有绝对路径与凭据特征

## decisions

- t061、t063、t064、t068、t074、t075 等系列架构重构，通过 task 链路清晰保留了方案论证与技术取舍
- t027 补充了 reference_demo.html 作为前端交互原型的保真参考

## evidence

- docs/archive/tasks/t027_account_group_ordering/task.md:1-35
- docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/review_code.md:6
- docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md:6

## uncertainties

- 后续任务归档时如何通过 pre-commit 钩子强制阻断 review 记录中再次带入本地绝对路径

## Findings

- [Medium][100] docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md:6 — 归档任务 review 文件硬编码开发者本地绝对路径及系统用户名
    - ID: f_docs_archive_tasks_b_absolute_paths_in_reviews; verification: static
    - Evidence: docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md:6 及 review_test.md:6 原包含宿主机私有绝对路径 target：git -C '<workspace>/kkmail_t075'（现已脱敏并勘误）；docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/review_code.md:6 及 review_test.md:6 原包含本地工作区绝对路径 target：git -C '<workspace>/kkmail_t061'（现已脱敏并勘误）；此问题此前已在第三轮审阅 docs/archive/reviews/review_20261025_020805/bundle_privacy_history.md 与第四轮审阅中被定为 Medium，但在新增任务归档时再次被带入
    - Impact: 在公开开源仓库暴露维护者的本地工作目录层级与操作系统用户名，违反公开仓安全基线
    - Fix: 对 docs/archive/tasks/t061/ 及 t075/ 的 review_code.md 与 review_test.md 执行脱敏清洗，将本地绝对路径统一替换为相对路径或占位符（如 git -C '<local-path>'），并在 CI/pre-commit 增加路径门禁

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_docs"
  }
}
```

## files_reviewed

```json
[
  "docs/archive/tasks/t027_account_group_ordering/handoff.json",
  "docs/archive/tasks/t027_account_group_ordering/progress.md",
  "docs/archive/tasks/t027_account_group_ordering/reference_demo.html",
  "docs/archive/tasks/t027_account_group_ordering/review_code.md",
  "docs/archive/tasks/t027_account_group_ordering/review_test.md",
  "docs/archive/tasks/t027_account_group_ordering/source_notes.md",
  "docs/archive/tasks/t027_account_group_ordering/task.md",
  "docs/archive/tasks/t028_group_mail_scope/progress.md",
  "docs/archive/tasks/t028_group_mail_scope/task.md",
  "docs/archive/tasks/t029_sidebar_group_navigation/progress.md",
  "docs/archive/tasks/t029_sidebar_group_navigation/task.md",
  "docs/archive/tasks/t030_sidebar_group_management/progress.md",
  "docs/archive/tasks/t030_sidebar_group_management/task.md",
  "docs/archive/tasks/t031_sidebar_drag_ordering/progress.md",
  "docs/archive/tasks/t031_sidebar_drag_ordering/task.md",
  "docs/archive/tasks/t032_sidebar_shell_controls/handoff.json",
  "docs/archive/tasks/t032_sidebar_shell_controls/macos_window_validation.md",
  "docs/archive/tasks/t032_sidebar_shell_controls/progress.md",
  "docs/archive/tasks/t032_sidebar_shell_controls/review_general.md",
  "docs/archive/tasks/t032_sidebar_shell_controls/task.md",
  "docs/archive/tasks/t033_message_list_total_count_and_infinite_scroll/handoff.json",
  "docs/archive/tasks/t033_message_list_total_count_and_infinite_scroll/progress.md",
  "docs/archive/tasks/t033_message_list_total_count_and_infinite_scroll/review_general.md",
  "docs/archive/tasks/t033_message_list_total_count_and_infinite_scroll/task.md",
  "docs/archive/tasks/t034_on_demand_body_sync_and_archive_priority/handoff.json",
  "docs/archive/tasks/t034_on_demand_body_sync_and_archive_priority/progress.md",
  "docs/archive/tasks/t034_on_demand_body_sync_and_archive_priority/review_code.md",
  "docs/archive/tasks/t034_on_demand_body_sync_and_archive_priority/review_test.md",
  "docs/archive/tasks/t034_on_demand_body_sync_and_archive_priority/task.md",
  "docs/archive/tasks/t035_partial_provider_metadata/handoff.json",
  "docs/archive/tasks/t035_partial_provider_metadata/progress.md",
  "docs/archive/tasks/t035_partial_provider_metadata/review_code.md",
  "docs/archive/tasks/t035_partial_provider_metadata/review_test.md",
  "docs/archive/tasks/t035_partial_provider_metadata/task.md",
  "docs/archive/tasks/t036_mail_datetime_provenance/handoff.json",
  "docs/archive/tasks/t036_mail_datetime_provenance/progress.md",
  "docs/archive/tasks/t036_mail_datetime_provenance/review_code.md",
  "docs/archive/tasks/t036_mail_datetime_provenance/review_test.md",
  "docs/archive/tasks/t036_mail_datetime_provenance/task.md",
  "docs/archive/tasks/t037_legacy_migration_fidelity/handoff.json",
  "docs/archive/tasks/t037_legacy_migration_fidelity/progress.md",
  "docs/archive/tasks/t037_legacy_migration_fidelity/review_code.md",
  "docs/archive/tasks/t037_legacy_migration_fidelity/review_test.md",
  "docs/archive/tasks/t037_legacy_migration_fidelity/task.md",
  "docs/archive/tasks/t038_reader_recipient_truth/handoff.json",
  "docs/archive/tasks/t038_reader_recipient_truth/progress.md",
  "docs/archive/tasks/t038_reader_recipient_truth/review_general.md",
  "docs/archive/tasks/t038_reader_recipient_truth/task.md",
  "docs/archive/tasks/t039_folder_stats_scope_truth/handoff.json",
  "docs/archive/tasks/t039_folder_stats_scope_truth/progress.md",
  "docs/archive/tasks/t039_folder_stats_scope_truth/review_general.md",
  "docs/archive/tasks/t039_folder_stats_scope_truth/task.md",
  "docs/archive/tasks/t040_mail_data_truth_docs/progress.md",
  "docs/archive/tasks/t040_mail_data_truth_docs/review_general.md",
  "docs/archive/tasks/t040_mail_data_truth_docs/task.md",
  "docs/archive/tasks/t041_unknown_mail_status/progress.md",
  "docs/archive/tasks/t041_unknown_mail_status/review_code.md",
  "docs/archive/tasks/t041_unknown_mail_status/review_test.md",
  "docs/archive/tasks/t041_unknown_mail_status/task.md",
  "docs/archive/tasks/t042_partial_provider_delta/progress.md",
  "docs/archive/tasks/t042_partial_provider_delta/review_code.md",
  "docs/archive/tasks/t042_partial_provider_delta/review_test.md",
  "docs/archive/tasks/t042_partial_provider_delta/task.md",
  "docs/archive/tasks/t043_reader_preview_closure/progress.md",
  "docs/archive/tasks/t043_reader_preview_closure/review_general.md",
  "docs/archive/tasks/t043_reader_preview_closure/task.md",
  "docs/archive/tasks/t044_sidebar_tree_alignment/handoff.json",
  "docs/archive/tasks/t044_sidebar_tree_alignment/progress.md",
  "docs/archive/tasks/t044_sidebar_tree_alignment/review_general.md",
  "docs/archive/tasks/t044_sidebar_tree_alignment/task.md",
  "docs/archive/tasks/t045_account_sync_failure_and_unread_stats/handoff.json",
  "docs/archive/tasks/t045_account_sync_failure_and_unread_stats/progress.md",
  "docs/archive/tasks/t045_account_sync_failure_and_unread_stats/review_code.md",
  "docs/archive/tasks/t045_account_sync_failure_and_unread_stats/review_test.md",
  "docs/archive/tasks/t045_account_sync_failure_and_unread_stats/task.md",
  "docs/archive/tasks/t046_mail_list_cache_isolation/handoff.json",
  "docs/archive/tasks/t046_mail_list_cache_isolation/progress.md",
  "docs/archive/tasks/t046_mail_list_cache_isolation/review_general.md",
  "docs/archive/tasks/t046_mail_list_cache_isolation/task.md",
  "docs/archive/tasks/t047_dark_palette_and_reader_copy/handoff.json",
  "docs/archive/tasks/t047_dark_palette_and_reader_copy/progress.md",
  "docs/archive/tasks/t047_dark_palette_and_reader_copy/review_general.md",
  "docs/archive/tasks/t047_dark_palette_and_reader_copy/task.md",
  "docs/archive/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/handoff.json",
  "docs/archive/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/progress.md",
  "docs/archive/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/review_code.md",
  "docs/archive/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/review_test.md",
  "docs/archive/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/task.md",
  "docs/archive/tasks/t049_sync_retry_double_enqueue/handoff.json",
  "docs/archive/tasks/t049_sync_retry_double_enqueue/progress.md",
  "docs/archive/tasks/t049_sync_retry_double_enqueue/review_code.md",
  "docs/archive/tasks/t049_sync_retry_double_enqueue/review_test.md",
  "docs/archive/tasks/t049_sync_retry_double_enqueue/task.md",
  "docs/archive/tasks/t050_imap_noselect_and_graph_transient_retry/handoff.json",
  "docs/archive/tasks/t050_imap_noselect_and_graph_transient_retry/progress.md",
  "docs/archive/tasks/t050_imap_noselect_and_graph_transient_retry/review_general.md",
  "docs/archive/tasks/t050_imap_noselect_and_graph_transient_retry/task.md",
  "docs/archive/tasks/t051_mailbox_folder_role_aliases/handoff.json",
  "docs/archive/tasks/t051_mailbox_folder_role_aliases/progress.md",
  "docs/archive/tasks/t051_mailbox_folder_role_aliases/review_code.md",
  "docs/archive/tasks/t051_mailbox_folder_role_aliases/review_test.md",
  "docs/archive/tasks/t051_mailbox_folder_role_aliases/task.md",
  "docs/archive/tasks/t052_qq_noselect_folder_state/handoff.json",
  "docs/archive/tasks/t052_qq_noselect_folder_state/progress.md",
  "docs/archive/tasks/t052_qq_noselect_folder_state/review_code.md",
  "docs/archive/tasks/t052_qq_noselect_folder_state/review_test.md",
  "docs/archive/tasks/t052_qq_noselect_folder_state/task.md",
  "docs/archive/tasks/t053_provider_account_forms/progress.md",
  "docs/archive/tasks/t053_provider_account_forms/review_code.md",
  "docs/archive/tasks/t053_provider_account_forms/review_test.md",
  "docs/archive/tasks/t053_provider_account_forms/task.md",
  "docs/archive/tasks/t054_google_oauth_callback/progress.md",
  "docs/archive/tasks/t054_google_oauth_callback/review_code.md",
  "docs/archive/tasks/t054_google_oauth_callback/review_test.md",
  "docs/archive/tasks/t054_google_oauth_callback/task.md",
  "docs/archive/tasks/t055_microsoft_oauth_callback/progress.md",
  "docs/archive/tasks/t055_microsoft_oauth_callback/review_code.md",
  "docs/archive/tasks/t055_microsoft_oauth_callback/review_test.md",
  "docs/archive/tasks/t055_microsoft_oauth_callback/task.md",
  "docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/handoff.json",
  "docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/progress.md",
  "docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/review_code.md",
  "docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/review_test.md",
  "docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/task.md",
  "docs/archive/tasks/t057_periodic_inbox_sync_and_auto_archive/handoff.json",
  "docs/archive/tasks/t057_periodic_inbox_sync_and_auto_archive/progress.md",
  "docs/archive/tasks/t057_periodic_inbox_sync_and_auto_archive/review_code.md",
  "docs/archive/tasks/t057_periodic_inbox_sync_and_auto_archive/review_test.md",
  "docs/archive/tasks/t057_periodic_inbox_sync_and_auto_archive/task.md",
  "docs/archive/tasks/t058_centralized_config_and_runtime_params/handoff.json",
  "docs/archive/tasks/t058_centralized_config_and_runtime_params/progress.md",
  "docs/archive/tasks/t058_centralized_config_and_runtime_params/review_code.md",
  "docs/archive/tasks/t058_centralized_config_and_runtime_params/review_test.md",
  "docs/archive/tasks/t058_centralized_config_and_runtime_params/task.md",
  "docs/archive/tasks/t059_imap_idle_inbox_realtime/progress.md",
  "docs/archive/tasks/t059_imap_idle_inbox_realtime/task.md",
  "docs/archive/tasks/t060_all_folder_status_periodic_patrol/progress.md",
  "docs/archive/tasks/t060_all_folder_status_periodic_patrol/task.md",
  "docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/handoff.json",
  "docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/progress.md",
  "docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/review_code.md",
  "docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/review_test.md",
  "docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/task.md",
  "docs/archive/tasks/t062_outbox_and_job_notify_wake/handoff.json",
  "docs/archive/tasks/t062_outbox_and_job_notify_wake/progress.md",
  "docs/archive/tasks/t062_outbox_and_job_notify_wake/review_code.md",
  "docs/archive/tasks/t062_outbox_and_job_notify_wake/review_test.md",
  "docs/archive/tasks/t062_outbox_and_job_notify_wake/task.md",
  "docs/archive/tasks/t063_worker_concurrent_executor/handoff.json",
  "docs/archive/tasks/t063_worker_concurrent_executor/progress.md",
  "docs/archive/tasks/t063_worker_concurrent_executor/review_code.md",
  "docs/archive/tasks/t063_worker_concurrent_executor/review_test.md",
  "docs/archive/tasks/t063_worker_concurrent_executor/task.md",
  "docs/archive/tasks/t064_batched_remote_writeback/handoff.json",
  "docs/archive/tasks/t064_batched_remote_writeback/progress.md",
  "docs/archive/tasks/t064_batched_remote_writeback/review_code.md",
  "docs/archive/tasks/t064_batched_remote_writeback/review_test.md",
  "docs/archive/tasks/t064_batched_remote_writeback/task.md",
  "docs/archive/tasks/t065_dark_mode_mail_body_inversion/handoff.json",
  "docs/archive/tasks/t065_dark_mode_mail_body_inversion/progress.md",
  "docs/archive/tasks/t065_dark_mode_mail_body_inversion/review_general.md",
  "docs/archive/tasks/t065_dark_mode_mail_body_inversion/task.md",
  "docs/archive/tasks/t066_remote_images_persist_and_reload/handoff.json",
  "docs/archive/tasks/t066_remote_images_persist_and_reload/progress.md",
  "docs/archive/tasks/t066_remote_images_persist_and_reload/review_code.md",
  "docs/archive/tasks/t066_remote_images_persist_and_reload/review_test.md",
  "docs/archive/tasks/t066_remote_images_persist_and_reload/task.md",
  "docs/archive/tasks/t067_reader_isolated_html_endpoint/progress.md",
  "docs/archive/tasks/t067_reader_isolated_html_endpoint/task.md",
  "docs/archive/tasks/t068_remote_image_proxy/handoff.json",
  "docs/archive/tasks/t068_remote_image_proxy/progress.md",
  "docs/archive/tasks/t068_remote_image_proxy/review_code.md",
  "docs/archive/tasks/t068_remote_image_proxy/review_test.md",
  "docs/archive/tasks/t068_remote_image_proxy/task.md",
  "docs/archive/tasks/t069_remote_image_extract_and_fetch_robustness/handoff.json",
  "docs/archive/tasks/t069_remote_image_extract_and_fetch_robustness/progress.md",
  "docs/archive/tasks/t069_remote_image_extract_and_fetch_robustness/review_code.md",
  "docs/archive/tasks/t069_remote_image_extract_and_fetch_robustness/review_test.md",
  "docs/archive/tasks/t069_remote_image_extract_and_fetch_robustness/task.md",
  "docs/archive/tasks/t070_remote_image_connect_total_budget/handoff.json",
  "docs/archive/tasks/t070_remote_image_connect_total_budget/progress.md",
  "docs/archive/tasks/t070_remote_image_connect_total_budget/review_code.md",
  "docs/archive/tasks/t070_remote_image_connect_total_budget/review_test.md",
  "docs/archive/tasks/t070_remote_image_connect_total_budget/task.md",
  "docs/archive/tasks/t071_idle_connect_catchup_inbox_delta/handoff.json",
  "docs/archive/tasks/t071_idle_connect_catchup_inbox_delta/progress.md",
  "docs/archive/tasks/t071_idle_connect_catchup_inbox_delta/review_code.md",
  "docs/archive/tasks/t071_idle_connect_catchup_inbox_delta/review_test.md",
  "docs/archive/tasks/t071_idle_connect_catchup_inbox_delta/task.md",
  "docs/archive/tasks/t072_t061_idle_watcher_red_test_repair/handoff.json",
  "docs/archive/tasks/t072_t061_idle_watcher_red_test_repair/progress.md",
  "docs/archive/tasks/t072_t061_idle_watcher_red_test_repair/review_general.md",
  "docs/archive/tasks/t072_t061_idle_watcher_red_test_repair/task.md",
  "docs/archive/tasks/t073_idle_catchup_enqueue_failure_selfheal/handoff.json",
  "docs/archive/tasks/t073_idle_catchup_enqueue_failure_selfheal/progress.md",
  "docs/archive/tasks/t073_idle_catchup_enqueue_failure_selfheal/review_code.md",
  "docs/archive/tasks/t073_idle_catchup_enqueue_failure_selfheal/review_test.md",
  "docs/archive/tasks/t073_idle_catchup_enqueue_failure_selfheal/task.md",
  "docs/archive/tasks/t074_inbox_first_account_sync/handoff.json",
  "docs/archive/tasks/t074_inbox_first_account_sync/progress.md",
  "docs/archive/tasks/t074_inbox_first_account_sync/review_code.md",
  "docs/archive/tasks/t074_inbox_first_account_sync/review_test.md",
  "docs/archive/tasks/t074_inbox_first_account_sync/task.md",
  "docs/archive/tasks/t075_backup_export_permission_boundary/handoff.json",
  "docs/archive/tasks/t075_backup_export_permission_boundary/progress.md",
  "docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md",
  "docs/archive/tasks/t075_backup_export_permission_boundary/review_test.md",
  "docs/archive/tasks/t075_backup_export_permission_boundary/task.md"
]
```
