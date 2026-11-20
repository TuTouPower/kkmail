# Task review t081（reviewer_focus: 测试）

- task：`t081_mail_document_rendering_contract`
- spec：`docs/tasks/t081_mail_document_rendering_contract/task.md`
- diff_anchor：`bb05825c9de416f92af090b8a258597456ee87f0`
- target：`git diff bb05825c9de416f92af090b8a258597456ee87f0`
- round：1
- reviewed_at：2026-11-20T19:56:37+08:00

reviewed_scope: e62eab455bc7f7d2

## Findings

本轮 0 finding。

## 红绿有效性

- 绿：在 worktree 完整交付内容上实跑 `npm --prefix src/frontend run test:e2e`，新用例 `固定宽度 HTML 邮件在 360px 视口不横向溢出`（`tests/e2e/mail_body_viewport.spec.ts:16`）通过；全量 23 passed（28.8s）。前端 `npm test` 593 passed，`openapi:check` 与 `css:check` 通过。
- 红：反转 diff 中两处实现改动（移除 `mailBody.ts` 的 viewport meta、把 `widthStyle` 换回 `img{max-width:100%;height:auto}` 并去掉 `overflow-wrap:anywhere`），用测试同款 680px fixture 在 309px 宽 iframe 中实测：`html`/`body` 的 `scrollWidth=680`、`clientWidth=309`，`assertNoHorizontalOverflow` 的 `680 <= 309+1` 为 false（红）；修复后同为 `309/309`，断言为 true（绿）。与实施方声称的 680/309 红、绿一致。
- 结论：`assertNoHorizontalOverflow` 是真实几何断言，对被测修复敏感，非恒真；E2E 经 `frameLocator('iframe[title="邮件正文"]')` 进入真实浏览器 iframe 文档（标题与 `MessageReader.tsx:632,643` 的 iframe title 一致），非 jsdom/字符串 mock。

## 危险模式扫描

|模式|结论|
|---|---|
|恒真断言 / 纯存在性断言|未命中。`tests/e2e/layoutGeometry.ts:18-27` 读真实 `scrollWidth`/`clientWidth` 并 `toBeLessThanOrEqual(clientWidth + 1)`；`+1` 为 1px 亚像素容差，不遮盖 680 vs 309 的差异。|
|删/反转/注释断言、弱化断言|未命中。`mailBody.test.ts` diff 仅新增 51-58 行 `it`，既有断言原样保留；新增 `toContain` 用于 srcdoc 字符串契约属正当用法，几何断言用 `toBeLessThanOrEqual`。|
|删测试 / `.skip` / `.only` / `@Ignore`|未命中。|
|静默错误（`eslint-disable` / `@ts-ignore` 等）|未命中。|
|mock 误用 / mock 被测逻辑|未命中。`setupStubApi` 只在系统边界 stub HTTP API；被测 `buildMailSrcdoc`、srcdoc 注入与 iframe 渲染均为生产实现。|
|阈值掩盖（timeout/重试/容差增大）|未命中；仅新增 1px 几何容差，合理。|
|条件跳过弱化断言|未命中。|
|程序赋值替代真实交互 / 存在即通过|未命中。用 `page.goto` + `getByText(...).click()` 真实打开邮件；`toContainText('Your weekly Web Analytics summary')` 仅作前置确认，AC 证据是几何断言。|

## 结论

- 前轮 finding 复核：无（Round 1）。
- 改测方向复核：无。`mailBody.test.ts` 只增新 `it`，无「把旧预期改成当前实现输出」；E2E 为新增文件，非改测迁就实现。
- 本轮新发现：0 条。
- 未进表的提示：无。AC-001 未单独断言 `h1`/`table` 的 `boundingBox` 右边界，但 `html`/`body` 的 `scrollWidth <= clientWidth` 已蕴含文档无横向溢出、内容右边界在视口内，对本 fixture 等价；属「可再细化」级别，不进表。
- 总体判断：E2E 真实触达 iframe 文档并测得横向溢出红绿有效，srcdoc 契约单测覆盖 viewport/宽度约束且 CSP 不变量未回归，共享 helper 复用与文档同步属实，无危险模式；全部 AC 打勾成立。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/e2e/mail_body_viewport.spec.ts:28-32` 真实打开邮件后对 iframe 内 `html`/`body` 断言 `scrollWidth <= clientWidth+1`；实跑绿、反转实现红（680/309）；`mailBody.ts:416` viewport meta 无条件注入，单测 `mailBody.test.ts:53` 断言该字符串。
- AC-002：TICK-VALID，re_verified。`mailBody.test.ts:51-58` 断言 viewport、`width:auto !important`、`max-width:100% !important` 及 CSP；CSP/sandbox/base/no-referrer 既有断言（`:42-49,134-159`）原样保留；vitest 593 passed。
- AC-003：TICK-VALID，re_verified。`docs/blueprint/decisions/20261120_mail_document_rendering_contract.md:3-11` 含选型、理由、安全边界不变量；`docs/blueprint/conventions.md` 增补渲染契约条款。
- AC-004：TICK-VALID，re_verified。`tests/e2e/mail_body_viewport.spec.ts:3,31-32` 从 t080 共享 `tests/e2e/layoutGeometry.ts` 导入 `assertNoHorizontalOverflow`/`setNarrowViewport`；全仓仅一处 `assertNoOverlap`（`layoutGeometry.ts:30`），无第二套；`progress.md`「复用关系」已记录。
- AC-005：TICK-VALID，re_verified。`docs/blueprint/testing.md:49` 纳入黑盒、`docs/specs/inbox_ui_and_search.md` tasks 增 t081 并补契约条款、`docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` status=closed / fix_ref=t081。
- AC-006：TICK-VALID，re_verified。`test_cmd` 前端部分（vitest 593 + openapi:check + css:check）与 `blackbox_verify`（E2E 23/23）实跑通过；危险模式扫描全未命中，交付 diff 无临时补丁/debug 残留。

coverage = 6 / 6

verdict: PASS

## Round 2 (2026-11-20T20:05:28+08:00)

reviewed_scope: b7a8224d6fcf6f17

- round：2

### 本轮范围与前轮复核

- 前轮 finding 复核：测试轴 Round 1 为零 finding，无可复核项。
- 交付变化：相对 `diff_anchor`，本轮两点变化——`src/frontend/src/lib/mailBody.ts` 的 `bodyStyle` 移除 `overflow-wrap:anywhere`（`widthStyle` 宽度收敛机制不变）；`task.md` 范围段 p081 闭环措辞改为「立项时以 transferred 转办至本 task，完成后不再二次闭环」，与 AC-005 及 `docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7`（`closed`/`transferred`/`fix_ref: t081`）一致。测试文件本身无改动，但按新 reviewed_scope 对全部测试轴独立重验。

### 红绿有效性复验

- 绿（实跑）：`vitest run src/lib/mailBody.test.ts` 26/26 passed；`npm run test:e2e` 全量 23/23 passed，其中新用例 `固定宽度 HTML 邮件在 360px 视口不横向溢出`（`tests/e2e/mail_body_viewport.spec.ts:16`）通过。
- 红（内存 Chromium 几何对照，不写文件）：同款 680px fixture、309px 视口下，修复前文档（无 viewport meta / 无 `widthStyle`，仅 `img{max-width:100%}`）测得 `html.scrollWidth=680 / clientWidth=309`，`assertNoHorizontalOverflow` 门 `680 <= 309+1` 为 false（红）；当前契约文档在移除 `overflow-wrap:anywhere` 后仅靠 `widthStyle`（`width:auto !important;max-width:100% !important`）测得 `309/309`，门为 true（绿）。红由 viewport + widthStyle 缺失单独驱动，宽度收敛机制未变，断言真实敏感、非恒真、非 jsdom/字符串 mock。

### srcdoc 契约单测 / CSP 不变量 / 共享 helper

- srcdoc 契约单测：`mailBody.test.ts:51-58` 用真实 `buildMailSrcdoc()` 输出断言 viewport meta、`width:auto !important`、`max-width:100% !important`、`default-src 'none'`、`img-src 'self' data: cid:`；随 26/26 通过。
- CSP 不变量：`mailBody.ts:386` 的 csp 常量原样（`default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src data:`）；`mailBody.test.ts:42-49,134-159` 的 CSP/sandbox/base/no-referrer 断言原样保留并通过；无放宽。
- 共享 helper：`tests/e2e/mail_body_viewport.spec.ts:3` 从 `./layoutGeometry` 导入 `assertNoHorizontalOverflow`/`setNarrowViewport`；全仓 `assertNoOverlap` 仅 1 处定义（`tests/e2e/layoutGeometry.ts:30`）、`assertNoHorizontalOverflow` 仅 1 处（`:18`），无第二套；`progress.md`「复用关系」已记录。
- 危险模式扫描：rg 确认两份测试文件无 `.skip`/`.only`/`eslint-disable`/`@ts-ignore`；几何断言读真实 `scrollWidth`/`clientWidth` 并仅用 1px 亚像素容差；恒真断言、弱化断言、删 expect、mock 误用、阈值掩盖、程序赋值替代真实交互、存在即通过均未命中。

## 结论

- 前轮 finding 复核：无（测试轴 Round 1 零 finding）。
- 改测方向复核：无。本轮交付无测试文件改动，不存在「把旧预期改成当前实现输出」的迁就改测。
- 本轮新发现：0 条。
- 未进表的提示：无。
- 总体判断：移除 `overflow-wrap:anywhere` 后红绿仍成立，宽度收敛完全由未变的 `widthStyle` 驱动；srcdoc 契约单测覆盖 viewport/宽度约束且 CSP/sandbox/base/no-referrer 不变量未回归；共享 helper 复用与文档同步属实；无危险模式；全部 AC 打勾成立。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/e2e/mail_body_viewport.spec.ts:29-32` 经 `frameLocator('iframe[title="邮件正文"]')` 进入真实 iframe 文档，对 `html`/`body` 断言 `scrollWidth <= clientWidth+1`；实跑 23/23 绿、内存对照 680/309 红；`mailBody.ts:416` viewport meta 无条件注入，单测 `mailBody.test.ts:53` 断言该字符串。
- AC-002：TICK-VALID，re_verified。`mailBody.test.ts:51-58` 断言 viewport、`width:auto !important`、`max-width:100% !important` 与两条 CSP 字符串，26/26 通过；`mailBody.ts:406` widthStyle 收敛机制未变，`overflow-wrap:anywhere` 移除不影响宽度收敛。
- AC-003：TICK-VALID，re_verified。`docs/blueprint/decisions/20261120_mail_document_rendering_contract.md:4,7,10` 含选型、宽度收敛理由与安全边界不变量；`docs/blueprint/conventions.md:12-13` 增补渲染契约条款。
- AC-004：TICK-VALID，re_verified。`tests/e2e/mail_body_viewport.spec.ts:3,31-32` 从共享 `tests/e2e/layoutGeometry.ts` 导入 `assertNoHorizontalOverflow`/`setNarrowViewport`；全仓 `assertNoOverlap` 与 `assertNoHorizontalOverflow` 各仅一处定义（`:30`/`:18`），无复制实现；`progress.md`「复用关系」已记录。
- AC-005：TICK-VALID，re_verified。`docs/blueprint/testing.md:49` 纳入黑盒、`docs/specs/inbox_ui_and_search.md:4,21` tasks 增 t081 并补契约条款；本轮 `task.md:15` 措辞修正后与 AC-005 一致；`docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` 为 `closed`/`transferred`/`fix_ref: t081`。
- AC-006：TICK-VALID，re_verified。`vitest run src/lib/mailBody.test.ts` 26/26 与 `npm run test:e2e` 23/23 实跑通过；危险模式扫描全未命中，交付 diff 无临时补丁/debug 残留。

coverage = 6 / 6

verdict: PASS
