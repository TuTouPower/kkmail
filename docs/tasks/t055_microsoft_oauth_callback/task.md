---
tid: "t055"
slug: "microsoft_oauth_callback"
title: "支持 Microsoft OAuth 跳转与设备码登录"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t054"
conflicts_with: ""
note: "来源：用户明确增加设备码；Microsoft 支持跳转回调与设备码两条新增/重新授权路径，统一获取并加密保存令牌；复用 t054 会话绑定与最终保存；不做 Microsoft IMAP 或迁移"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：官方确认 Microsoft 支持授权码跳转回调；Client ID 来自 Entra 注册，Refresh Token 由回调换取。复用 t054，full review。当前运行 DB 无 Microsoft IMAP，用户确认不考虑迁移。
- `2026-10-24`：用户明确要求增加设备码流程。范围扩展为浏览器回调和设备码两条新增/重新授权路径，补充轮询/取消/过期与公共客户端配置 AC；“离线权限”由程序自动处理，界面使用后台同步说明。
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
