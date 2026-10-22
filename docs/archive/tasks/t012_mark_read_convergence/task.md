---
tid: "t012"
slug: "mark_read_convergence"
title: "修复已读写回收敛与未读计数一致性"
status: "done"
branch: "t012_mark_read_convergence"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "330008b1dfc166f67b60766d639b697d04e37915"
depends_on: ""
conflicts_with: ""
note: "来源 p016；修复续跑丢失、旧同步覆盖本地意图与计数落库顺序；不提交"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 调度闭环：在 `src/mail_core/sync/jobs.py` 中允许 claimed 任务捕获后续唤醒载荷并在 `worker/handlers.py:_evaluate_result` 完成时派生新 pending 任务，彻底解决批次余量丢失调度缺陷；在 `sync/remote_push.py` 中暴露 `has_more` 与 `next_run_after`。
2. 意图保护：在 `src/mail_core/sync/remote_push.py` 中实现 `get_unconverged_field_intents`，在 `sync/metadata.py` 与 `sync/delta.py` 中阻止旧远端快照覆盖本地待推送与 60s 内刚完成的读/标意图，同时允许非相关字段正常同步与收敛后正常更新。
3. 统计一致性与恢复：在 `src/mail_core/mail/storage/folder_stats.py` 中强制在 SQL 聚合前 flush 会话，杜绝 `autoflush=False` 导致的计数失真；实现 `reconcile_account_writeback_and_stats` 幂等安全恢复孤儿任务与失配统计；前端 `MessageList.tsx` 避免因服务端陈旧零计数禁用仍有未读邮件的全部已读操作。
4. 验证与门禁：编写 `test_mark_read_convergence_suite.py` 覆盖 AC-001 至 AC-008；通过全量测试（385 passed）、前端与桌面测试、以及 Playwright E2E。更新 blueprint architecture.md, decisions.md, conventions.md 与 testing.md。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：`scripts/run-mail-core-tests.sh run` (385 passed), 前端单元 (183 passed), 桌面打包冒烟 passed
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：code PASS / test PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复写回首批完成后丢失续跑的调度缺陷，超过 20 条操作经真实 worker 生命周期自然自动排空；
- 建立本地已读/旗标意图保护机制，杜绝旧远端快照覆盖最新本地意图；
- 修复 autoflush=False 导致的文件夹统计计算时序缺陷，保证 Message 状态与 FolderStats 一致；
- 提供账号级写回任务与统计对账恢复入口。
