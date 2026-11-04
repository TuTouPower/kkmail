---
tid: "t071"
slug: "idle_connect_catchup_inbox_delta"
title: "IMAP IDLE 建连与重连后补偿收件箱增量同步"
status: "done"
branch: "t071_idle_connect_catchup_inbox_delta"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "e4752c2415d34ac80ebb5ff1e76409a7351fb62d"
depends_on: ""
conflicts_with: ""
note: "来源 p070；IDLE 断线/重启窗口内到达的邮件无事件也无轮询，需在建连后入队补偿 delta"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 实现：`IdleWatcherManager._watch_loop` 在每次会话成功建立后，先置 `idling` 再调用 `_enqueue_catchup`；补偿复用 `delta:{account_id}:{folder_id}` 去重键走既有 baseline/lease/fencing 流水线，入队异常只记录日志不终止 watch。
- 停机：`stop()` 改为先一次性唤醒全部 watch，再在 5s 共享 deadline 内 join；跳过 `ident is None` 的未启动线程，避免停机竞态。
- 测试：新增首连、断线重连、pending 合并、claimed 合并、无 IDLE/永久认证降级、入队失败隔离、断线窗口邮件补偿入库、未启动 watch 停机 8 个测试函数（AC-004 参数化后共 9 个用例）。已知 `test_ac005_quota_limits_sessions`、`test_load_candidates_ranks_by_arrival_not_checkpoint` 为 anchor 既有失败，登记 p071；补偿入队失败后无事件时的长期缺失风险登记 p072。
- 验证：`pytest .repo_template/tests -q -m contract` 189 passed；t061 相关测试（除 anchor 既有 2 项）31 passed；快速 UI E2E 21 passed；全栈 E2E 8 passed。全量后端套件在本 worktree 为 91 failed / 1834 passed / 2 skipped，失败面包含 anchor 既有问题（仅抽样复核 t061 两项在 anchor 同样失败），未作为本 task 通过证据。
- 文档：`docs/blueprint/architecture.md`、`docs/specs/mail_sync_and_storage.md` 的 t061 章节已补建连补偿、去重合并与降级边界。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T21:14:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t071_code_f001|minor|已修|stop() 改为一次性唤醒全部 watch 后共享 5s deadline join，消除串行停机与无全局上限|`src/mail_core/sync/idle_watcher.py:258`|
|t071_code_f002|minor|已修|模块 docstring 补齐建连补偿与失败隔离语义|`src/mail_core/sync/idle_watcher.py:7`|
|t071_test_f001|important|已修|合并用例改为等待真实合并完成后的 priority/run_after 状态；复跑 20/20 通过|`tests/mail_core/test_t061_idle_watcher.py:887`|
|t071_test_f002|minor|已修|AC-004 参数化覆盖 no_idle 与 permanent_auth 两个阻断分支|`tests/mail_core/test_t061_idle_watcher.py:973`|
|t071_test_f003|minor|已修|新增 claimed 同键合并用例，断言 `_followup_needed` 与 `_queue_next`|`tests/mail_core/test_t061_idle_watcher.py:929`|

### Round 2 (2026-10-31T21:56:42+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t071_code_f003|minor|已修|stop() join 前跳过未启动线程，并新增白盒回归测试|`src/mail_core/sync/idle_watcher.py:273` / `tests/mail_core/test_t061_idle_watcher.py:693`|

Round 2 测试 review 零 finding；Round 3 代码 review 零 finding。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：contract 189 passed；t061 相关 31 passed（2 项 anchor 既有红测试登记 p071）；t071 新增 9 用例全过；全量后端套件 1834 passed / 91 failed / 2 skipped，失败为 baseline 既有问题
- 黑盒：快速 UI E2E 21 passed；真实全栈 E2E 8 passed
- review：code Round 3 PASS、test Round 2 PASS，0 未解决 finding，review_scope=898cb8ed146309d5
- AC 证据：见 `handoff.json`

### 结果摘要

- IDLE 首连与重连后入队一次同去重键补偿 delta，覆盖无活动会话窗口内到达的邮件；入队失败隔离，无 IDLE/永久认证失败保持轮询。遗留既有测试问题见 p071，补偿失败无事件时的长期缺失风险见 p072。
