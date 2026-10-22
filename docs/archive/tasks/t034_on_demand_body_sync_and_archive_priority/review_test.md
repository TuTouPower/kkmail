# Task review t034（reviewer_focus: 测试）

- task：`t034_on_demand_body_sync_and_archive_priority`
- spec：`docs/tasks/t034_on_demand_body_sync_and_archive_priority/spec.md`
- diff_anchor：`ed3bfeecc579b99de892b9c364de03101efb9531`
- target：`git -C '/Users/karson/kar/code/kkmail_t034' diff ed3bfeecc579b99de892b9c364de03101efb9531`
- round：1
- reviewed_at：2026-10-23T14:20:00+08:00

reviewed_scope: 86dfd16022521d64

## Findings

无。

## 验收标准覆盖复核 (AC Verification)

- [x] **AC-001**：对处于 `metadata_synced` 状态的邮件，调用按需正文同步接口或请求详情时，能将该邮件置为最高归档优先级（priority=10），并成功触发即时归档任务
  - 验证证据：`tests/mail_core/test_on_demand_body_sync.py::test_ac001_get_message_unarchived_escalates_priority_and_enqueues_job`
  - 验证逻辑：对数据库中处于 `metadata_synced` 且 priority=2 的邮件调用 `GET /api/mail/messages/{mid}`，断言响应返回 200 且 body 为空；验证数据库中 `MessageArchiveState.priority` 提升为 0（最高优先级），且成功在 `worker_jobs` 入队 `ARCHIVE_MIME_BATCH` 任务，优先级为 10。

- [x] **AC-002**：按需归档任务执行后，能成功从 Provider 拉取原始 MIME 邮件，完成正文解析（HTML/纯文本）及附件元数据入库，并将 `MessageArchiveState` 更新为 `archive_complete`
  - 验证证据：`tests/mail_core/test_on_demand_body_sync.py::test_ac002_post_sync_body_completes_archive_and_returns_body`
  - 验证逻辑：调用 `POST /api/mail/messages/{mid}/sync-body`，Provider 边界返回包含 HTML 的标准 MIME 原文；验证接口即时返回 200 及完整 HTML 正文；数据库核验 `MessageArchiveState.state` 跃迁为 `archive_complete`，`MessageBody` 表持久化存入对应 HTML 正文。

- [x] **AC-003**：优化 Worker 任务队列调度优先级：普通增量轮询 `sync_folder_delta` 与后台批量归档 `archive_mime_batch` 优先级合理分层，后台批量归档任务不再被频繁生成的增量轮询无限饥饿阻塞
  - 验证证据：`tests/mail_core/test_on_demand_body_sync.py::test_ac003_worker_jobs_priority_governance`
  - 验证逻辑：触发增量轮询 `sync_folder_delta`，断言新生成的增量任务 priority 为 75（从 70 调整为 75），并具有 `dedupe_key`（`delta:{aid}:{fid}`）防积压；结合生产代码 `run_archive_batch` 批量归档任务优先级调整为 60（高于增量轮询 75，按需归档为 10），从调度体系上消除后台批量正文归档被增量轮询高频饥饿抢占的倒挂现象。

- [x] **AC-004**：前端在打开正文未同步的邮件时，展示正在同步中的动态加载提示，并在按需同步完成或收到更新通知后自动刷新展示正文，不再停留在静态未完成提示上
  - 验证证据：`src/frontend/src/components/MessageReader.test.tsx::displays syncing state on unarchived email and smoothly renders body after on-demand sync (AC-004)`
  - 验证逻辑：挂载选择未归档邮件 `m-unarchived`（`is_archived: false`, `body: ''`），验证自动触发 `POST /api/mail/messages/m-unarchived/sync-body`，界面展示正在同步加载提示（Spin 图标及“正在优先同步邮件正文…”）；同步返回正文后，`iframe` 平滑刷新展示正文内容（`Instant fetched on-demand body`），且无解析错误提示。

- [x] **AC-005**：若邮件在 Provider 端拉取失败或解析错误，按需同步应捕获并正确持久化 `parse_error`，前端展示对应错误提示而不是无限加载
  - 验证证据：
    - 后端：`tests/mail_core/test_on_demand_body_sync.py::test_ac005_sync_body_captures_provider_or_parse_error` 模拟 Provider 拉取超时抛错，验证接口优雅返回 200 且响应体与数据库 `MessageBody.parse_error` 字段均成功持久化存储错误信息。
    - 前端：`src/frontend/src/components/MessageReader.test.tsx::displays error and retry button when on-demand sync fails (AC-005)` 模拟接口同步失败，前端捕获异常并在界面展示明确错误提示与“立即重试同步”操作按钮，杜绝无限加载。

## 结论

- 改测方向复核：既有测试仅在 `mailCore.client.test.ts` 与 `mailCore.test.ts` 中补充了 DTO 新增属性 `is_archived: true` 假数据，既有断言无弱化、无删除、无反转，不存在“迁就实现”的改测。
- 危险模式扫描：逐项扫描恒真断言、弱化断言、跳过独占、静默错误、mock 边界越界、条件跳过等，均未命中。
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：测试用例直接对齐 AC-001 至 AC-005。后端测试在真实 PostgreSQL 环境下覆盖按需同步接口、归档优先级跃迁、Worker 调度分层治理及解析失败持久化；前端测试通过 RTL 验证未归档邮件自动按需拉取、加载反馈、正文刷新以及拉取失败重试呈现。全量测试通过。
- 系统性 follow-up：无

verdict: PASS
