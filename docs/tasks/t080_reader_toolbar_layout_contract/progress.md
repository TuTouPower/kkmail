---
tid: "t080"
slug: "reader_toolbar_layout_contract"
title: "阅读页工具栏布局契约与窄屏降级"
status: "done"
branch: "t080_reader_toolbar_layout_contract"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "81b6a255979bbd771f16c59e177da1378e04683f"
spec_source_sha: "81b6a255979bbd771f16c59e177da1378e04683f"
depends_on: ""
conflicts_with: ""
note: "来源 p080；按开发铁律建立设计系统级工具栏布局契约、断点单一真相与 360px 几何门禁；共享门禁由本 task 先落地供 t081 复用"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 设计系统新增 `.app-toolbar` / `.app-toolbar-primary` / `.app-toolbar-actions` 共享原语；阅读页工具栏迁移到该原语，操作组由绝对定位居中改为常规 flex 项（`flex:0 0 auto`），主信息槽 `flex:1; min-width:0` 省略溢出。
- 断点单一来源：`src/frontend/src/design-system/breakpoints.ts` 导出 `BREAKPOINTS`，`viewport.ts` 复用并再导出；`check_layout_contracts.mjs` 校验 CSS 媒体查询值属于该来源且操作区不回归绝对定位，已挂入 `npm run css:check`。
- 共享 360px 几何门禁落盘于 `tests/e2e/layoutGeometry.ts`（`assertNoOverlap` / `setNarrowViewport`），`reader_toolbar.spec.ts` 接入；t081 直接复用，不复制实现。
- AC-003 审计：`.list-header`（`components.css:912,1003`）与 `.settings-toolbar`（`:1732,1846`）均为常规 flex/wrap + `min-width:0`，不存在绝对覆盖，符合契约，未改动；其余工具栏无绝对覆盖命中。
- AC-004 反例验证：临时把 `breakpoints.ts` 的 mobile 改为 720 后 `check_layout_contracts.mjs` 以退出码 1 失败并列出 760px 媒体查询不在单一来源；恢复后重跑通过。
- 门禁实测：`npm test`（vitest + openapi + css:check 含新脚本）通过、`npx tsc -b` 通过、`npm run build` 通过、`npm run test:e2e` 22 passed（含新增 reader_toolbar.spec.ts）。
- worktree 环境：`src/frontend/node_modules` 软链主仓已安装依赖，该路径被 `src/frontend/.gitignore` 忽略，不进入交付 diff。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-20T19:35:00+08:00)

双轴均 PASS（code / test），AC 7/7 全部 TICK-VALID；finding 2 条，均 minor。code f001 已修复并在 Round 2 复审确认；test f001 撤回（理由见下表）。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t080_code_f001|minor|已修|断点检查器正则只取 `@media` 后第一个括号，漏检 `@media screen and (max-width: 723px)` 等复合写法；现改为先取 `@media[^{]+` 预条件、再对整段全局匹配 `max-width:\s*(\d+)px`，复合负例实测退出码 1、恢复后退出码 0，Round 2 独立复验通过|src/frontend/scripts/check_layout_contracts.mjs:20|
|t080_test_f001|minor|撤回|契约单测只断言 class 标记而非 computed style：jsdom 测试环境不加载 CSS，`getComputedStyle().position` 无法真实反映样式表；AC-002 的有效证据是 360px E2E `boundingBox` 不相交断言与静态契约检查（绝对定位反例退出码 1），二者均已由 reviewer 独立复验，单测仅作契约标记，不重复无效断言|—|

### Round 2 (2026-11-20T19:42:00+08:00)

双轴均 PASS，reviewed_scope=0b63f6061dbac01b，AC 7/7 TICK-VALID，零新 finding；前轮 t080_code_f001 经复合/带媒体类型/双 max-width 负例独立复验确认修复。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：src/frontend `npm test` 通过（vitest + openapi:check + css:check 含新增 `check_layout_contracts.mjs`）；`npx tsc -b`、`npm run build` 通过；断点单一来源正例退出 0、mobile=720 与复合 723px 负例均退出 1。
- 黑盒：`npm run test:e2e` 22 passed，含新增 `reader_toolbar.spec.ts` 在 360px 视口、长邮箱账号下断言 `.reader-location` 与 `.reader-toolbar-actions` 矩形不相交。
- review：full 双轴 2 轮；Round 1 code/test 均 PASS（minor 各 1），Round 2 双轴均 PASS 零 finding；AC 7/7 TICK-VALID。
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 全部 7 条 AC 满足；交付共享工具栏原语、断点单一来源与可复用 360px 几何门禁，t081 可直接复用；无遗留 finding、无 follow-up。
- specs_index：docs/specs/inbox_ui_and_search.md 的 tasks 已登记 t080，并补入工具栏布局契约与断点单一来源条款。
