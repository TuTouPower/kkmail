---
tid: "t072"
slug: "t061_idle_watcher_red_test_repair"
title: "修复 t061 IDLE watcher 测试既有红与同步竞态"
status: "done"
branch: "t072_t061_idle_watcher_red_test_repair"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "20e90ce6154e472239ad71d805f90aea759359a2"
depends_on: ""
conflicts_with: ""
note: "来源 p071；修复 frozen config setattr、detached ORM 与禁用账号用例同步点竞态"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `_manager()` 改为构造 `IdleWatcherConfig(**options)`，不再对 frozen dataclass 执行 `setattr`。
- `test_load_candidates_ranks_by_arrival_not_checkpoint` 在 session 内 flush 后保存账号 ID，commit 后不再访问 detached ORM 实例。
- `test_ac006_disabled_account_session_closed` 先等待 `fake.closed`，再断言 held 为空，消除 pop-then-join 窗口竞态。
- 验证：3 个目标用例 passed；t061 文件相关 34 用例 passed；禁用账号用例连续 10 次 1 passed；`pytest .repo_template/tests -q -m contract` 189 passed。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T22:47:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：3 个目标用例 passed；t061 文件相关 34 passed；禁用账号用例连续 10 次 passed；contract 189 passed
- 黑盒：不适用（纯测试修复，无用户可观察行为变化）
- review：single Round 1 PASS，0 finding，review_scope=bd77230c16047d8c
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复 t061 IDLE watcher 测试辅助的 frozen config 赋值、detached ORM 访问与禁用账号关闭同步竞态；t061 相关测试全绿。
