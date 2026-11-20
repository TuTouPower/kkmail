---
pid: "p080"
slug: "reader_toolbar_actions_overlap_sender_email"
status: "closed"
resolution: "transferred"
reason: "已核实范围与根因链，转交 t080 建立工具栏布局契约、断点单一真相与共享 360px 几何门禁"
fix_ref: "t080"
---
# p080 手机端阅读页工具栏操作按钮绝对定位居中，窄屏遮挡邮箱地址

- 现象：2026-11-20 用户实报并附两张手机截图（`/tmp/kkmail_shot_phone.png` 为 kkmail 阅读页，`/tmp/kkmail_shot_gmail.png` 为 Gmail 打开同一封 Cloudflare 周报，渲染正常）。kkmail 截图顶部标题栏中，账号邮箱 `fengandelliot@gmail.com` 的文字被一排操作图标压住：归档图标叠在邮箱文字上，删除、标记图标紧跟其后，邮箱地址被遮挡而难以辨认。用户原话「上面那 3 个按钮布局有问题，和邮箱挡住了」。

- 范围澄清：截图中远程图片拦截提示条本身（`远程图片已拦截（防追踪）。[仅此邮件允许加载]` / `[总是允许来自此发件人的图片]`）使用 `display:flex; flex-wrap:wrap`，已正常换行成两行，未与上方信息重叠；用户所指「3 个按钮」是标题栏中居中的操作按钮（标为已读/未读、删除、标记）。本条只登记标题栏遮挡问题。

- 影响：手机窄屏下阅读页顶部账号邮箱被操作按钮遮挡，用户无法看清当前邮箱账号；按钮图标与邮箱文字叠在一起也影响点击目标辨识。桌面宽屏因邮箱文字较短通常不触发，问题被掩盖。

- 根因：（产品缺陷，前端布局）

    1. JSX：`src/frontend/src/components/MessageReader.tsx:386-423`，工具栏结构为 `<div class="reader-toolbar">` 内含「返回按钮（mobile-only）」+ `<div class="reader-location">账号邮箱</div>` + `<div class="reader-toolbar-actions">操作按钮组</div>`（MR02 已读、MR04 删除、MR03 标记，暗色下另有 MR11）。
    2. CSS：`src/frontend/src/design-system/components.css:1258-1269` 定义 `.reader-toolbar` 为 `position:relative; display:flex; justify-content:space-between; height:47px`；`:1350-1358` 定义 `.reader-location` 为 `flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis`，即会占满剩余宽度；`:1360-1368` 定义 `.reader-toolbar-actions` 为 `position:absolute; left:50%; top:50%; transform:translate(-50%,-50%)`；`:1370-1379` `.reader-action` 为 36×36。
    3. 机制：操作按钮组被绝对定位移出 flex 文档流并强制居中于工具栏，而邮箱文字所在 `.reader-location` 是 `flex:1` 占满整行。两者不在同一布局约束中，按钮组直接覆盖在邮箱文字中部；窄屏时邮箱地址更长、可用宽度更小，遮挡必然发生（截图中归档图标正好压在邮箱文字上）。移动端媒体查询（`components.css:1550` 附近）只切换 pane 显隐，未对工具栏布局做任何窄屏适配。
    4. 同类位点扫描：全仓 CSS 中仅此一处 `transform: translate(-50%, -50%)` 的绝对定位居中工具条；未发现其他已确认同类位点。任何较长账号邮箱在窄容器中都会复现，属同一位点而非独立缺陷。

- 修复方向建议（未实施）：取消 `.reader-toolbar-actions` 的绝对定位与 `left:50%/transform`，改为正常 flex 项（`flex:0 0 auto`），让 `.reader-location` 保留 `flex:1; min-width:0; text-overflow:ellipsis` 自动让位；窄屏下进一步给邮箱文字更明确的最大宽度或把操作按钮移入独立一行/收进菜单，保持 36px 点击目标。避免用固定宽度或 `z-index` 打补丁掩盖重叠。

- 测试缺口：现有 `src/frontend/src/components/MessageReader.test.tsx:334/343/368/468/548/568/594` 只断言 `.reader-location` 的 `textContent`，从不测量元素几何；测试环境为 jsdom（`vite.config.ts:10`），无真实布局与 CSS 计算，故漏过。建议补：其一，CSS/组件层断言操作按钮组不再使用绝对定位居中（防回归）；其二，移动端 E2E（如 360px 视口）取 `.reader-location` 与 `.reader-toolbar-actions` 的 `getBoundingClientRect()`，断言两者矩形不相交，并用长邮箱账号覆盖边界场景。

- 线索：截图 `/tmp/kkmail_shot_phone.png`、`/tmp/kkmail_shot_gmail.png`（本轮已查看）；代码位置 `src/frontend/src/components/MessageReader.tsx:386-423`、`src/frontend/src/design-system/components.css:1258-1269,1350-1379`。本轮只做只读取证与截图核对，未创建 `.scratch/` 复现文件，未改代码。

- 登记判断：与 p081 为**独立根因、分开登记**。本条是宿主应用标题栏 flex/绝对定位布局错误；p081 是邮件正文 iframe 文档缺 viewport 与宽度适配，二者无共享组件或样式，修复范围互不重叠。

- 处理：t080；resolution=transferred；reason=已核实范围与根因链，转交 t080 建立工具栏布局契约、断点单一真相与共享 360px 几何门禁

- 架构级根因链（开发铁律视角：不停留在某行 CSS）：

    1. **响应式被降格为一个断点常量 + 页面级 pane 切换，没有组件级窄屏降级规范**。`docs/blueprint/conventions.md:19` 只写「移动端 760px 响应式断点（`src/frontend/src/lib/viewport.ts`）」，`:72` 也只规范侧栏抽屉与 760px 状态独立；`viewport.ts:4` 仅导出 `MOBILE_MAX_WIDTH=760`，真正消费者只有 `MessageList.tsx`（`:10,496` 切换 mobileView）。CSS 侧 `components.css:1524` 用注释「760px must match MOBILE_MAX_WIDTH」手工同步常量；`@media (max-width:760px)`（`:1525-1575`）只处理侧栏抽屉、list/reader pane 显隐、backdrop。没有任何条款规定「工具栏在窄屏如何降级」，故 `.reader-toolbar` 的绝对定位居中从未被契约覆盖。
    2. **设计系统缺少工具栏原语，同类组件各自为政**。`src/frontend/src/design-system/` 只有 `base.css`/`tokens.css`/`components.css`/`darkTheme.test.ts`，无 `AppToolbar`/`ActionBar` 之类共享组件或布局规范。结果是两套互不兼容的写法并存：`.reader-toolbar-actions` 绝对定位居中（`components.css:1360-1368`），`.settings-toolbar` 却是 `display:flex; flex-wrap:wrap`（`:1732`）并在窄屏追加 `flex-basis:100%`（`:1846`）。设置页做对了换行、阅读页没做，不是偶发笔误而是缺少统一抽象。
    3. **补丁式积累已被写进样式表结构**。`components.css:1579` 出现全局追加块 `/* --- list header / selection / checkbox fixes (review 2026-10-20) --- */`，依赖选择器和 `min-width:0` 逐点兜底；`docs/pending/` 中含「手机/移动端/窄屏/布局/溢出/重叠/遮挡」的条目共 15 个（p014、p018、p026、p064、p065、p061 等）。本条是这个模式的又一次复现，而非孤立缺陷。
    4. **测试层同样是个案式，不是体系式**。前端 54 个测试文件中仅 2 个使用几何断言且都被 mock（`UiReferenceOverlay.test.tsx:30-233`、`CopyAddress.test.tsx:72`），16 个文件依赖 `textContent`；`MessageReader.test.tsx:334/343/368/468/548/568/594` 只断言邮箱文本。E2E 确实有几何检查，但都绑定具体 bug：`sidebar_tree.spec.ts:77-534` 大量 `boundingBox()` 对齐断言源于 p018/p026，`provider_account_forms.spec.ts:23-24` 的 320px `scrollWidth<=clientWidth` 源于 p055；没有通用「窄屏 + 长文本 + 工具栏不重叠」门禁。`test_cmd`/`blackbox_verify`（`docs/blueprint/testing.md:29-46`）因此漏过阅读页工具栏。与 p081 共享同一共性根因：**布局保证靠逐 bug 补 CSS + 逐案加测试，缺少设计系统级契约与通用几何门禁**。

- 治本方案（根因级，未实施）：

    1. **设计系统引入工具栏原语与窄屏降级规范**：新增共享 `AppToolbar`/`ActionBar`（或等价 CSS 原语），契约规定——主标题/账号信息占 `flex:1; min-width:0` 并省略，操作区作为常规 flex 项 `flex:0 0 auto`、**禁止绝对定位覆盖内容**，窄屏时次要信息换行/省略或操作收进次级行/菜单，点击目标统一 36px。迁移 `.reader-toolbar`，并同步审计 `.list-header`、`.settings-toolbar`，消除两套写法。
    2. **断点单一真相**：把 `MOBILE_MAX_WIDTH` 作为唯一来源，CSS 断点由构建生成或 TS 从 CSS 变量读取，删除 `:1524` 手工同步注释；避免下次两端漂移产生新的窄屏空洞。
    3. **补一层通用几何门禁**：提供 `assertNoOverlap(rectA, rectB)` 测试 helper 与「360px 视口 + 长邮箱账号」E2E 模板，覆盖所有工具栏；同时加一条组件/CSS 契约断言禁止 `.reader-toolbar-actions` 回归到绝对定位居中。把该模板纳入 `blackbox_verify`，使同类问题以后被自动拦住。
    4. **为什么是根因级而非补丁**：本方案改的是「组件布局契约 + 单一断点来源 + 通用门禁」，覆盖所有工具栏与后续新增组件；只改 `.reader-toolbar-actions` 的定位仍是逐点补丁，下次换个工具栏/换段长文本会再犯。
    5. **代价与风险**：共享原语迁移触及阅读页、列表头部、设置工具栏三处，存在视觉回归风险，需逐屏截图比对；断点单一真相可能需要小型构建脚本或 CSS 变量桥接；几何 helper 依赖真实浏览器 E2E（jsdom 无布局），会增加 `blackbox_verify` 时长。风险可控且一次性，换来整类缺陷的自动拦截。
