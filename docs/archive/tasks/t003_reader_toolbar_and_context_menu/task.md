---
tid: "t003"
slug: "reader_toolbar_and_context_menu"
title: "重构邮件详情居中工具栏与支持邮件列表右键菜单"
status: "done"
branch: "t003_reader_toolbar_and_context_menu"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "ca9a9309f40c856e550b103ed6b69a5ea62445c0"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. `queries.ts`：导出 `setReadOptimistic(items, nextRead)`，统一支持正向标已读与反向标未读。
2. `MessageReader.tsx`：工具栏操作按钮组居中放置；已读/未读按钮动态根据状态双向切换；增加回复、回复所有人、转发占位按钮并设为 disabled 禁用状态。
3. `MessageList.tsx`：在邮件卡片上实现原生风格右键上下文菜单（Context Menu），包含打开、动态标为已读/未读、标记旗标、移到废纸篓及禁用的发信项，支持 ESC 和点击外部关闭。
4. 测试覆盖：更新 `MessageReader.test.tsx` 与 `MessageList.test.tsx` 覆盖居中、状态动态切换、disabled 发信项及右键菜单各项交互。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-22T05:16:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`npm test && npx tsc -b && npm run build` (119 passed)、`(cd src/desktop && npm test)`、`pytest .repo_template/tests -q -m contract` (149 passed) 全绿。
- 黑盒：`npm --prefix src/frontend run test:e2e` (2 passed)。
- review：`review_general.md` verdict: PASS (Round 1)。
- AC 证据：见 `handoff.json`

### 结果摘要

- 成功实现邮件详情工具栏居中与已读/未读动态双向切换，邮件列表完整支持原生风格右键快捷菜单并禁用未支持发信项。
