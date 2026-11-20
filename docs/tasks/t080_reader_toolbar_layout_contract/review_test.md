# Task review t080（reviewer_focus: 测试）

- task：t080_reader_toolbar_layout_contract
- spec：docs/specs/inbox_ui_and_search.md
- diff_anchor：81b6a255979bbd771f16c59e177da1378e04683f
- target：git diff 81b6a255979bbd771f16c59e177da1378e04683f
- round：1
- reviewed_at：2026-11-20T19:37:45+08:00

reviewed_scope: 661f79e53dcff6ae

## Findings

### t080_test_f001 - 契约层单测只验证 class 标记存在，未直测绝对定位缺失与 36px 点击目标

- 严重度：minor
- 锚点：AC-002
- 位置：src/frontend/src/components/MessageReader.test.tsx:346-352
- 问题：新增用例 `keeps toolbar actions in the shared non-overlay contract` 只用 `classList.contains('app-toolbar' / 'app-toolbar-actions')` 断言两个 class 标记存在，前置 `waitFor` 仅确认 `.reader-location` 的邮箱文本。未断言 `.reader-toolbar-actions` 的计算样式 `position` 不为 `absolute`，也未验证窄屏降级后操作按钮维持 36px 点击目标可见可点。该断言本身只证明"阅读页挂上了契约 class"；它**不构成 AC-002 的假绿**——AC-002 主证据是 `reader_toolbar.spec.ts` 的真实浏览器 boundingBox 不相交断言与 `check_layout_contracts.mjs` 的绝对定位反例（二者均已独立复验）。按 blocking 硬阈值，本条属"覆盖可更强"的扩展建议，降为 minor，不阻断。
- 建议：把该契约断言改为读取 computed style 断言操作区 `position !== absolute`，使契约层单测自身具备防回归力；36px 点击目标可在 E2E 增加 boundingBox 宽高断言（可选强化，非阻断）。

## 结论

- 前轮 finding 复核：无（round 1）
- 改测方向复核：无。本轮 diff 未修改既有测试的断言预期；`MessageReader.test.tsx` 为新增用例，`reader_toolbar.spec.ts` 为新增文件，不存在"改预期迁就实现"。
- 本轮新发现：1 条（minor）
- 未进表的提示：
    - `check_layout_contracts.mjs` 用正则文本匹配而非 CSS AST：`.app-toolbar-actions,` 带逗号选择器与 `flex: 0 0 auto` 字面量被硬编码，若将来改写选择器写法或 flex 简写会产生假阴性（当前 CSS 匹配，非缺陷）。属健壮性强化建议，不阻断。
    - 未对全量 `test_cmd` 的模板契约/桌面单测/敏感扫描项在本轴复跑，详见 AC-007 披露。
- 总体判断：AC-001~AC-007 打勾均获真实测试或独立验证支撑；E2E 几何断言经红测试验证对重叠敏感，断点检查正反例均有效，无 mock 被测逻辑 / 弱化断言 / `.skip` 等危险模式。仅 1 条 minor 强化建议，无 critical / important，无 TICK-VOID，PASS。
- 系统性 follow-up：无

### 危险模式扫描

- 恒真断言 / 存在即通过：未命中。`assertNoOverlap` 以 `rectsOverlap(...).toBe(false)` 为用户可观察几何断言；红测试验（注入 `position:absolute; left:50%; transform:translate(-50%,-50%)` 的旧布局）在 `tests/e2e/layoutGeometry.ts:27` 失败并报 `.reader-location overlaps .reader-toolbar-actions`，证明断言对真实重叠敏感、非恒真。`MessageReader.test.tsx` 的 class 存在性断言不构成 AC 主证据，已记 minor f001。
- 删/反转 expect、注释断言、弱化断言：未命中。diff 中仅 `toContainText` 两处（`reader_toolbar.spec.ts:22,34`），分别断言主题与长邮箱文本，属正当文本包含断言，非 `toBe`→`toContain` 弱化。
- `.skip` / `.only` / `ts-ignore` / `eslint-disable`：未命中（diff 全文扫描无匹配）。
- mock 误用：`tests/e2e/stubApi.ts` 新增 `messages?: MockMessage[]` 仅在 `page.route('**/api/**')` 系统边界注入响应数据，未 mock 被测组件、store 或内部函数；`MockMessage.accountEmail` 已存在于类型定义（`stubApi.ts:15`），fixture 合法。
- 阈值掩盖 / 条件跳过：未命中。`timeout: 10000 / 5000` 为正常等待上限；`assertNoOverlap` 无条件执行，无 `if (cond)` 包裹断言。
- 程序赋值替代真实交互：未命中。测试通过 `page.getByText(subject).click()` 真实点击进入阅读页，`setViewportSize` 设置视口，无 `.value =` 冒充拖拽/点击。

### 红绿有效性

- 绿：`npm test` 全量 55 文件 / 592 passed，含 openapi:check 与 css:check（新脚本 `check_layout_contracts.mjs` 通过）；E2E `reader_toolbar.spec.ts` 1 passed；`MessageReader.test.tsx` 46 passed。
- 红（反例有效性）：`check_layout_contracts.mjs` 以真实脚本副本独立复跑——(1) 把 `breakpoints.ts` mobile 改为 720 时 exit 1 并列出"760px 媒体查询不在单一来源"；(2) 在 `.app-toolbar-actions` 块注入 `position:absolute` 时 exit 1。实施方声称的反例退出码 1 属实。
- 红（几何断言敏感性）：真实 `assertNoOverlap` 对注入的绝对定位重叠 DOM 失败于 `layoutGeometry.ts:27`。证明 E2E 测的是用户可观察的重叠缺陷，而非"元素存在即通过"。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/e2e/reader_toolbar.spec.ts:7-34` 用 `LONG_EMAIL` 注入 message/account fixture，真实点击主题进入阅读页后 `assertNoOverlap(page, '.reader-location', '.reader-toolbar-actions')` 断言 boundingBox 不相交；红测试验证明该断言对绝对定位重叠会失败；E2E 实跑 1 passed。
- AC-002：TICK-VALID，re_verified。旧绝对居中块已从 `components.css` 删除，新增 `.app-toolbar-primary`(`flex:1;min-width:0`) / `.app-toolbar-actions`(`flex:0 0 auto`) 原语；`check_layout_contracts.mjs:44-48` 反例 exit 1；E2E 几何断言通过。36px 点击目标缺专门断言记 minor f001，核心"不以绝对定位覆盖"已真实覆盖。
- AC-003：TICK-VALID，re_verified。`progress.md:27` 审计记录存在；复验 `components.css:912 .list-header`(flex:0 0 auto，无 absolute)、`:1737 .settings-toolbar`(flex+wrap)、全 CSS `position:absolute` 命中均已分类为对话框/侧栏抽屉(`:1541`，属有意不测)/sr-only(`:1833`)，无遗留工具栏操作区绝对覆盖。
- AC-004：TICK-VALID，re_verified。`check_layout_contracts.mjs:11-31` 校验 CSS max-width 属于 `breakpoints.ts` 单一来源；正例 exit 0（`npm test` css:check 通过），反例 mobile→720 与绝对定位两例均 exit 1，独立复跑确认。
- AC-005：TICK-VALID，re_verified。`tests/e2e/layoutGeometry.ts:1-28` 以独立文件导出 `assertNoOverlap` / `setNarrowViewport`；`reader_toolbar.spec.ts:3` 以 import 接入（红测试亦独立 import 成功）；`run_e2e.mjs:10` 已加入默认 targets；`testing.md:49` 明确禁止复制第二套实现，t081 可直接复用。
- AC-006：TICK-VALID，re_verified。`docs/pending/p080_...:4-7` 为 `status:closed / resolution:transferred / fix_ref:t080`；`docs/specs/inbox_ui_and_search.md:3` tasks 含 t080；`conventions.md`/`testing.md` 契约条款 diff 已落地。
- AC-007：TICK-VALID，trust_prior。依赖 `progress.md:29` 门禁实测记录；测试轴独立复跑 `npm test`（592 passed，含 openapi:check 与 css:check）与 `blackbox_verify` 的 E2E（1 passed）均通过，危险模式扫描无弱化断言 / `.skip` / 临时补丁；模板契约、桌面单测、敏感扫描未在本轴复跑。

coverage = 6 / 7

verdict: PASS

## Round 2 (2026-11-20T19:43:30+08:00)

- task：t080_reader_toolbar_layout_contract
- spec：docs/specs/inbox_ui_and_search.md
- diff_anchor：81b6a255979bbd771f16c59e177da1378e04683f
- target：git diff 81b6a255979bbd771f16c59e177da1378e04683f
- round：2
- reviewed_at：2026-11-20T19:43:30+08:00

reviewed_scope: 0b63f6061dbac01b

## Findings

Round 2 零 finding：本轮无新 finding。

## 结论

- 前轮 finding 复核：
    - `t080_test_f001`（minor，契约单测只断言 class 标记）：同意撤回。理由成立——jsdom 不加载 CSS，vitest/jsdom 下 `getComputedStyle(...).position` 仅返回默认 static，无法真实断言 CSS 规则，原建议的 computed-style 断言在该环境不可行；该 class 断言属契约层 smoke，非 AC-002 主证据。AC-002 主证据本轮已独立复验：`tests/e2e/reader_toolbar.spec.ts` 真实浏览器 boundingBox 不相交断言（实跑 1 passed）+ `check_layout_contracts.mjs` 绝对定位反例（注入 `position:absolute` 后 exit 1）。不改变交付内容，非阻断。
    - `t080_code_f001`（minor，code 轴；复合/带媒体类型 max-width 断点漏检）：修复已消除。相对 Round 1 唯一交付变更为 `check_layout_contracts.mjs:20-24` 的断点正则改为 `@media([^{]+)\{` 截取完整预条件后全局匹配 `max-width:\s*(\d+)px`。本轮在仓库外临时副本独立复跑：正例 exit 0；复合查询 `(min-width:361px) and (max-width:723px)`、媒体类型 `screen and (max-width:723px)`、双 max-width 第二项越界 723px 三例均 exit 1；mobile→720 与操作槽注入 `position:absolute` 两反例仍 exit 1。修复真实有效。
- 改测方向复核：无。本轮唯一交付变更是 checker 的检测逻辑修复，非「把断言预期改成迁就当前实现」；无既有测试断言被改写。
- 本轮新发现：0 条（Round 2 零 finding）。
- 未进表的提示：范围外——pytest contract、desktop `npm test`、敏感文档扫描因本 worktree 缺 pytest 模块与 electron 依赖未在本测试轴复跑（code 轴 Round 1 已记录敏感扫描 33 文件 0 违规），与本次前端交付无关。
- 总体判断：前轮两条 finding 均已核实闭环（test_f001 同意撤回、code_f001 修复经复合 max-width 负例验证已消除）；本轮独立复跑前端 test_cmd 链（vitest 55 文件 592 passed + openapi:check + css:check）、`npx tsc -b`、`npm run build`、blackbox E2E（reader_toolbar 1 passed）及 checker 正反例全通过；AC-001~AC-007 打勾持续获真实支撑，无危险模式、无新 finding、无 TICK-VOID，PASS。
- 系统性 follow-up：无

### 危险模式扫描（Round 2）

- 恒真 / 存在即通过 / 弱化断言 / 删反转或注释断言 / `.skip` / `.only` / `ts-ignore` / `eslint-disable` / mock 被测逻辑 / 阈值掩盖 / 条件跳过 / 程序赋值替代真实交互：相对 Round 1 无新增测试改动，复扫 diff 全文未命中；`assertNoOverlap` 仍为 `rectsOverlap(...).toBe(false)` 真实几何断言，`reader_toolbar.spec.ts` 经真实点击进入阅读页，stubApi 仅在 `page.route('**/api/**')` 系统边界注入。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/e2e/reader_toolbar.spec.ts:7-34` 用 93 字符长邮箱注入 message/account fixture，360px 视口真实点击进入阅读页后 `assertNoOverlap(page, '.reader-location', '.reader-toolbar-actions')` 取 `boundingBox` 判 `rectsOverlap(...).toBe(false)`（`tests/e2e/layoutGeometry.ts:23-27`），断言非恒真；本轮实跑 1 passed。
- AC-002：TICK-VALID，re_verified。旧绝对居中块已从 `components.css` 删除，操作槽为 `flex:0 0 auto`（`:1288-1294`）；本轮独立复跑 `check_layout_contracts.mjs`，向 `.app-toolbar-actions` 块注入 `position:absolute` 后 exit 1，E2E 几何断言通过。36px 点击目标无专门断言（前轮 f001 已同意撤回，非主证据）。
- AC-003：TICK-VALID，re_verified。共享原语 `.app-toolbar`/`.app-toolbar-primary`/`.app-toolbar-actions` 位于 `src/frontend/src/design-system/components.css:1259-1294`，条款在 `docs/blueprint/conventions.md:19-24`，阅读页已挂载（`MessageReader.tsx:386-389`）；本轮 grep 全 CSS `position:absolute` 命中均为对话框/侧栏抽屉(`:1541`)/sr-only(`:1833`)，`.list-header`(`:912`)/`.settings-toolbar`(`:1737`) 无绝对覆盖。
- AC-004：TICK-VALID，re_verified。本轮正向 `npm run css:check` 通过；反向独立复跑——复合查询、媒体类型查询、双 max-width 第二项越界 723px 三例均 exit 1，`breakpoints.ts` mobile→720 亦 exit 1；修复后正则无漏检。
- AC-005：TICK-VALID，re_verified。`tests/e2e/layoutGeometry.ts:1-28` 以独立文件导出 `assertNoOverlap`/`setNarrowViewport`/`rectsOverlap`，`reader_toolbar.spec.ts:3` import 接入，`run_e2e.mjs:10` 加入默认 targets，`docs/blueprint/testing.md:49` 写明禁止复制第二套实现，t081 可直接复用。
- AC-006：TICK-VALID，re_verified。本轮核对 `docs/pending/p080_reader_toolbar_actions_overlap_sender_email.md:4-7` 为 `status: closed`/`resolution: transferred`/`fix_ref: t080`；`docs/specs/inbox_ui_and_search.md:3` tasks 含 t080；`conventions.md`/`testing.md` 契约条款 diff 已落地。
- AC-007：TICK-VALID，re_verified。本轮实跑前端 test_cmd 链 `npm test`（vitest 55 文件 592 passed + openapi:check + css:check）、`npx tsc -b`、`npm run build` 均通过；`blackbox_verify` 的 `reader_toolbar.spec.ts` E2E 1 passed；危险模式扫描无弱化断言/恒真断言/`.skip`/mock 被测逻辑/临时补丁。pytest contract、desktop `npm test`、敏感扫描未在本测试轴复跑（缺 pytest 模块/electron 依赖，code 轴 Round 1 已记录），与前端交付无关。

coverage = 7 / 7

verdict: PASS
