---
tid: "t024"
slug: "sidebar_folder_tree_layout"
title: "修复侧栏账号文件夹树布局并保持导航可访问性"
status: "done"
branch: "t024_sidebar_folder_tree_layout"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "9454a1d2cc9412caf86c5381b427619fdb661a86"
depends_on: ""
conflicts_with: ""
note: "来源 p018；固定高度横向 flex 容器导致文件夹树错位；鼠标焦点缺陷未复现，保留键盘焦点可见性"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源 p018。2026-10-23 使用现有 CSS 和真实 Electron 渲染核实布局重叠；普通鼠标点击焦点环未复现，保留键盘 focus-visible，不将原 autofocus 示例当作鼠标缺陷证据。创建期不执行代码修复。

2026-10-23 实施记录：
1. 复现与几何红灯门禁：扩展 `tests/e2e/stubApi.ts` 支持多账号与自定义文件夹状态；新增 `tests/e2e/sidebar_tree.spec.ts` 进行真实 Chromium 视口几何测量（桌面 1200x800 与移动 375x667）。在未修改前实测证实：树被水平挤在 x=156px 侧边（AC-001 失败）、错误状态横向错位（AC-002 失败）、长名称撑出 561px 溢出侧栏（AC-003 失败）。
2. 样式与布局修复：在 `src/frontend/src/design-system/tokens.css` 中将 `.account-row` 移除固定 `height: 33px` 与横向 flex 限制，转为自然块级纵向流；补充 `.side-item-group` `width: 100%; min-width: 0;`；为 `.account-folders`、`.folder-tree-row`、`.category-account-btn` 与 `.folder-item-btn` 声明 `width: 100%`，确保展开的子树与状态提示垂直排列于所属账号下方且后续账号顺延。
3. 单元测试与端到端回归：在 `Sidebar.test.tsx` 补充多账号同时展开独立折叠、空目录、加载失败及键盘 aria-expanded 的交互测试；在 `run_e2e.mjs` 纳入 `sidebar_tree.spec.ts` 形成自动化黑盒回归。
4. 规范同步：更新 `docs/blueprint/conventions.md` 固化账号标题与文件夹树纵向流排版及键盘焦点保护规则；更新 `docs/specs/inbox_ui_and_search.md` 与 `docs/specs_index.md`。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T03:15:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract`、`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 与 `(cd src/desktop && npm test)` 全通
- 黑盒：`npm --prefix src/frontend run test:e2e` 全通（7 项 E2E 用例，7.8s）
- review：Round 1 PASS（review_level=single, `review_general.md`）
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复侧栏账号文件夹树布局冲突，将 `.account-row` 改为正常块级排版并规整树项宽度，消除横向错排与纵向遮挡；完善端到端几何断言与组件单测，保持键盘焦点与 aria-expanded 可访问性。
