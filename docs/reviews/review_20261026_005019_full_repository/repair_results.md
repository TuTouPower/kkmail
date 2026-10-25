# kkmail 审阅问题与 p045–p052 修复验收总结

- 交付时间：`2026-10-26T03:50:00+08:00`
- 最终集成分支：`review_fix/integration`
- 基线 SHA：`332de0ff7ed00f0be8725dba647b1ec0035ff8ab`

## 1. 22 项来源最终解决状态表

|编号|来源|类别|最终状态|实施交付 SHA / 对应工作包|核心验证证据|
|---|---|---|---|---|---|
|01|P1-01|安全|已修复|`008825b8` (F02)|`test_backup_package.py::test_validate_blob_members_matrix`, `test_validate_restore_destination_matrix`|
|02|P1-02|安全|已修复|`a7992618` (F02)|`test_backup_package.py::test_restore_database_identity_ignores_username_and_normalizes_aliases`, `test_backup_restore_drill_live.py`|
|03|P1-03|并发|已修复|`8af7746c` (F03)|`test_job_successor_atomicity.py::test_enqueue_during_complete_never_loses_wakeup`, `test_enqueue_never_returns_terminal_done_job`|
|04|P1-04|实时|已修复|`e08160f6`, `da7daaf6` (F07)|`test_outbox_publication_order.py`, `test_sse_outbox.py`|
|05|P1-05|安全|已修复|`b3a7f311` (F01)|`test_logging_trace_and_redact.py::test_redacting_trace_formatter_provider_exception_chain_never_leaks_body_or_token`|
|06|P2-01|调度|已修复|`f53b1a99` (F03)|`test_sync_hardening_a27_a28_a29.py::test_a27_sync_folder_delta_sanitizes_errors`, `test_worker_loop.py`|
|07|P2-02|数据|已修复|`7ba43b3c` (F05)|`test_delta_flag_patch.py::test_multilocation_flag_update_refreshes_all_folder_stats`|
|08|P2-03|数据|已修复|`bab48228` (F05)|`test_delta_flag_patch.py::test_multilocation_delete_single_location_refreshes_stats_and_emits_event`|
|09|P2-04|协议|已修复|`a4180e96` (F05)|`test_primary_location.py::test_resolve_imap_trash_folder`|
|10|P2-06|进程|已修复|`502ea11d` (F06)|`test_worker_loop.py::test_worker_heartbeat_loop_runs_independently_and_stops`|
|11|P2-07|指标|已修复|`7c4597f3` (F06)|`test_system_health.py::test_system_health_sync_metrics_with_real_sync_run_done_status`|
|12|P2-08|契约|已修复|`0b05890f` (F00), F07, F08, F10|`scripts/export_openapi.py --check`, `npm run openapi:check` 严格一致|
|13|P2-09|前端|已修复|`bdcc135b` (F09)|`App.tsx` 消除 `react/set-state-in-effect` 告警，`npm run lint` 0 警告|
|14|P2-10|前端|已修复|`af8b8342` (F09)|`clipboard.test.ts::appends textarea inside active dialog and restores focus`|
|15|p045|交互|已修复|`791b22f1` (F04)|`Sidebar.test.tsx::closes scoped search on outside pointerdown and outside focusout`|
|16|p046|交互|已修复|`22ce64e9`, `38e51d6c` (F10)|`MessageList.test.tsx` 增量同步与全量同步分离，移除成功横条|
|17|p047|性能|已修复|`22ce64e9`, `d94b017b`, `2107c33f` (F10)|跨进程 8 槽连接管控与 JobPriority 调度优先级划分|
|18|p048|体验|已修复|`50014f6b` (F08)|`test_on_demand_body_sync.py::test_sync_body_idempotent`, `MessageReader.test.tsx` 隔离迟到请求|
|19|p049|布局|已修复|`0b7b2ebe` (F09)|`SettingsModal.test.tsx` 移除顶部冗余通栏，ST01 收纳进导航|
|20|p050|样式|已修复|`03c51465` (F04)|`.footer-btn` 常态透明弱化，hover/active/focus-visible 状态明确|
|21|p051|几何|已修复|`98da0f01` (F04)|`Sidebar.test.tsx` 收件箱在未读前，行缩进满足 24px 几何基准|
|22|p052|功能|已修复|`bb922e9b` (F11)|生产打包保留 `UiReferenceOverlay`，设置页支持开关与快捷键偏好|

## 2. 明确排除项说明

- **P1-06（桌面 CI 资产依赖）**：按计划明确排除，桌面端基础单测全部通过。
- **P2-05（健康指标匿名访问）**：按计划明确排除，端点保持现有开放口径，契约由 OpenAPI 忠实导出。

## 3. 全局门禁验证结果

- 前端：Vitest 45 个测试文件（394 项用例）全绿；CSS 检查全绿；OpenAPI 契约校验全绿；`oxlint --deny-warnings` 0 警告；Vite 生产构建成功。
- 桌面端：`npm --prefix src/desktop test` 11 项套件全部通过。
- 后端：数据库迁移升至 `20261026_0024`；所有新特性与缺陷回归用例全部通过；工具链契约测试 150 passed。
