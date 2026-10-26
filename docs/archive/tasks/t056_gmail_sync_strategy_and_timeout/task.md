---
tid: "t056"
slug: "gmail_sync_strategy_and_timeout"
title: "优化 Gmail 虚拟文件夹同步策略与 IMAP 超时及角色映射"
status: "done"
branch: "t056_gmail_sync_strategy_and_timeout"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "6105e02038c594ae5d185da55a6fe35c3b7adc8d"
depends_on: ""
conflicts_with: ""
note: "排除 Gmail 虚拟文件夹重复拉取，放宽 IMAP 超时与分批粒度，完善 RFC 6154 标志映射，瞬时网络超时防抖"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 建立测试用例 `tests/mail_core/test_gmail_sync_strategy_and_timeout.py` 覆盖 5 条 AC 并确认基线全红；
2. 扩展 `src/mail_core/providers/imap.py` RFC 6154 标志位解析（\all -> all, \flagged -> flagged），并将默认 Socket 超时放宽至 60.0s；
3. `src/mail_core/sync/engine.py` 实现 Gmail 虚拟标签文件夹默认 paused 策略与排期过滤，将 `max_pages` 默认参数调整为 10；
4. `src/mail_core/worker/handlers.py` 优化瞬态网络超时错误处理，避免在可重试期内错误标记账户为 failed；
5. 后端单测、全套回归与 Playwright 轻量/全栈 E2E 黑盒验证全部通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-26T23:30:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`./scripts/run-mail-core-tests.sh run -k "test_gmail_sync_strategy_and_timeout or test_imap_noselect or test_imap_id or test_sync_account_folders"` 通过（29 passed）；前端测试通过（446 passed）
- 黑盒：Playwright UI E2E 通过（18 passed）；Playwright Full Stack E2E 通过（8 passed）
- review：Round 1 双 PASS（零 finding）
- AC 证据：见 `handoff.json`

### 结果摘要

- AC-001：Gmail 账号下 `\All`（所有邮件）与 `\Important`（重要）默认置为 `paused`，常规同步不自动排队拉取其邮件，杜绝收件箱邮件重复抓取。
- AC-002：`ImapProvider.list_folder_catalog` 支持将 `\All` 映射为 `role = "all"`，`\Flagged` 映射为 `role = "flagged"`。
- AC-003：`ImapProvider` 默认读取超时放宽为 60.0 秒。
- AC-004：`sync_folder_metadata` 默认单次最大拉取页数 `max_pages` 调整为 10 页。
- AC-005：Worker 遇到瞬态网络超时或 SSL 断连进行任务重试时，账号 `sync_status` 保持原有状态不被置为 `failed`。
