---
pid: "p081"
slug: "mail_body_iframe_missing_viewport_overflow"
status: "closed"
resolution: "transferred"
reason: "已核实范围与根因链，转交 t081 在 srcdoc 唯一收口处确立邮件文档渲染契约并复用 t080 共享门禁"
fix_ref: "t081"
---
# p081 HTML 邮件正文 iframe 缺少 viewport 与宽度适配，固定宽度邮件在手机上横向溢出

- 现象：2026-11-20 用户实报并附两张手机截图（`/tmp/kkmail_shot_phone.png` 为 kkmail 阅读页，`/tmp/kkmail_shot_gmail.png` 为 Gmail 打开同一封 Cloudflare 周报，渲染正常）。kkmail 截图中邮件正文按桌面宽度排版并横向溢出：大标题 `Your weekly Web Analytics` 右侧被截断（只显示到 `Analytics`），列表项 `Account: Fengandelliott@gmail.com's Acco…` 被截断，`Weekly summary from November 8, 2…` 被截断，底部表格列名 `Total sites / Visits / …` 右侧内容被切掉；页面整体没有把邮件内容约束/缩放到屏幕宽度内。Gmail 截图显示同一邮件标题换行、Cloudflare logo 与正文表格完整适配手机屏宽。用户原话「邮件正文的网页没有使用移动端展示」。

- 影响：所有含固定宽度排版（常见于邮件 HTML 的 `width` 表格布局）的 HTML 邮件，在手机上正文右侧内容不可见，需手动横向滚动且仍难阅读；标题、链接、统计表格等关键信息被截断。桌面端因宽度足够不受影响。

- 根因：（产品缺陷，前端渲染适配缺失）

    1. 渲染路径：`src/frontend/src/components/MessageReader.tsx:566-657`，HTML 正文通过 `<iframe className="email-body email-body-frame" srcDoc={mailSrcdoc} sandbox={MAIL_IFRAME_SANDBOX} ...>` 渲染，iframe 自身样式为 `width:'100%', flex:1, minHeight:'calc(100vh - 240px)'`，只约束了 iframe 外框宽度。
    2. `src/frontend/src/lib/mailBody.ts:385-414` 的 `buildMailSrcdoc()` 构造 iframe 文档：`<head>` 包含 `<meta charset>`、`<meta name="referrer">`、`<meta name="color-scheme">`、CSP、`<base>` 和 `<style>`；**没有 `<meta name="viewport" content="width=device-width, initial-scale=1">`**。宿主 `src/frontend/index.html:6` 虽有 viewport meta，但只作用于宿主页面，不会继承进 `srcdoc` 这个独立文档。
    3. srcdoc 内的样式仅有 `body{margin:0;font:...;word-wrap:break-word;background;color}`、`a{color:...}`、`img{max-width:100%;height:auto}`（`:401-403`）。没有任何针对 `table` 的宽度约束，也没有缩放（transform scale）、iframe `scrollWidth` 适配或固定宽度重写逻辑。`word-wrap:break-word` 与 `img{max-width:100%}` 只能处理长文本与图片，无法约束邮件 HTML 中以 `width="..."` 属性/内联样式写死的表格与单元格宽度。
    4. 机制：sandbox iframe 是独立浏览上下文；缺少 viewport meta 时移动浏览器按默认约 980px 的桌面布局视口排版内文档，固定宽度邮件表格按该宽度渲染，iframe 的可视口只有手机屏宽，右侧内容落在水平可滚动/被裁剪区域，表现为截图中的整片右侧截断。属于「渲染容器宽度约束缺失」，不是邮件内容被安全清洗破坏（CSP/sandbox/DOMPurify 仍按设计工作）。
    5. 同类位点扫描：全仓仅 `buildMailSrcdoc()` 一处构造邮件正文 srcdoc（`MessageReader.tsx` 两个 iframe 分支均复用 `mailSrcdoc`），故该根因覆盖所有 HTML 邮件；纯文本正文分支（`MessageReader.tsx:659` 起）与解析失败占位组件不经过此路径，不受影响。未发现其他已确认同类位点。

- 修复方向建议（未实施）：在 `buildMailSrcdoc()` 的 `<head>` 补 viewport meta；在 srcdoc 内增加防御性宽度约束（例如 `html,body{max-width:100%;overflow-x:auto}` 配合 `table{max-width:100%;height:auto}` 或按邮件固定宽度计算缩放），必要时参考 Gmail 做法把写死的表格宽度重写为百分比/自适应。须保留现有 CSP、sandbox、`no-referrer` 安全边界；注意过度覆盖表格内联宽度可能破坏邮件原有版式，建议先用 Cloudflare 周报这类固定宽度样本分级验证（先 viewport meta，再表格约束/缩放）。

- 测试缺口：`src/frontend/src/lib/mailBody.test.ts` 与 `src/frontend/src/components/MessageReader.test.tsx:434-731` 只断言 srcdoc 的 CSP、颜色、暗色反相、远程图片代理等字符串，没有任何 viewport meta 或表格宽度断言；jsdom（`vite.config.ts:10`）无布局引擎，测不出横向溢出。建议补：其一，在 `mailBody.test.ts` 断言 srcdoc 含 viewport meta 与表格宽度约束样式（防回归）；其二，移动端 E2E/截图测试，用固定宽度表格邮件的 fixture 在 360px 视口断言 iframe 文档 `scrollWidth <= clientWidth`（或标题/表格右边界落在屏内），对照 Gmail 效果。

- 线索：截图 `/tmp/kkmail_shot_phone.png`、`/tmp/kkmail_shot_gmail.png`（本轮已查看）；代码位置 `src/frontend/src/components/MessageReader.tsx:566-657`、`src/frontend/src/lib/mailBody.ts:385-414`、`src/frontend/index.html:6`（宿主有 viewport、srcdoc 无）。本轮只做只读取证与截图核对，未创建 `.scratch/` 复现文件，未改代码。

- 登记判断：与 p080 为**独立根因、分开登记**。p080 是宿主应用标题栏 flex/绝对定位布局错误；本条是邮件正文 iframe 内文档缺 viewport 与宽度适配，二者无共享组件或样式，修复范围互不重叠。

- 处理：t081；resolution=transferred；reason=已核实范围与根因链，转交 t081 在 srcdoc 唯一收口处确立邮件文档渲染契约并复用 t080 共享门禁

- 架构级根因链（开发铁律视角：不停留在缺一行 meta）：

    1. **iframe/srcdoc 的技术选型只完成了「安全契约」，从未定义「渲染契约」**。`docs/blueprint/architecture.md:145-159` 记录该选型的驱动是零外部出网与 CSP/sandbox 隔离（沙箱 `srcdoc` 继承宿主 CSP、`img-src 'self' data: cid:`、安全图片代理），`src/frontend/src/lib/mailBody.ts:418-447` 的 A384 决策也只围绕 sandbox 标志与弹窗安全。选型本身正确，但「这个独立文档应如何适配不同视口」不在决策范围，移动端适配从一开始就漏在选型环节——srcdoc 是独立浏览上下文，宿主 `index.html:6` 的 viewport meta 不会继承进去。
    2. **唯一的文档构造收口处没有布局契约**。`buildMailSrcdoc()`（`mailBody.ts:385-414`）是全部 HTML 正文的唯一生成点，head 里注入了 charset、referrer、color-scheme、CSP、`<base>`，style 里只有 `img{max-width:100%;height:auto}`（`:403`），既无 viewport meta，也无 `table` 宽度约束或缩放策略。邮件 HTML 的固定宽度表格因此按移动浏览器默认约 980px 布局视口渲染，iframe 只露出左侧一屏——这是「文档构造层缺契约」，不是某一封邮件的问题。
    3. **布局契约在别处有、在邮件正文处没有，说明是体系缺口而非疏忽**。`docs/blueprint/conventions.md:86-87` 对侧栏几何有严格规范（`boundingBox.x` 误差 ≤1px、24px 阶梯缩进），并有 `sidebar_tree.spec.ts` 的 E2E 几何断言；`provider_account_forms.spec.ts:23-24` 也有 320px 视口 `scrollWidth<=clientWidth` 断言。这些是按 bug 逐案补的（p018/p026/p055），说明团队具备几何验收能力，但没有任何通用机制把它施加到邮件正文 iframe 上。与 p080 共享同一共性根因：**布局保证靠逐 bug 补 CSS + 逐案加测试，缺少设计系统级契约与通用几何门禁**（p080 侧表现为工具栏绝对定位无窄屏降级规范，本条表现为 srcdoc 文档无视口/宽度契约）。
    4. **测试体系天然看不见此类问题**：`mailBody.test.ts` 与 `MessageReader.test.tsx:434-731` 只对 srcdoc 做 CSP/颜色/代理字符串断言；jsdom（`vite.config.ts:10`）无布局引擎；`test_cmd`/`blackbox_verify`（`docs/blueprint/testing.md:29-46`）的快速 E2E 未覆盖阅读页正文的窄屏场景。非个案：全仓 54 个前端测试文件中仅 2 个使用几何断言且均为 mock。

- 治本方案（根因级，未实施）：

    1. **在唯一收口处确立「邮件文档渲染契约」**：`buildMailSrcdoc()` 的 head 固定注入 `<meta name="viewport" content="width=device-width, initial-scale=1">`，把「移动视口适配」变成所有 HTML 正文的强制属性，而不是给某封邮件打补丁。
    2. **选型需明确并写入决策**：viewport meta 只设定布局视口，挡不住邮件内联 `width="..."` 表格，单靠它不够。可选策略：(i) srcdoc 内保守宽度约束（`table{max-width:100%;height:auto}` + 现有 `img` 规则）；(ii) 按 iframe 实测 `scrollWidth` 对正文做 scale-to-fit 兜底；(iii) 在 `prepareMailHtml` 清洗阶段把固定宽度重写为百分比/自适应（Gmail 式，最保真但最复杂）。建议分阶段：先落地 (1)+(i) 作为基线契约，再用固定宽度邮件样本实测；仍溢出才引入 (ii) 兜底，并设最小可读缩放比；(iii) 作为长期演进单独评估。策略一经选定写入 `docs/blueprint/decisions/`，成为渲染契约的一部分。
    3. **安全边界不变**：CSP、sandbox、`<base target=_blank>`、`no-referrer` 与图片代理重写逻辑全部保留；适配只在 srcdoc 的 head/style 层增加，不放松任何隔离约束。
    4. **测试体系补层**：在 `mailBody.test.ts` 断言 srcdoc 含 viewport meta 与约定的宽度约束样式（契约防回归）；新增固定宽度表格邮件 fixture 的移动端 E2E，在 360px 视口断言 iframe 内文档 `scrollWidth <= clientWidth` 且标题/表格右边界落在屏内，纳入 `blackbox_verify`；复用 p080 提出的通用几何 helper 与窄屏模板，使两类问题共用一道门禁。
    5. **为什么是根因级而非补丁**：把视口/宽度适配放进唯一文档构造点并升级为有决策记录的渲染契约，所有 HTML 邮件一次性受益；只给某封邮件改 HTML 或只加一条 CSS 仍是逐点补丁，下一封固定宽度邮件必然复发。
    6. **代价与风险**：强制 `max-width` 可能挤压复杂表格邮件版式，scale-to-fit 可能缩小字号影响可读性，宽度重写 (iii) 复杂度和回归面最大；需建立固定宽度邮件样本集（含本次 Cloudflare 周报）做视觉基线比对。相对地，当前「右侧永久截断」已是确定缺陷，风险可控且可回退。
