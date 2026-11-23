---
tid: "t085"
slug: "themed_select_dropdown_primitive"
title: "设置页下拉控件主题化原语与原生 select 迁移"
status: "done"
branch: "t085_themed_select_dropdown_primitive"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "47e44e0b48219c696f9428e682de6b064cd6e6e8"
spec_source_sha: "47e44e0b48219c696f9428e682de6b064cd6e6e8"
depends_on: ""
conflicts_with: ""
note: "来源 p085；原生 select/datalist 弹出层脱离 DESIGN.md，需设计系统原语 + 12 处迁移 + 静态/E2E 门禁"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 在 `src/frontend/src/design-system/` 新建 `Select.tsx` / `select.css`，`Select` 与 `Combobox` 均以应用内 DOM 渲染弹出层，全部颜色/圆角/阴影引用新增 `--dropdown-*` 语义 token；键盘、Escape 焦点恢复、外部点击、disabled、无障碍名称在 `Select.test.tsx` 逐项覆盖。
- 迁移 `settings_account_form.tsx`（5 select + 1 datalist）与 `SettingsModal.tsx`（5 select + 1 datalist）；删除 `components.css` / `base.css` 中残留的原生 select 兜底规则。
- 新增 `check_native_select.mjs` 与 node-test 正反例，挂入 `css:check` → `npm test`；测试辅助 `changeSelect` 改为驱动新原语，`selectOptions` 读取弹出层选项；`provider_account_form.test.tsx`、`SettingsModal.test.tsx`、`settings_redesign.test.tsx`、`microsoft_account_form.test.tsx` 同步改写断言语义（非改预期凑绿）。
- 双主题 E2E `dropdown_theming.spec.ts` 覆盖供应商、所属分组、分组筛选、租户建议、时区建议五类，断言弹出层计算样式等于 token 探针值并留 `.scratch/t085_*_*.png` 截图。
- worktree 通过 `.gitignore` 内的 `src/frontend/node_modules` 软链复用主仓依赖，不进入 diff。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-23T11:29:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t085_gen_f001|important|已修|Combobox 提交后 focus 触发 onFocus 重开弹层；改为 onClick 开合并补回归断言|src/frontend/src/design-system/Select.tsx:186、Select.test.tsx:64|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`npm test`（vitest 596/596、openapi:check、css:check 全部通过）、`npx tsc -b`、`npm run build`、`npm run lint`、`npm --prefix src/desktop test`、`check_doc_sensitive.py docs --check` 全通过
- 黑盒：`npm --prefix src/frontend run test:e2e` 25 passed，含双主题 `dropdown_theming.spec.ts` 2 passed；截图落 `.scratch/t085_*_*.png`
- review：Round 1 一条 important finding 已根因修复并补回归断言；Round 2 独立复核 PASS，7/7 AC TICK-VALID
- AC 判定：见 `task.md` 行内打勾（AC-001~007 全部勾选，review Round 2 复核 TICK-VALID）

### 结果摘要

- 共享下拉原语与 12 处迁移完成，浏览器默认弹出层消失；静态门禁、组件测试与双主题 E2E 三层守护；review 发现并修复 Combobox 提交后重开回归。

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。

- specs_index: docs/specs/inbox_ui_and_search.md # tasks 增加 t085，并增补下拉控件原语契约条款
