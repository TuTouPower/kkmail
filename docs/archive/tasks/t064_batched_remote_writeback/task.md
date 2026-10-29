---
tid: "t064"
slug: "batched_remote_writeback"
title: "远程写回按文件夹批量合并提交"
status: "done"
branch: "t064_batched_remote_writeback"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "c648c87e58ba8886a527d0f890fc990afb17a477"
depends_on: ""
conflicts_with: ""
note: "来源 p063 根因 3；单连接按文件夹/操作/目标分组发 UID 集合命令，Graph 用 $batch，逐条 revision CAS 结算"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 在 `mail_core.providers.base` 增加 `RemoteOperationItem`，定义 Provider 级批量接口 `apply_remote_operations` 并为单条调用提供兼容委托。
2. 在 `mail_core.providers.remote_writeback` 实现 `compress_uids` 与 `compress_uids_chunked`，支持连续 UID 区间合并与 1000 字符分块。
3. 在 `mail_core.providers.imap` 实现 `ImapProvider.apply_remote_operations`：全批单连接登录，按源文件夹与（操作类型，目标值）分组，使用 UID STORE 响应与缺失 FETCH 补查校验标记，通过 COPYUID 映射目标 UID。
4. 在 `mail_core.providers.graph` 实现 `GraphProvider.apply_remote_operations`：利用 Microsoft Graph `$batch` 批量接口，按 20 个子请求切片，处理单个子请求 429 限流隔离。
5. 在 `mail_core.sync.remote_push` 改造 `push_remote_operations`：批处理上限提升至 500 条，网络前短事务统一置为 IN_PROGRESS，网络后逐条依 revision CAS 结算，超量自动排队后继任务。
6. 编写 9 项单元与集成测试（`tests/mail_core/test_t064_batched_remote_writeback.py`），覆盖 AC-001 至 AC-013。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-30T06:50:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`scripts/run-mail-core-tests.sh run -k test_t064_batched_remote_writeback` (9 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (18 passed)
- review：code PASS / test PASS (overall PASS)
- AC 证据：见 `handoff.json`

### 结果摘要

- 远程写回升级为按文件夹与操作批量合并提交管道，消除逐条建连登录瓶颈；IMAP 与 Graph 支持分批分块与错误隔离；fencing 与 CAS 状态结算机制完整。
