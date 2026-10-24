---
tid: "t053"
slug: "provider_account_forms"
title: "按邮箱供应商定制添加与编辑账户表单"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源：用户确认；供应商定制新增/编辑表单、获取凭据帮助图标与弹窗、下线 Microsoft IMAP；当前运行 DB 25 Graph/9 IMAP，未发现 Microsoft IMAP；Google/Microsoft 跳转回调分别由 t054/t055 交付"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：用户要求设置页添加与编辑账户按供应商定制；官方依据和供应商矩阵写入 spec，统一为一个可验收账户配置交付。
- 查重依据：仅 main 分支，无登记 worktree；t051、t052 是文件夹任务，无等价账户表单 backlog。
- 用户补充后：t053 交付表单/帮助弹窗/Microsoft IMAP 下线；t054/t055 分别实现 Google/Microsoft 跳转与回调，全部 full review。
- 只读核对当前运行 DB：25 Graph、9 IMAP，未发现 Microsoft IMAP。用户确认无须迁移，不增加迁移范围。
- 创建期仅落盘本 task 与派生索引，不改生产实现，不 start；创建 commit 待用户确认。

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
