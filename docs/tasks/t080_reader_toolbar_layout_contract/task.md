# Task spec

## 背景

p080（2026-11-20 用户实报 + 两张手机截图）记录：手机窄屏阅读页顶部账号邮箱被标已读/删除/标记三个操作图标遮挡。根因不止某行 CSS：`docs/blueprint/conventions.md:19` 只规定一个 760px 断点常量，`:72` 只规范侧栏抽屉；`components.css:1525-1575` 的 760px 媒体查询只切换 pane 显隐，没有组件级窄屏降级规范。设计系统无工具栏原语，`.reader-toolbar-actions` 用绝对定位居中（`components.css:1360-1368`），而 `.settings-toolbar` 用 flex-wrap + 窄屏规则（`:1732,1846`），两套写法并存。测试层 54 个前端测试文件仅 2 个用几何断言且均为 mock，E2E 的几何断言都是逐 bug 补的（sidebar_tree.spec.ts、provider_account_forms.spec.ts），没有通用窄屏几何门禁。按开发铁律必须从布局契约、断点单一真相与通用门禁三层根治，禁止只挪按钮。

## 契约区

### 范围

- 在设计系统层确立工具栏布局契约：标题/账号等主信息占 `flex:1; min-width:0` 并省略；操作区为常规 flex 项 `flex:0 0 auto`，禁止用绝对定位覆盖主信息；窄屏降级规则（次要信息省略/换行、操作收进次级行或菜单、36px 点击目标）写入 `docs/blueprint/conventions.md` 与设计系统 CSS 原语。
- 迁移 `.reader-toolbar` 到该契约；审计 `.list-header`、`.settings-toolbar` 等工具栏，记录符合/不符合及处置，不允许遗留同类绝对覆盖写法。
- 断点单一真相：`src/frontend/src/lib/viewport.ts` 的 `MOBILE_MAX_WIDTH` 为唯一来源，建立静态检查确保 CSS `@media (max-width: …)` 的移动端断点与之相等，移除 `components.css` 中手工同步注释；检查纳入 `npm test` 的 css:check 链。
- 建立可复用的 360px 窄屏几何门禁：共享 `assertNoOverlap` 测试 helper + E2E 模板（360px 视口、长邮箱账号、取 boundingBox 断言不相交），阅读页工具栏必须接入；该共享层由本 task 先落地，供 t081 复用（t081 依赖本 task）。
- 补测试：`MessageReader.test.tsx` 增加契约层断言（操作区不得绝对定位覆盖）；新增/扩展 E2E 窄屏用例；更新 `docs/blueprint/testing.md` 的黑盒说明使门禁在执行链上。
- p080 在本 task 完成后由 `pending.py close --resolution resolved --fix-ref t080` 闭环；spec `inbox_ui_and_search` 的 tasks 登记 t080。

### 非范围

- 不修 p081 邮件正文 iframe 的 viewport/宽度适配（独立 task t081，依赖本 task 的共享门禁）。
- 不改 CSP、sandbox、图片代理、鉴权与后端逻辑。
- 不重做无关页面视觉风格，不顺手修 docs/pending 中其它布局条目。
- 不 push、不重新部署生产、不改现役 .env/容器。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：360px 视口下阅读页账号邮箱文本与操作按钮组的 `boundingBox()` 不相交；使用长邮箱账号作为边界样本，E2E 断言通过。
- [ ] AC-002：阅读页工具栏操作区不再以绝对定位覆盖主信息；契约层测试断言该写法不存在，且窄屏降级后 36px 点击目标保持可见可点。
- [ ] AC-003：设计系统存在单一工具栏布局契约（CSS 原语 + conventions 条款），阅读页已迁移；列表头部与设置工具栏完成审计，结论与处置记录在 progress.md。
- [ ] AC-004：`MOBILE_MAX_WIDTH` 是断点唯一来源，静态检查能发现 CSS 中与之不一致的移动端断点；人工制造不一致时检查失败（验证记录入 progress.md）。
- [ ] AC-005：共享 `assertNoOverlap` helper 与 360px E2E 模板以可复用形式落盘（独立文件/导出），阅读页用例已接入，t081 可直接复用且无需复制实现。
- [ ] AC-006：`docs/blueprint/conventions.md` / `testing.md` 与 spec `inbox_ui_and_search` 同步更新；p080 已转办闭环指向 t080。
- [ ] AC-007：`docs/blueprint/testing.md` 的 `test_cmd` 与 `blackbox_verify` 全量通过；无弱化断言、无临时补丁残留。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。AC-001/002/005 由 Playwright 真实浏览器几何断言验证；AC-003 由代码/文档检索与审计记录验证；AC-004 由静态检查脚本的正反两例验证；AC-006 由文件与 pending.py 状态验证；AC-007 由门禁命令实际执行结果验证。不使用真机，360px Chromium 视口作为窄屏替代，理由记入有意不测。

## 上下文区

- 关联 spec：docs/specs/inbox_ui_and_search.md
- 来源：p080（2026-11-20 用户实报与截图；根因链与治本方案见 docs/pending/p080_reader_toolbar_actions_overlap_sender_email.md「架构级根因链」「治本方案」两节）

### 有意不测

- 真实 Android/iOS 真机：无可用真机自动化环境；以 Playwright 360px Chromium 视口 + 长邮箱样本覆盖几何根因，截图证据见 p080。
- 第三方邮件客户端对照效果：仅作人工参照，不作为自动化 AC。

### 测试策略

- 单测/契约层：断言工具栏操作区不使用绝对定位覆盖，断点静态检查正反例。
- E2E：共享 360px 几何 helper + 阅读页长邮箱用例；断言 `assertNoOverlap`。
- 门禁：test_cmd（vitest + openapi + css:check + 断点检查）与 blackbox_verify（stubApi E2E）。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：共享工具栏原语迁移引起列表/设置页视觉回归；断点静态检查误伤历史媒体查询；E2E 几何断言在字体差异下抖动。
- 回退：按文件粒度回退迁移并保留门禁 helper；静态检查先以白名单收敛再逐步消除（白名单须写理由，不得永久豁免）；E2E 用 `boundingBox` 容差 1px 内判定。

### 依赖与约束

- t081 依赖本 task：共享 360px 几何 helper/E2E 模板与断点单一真相必须先在本 task 落地，t081 只复用不重写。
- 不改后端、不动现役部署；双轴审阅（review_level=full）。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：工具栏窄屏降级契约与断点唯一来源条款。
- `docs/blueprint/testing.md`：共享 360px 几何门禁纳入 blackbox_verify。
- `docs/specs/inbox_ui_and_search.md`：tasks 增加 t080，补工具栏布局契约条款。
