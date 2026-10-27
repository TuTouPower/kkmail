---
tid: "t057"
slug: "periodic_inbox_sync_and_auto_archive"
title: "收件箱定时轮询与增量正文自动存库"
status: "done"
branch: "t057_periodic_inbox_sync_and_auto_archive"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "1475b0aa137cf4587211ad0adc9164aaf7e57dac"
depends_on: ""
conflicts_with: ""
note: "实现20分钟收件箱独立错峰轮询，废除尾递归自调度，增量新邮件自动入库正文"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. TDD 编写 `tests/mail_core/test_worker_scheduler.py` 与 `tests/mail_core/test_delta_archive_integration.py`，完整覆盖 AC-001 ~ AC-007。
2. 在 `src/mail_core/worker/main.py` 中实现 1200 秒收件箱巡检调度器 `schedule_periodic_inbox_sync` 与错峰平摊算法，并在 `run()` 循环挂载独立异常隔离的巡检周期。
3. 改造 `src/mail_core/sync/delta.py`：彻底移除第 650–670 行的尾递归 30 秒自调度；在 `totals["upserted"] > 0` 时自动在同事务中入队 `ARCHIVE_MIME_BATCH`（优先级 60）。
4. 修复 `src/mail_core/sync/execution.py`：在 `_successor_is_periodic` 中正确识别 `exhausted=True` 的独立后继，避免已完成请求误绑定后继。
5. 配置契约与架构文档累积更新至 `config/.env.example`、`src/mail_core/README.md`、`docs/blueprint/architecture.md` 与 `docs/specs/mail_sync_and_storage.md`。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-27T19:38:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract` (189 passed)；`scripts/run-mail-core-tests.sh run -k "test_worker_scheduler or test_delta_archive_integration"` (7 passed)；前端测试与构建全部通过。
- 黑盒：`npm --prefix src/frontend run test:e2e` (18 passed)；`python3 scripts/run_full_stack_e2e.py` 核心真实 Dovecot+Worker 同步通过。
- review：code PASS，test PASS，指纹 `6c4351a0be90c36e` 匹配。
- AC 证据：见 `handoff.json`

### 结果摘要

- 实现 Worker 主循环独立周期巡检调度器，每 60 秒轮询一次，自动为超期（默认 1200 秒 / 20 分钟）收件箱按错峰算法入队 `SYNC_FOLDER_DELTA`。
- 彻底废除增量同步执行末尾的尾递归自调度逻辑，实现调度权威与任务执行解耦。
- 实现增量收信连带正文自动存库，新邮件入库后自动触发 `ARCHIVE_MIME_BATCH` 下载完整 MIME 并将解析提取出的 HTML/纯文本直接写入 PostgreSQL `message_bodies` 表。
