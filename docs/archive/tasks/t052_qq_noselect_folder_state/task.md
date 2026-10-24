---
tid: "t052"
slug: "qq_noselect_folder_state"
title: "正确处理 QQ IMAP 不可选择文件夹"
status: "done"
branch: "t052_qq_noselect_folder_state"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7c35f2e63bd4edac11ad5264acb31c2464dff1a0"
depends_on: ""
conflicts_with: ""
note: "来源 p038；保留不可选择父目录与子目录关系，不删除历史邮件位置"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

按用户要求在主分支完成实现，最终实现提交为 `d626852`。本 task worktree 用于补齐 review 处置、exact handoff 与归档，不重复修改业务代码。

IMAP `\NoSelect` 目录保留为不可选择树节点；已存在目录在发现时转为 `paused`，跳过 metadata、delta 与 reconcile 调用。Folder stats 暴露同步状态，侧栏禁用父节点并隐藏未知未读数；子目录仍可独立同步。既有邮件、位置和 checkpoint 保留。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-24T13:19:29+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t052_code_f001|medium|已修|paused 文件在 delta/reconcile 调用 provider 前返回 skipped。|src/mail_core/sync/delta.py；src/mail_core/sync/reconcile.py|
|t052_test_f001|medium|已修|三类旧任务完成后再次核对 checkpoint 游标、UIDVALIDITY 与 full-scan 状态。|tests/mail_core/test_sync_retry_queue.py|

代码与测试复审确认以上 finding 已关闭，未发现新问题。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：完整后端 505 passed；定向 noselect 2 passed；前端 276 passed；Desktop 单测与 packaged 测试通过；OpenAPI、TypeScript、生产构建与 lint 通过；模板契约 149 passed / 1 skipped。
- 黑盒：UI E2E 16 passed；真实全栈 E2E 8 passed。
- review：代码与测试复审均 PASS；实现提交 `d626852`，额外防护与 checkpoint 回归在该提交内。
- AC 证据：见 `handoff.json`

### 结果摘要

不可选择的 QQ 父目录会保留为 disabled tree container，不再触发同步失败；子目录保持可用，历史邮件数据与 checkpoint 未删除。
