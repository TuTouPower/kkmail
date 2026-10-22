---
tid: "t009"
slug: "sidebar_full_hide"
title: "侧栏完全隐藏并迁移展开入口"
status: "backlog"
branch: ""
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p014；覆盖桌面网格与移动端导航"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

创建依据：p014（2026-10-22 核实：workspaceLayout.ts 折叠分支返回 48px，workspaceGridChildRoles 始终含 sidebar；App.tsx 始终挂载 Sidebar；MessageList 仅在标题行右侧提供 mobile-only 导航按钮。workspaceLayout.test.ts 覆盖默认与设置展开布局，但缺折叠用例；无等价 effective task。）

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

尚未开始 review，无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：尚未实施
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
