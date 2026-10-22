---
tid: "t009"
slug: "sidebar_full_hide"
title: "侧栏完全隐藏并迁移展开入口"
status: "done"
branch: "t009_sidebar_full_hide"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "77f8cdc44f122e11f8666bfa5958a166d1425f74"
depends_on: ""
conflicts_with: ""
note: "来源 p014；覆盖桌面网格与移动端导航"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 布局重构：在 `src/frontend/src/lib/workspaceLayout.ts` 中移除折叠侧栏的 48px 残留轨与分割条占位，重写 `workspaceGridColumns` 与 `workspaceGridChildRoles`，在桌面折叠时不向网格注入侧栏与侧栏拖拽条。
2. 入口迁移：在 `src/frontend/src/App.tsx` 中仅在未折叠或移动端时挂载侧栏；在 `MessageList.tsx` 列表标题左侧与 `SettingsModal.tsx` 设置标题左侧增加键盘可操作的展开入口按钮，展开后无重复占位；移除列表右侧过时的单移动端导航按钮。
3. 验证与门禁：补充 `workspaceLayout.test.ts` 覆盖折叠网格布局与子节点角色匹配用例；通过全套前端单元测试、构建、桌面打包冒烟与 Playwright E2E。更新 `docs/blueprint/conventions.md`。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：前端单元 (170 passed), 桌面打包冒烟 passed, 后端全量 (381 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：general PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 桌面侧栏折叠时完全从网格轨与 DOM 移除，消除 48px 窄轨与隐藏键盘焦点陷阱；
- 侧栏展开入口统一迁移至列表标题及设置页标题左侧，展开后不重复占位；
- 移动端导航通过同一左侧按钮唤起独立抽屉，760px 响应式断点两侧状态与行为相互独立；
- 侧栏拖拽与列表拖拽宽度在折叠/展开切换时保持持久化记忆。
