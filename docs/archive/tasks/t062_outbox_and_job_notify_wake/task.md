---
tid: "t062"
slug: "outbox_and_job_notify_wake"
title: "统一 Outbox 事件与任务入队的 PostgreSQL 即时唤醒"
status: "done"
branch: "t062_outbox_and_job_notify_wake"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "9bbe0991a56575ce32645bfea41a4f8777c59f1a"
depends_on: ""
conflicts_with: ""
note: "来源 p063 根因 1 及核实新增的 Worker 空闲退避延迟；事务提交即唤醒 API 推送与 Worker 认领"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 在 `src/mail_core/realtime/notify.py` 中新增 `JOB_CHANNEL = "mail_core_jobs"` 与 `notify_jobs(session)`。
2. 在 `src/mail_core/db/events.py` 中基于 SQLAlchemy Session 事件（`before_flush`、`before_commit`、`after_transaction_create`、`after_transaction_end`、`after_rollback`）建立统一的事务提交 NOTIFY 唤醒机制，通过 savepoint 保护业务事务不因 `pg_notify` 异常受损，针对非 PostgreSQL 方言透明 no-op。
3. 移除 `metadata.py`、`remote_push.py`、`mutations.py` 中分散的手工 `try_notify_outbox` 显式调用。
4. 在 `src/mail_core/worker/wake.py` 实现 `JobWakeListener` 监听 `mail_core_jobs`，并在 `src/mail_core/worker/main.py` 的 `_wait_for_next_poll` 挂载 `_wake_event`，实现空闲等待即时打断与连接断线重连降级。
5. 编写 9 项单元与集成测试（`tests/mail_core/test_t062_outbox_and_job_notify_wake.py`），覆盖 AC-001 至 AC-008。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-30T06:08:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`scripts/run-mail-core-tests.sh run -k test_t062_outbox_and_job_notify_wake` (9 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (18 passed), `python3 scripts/run_full_stack_e2e.py` (7 passed)
- review：code PASS / test PASS (overall PASS)
- AC 证据：见 `handoff.json`

### 结果摘要

- 统一 Outbox 写入即 NOTIFY，移除分散手动调用；任务入队即刻唤醒 Worker 空闲等待，1 秒内完成抢占认领；断连自动重连与定时轮询降级机制完整。
