# Task review t080（reviewer_focus: 代码）

- task：`t080_reader_toolbar_layout_contract`
- spec：`docs/tasks/t080_reader_toolbar_layout_contract/task.md`
- diff_anchor：`81b6a255979bbd771f16c59e177da1378e04683f`
- target：`git diff 81b6a255979bbd771f16c59e177da1378e04683f`
- round：1
- reviewed_at：2026-11-20T19:38:11+08:00

reviewed_scope: 661f79e53dcff6ae

## Findings

### t080_code_f001 - 断点静态检查漏检复合/带媒体类型的 max-width 写法

- 严重度：minor
- 锚点：AC-004（静态检查须发现 CSS 中与单一来源不一致的移动端断点）。当前声明的「人工制造不一致时检查失败」仅对简单 `@media (max-width: Npx)` 成立，复合查询漏检。
- 位置：`src/frontend/scripts/check_layout_contracts.mjs:20-24`
- 问题：`const mediaValues = [...css.matchAll(/@media\s*\(([^)]*max-width:\s*(\d+)px[^)]*)\)/g)]` 只匹配紧跟 `@media` 之后的第一个括号。在临时副本（未改交付文件）向 `components.css` 追加 `@media (min-width: 361px) and (max-width: 723px)` 与 `@media screen and (max-width: 723px)` 两种含越界值 723px 的写法，脚本仍输出「布局契约与断点单一来源检查通过」且 exit 0。未来若以这类形式写入错误移动端断点，门禁不会拦截，与「断点唯一来源」守护目标存在差距。当前 CSS 全部为简单 max-width 写法（1180/900/760/1100，均在 `BREAKPOINTS` 内），无即时可观测缺陷，故为 minor。
- 建议：先按 `@media[^{]+` 截取完整预条件，再对整段全局匹配 `max-width:\s*(\d+)px`，不要只取 `@media` 后第一个括号；同步补一条复合查询的正/反例回归。

## 七视角扫描结论

- 安全：无命中。新增 `messages` 仅为 stubApi 测试夹具，未触及鉴权、CSP、sandbox、图片代理或后端；无凭据硬编码、注入或越权面。
- 正确性：无阻断缺陷。操作槽由绝对定位改为常规 flex（`components.css:1288-1294`），主信息槽 `flex:1 1 auto; min-width:0` 省略；`data-ui`（MR01/MR02/MR03/MR04/MR11）、`CopyAddress`、移动端返回按钮均保留，`.reader-action` 仍为 36×36。E2E 360px 长邮箱几何断言通过。
- 契约·Breaking：无。`MOBILE_MAX_WIDTH` 由 `viewport.ts` 再导出，公开导入路径与语义不变；无 API/schema/配置键变更。
- 性能·资源：无命中。仅 CSS 规则合并与一个轻量静态脚本，无循环查库、N+1、大库整体 import 或重复渲染。
- 架构·可维护性：工具栏原语（`.app-toolbar` / `.app-toolbar-primary` / `.app-toolbar-actions`）为设计系统层独立契约，非逐点补丁；断点收敛到 `breakpoints.ts` 由 checker 守护。可复用性边际问题见结论段与 f001。
- 健壮性·可观测：checker 对命中问题输出明确 FAIL 行并以 exit 1 终止；无空 catch、吞错或仅 console.log。漏检盲点见 f001。
- 测试·文档·规格：契约测试非恒真、E2E 用真实 `boundingBox` 几何断言；`conventions.md` / `testing.md` / `inbox_ui_and_search.md` 同步更新；diff 无 `.skip` / `.only` / 弱断言 / 临时补丁残留。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 本轮新发现：1 条（minor）。
- 未进表的提示：
    - 文件过大 / 圈复杂度：无命中。新增最大文件 `check_layout_contracts.mjs` 55 行、`reader_toolbar.spec.ts` 34 行、`layoutGeometry.ts` 28 行，远低于阈值；无函数分支超阈值。
    - 架构观察：`.app-toolbar-primary` 把布局槽与阅读页特定排版（`font-size:11px; color:var(--muted)`，`components.css:1277-1286`）耦合，后续复用方可能继承非预期字形；建议排版留给调用方或独立修饰类。无当前缺陷，不进 finding。
    - checker 脆弱性：`css.indexOf('.app-toolbar-actions,')`（`check_layout_contracts.mjs:38`）依赖逗号别名写法；若后续收敛为单一 `.app-toolbar-actions {` 会误报缺失，建议改稳健的存在性判断。
    - 环境缺口：本 worktree 缺 pytest 模块、desktop 缺 electron 依赖，pytest contract 与 desktop `npm test` 未能复跑（与本次前端 diff 无关）；敏感扫描 33 文件 0 违规、`npm run build` 通过。
    - 措辞差异：`docs/pending/p080_...md` 为 `status: closed` / `resolution: transferred` / `fix_ref: t080`，符合 AC-006「转办闭环指向 t080」；spec 范围行写 `--resolution resolved`，建议 finalization 统一措辞。不判 FAIL。
- 总体判断：契约迁移、绝对定位根除、断点单一来源与共享几何门禁均真实落地，7 条 AC 打勾成立；仅 1 条 minor 门禁健壮性缺口，不阻断。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/e2e/reader_toolbar.spec.ts:7` 在 360px 视口 + 93 字符长邮箱下经 `assertNoOverlap` 用真实 `boundingBox` 断言 `.reader-location` 与 `.reader-toolbar-actions` 不相交；单独跑 1 passed，全量 E2E 22 passed。
- AC-002：TICK-VALID，re_verified。`src/frontend/src/design-system/components.css:1288-1294` 操作槽为常规 flex `flex:0 0 auto`，全文无 toolbar 相关 absolute/translate 残留；`MessageReader.test.tsx:346-351` 契约断言实跑通过；`.reader-action` 36×36 保留（`:1375-1377`）。
- AC-003：TICK-VALID，re_verified。共享原语在 `components.css:1260-1294`，条款在 `docs/blueprint/conventions.md:19-24`，阅读页已挂载（`MessageReader.tsx:386-389`）；独立 grep 确认 `.list-header` / `.settings-toolbar` 无绝对覆盖（审计记录见 `progress.md`）。
- AC-004：TICK-VALID，re_verified。正向 `npm run css:check` 通过；反向在临时副本把 `breakpoints.ts` mobile 改为 720 后 checker 以 exit 1 列出未授权 760px 媒体查询；TS/TSX 无其它硬编码断点，全部 media 值均属 `BREAKPOINTS`。复合查询漏检另记 f001（minor）。
- AC-005：TICK-VALID，re_verified。`tests/e2e/layoutGeometry.ts:1-28` 导出 `assertNoOverlap` / `setNarrowViewport` / `rectsOverlap` 为独立可复用模块，`reader_toolbar.spec.ts:3` 直接 import，无复制实现，t081 可复用。
- AC-006：TICK-VALID，re_verified。diff 同步 `conventions.md` / `testing.md` / `inbox_ui_and_search.md` 并在 tasks 登记 t080；`docs/pending/p080_reader_toolbar_actions_overlap_sender_email.md` 为 `status: closed`、`fix_ref: t080`、`resolution: transferred`，符合「转办闭环指向 t080」。
- AC-007：TICK-VALID，re_verified。独立复跑 `npm test`（vitest + openapi + css:check）、`npx tsc -b`、`npm run build`、敏感扫描（33 文件 0 违规）与 blackbox E2E（22 passed）均通过；diff 无弱化断言或临时补丁。pytest contract 与 desktop `npm test` 因本 worktree 缺 pytest 模块 / electron 依赖未复跑（与前端 diff 无关）。

coverage = 7 / 7

verdict: PASS

## Round 2 (2026-11-20T19:42:49+08:00)

- round：2
- reviewed_at：2026-11-20T19:42:49+08:00

reviewed_scope: 0b63f6061dbac01b

## Findings

本轮无新 finding（Round 2 零 finding）。

## 结论

- 前轮 finding 复核：t080_code_f001（断点静态检查漏检复合/带媒体类型 max-width，minor）——已修复，复核确认真修。实施方把 `check_layout_contracts.mjs:21-23` 改为先以 `@media([^{]+)\{` 截取完整媒体预条件，再在整段上全局匹配 `max-width:\s*(\d+)px`。独立复验：仅在临时副本（未改交付文件）向 `components.css` 追加 `@media (min-width: 361px) and (max-width: 723px)` 与 `@media screen and (max-width: 723px)`，checker 输出两条 `FAIL: ... @media max-width 723px 不在 breakpoints.ts 的单一来源中` 且 exit 1（Round 1 同输入 exit 0）；交付 CSS 正向仍 exit 0；把 `breakpoints.ts` 的 mobile 改为 720 后 checker exit 1 并列出未授权 760px。f001 消除。
- 本轮新发现：0 条（Round 2 零 finding，无新严重度）。
- 未进表的提示：无新增。沿用 Round 1 结论段关于 `.app-toolbar-primary` 排版耦合、`css.indexOf('.app-toolbar-actions,')` 脆弱性与环境缺口的观察，均非本轮修复引入，不阻断。修复未引入新缺陷：新正则以首个 `{` 截断预条件，交付 CSS 无注释内 `@media`/`{` 干扰，正负两例均验证。
- 总体判断：f001 复核为已消除，AC-001~AC-007 打勾在本轮独立复验下全部成立；无未解决 critical / important。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立运行 `npm run test:e2e -- reader_toolbar.spec.ts`（1 passed）：360px 视口 + 长邮箱样本下 `assertNoOverlap` 用真实 `boundingBox` 断言 `.reader-location` 与 `.reader-toolbar-actions` 不相交，并断言邮箱全文可见。
- AC-002：TICK-VALID，re_verified。`components.css:1288-1294` 操作槽为常规 flex `flex:0 0 auto`，`.reader-toolbar-actions` 全文无 absolute/translate；`MessageReader.test.tsx:346-351` 契约层断言随 `npm test`（592 passed）通过；`.reader-action` 36×36 保留（`:1375`）。
- AC-003：TICK-VALID，re_verified。`components.css:1260-1294` 定义单一原语 `.app-toolbar` / `.app-toolbar-primary` / `.app-toolbar-actions`；`MessageReader.tsx:386-389` 已挂 `app-toolbar` 类；grep 确认 `.list-header`（`:912,1586`）/ `.settings-toolbar`（`:1737-1742`）为 flex 无绝对覆盖；条款在 `conventions.md:20-24`。
- AC-004：TICK-VALID，re_verified。独立跑 checker 三例：交付 CSS exit 0；追加复合与带媒体类型 723px 负例 exit 1；`breakpoints.ts` mobile=720 反向 exit 1 并列出未授权 760px。TS/TSX 无其它硬编码媒体断点（`mailBody.ts:403` 的 `max-width:100%` 是邮件 HTML 内联样式，非媒体查询）。f001 已消除。
- AC-005：TICK-VALID，re_verified。`tests/e2e/layoutGeometry.ts:1-28` 独立导出 `assertNoOverlap` / `setNarrowViewport` / `rectsOverlap`，`reader_toolbar.spec.ts:3` 直接 import 无复制实现；`npx tsc -b` 通过。
- AC-006：TICK-VALID，re_verified。diff 同步 `conventions.md` / `testing.md` / `inbox_ui_and_search.md`（tasks 增 t080）；`docs/pending/p080_reader_toolbar_actions_overlap_sender_email.md` 为 `status: closed` / `resolution: transferred` / `fix_ref: t080`，符合转办闭环指向 t080。
- AC-007：TICK-VALID，re_verified。独立复跑 `npm test`（vitest 55 文件 / 592 passed + openapi + css:check 均绿）、`npx tsc -b`（exit 0）、`npm run build`（通过）、`npm run test:e2e -- reader_toolbar.spec.ts`（1 passed）；diff 无弱化断言 / 临时补丁残留。pytest contract 与 desktop `npm test` 因本 worktree 缺 pytest 模块 / electron 依赖未复跑（与前端 diff 无关）。

coverage = 7 / 7

verdict: PASS
