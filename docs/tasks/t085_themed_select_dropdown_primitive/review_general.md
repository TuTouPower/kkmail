# Task review t085（reviewer_focus: 通用）

- task：`t085_themed_select_dropdown_primitive`
- spec：`docs/tasks/t085_themed_select_dropdown_primitive/task.md`
- diff_anchor：`47e44e0b48219c696f9428e682de6b064cd6e6e8`
- target：`git diff 47e44e0b48219c696f9428e682de6b064cd6e6e8`
- round：1
- reviewed_at：2026-11-23T11:32:58+08:00

reviewed_scope: 07a11144f2d93f00

## Findings

### t085_gen_f001 - Combobox 鼠标选择建议项后 popover 立即重新展开

- 严重度：important
- 锚点：AC-002（"关闭后焦点回到触发器"及"组件层测试逐项断言通过"）——鼠标选择路径下选择后未保持关闭，测试因未模拟真实失焦而假绿；同时构成可观测交互回归
- 位置：`src/frontend/src/design-system/Select.tsx:187`（`onFocus`）、`src/frontend/src/design-system/Select.tsx:133`（`close`，focus 在 135）、`src/frontend/src/design-system/Select.tsx:138`（`commit`）；假绿根因 `src/frontend/src/test/render.tsx:50`（`click` 仅派发 click）
- 问题：Combobox 的 input `onFocus={() => setOpen(true)}`（Select.tsx:187）无条件在每次聚焦时展开。`commit()`（:138）调用 `close(true)`（:133），其中先 `setOpen(false)` 再 `inputRef.current?.focus()`（:135）。用户用鼠标点击 `div[role=option]` 时，mousedown 使 input 失焦（activeElement→body）；随后 commit 的 `focus()` 重新聚焦 input，同步触发 `onFocus` → `setOpen(true)`。React 批处理下最终 `open=true`，建议列表在选择后立刻重开并遮挡下方内容；原生 `<datalist>` 选择后关闭，属迁移引入的交互回归。`Select.test.tsx` 用的是 `render.tsx:50` 的 `click` helper（仅 `el.click()`，不派发 mousedown、不模拟焦点转移），input 不失焦，`focus()` 不触发 `onFocus`，因此测试全绿却未覆盖该路径。E2E `dropdown_theming.spec.ts` 也只点击 trigger 关闭，不提交选项，同样未覆盖。
- 建议：在 `close(true)` 中以 ref 标志抑制紧随 focus 的一次 `onFocus` 重开（如 `suppressFocusOpenRef`，在 onFocus 中检查并复位）；或把 `onFocus` 展开条件收敛为仅空输入时展开；或在 option 的 `onMouseDown` 上 `preventDefault()` 保持 input 焦点。补一条用真实 `mousedown→mouseup→click` 序列断言"选择后 `[data-select-open]` 消失"的组件测试。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 本轮新发现：1 条（important×1）
- 未进表的提示：`src/frontend/scripts/check_native_select.mjs:173` 的门禁为逐行、大小写敏感匹配 `<select`/`<datalist>`；当前源码无跨行或大写变体写法，不构成现役绕过，仅作严格性提示。
- 总体判断：存在 1 条未解决 important（f001，Combobox 选择后重开 + 测试假绿），AC-002 打勾作废，判 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。实跑 `check_native_select.mjs` 全 src 扫描通过，两文件 10 select + 2 datalist 全部迁移为 Select/Combobox，无原生控件残留。
- AC-002：TICK-VOID，re_verified。键盘/Enter/Escape/焦点恢复/无障碍名称/disabled 测试虽全过，但 Combobox 鼠标选择后 popover 因无条件 onFocus 重开（f001）；click helper 不模拟 mousedown 失焦导致该路径假绿，"关闭后"语义未在真实交互下成立。
- AC-003：TICK-VALID，re_verified。实跑 `dropdown_theming.spec.ts` 双主题 2/2 通过，五类下拉计算样式分别等于 `--dropdown-*` token 探针值并留 `.scratch/t085_*_*.png` 截图。
- AC-004：TICK-VALID，re_verified。`DESIGN.md` 增补组件规范与 token 清单；`css:check` 的 dark token 一致性检查通过，8 个 `--dropdown-*` 均引用双主题已定义语义 token。
- AC-005：TICK-VALID，re_verified。实跑 `check_native_select.node-test.mjs` 正反例与 `check_native_select.mjs` 全绿，`package.json` 的 `css:check` 链确已纳入，`npm test` 调用 css:check。
- AC-006：TICK-VALID，re_verified。vitest 596/596、css:check、tsc -b、vite build、dropdown E2E 全过；改动测试均为语义适配，未见 .skip/恒真断言/临时补丁；test_cmd 中与本 task 无关的 pytest contract、desktop、doc sensitive 门禁未单独重跑。
- AC-007：TICK-VALID，re_verified。`conventions.md`/`testing.md`/spec `inbox_ui_and_search.md` 均同步更新；p085 基线已 `fix_ref: t085`、`resolution=transferred` 闭环。

coverage = 7/7

verdict: FAIL

## Round 2 (2026-11-23T11:38:42+08:00)

- round：2
- reviewed_at：2026-11-23T11:38:42+08:00

reviewed_scope: c0409b7a1531ea0b

## Findings

本轮无新发现。

## 结论

- 前轮 finding 复核：t085_gen_f001 已消除。`src/frontend/src/design-system/Select.tsx:187` 的 Combobox input 由 `onFocus={() => setOpen(true)}` 改为 `onClick={() => setOpen(true)}`；`close(true)` 中的 `inputRef.current?.focus()`（:135）仅触发 focus 事件，不再经 onClick 重开 popover。`src/frontend/src/design-system/Select.test.tsx` 第三用例新增两条断言：鼠标选中后 `[data-select-open="true"]` 为 null、`click(input)` 后可重开。`src/frontend/src/test/render.tsx:55-62` 的 `typeInto` 不聚焦 input，故 `commit` 的 `focus()` 产生真实焦点转移（body→input）与 focus 事件——旧 onFocus 实现下该断言会变红，新增测试非假绿；本轮实跑 3/3 通过。全 src grep `onFocus` 仅命中 `settings_account_form.tsx:221` 的 window focus 监听，无其他展开位点，无同类问题。
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：前轮唯一 blocker f001 已真实修复且新增测试能有效锁死回归；重跑 css:check、vitest 596/596、双主题 E2E 2/2 全绿，全部 AC 打勾成立，判 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`check_native_select.mjs` 全 src 扫描通过；`settings_account_form.tsx`/`SettingsModal.tsx` grep `<select`/`<datalist` 无命中，10+2 调用点均迁移为 Select/Combobox。
- AC-002：TICK-VALID，re_verified。实跑 `src/frontend/src/design-system/Select.test.tsx` 3/3：方向键/Enter/Escape、焦点恢复、无障碍名称、disabled 与 f001 回归断言全过；Combobox 改用 onClick 后选择不再重开且可重开。
- AC-003：TICK-VALID，re_verified。本轮实跑 `dropdown_theming.spec.ts` 双主题 2/2 通过，五类下拉计算样式等于 `--dropdown-*` token 探针值，并生成 10 张 `src/frontend/.scratch/t085_*_{dark,light}.png` 截图。
- AC-004：TICK-VALID，re_verified。`css:check` 的 dark token 一致性检查 9/9 通过，`DESIGN.md` 下拉组件规范与 token 清单齐备。
- AC-005：TICK-VALID，re_verified。`css:check` 输出含 `check_native_select.node-test.mjs` 正反例 2/2 通过；`src/frontend/package.json` 的 `test` 脚本确含 `npm run css:check`。
- AC-006：TICK-VALID，re_verified。本轮实跑 vitest 全量 596/596、css:check、双主题 E2E 2/2 全过；改动测试均为语义适配，未见 `.skip`/恒真断言/临时补丁。
- AC-007：TICK-VALID，re_verified。`conventions.md`/`testing.md`/spec `inbox_ui_and_search.md` 同步更新；p085 `fix_ref: t085`、`resolution=transferred` 闭环。

coverage = 7/7

verdict: PASS
