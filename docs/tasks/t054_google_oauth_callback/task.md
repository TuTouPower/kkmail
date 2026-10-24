---
tid: "t054"
slug: "google_oauth_callback"
title: "支持 Google OAuth 跳转回调与账户重新授权"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t053"
conflicts_with: ""
note: "来源：用户补充；Google 保留 IMAP 应用密码并新增 OAuth 授权码跳转回调，覆盖网页与 Electron；依赖 t053"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：用户明确增加 Google 登录跳转与回调，独立交付网页/桌面新增及重新授权。依赖 t053，full review；官方协议已核实，尚未实施。
- 创建期仅写本批 task 与派生索引；不 start、不改生产代码，创建 commit 待用户确认。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round N (YYYY-MM-DDThh:mm:ss+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t000_code_f001|critical/important/minor|已修/遗留/撤回|一句话|文件:行 / pNNN / tid|

无 finding 时写“Round N 零 finding”。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足 / 未满足
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
