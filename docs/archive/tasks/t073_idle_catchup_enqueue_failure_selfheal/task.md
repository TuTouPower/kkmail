---
tid: "t073"
slug: "idle_catchup_enqueue_failure_selfheal"
title: "IDLE 补偿 delta 入队失败自愈"
status: "done"
branch: "t073_idle_catchup_enqueue_failure_selfheal"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "c7ce5875956c622498af62bd7397b3bc86b726a6"
depends_on: ""
conflicts_with: ""
note: "来源 p072；建连补偿入队失败后重试，持续失败释放 IDLE 席位让 t057 轮询兜底"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `_enqueue_catchup` 改为有界重试（3 次，0.2s/0.4s 指数退避，上限 2s），重试期间响应 `stop_event`；成功返回 True。
- 重试预算耗尽时 `_watch_loop` 置 `backoff`、关闭当前会话并释放 held 席位，使 t057 收件箱轮询可入队；下次重连继续补偿；账号不标记 failed。
- 新增 3 个测试：瞬时失败后成功且保持 held/idling；持续失败后 backoff/释放席位并可由 t057 入队；stop 期间退避 2s 内退出。复用 t071 去重测试回归 AC-004。
- 验证：contract 189 passed；t061 相关 37 passed；UI E2E 21 passed；全栈 E2E 8 passed。
- 文档：`architecture.md` 与 `mail_sync_and_storage.md` 的 t061 契约已补补偿失败重试与释放 held 兜底。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T23:16:08+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t073_test_f001|important|已修|AC-003 测试改为等待至少一次重试后再停止，等待超过剩余退避断言不再重试，并验证另一健康 watch 仍 held/alive/未关闭|`tests/mail_core/test_t061_idle_watcher.py:1104`|

Round 1 代码 review 零 finding。

### Round 2 (2026-10-31T23:43:00+08:00)

Round 2 代码与测试 review 均零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：contract 189 passed；t061 相关 37 passed；t073 新增 3 用例全过
- 黑盒：UI E2E 21 passed；真实全栈 E2E 8 passed
- review：code Round 2 PASS、test Round 2 PASS，0 未解决 finding，review_scope=eb456e938615009f
- AC 证据：见 `handoff.json`

### 结果摘要

- 补偿入队瞬时失败按 3 次有界指数退避重试；预算耗尽则关闭会话、置 backoff 并释放 held 席位，由 t057 轮询兜底，下次重连继续补偿；账号不标记 failed。
