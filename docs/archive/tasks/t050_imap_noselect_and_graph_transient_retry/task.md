---
tid: "t050"
slug: "imap_noselect_and_graph_transient_retry"
title: "过滤 IMAP 非选文件夹并增强 Graph 传输瞬态重试"
status: "done"
branch: "t050_imap_noselect_and_graph_transient_retry"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "cdfafc7317b37209678c512cb49adefa3fa17e63"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. TDD 流程：先编写 `tests/mail_core/test_imap_noselect_and_transient_retry.py` 覆盖 5 条 AC，运行确认为预期红灯失败。
2. 问题 3 修复：在 `ImapProvider.list_folders` 解析 flags 时过滤 `\noselect` 与 `\nonexistent` 属性目录；实现 `_is_mailbox_noselect`，并在 `fetch_metadata_page` 与 `reconcile` 遇到非选目录拒绝（NO）时安全降级为空页，避免异常崩溃。
3. 问题 4 修复：在 `src/mail_core/providers/oauth.py` 的 `urllib_json_request` 引入最多 3 次有限重试循环，针对 HTTP 503/504（优先遵循 Retry-After）及网络瞬断（TLS SSLEOFError、RemoteDisconnected、ConnectionReset）进行指数退避（单次上限 10 秒）；耗尽后抛出 `ProviderHttpError`。
4. 全量验证：单元测试 5 passed，相关集成测试 111 passed，前端全量 274 passed，桌面端 11 passed，黑盒测试 16 passed 全部绿灯。

## Review 处置

### Round 1 (2026-10-24T12:00:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`tests/mail_core/test_imap_noselect_and_transient_retry.py` 5 passed；集成测试 111 passed；前端 274 passed；桌面端 11 passed
- 黑盒：Playwright UI 冒烟测试 16 passed
- review：`review_general.md` PASS（0 finding，reviewed_scope: d3f6743c91ff4390）
- AC 证据：见 `handoff.json`

### 结果摘要

- 过滤带有 `\Noselect` 或 `\NonExistent` 属性的 IMAP 容器目录，并在只读非选邮箱查询受拒时安全处理，解决 QQ IMAP“其他文件夹”UID SEARCH 返回 NO 的同步失败问题。
- 在 Graph API stdlib 传输层提供 HTTP 503/504 与 TLS/连接瞬态有限退避重试（最多 3 次），解决 Outlook Graph 账号偶发 503 与 TLS 连接提前断开导致的同步中断。
