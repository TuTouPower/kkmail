# Task review t057（reviewer_focus: 测试）

## Round 1 (2026-10-27T19:38:00+08:00)

- reviewed_at: 2026-10-27T19:38:00+08:00
- reviewed_scope: 6c4351a0be90c36e

测试复审 PASS。
测试套件完整覆盖 AC-001 ~ AC-007，均在真实 PostgreSQL 隔离测试库中完成断言验证：
1. `tests/mail_core/test_worker_scheduler.py`：
   - 验证超期判定、优先级设置、payload 格式与任务状态（AC-001）；
   - 验证禁用账号、paused 文件夹与非收件箱的过滤边界（AC-001）；
   - 验证多账号均匀错峰平摊算法，断言任务 `run_after` 严格递增且不重叠（AC-002）；
   - 验证活跃任务去重保护与终态失败后的自愈补发能力（AC-006）；
   - 验证环境变量 `MAIL_CORE_INBOX_POLL_INTERVAL_S` 动态解析及非法值回退契约（AC-007）。
2. `tests/mail_core/test_delta_archive_integration.py`：
   - 验证 `sync_folder_delta` 在翻页结束时不再产生 30 秒自调度任务（AC-003）；
   - 验证新邮件增量入库后自动入队 `ARCHIVE_MIME_BATCH`（AC-004）；
   - 验证 Worker 消费归档批次后，真实将邮件完整 HTML 正文解析并持久化写入 PostgreSQL `message_bodies` 表（AC-005）。
3. 所有测试断言精准触达生产逻辑与真实数据库，未弱化断言，未 mock 核心业务逻辑。

零 finding。

verdict: PASS
