---
tid: "t005"
slug: "sync_refresh_and_imap_id"
title: "修复列表刷新联动远端同步新建账号入队与网易IMAP握手"
status: "done"
branch: "t005_sync_refresh_and_imap_id"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "51947c44b01f95ed69799ce2de4cf13b924d95a3"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 前端 `MessageList.tsx` 改造 `refreshView()`：判断单账号 vs 全局收件箱分别发起 `api.syncAccount` 或 `api.syncAll()`，显示排队状态提示并在请求过程中增加旋转动效；
2. 应用层 `accounts.py` 在 `create_account_app` 创建账号时自动调用 `enqueue_account_sync`，账号创建即进入后台同步队列；
3. 后端 `imap.py` 在 `_connect()` 认证后自动下发 RFC 2971 `ID` 客户端标识指令，解除网易等邮箱服务 `SELECT Unsafe Login` 拦截，异常安全捕获放行保证兼容性；
4. 补充针对性单元测试，全量门禁检查通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-22T11:25:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：pytest 217 passed；vitest 30 files / 146 tests passed
- 黑盒：playwright E2E 3 passed
- review：review_general.md PASS
- AC 证据：见 `handoff.json`

### 结果摘要

已完成列表刷新触发远端同步、新建账号自动排队初始同步及网易 IMAP ID 握手支持，闭环 p009。
