# bundle_local_docs_archive_tasks_a

## responsibilities

- 归档并保存 t001 至 t026 早期任务的需求背景、契约定义、行为验收标准（AC）及实现进度
- 留存早期任务的代码审阅与测试审阅报告，提供完整的工程追溯凭证
- 在 docs/archive/tasks/README.md 中统领归档规范，声明历史快照属性与三态划分

## interfaces

- task.md：任务范围与可独立观察的 AC-NNN 行为验收标准
- handoff.json：包含 task_id、git commit、测试结果与收尾元数据的机器可读回执
- progress.md：任务生命周期状态与执行推进轨迹记录

## dependencies

- docs/specs_index.md 与历史 spec 积累
- .repo_template/scripts/task.py 任务管理工具链

## flows

- 任务生命周期归档流：task 在 docs/tasks/ 创建、实施并完成复审后，由 task-integrate 脚本整体原子迁移至 docs/archive/tasks/

## constraints

- 历史归档只读约束：仅允许追加，禁止破坏或篡改历史记录
- 三态定义：本目录下所有 task 均为历史执行时点快照，不代表现行真理契约

## decisions

- t013-t023 批次经用户授权直接在 main 分支顺序执行，无 handoff.json，在 README.md 明确统筹声明免责
- 早期本地绝对路径在前期审阅中已通过 <local-path> 脱敏占位处理

## evidence

- docs/archive/tasks/README.md:1-11
- docs/archive/tasks/t001_mail_core_sent_query/task.md:1-30
- docs/archive/tasks/t026_mime_archive_decode_failure/task.md:1-25

## uncertainties

- 早期任务中部分关于已废弃模块（如旧版状态角标逻辑）的 AC 描述已不适用于现行代码，依赖 README 统一免责

## Findings

- [Info][85] docs/archive/tasks/README.md:1-11 — 早期归档 task 契约与现行实现存在演进漂移（已在 README 免责声明）
    - ID: f_docs_archive_tasks_a_historical_ac_drift; verification: static
    - Evidence: t001 至 t012 中部分关于未读统计与分类视图的 AC 已在后续 t027/t041/t045 中被重构替代; docs/archive/tasks/README.md:1-7 明确声明本目录下各 task 为历史快照，不代表现行契约，现行以 docs/specs/ 为准
    - Impact: 无负面影响；若读者未读 README 直接引用早期 task.md 可能误解当前系统行为
    - Fix: 保持现状，继续维持 README.md 的统领免责约定

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
  "docs/archive/tasks/README.md",
  "docs/archive/tasks/t001_mail_core_sent_query/handoff.json",
  "docs/archive/tasks/t001_mail_core_sent_query/progress.md",
  "docs/archive/tasks/t001_mail_core_sent_query/review_general.md",
  "docs/archive/tasks/t001_mail_core_sent_query/task.md",
  "docs/archive/tasks/t002_frontend_favorites_views/handoff.json",
  "docs/archive/tasks/t002_frontend_favorites_views/progress.md",
  "docs/archive/tasks/t002_frontend_favorites_views/review_general.md",
  "docs/archive/tasks/t002_frontend_favorites_views/task.md",
  "docs/archive/tasks/t003_reader_toolbar_and_context_menu/handoff.json",
  "docs/archive/tasks/t003_reader_toolbar_and_context_menu/progress.md",
  "docs/archive/tasks/t003_reader_toolbar_and_context_menu/review_general.md",
  "docs/archive/tasks/t003_reader_toolbar_and_context_menu/task.md",
  "docs/archive/tasks/t004_fix_accounts_dto_and_sidebar_error/handoff.json",
  "docs/archive/tasks/t004_fix_accounts_dto_and_sidebar_error/progress.md",
  "docs/archive/tasks/t004_fix_accounts_dto_and_sidebar_error/review_general.md",
  "docs/archive/tasks/t004_fix_accounts_dto_and_sidebar_error/task.md",
  "docs/archive/tasks/t005_sync_refresh_and_imap_id/handoff.json",
  "docs/archive/tasks/t005_sync_refresh_and_imap_id/progress.md",
  "docs/archive/tasks/t005_sync_refresh_and_imap_id/review_general.md",
  "docs/archive/tasks/t005_sync_refresh_and_imap_id/task.md",
  "docs/archive/tasks/t006_dark_reader_theme/handoff.json",
  "docs/archive/tasks/t006_dark_reader_theme/progress.md",
  "docs/archive/tasks/t006_dark_reader_theme/review_code.md",
  "docs/archive/tasks/t006_dark_reader_theme/review_test.md",
  "docs/archive/tasks/t006_dark_reader_theme/task.md",
  "docs/archive/tasks/t007_imap_header_decode/handoff.json",
  "docs/archive/tasks/t007_imap_header_decode/progress.md",
  "docs/archive/tasks/t007_imap_header_decode/review_code.md",
  "docs/archive/tasks/t007_imap_header_decode/review_test.md",
  "docs/archive/tasks/t007_imap_header_decode/task.md",
  "docs/archive/tasks/t008_account_folder_navigation/handoff.json",
  "docs/archive/tasks/t008_account_folder_navigation/progress.md",
  "docs/archive/tasks/t008_account_folder_navigation/review_code.md",
  "docs/archive/tasks/t008_account_folder_navigation/review_test.md",
  "docs/archive/tasks/t008_account_folder_navigation/task.md",
  "docs/archive/tasks/t009_sidebar_full_hide/handoff.json",
  "docs/archive/tasks/t009_sidebar_full_hide/progress.md",
  "docs/archive/tasks/t009_sidebar_full_hide/review_general.md",
  "docs/archive/tasks/t009_sidebar_full_hide/task.md",
  "docs/archive/tasks/t010_account_icon_preference/handoff.json",
  "docs/archive/tasks/t010_account_icon_preference/progress.md",
  "docs/archive/tasks/t010_account_icon_preference/review_general.md",
  "docs/archive/tasks/t010_account_icon_preference/task.md",
  "docs/archive/tasks/t011_ui_reference/handoff.json",
  "docs/archive/tasks/t011_ui_reference/progress.md",
  "docs/archive/tasks/t011_ui_reference/review_general.md",
  "docs/archive/tasks/t011_ui_reference/task.md",
  "docs/archive/tasks/t012_mark_read_convergence/handoff.json",
  "docs/archive/tasks/t012_mark_read_convergence/progress.md",
  "docs/archive/tasks/t012_mark_read_convergence/review_code.md",
  "docs/archive/tasks/t012_mark_read_convergence/review_test.md",
  "docs/archive/tasks/t012_mark_read_convergence/task.md",
  "docs/archive/tasks/t013_test_pg_runtime/progress.md",
  "docs/archive/tasks/t013_test_pg_runtime/review_code.md",
  "docs/archive/tasks/t013_test_pg_runtime/task.md",
  "docs/archive/tasks/t014_backend_test_isolation/progress.md",
  "docs/archive/tasks/t014_backend_test_isolation/review_code.md",
  "docs/archive/tasks/t014_backend_test_isolation/review_test.md",
  "docs/archive/tasks/t014_backend_test_isolation/task.md",
  "docs/archive/tasks/t015_frontend_test_runtime/progress.md",
  "docs/archive/tasks/t015_frontend_test_runtime/review_general.md",
  "docs/archive/tasks/t015_frontend_test_runtime/task.md",
  "docs/archive/tasks/t016_mail_protocol_integration/progress.md",
  "docs/archive/tasks/t016_mail_protocol_integration/review_code.md",
  "docs/archive/tasks/t016_mail_protocol_integration/review_test.md",
  "docs/archive/tasks/t016_mail_protocol_integration/task.md",
  "docs/archive/tasks/t017_full_stack_e2e/progress.md",
  "docs/archive/tasks/t017_full_stack_e2e/review_code.md",
  "docs/archive/tasks/t017_full_stack_e2e/review_test.md",
  "docs/archive/tasks/t017_full_stack_e2e/task.md",
  "docs/archive/tasks/t018_migration_validation/progress.md",
  "docs/archive/tasks/t018_migration_validation/review_code.md",
  "docs/archive/tasks/t018_migration_validation/review_test.md",
  "docs/archive/tasks/t018_migration_validation/task.md",
  "docs/archive/tasks/t019_backup_restore_drill/progress.md",
  "docs/archive/tasks/t019_backup_restore_drill/review_code.md",
  "docs/archive/tasks/t019_backup_restore_drill/review_test.md",
  "docs/archive/tasks/t019_backup_restore_drill/task.md",
  "docs/archive/tasks/t020_worker_process_recovery/progress.md",
  "docs/archive/tasks/t020_worker_process_recovery/review_code.md",
  "docs/archive/tasks/t020_worker_process_recovery/review_test.md",
  "docs/archive/tasks/t020_worker_process_recovery/task.md",
  "docs/archive/tasks/t021_desktop_packaged_smoke/progress.md",
  "docs/archive/tasks/t021_desktop_packaged_smoke/review_code.md",
  "docs/archive/tasks/t021_desktop_packaged_smoke/review_test.md",
  "docs/archive/tasks/t021_desktop_packaged_smoke/task.md",
  "docs/archive/tasks/t022_mailbox_performance_baseline/progress.md",
  "docs/archive/tasks/t022_mailbox_performance_baseline/review_general.md",
  "docs/archive/tasks/t022_mailbox_performance_baseline/task.md",
  "docs/archive/tasks/t023_test_quality_gates/progress.md",
  "docs/archive/tasks/t023_test_quality_gates/review_code.md",
  "docs/archive/tasks/t023_test_quality_gates/review_test.md",
  "docs/archive/tasks/t023_test_quality_gates/task.md",
  "docs/archive/tasks/t024_sidebar_folder_tree_layout/handoff.json",
  "docs/archive/tasks/t024_sidebar_folder_tree_layout/progress.md",
  "docs/archive/tasks/t024_sidebar_folder_tree_layout/review_general.md",
  "docs/archive/tasks/t024_sidebar_folder_tree_layout/task.md",
  "docs/archive/tasks/t025_desktop_clipboard_copy/handoff.json",
  "docs/archive/tasks/t025_desktop_clipboard_copy/progress.md",
  "docs/archive/tasks/t025_desktop_clipboard_copy/review_code.md",
  "docs/archive/tasks/t025_desktop_clipboard_copy/review_test.md",
  "docs/archive/tasks/t025_desktop_clipboard_copy/task.md",
  "docs/archive/tasks/t026_mime_archive_decode_failure/handoff.json",
  "docs/archive/tasks/t026_mime_archive_decode_failure/progress.md",
  "docs/archive/tasks/t026_mime_archive_decode_failure/review_code.md",
  "docs/archive/tasks/t026_mime_archive_decode_failure/review_test.md",
  "docs/archive/tasks/t026_mime_archive_decode_failure/task.md"
]
```
