---
pid: "p085"
slug: "native_select_dropdown_default_style"
status: "closed"
resolution: "transferred"
reason: "已核实根因与全部同类位点（10 select + 2 datalist），转交 t085 建立下拉原语并迁移"
fix_ref: "t085"
---
# p085 设置页原生 select/datalist 下拉弹出层使用浏览器默认样式，不符合 DESIGN.md

- 现象：2026-11-23 用户实报并附两张桌面端暗色主题截图。截图 1「所属分组」展开后，选项（不加入分组/网易/QQ/Outlook/Gmail）为浏览器/OS 默认外观：选中项默认蓝色高亮、无设计系统表面/圆角/边框/焦点环；截图 2「邮箱供应商」展开后，10 个供应商选项同样为默认外观，选中项默认蓝底。用户原话「很多地方还在使用默认的样式，没有使用符合 design MD 的样式」。关闭态 select 已用 token（深灰、8px 圆角），问题集中在展开的弹出层。

- 影响：设置页所有下拉交互在展开态脱离 DESIGN.md 设计语言（语义 token、8px 圆角、低对比边框、清晰焦点环、双主题一致），与周围已主题化控件割裂；暗色下默认蓝高亮与 `--blue` / `--accent` 不一致。已确认同类位点共 10 个 `<select>` + 2 个 `<datalist>`，全部在设置区：

    01. `src/frontend/src/components/settings_account_form.tsx:441` 邮箱供应商
    02. `settings_account_form.tsx:442` 连接方式
    03. `settings_account_form.tsx:442` 所属分组
    04. `settings_account_form.tsx:485` OAuth 应用类型
    05. `settings_account_form.tsx:487` Microsoft 登录方式
    06. `settings_account_form.tsx:488` `<datalist id="microsoft-tenants">` 租户建议
    07. `src/frontend/src/components/SettingsModal.tsx:455` 按分组筛选
    08. `SettingsModal.tsx:456` 按同步状态筛选
    09. `SettingsModal.tsx:457` 按邮箱域名筛选
    10. `SettingsModal.tsx:461` 批量移动分组
    11. `SettingsModal.tsx:484` 每行移动分组
    12. `SettingsModal.tsx:621` `<datalist id="settings-timezones">` 时区建议

    疑似/待定（默认控件样式但非下拉列表，未计入已确认修复面）：`<details class="settings-advanced">` 的原生三角 marker（`settings_account_form.tsx:449/463/530`，`components.css:1830-1831` 仅设光标/字号/颜色）；`.settings-search input` 的原生 `::-webkit-search-cancel-button`（`SettingsModal.tsx:454/500`，仅 `.tree-account-search` 在 `components.css:638` 隐藏）；`input[type="number"]` 原生步进箭头（`settings_account_form.tsx:365`、`SettingsModal.tsx:621`）。原生 checkbox 已用 `accent-color`（`components.css:1755/1828`），不计入。

- 根因：（产品缺陷，前端设计系统缺少下拉原语）

    1. DESIGN.md 有完整 token 体系（colors/typography/spacing/rounded/components），但 Components 章节（`DESIGN.md:375-416`）没有 select/dropdown/下拉菜单的组件规范；`DESIGN.md:232-253` 只定义 `search-input-*` / `settings-panel-*`，无 select/popover/option 专用 token。「符合 design MD 的样式」因此只能落到「用语义 token 主题化」，而原生弹出层无法被主题化。
    2. 设计系统层（`src/frontend/src/design-system/` 仅 `tokens.css` / `base.css` / `components.css` / `darkTheme.test.ts`）没有共享 Select/Dropdown/Combobox 组件或原语。所有调用点直接用原生 `<select>` / `<option>` / `<datalist>`，关闭态靠散落选择器兜底：`components.css:1741` 的 `.settings-toolbar select` / `.settings-bulk-bar select` / `.settings-field select` 等、`:1763-1764` 的 `.settings-account-row > select`。10 个 select 关闭态全部被覆盖，所以关闭态看着正常；弹出层不在任何选择器内。
    3. 机制：原生 `<select>` 展开列表由浏览器/OS 作为独立 native widget 绘制（Chromium 为 `appearance:auto`，Electron 下由 OS 菜单绘制），author CSS 对 `<option>` 的 `background` / `color` / `border-radius` 在弹出层被忽略——只改变 computed style，不改变实际绘制。`.scratch/` 复现确认 `appearance:auto`、关闭态 token 生效（bg `rgb(40,45,48)`、radius `8px`）、`option` 无自定义规则；headless 截图无法捕获原生 popup（独立 widget），视觉证据以用户实机截图为准。这是平台行为，不是某个选择器写错。
    4. 架构级：与 p080 记录的「设计系统缺少工具栏原语，同类组件各自为政」「补丁式积累」同源——没有 Select 原语，靠选择器逐点兜底；新增下拉点只会继续复制原生 `<select>`，无法收敛。
    5. 同类位点已扫全：全前端 `<select>` 仅上述 10 个、`<datalist>` 仅 2 个，无其它文件使用；`components.css` / `tokens.css` 全文无 `option` 或弹出层自定义规则。以上 12 处构成同一修复面。

- 测试缺口：`src/frontend/scripts/check_css_tokens.mjs` 只校验 token 声明外无硬编码 hex（`:78-92`）、`var(--)` 引用均已声明（`:94-119`）、DESIGN.md 深色颜色与 tokens.css 一致（`:145-168`）。原生 `<select>` 关闭态全用 token，三项全过；弹出层绕过 CSS 体系，静态令牌门禁看不见。`src/frontend/src/design-system/darkTheme.test.ts` 只断言 token 值与少量组件规则（焦点环、分层加载、z-index、选中态），无 select/dropdown 或弹出层主题化断言。单测跑在 jsdom（`vite.config.ts:10`），无布局、不渲染原生 popup；`SettingsModal.test.tsx`、`provider_account_form.test.tsx`、`settings_redesign.test.tsx` 只断言值与交互语义。E2E 有 playwright，但无「逐个打开下拉并断言弹出层 token 化」的通用门禁。建议补：其一，静态门禁（扩展 check_css_tokens.mjs 或新脚本）禁止组件直接使用 `<select>` / `<datalist>`，强制走共享 Select 原语；其二，组件层断言共享 Select 渲染 token 化 popover（class/role/键盘交互）且 DOM 不出现原生 popup；其三，playwright 双主题 E2E 打开每类下拉，断言弹出层 surface/border/radius/highlight 来自 token，覆盖供应商、分组筛选、租户 datalist、时区 datalist 等代表场景。

- 修复方向建议（未实施）：设计系统新增 Select/Dropdown 原语（token 化 popover、键盘导航、双主题、`appearance:none` 或全自定义控件），迁移 10 个 `<select>` 与 2 个 `<datalist>` 调用点；datalist 建议改为带建议的 Combobox 或等价自定义控件。不要试图给 `<option>` 加 CSS 规则（对弹出层无效）；同时在 DESIGN.md 补 select/dropdown 组件规范与所需 token。

- 线索：`.scratch/select_default_style_repro.html`（最小页面：当前 `.settings-field select` token 样式 + 尝试给 `option` 上 token）、`.scratch/select_default_style_repro.mjs`（Playwright：打印 appearance/computed style 并截图）、`.scratch/select_default_style_closed.png`、`.scratch/select_default_style_open.png`（headless 不捕获原生弹出层，卡点已记录于脚本输出）。用户实机截图为原始视觉证据。代码位置：上文 TSX 行号、`components.css:1741-1745,1763-1764,1827-1832`、`DESIGN.md:375-416`。本轮只做只读取证与最小复现，未改生产代码。

- 处理：t085；resolution=transferred；reason=已核实根因与全部同类位点（10 select + 2 datalist），转交 t085 建立下拉原语并迁移
