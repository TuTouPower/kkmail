---
tid: "t051"
slug: "mailbox_folder_role_aliases"
title: "修正邮箱文件夹角色重复显示与映射"
status: "done"
branch: "t051_mailbox_folder_role_aliases"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "427bdb7ca2d10cfa3e12edc960bae37f30390023"
depends_on: ""
conflicts_with: ""
note: "来源 p037；保留远端 folder_id，不按 role 合并目录"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

按用户要求在主分支实现，代码已在 `970f74c`。本 task worktree 用于补齐 task 证据、复审与归档；未重复修改业务代码。

Graph 文件夹角色分类优先使用 canonical ID；同账号角色标签冲突时在侧栏显示原始名称或完整路径，保留各自 `folder_id`。IMAP `Deleted Messages` 映射到 `trash`。Outbox 与 Conversation History 在缺少权威角色标记时仍为 `other`。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round N (YYYY-MM-DDThh:mm:ss+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|

Round 1 零 finding。代码与测试复审均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：完整后端 505 passed；前端 276 passed；Desktop 单测与 packaged 测试通过；OpenAPI、TypeScript、生产构建与 lint 通过；模板契约 149 passed / 1 skipped。
- 黑盒：UI E2E 16 passed；真实全栈 E2E 8 passed。
- review：代码与测试复审均 PASS；复审目标为 `970f74c`（相对 `00c951b`）。
- AC 证据：见 `handoff.json`

### 结果摘要

文件夹角色映射与侧栏区分已完成。未删除或合并远端目录，三个验收条件均由自动测试覆盖。
