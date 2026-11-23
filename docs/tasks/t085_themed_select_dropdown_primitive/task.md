# Task spec

## 背景

p085（2026-11-23 用户实报 + 两张桌面端截图）记录：设置页下拉展开后弹出层为浏览器/OS 默认外观（默认蓝高亮、无设计系统表面/圆角/边框/焦点环）。根因不是某个选择器写错：原生 `<select>` / `<option>` / `<datalist>` 的弹出层由浏览器/OS 作为独立 widget 绘制，author CSS 对 `<option>` 的 background/color/border-radius 只影响 computed style、不改变绘制；`DESIGN.md:375-416` 无下拉组件规范，`src/frontend/src/design-system/` 无共享 Select 原语，关闭态只能靠 `components.css:1741/1763` 散落选择器兜底。全前端已确认 10 个 `<select>` + 2 个 `<datalist>` 均属此问题。门禁层只校验 token 语法/色值一致性（`check_css_tokens.mjs`）且 jsdom 不渲染原生 popup，故漏过。按开发铁律需补设计系统原语 + 全量迁移 + 静态/E2E 门禁，禁止只给 `<option>` 加 CSS 或逐点补丁。

## 契约区

### 范围

- 在设计系统层新增共享下拉控件原语（Select/Dropdown，含建议输入场景的 Combobox 或等价能力）：弹出层由应用内 DOM 渲染，背景/边框/圆角/选中态/焦点环全部引用 `tokens.css` 语义 token，支持双主题、键盘导航、Escape 关闭、焦点恢复、无障碍名称与 disabled 态。
- 迁移已确认的 10 个 `<select>` 与 2 个 `<datalist>` 调用点，`DESIGN.md` 增补下拉组件规范与所需 token。
- 建立静态门禁禁止组件直接使用原生 `<select>` / `<datalist>`，纳入 `npm test` 的 css:check 链；补组件层与 playwright 双主题 E2E 测试（五类代表下拉）。
- 同步 `docs/blueprint/conventions.md`、`docs/blueprint/testing.md`、spec `inbox_ui_and_search`；p085 转办闭环指向本 task。

### 非范围

- 不处理 p085 列为疑似/待定的默认控件位点：`settings-advanced` 三角 marker、`.settings-search` 的 `::-webkit-search-cancel-button`、`input[type="number"]` 步进箭头。
- 不改后端、鉴权、发信、同步逻辑；不重做无关页面视觉风格；不顺手修 docs/pending 其它条目。
- 不 push、不重新部署生产、不改现役 .env/容器。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：`settings_account_form.tsx` 与 `SettingsModal.tsx` 中已确认的 10 个 `<select>` 和 2 个 `<datalist>` 调用点全部迁移到共享下拉原语；静态扫描确认两文件不再出现原生 `<select>` / `<datalist>` 元素，其余前端文件本就无此类元素。
- [x] AC-002：共享原语具备键盘导航（方向键/Enter/Escape）、关闭后焦点回到触发器、无障碍名称与 disabled 态；组件层测试逐项断言通过。
- [x] AC-003：暗色与浅色主题下，供应商、所属分组、分组筛选、租户建议、时区建议五类代表下拉展开后，弹出层背景/边框/圆角/选中高亮均解析为 `tokens.css` 语义 token（E2E 计算样式断言 + 双主题截图），不再出现浏览器/OS 默认蓝高亮。
- [x] AC-004：`DESIGN.md` 增补 select/dropdown（含建议输入）组件规范与所需 token；`check_css_tokens.mjs` 的深色 token 一致性检查通过。
- [x] AC-005：静态门禁能拦截新增原生 `<select>` / `<datalist>` 用法：对当前源码通过、对含原生控件的反例失败，且该检查纳入 `npm test` 的 css:check 链。
- [x] AC-006：测试覆盖五类代表下拉与双主题；`docs/blueprint/testing.md` 的 `test_cmd` 与 `blackbox_verify` 全量通过，无弱化断言或临时补丁残留。
- [x] AC-007：`docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 spec `inbox_ui_and_search` 同步更新；p085 转办闭环指向 t085。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。AC-003 主断言为 E2E 计算样式，截图仅作人工复核证据；AC-001/004/005/007 由源码与文档检索、门禁正反例及 pending 状态验证；AC-002 由组件层测试验证；AC-006 由门禁命令实际执行结果验证。

## 上下文区

- 关联 spec：docs/specs/inbox_ui_and_search.md
- 关联说明：现有唯一前端 UI 契约 spec，已含 `.app-toolbar` 设计系统原语条款；本 task 在其中增补下拉控件契约并登记 t085
- 来源：p085（2026-11-23 用户实报与两张桌面端截图；现象、12 处位点清单、根因链、测试缺口与治本方向见 `docs/pending/p085_native_select_dropdown_default_style.md`）

### 有意不测

- 真实 macOS / Windows Electron 原生菜单弹出层：headless Chromium 不捕获原生 popup，且修复后弹出层改为应用内 popover；以应用内 DOM/计算样式与双主题截图替代，卡点已记入 p085 与 `.scratch/select_default_style_repro.mjs`。
- p085 疑似位点（settings-advanced 三角 marker、settings-search 清除按钮、number 步进箭头）：未计入已确认修复面，本 task 不处理。
- 后端、鉴权与发信流程：不在本 task 范围。

### 测试策略

- 静态：门禁脚本扫描 `<select>` / `<datalist>` 用法，正反例验证并挂入 css:check。
- 组件层：vitest 断言共享原语的键盘、焦点、无障碍名称与 disabled 行为。
- E2E：playwright 双主题打开五类代表下拉，断言弹出层计算样式来自 token 并留截图。
- 门禁：`test_cmd` 与 `blackbox_verify` 全量执行。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无（原生弹出层不可主题化已由 p085 与 `.scratch/` 最小复现确认，属已验证机制而非未知契约）

### 风险与回退

- 风险：12 处迁移引入交互回归（键盘、disabled、表单提交、datalist 的自由输入语义）；popover 定位/层级与现有 modal 冲突；静态门禁误伤历史或第三方用法。
- 回退：按调用点粒度逐个回退到原生控件，保留原语与门禁；popover 层级复用现有 `--z-*` token；门禁先以显式白名单收敛并写明理由，再逐步消除。

### 依赖与约束

- 无前置依赖；不改后端与现役部署；必须双主题一致。
- 约束：弹出层必须由 token 驱动，禁止硬编码颜色；不允许只用 `appearance:none` 美化关闭态而不替换弹出层（对弹出层无效）。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：下拉控件原语与禁止原生 `<select>` / `<datalist>` 条款。
- `docs/blueprint/testing.md`：原生控件静态门禁纳入 test_cmd。
- `docs/specs/inbox_ui_and_search.md`：tasks 增加 t085，增补下拉控件契约条款。
