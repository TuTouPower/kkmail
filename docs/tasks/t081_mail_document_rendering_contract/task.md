# Task spec

## 背景

p081（2026-11-20 用户实报 + 两张手机截图）：同一封 Cloudflare 周报在 Gmail 中完整适配手机屏宽，在 kkmail 中标题、账号链接、表格右侧被截断。根因不是缺一行 meta：`docs/blueprint/architecture.md:145-159` 记录 iframe/srcdoc 选型的驱动是零外部出网与 CSP/sandbox 隔离，`mailBody.ts:418-447` 的 A384 决策也只覆盖安全边界；「独立文档如何适配视口」从未进入渲染契约。`buildMailSrcdoc()`（`mailBody.ts:385-414`）是全部 HTML 正文的唯一构造点，注入了 CSP/base/配色和 `img{max-width:100%}`，却没有 viewport meta 与表格宽度约束；srcdoc 是独立浏览上下文，宿主 `index.html:6` 的 viewport 不继承。测试层是逐案补断言：srcdoc 测试只查 CSP/颜色字符串，jsdom 无布局，E2E 只在设置对话框/sidebar 有逐 bug 几何断言。按开发铁律应在唯一收口处确立「邮件文档渲染契约」，并复用 t080 先落地的共享 360px 几何门禁，禁止只给某封邮件打补丁。

## 契约区

### 范围

- 在 `buildMailSrcdoc()` 唯一收口处确立邮件文档渲染契约：注入 viewport meta（`width=device-width, initial-scale=1`），加入保守宽度约束样式，使固定宽度表格邮件在手机视口内不再横向截断；策略分级落地（viewport + 保守约束为基线，仍溢出时才引入按实测宽度的缩放兜底），不重写邮件内联宽度到无法辨读。
- 把策略选型、理由、安全边界与取舍写成 `docs/blueprint/decisions/YYYYMMDD_mail_document_rendering_contract.md` 决策记录，并在 `docs/blueprint/conventions.md` 增补邮件文档渲染契约条款；保留现有 CSP、sandbox、`no-referrer`、`<base target=_blank>` 与图片代理逻辑不变。
- 补契约级单测：`mailBody.test.ts` 断言 srcdoc 含 viewport meta 与约定的宽度约束样式，并断言 CSP/sandbox 相关字符串不回归。
- 复用 t080 落地的共享 `assertNoOverlap` helper 与 360px E2E 模板（不复制实现），新增固定宽度表格邮件 fixture 的阅读页 E2E：360px 视口下断言 iframe 内文档 `scrollWidth <= clientWidth`，标题/表格右边界落在屏内。
- `docs/blueprint/testing.md` 的 blackbox 说明同步覆盖邮件正文窄屏场景；spec `inbox_ui_and_search` 的 tasks 登记 t081；p081 已在立项时以 `transferred` 转办至本 task（fix_ref=t081），本 task 完成后不再二次闭环。

### 非范围

- 不修 p080 宿主工具栏布局（独立 task t080，且本 task 依赖其共享门禁）。
- 不放宽 CSP/sandbox、不引入外部网络资源、不改变远程图片代理与 SSRF 防护。
- 不做邮件内联宽度的全量重写（Gmail 式复杂重写仅作为决策记录中的长期演进，不在本 task 实施）。
- 不 push、不重新部署生产、不改现役 .env/容器。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：所有 HTML 正文的 srcdoc 都包含 viewport meta；固定宽度表格邮件在 360px 视口下标题与表格右边界落在屏内，iframe 内文档 `scrollWidth <= clientWidth`（E2E 黑盒）。
- [x] AC-002：srcdoc 含约定的宽度约束样式；契约单测覆盖 viewport 与宽度约束字符串，且 CSP/sandbox/base/no-referrer 相关断言不回归。
- [x] AC-003：策略选型与理由落盘为 blueprint 决策记录，conventions 增补邮件文档渲染契约；安全边界在决策中明确为不变量。
- [x] AC-004：阅读页正文 E2E 复用 t080 的共享几何 helper/模板，代码中不存在复制的第二套 `assertNoOverlap` 实现；复用方式记入 progress.md。
- [x] AC-005：`docs/blueprint/testing.md`、spec `inbox_ui_and_search` 与 p081 同步更新，p081 转办闭环指向 t081。
- [x] AC-006：`docs/blueprint/testing.md` 的 `test_cmd` 与 `blackbox_verify` 全量通过；无弱化断言、无临时补丁残留。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。AC-001 由 Playwright 360px 视口与固定宽度 fixture 验证；AC-002 由 srcdoc 字符串契约测试验证；AC-003/005 由文件存在性与 pending.py 状态验证；AC-004 由代码检索与 progress.md 记录验证；AC-006 由门禁命令实际执行结果验证。真机与多邮件客户端对照仅作人工参照，见有意不测。

## 上下文区

- 关联 spec：docs/specs/inbox_ui_and_search.md
- 来源：p081（2026-11-20 用户实报与截图；根因链与治本方案见 docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md「架构级根因链」「治本方案」两节）

### 有意不测

- 真实 Android/iOS 真机与 Gmail 客户端对照：无真机自动化环境；以 360px Chromium + 固定宽度 HTML 邮件 fixture 覆盖根因，截图对照见 p081。
- 任意邮件 HTML 的全量视觉等价：邮件版式千差万别，以样本集（含 Cloudflare 周报形态的固定宽度表格）验证，不承诺像素级还原。

### 测试策略

- 单测/契约层：srcdoc 字符串断言（viewport、宽度约束、CSP 不变量）。
- E2E：复用 t080 共享 360px 几何模板，新增固定宽度表格邮件 fixture，断言 iframe 文档 `scrollWidth <= clientWidth`。
- 门禁：test_cmd 与 blackbox_verify 全量通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：强制宽度约束可能挤压复杂表格邮件版式；缩放兜底可能缩小字号；安全字符串断言遗漏导致 CSP 回归。
- 回退：按样式条目逐条关闭约束并保留 viewport；缩放兜底可单独禁用；CSP/sandbox 相关改动一律不做，靠断言守住。

### 依赖与约束

- 依赖 t080：共享 360px 几何 helper/E2E 模板与断点单一真相由 t080 先落地，本 task 只复用。
- 不改后端、不动现役部署；双轴审阅（review_level=full）。

### Finalization 时更新的 blueprint

- `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md`（新建决策记录）。
- `docs/blueprint/conventions.md`：邮件文档渲染契约条款。
- `docs/blueprint/testing.md`：邮件正文窄屏 E2E 纳入 blackbox_verify。
- `docs/specs/inbox_ui_and_search.md`：tasks 增加 t081，补邮件文档渲染契约条款。
