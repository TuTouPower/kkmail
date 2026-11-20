# Task review t081（reviewer_focus: 代码）

- task：`t081_mail_document_rendering_contract`
- spec：`docs/tasks/t081_mail_document_rendering_contract/task.md`
- diff_anchor：`bb05825c9de416f92af090b8a258597456ee87f0`
- target：`git diff bb05825c9de416f92af090b8a258597456ee87f0`
- round：1
- reviewed_at：2026-11-20T20:01:25+08:00

reviewed_scope: e62eab455bc7f7d2

## Findings

### t081_code_f001 - bodyStyle 新增 `overflow-wrap:anywhere` 未纳入渲染契约文档，属契约外行为变更

- 严重度：minor
- 锚点：规格合规(实现层)「不自由发挥」/ 文档与规格一致性；不违反任何 AC
- 位置：`src/frontend/src/lib/mailBody.ts:401`
- 问题：本次在 `bodyStyle` 追加 `overflow-wrap:anywhere`（`word-wrap:break-word` 的更激进变体，后者被其覆盖），该条未写入决策记录 `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md:4` 的样式契约清单，也非 AC-001/002 所需——独立 Chromium 实验中仅 `width:auto !important;max-width:100% !important` 已使 `scrollWidth=clientWidth=360`。该变更会改变全部 HTML 正文的文本折行观感，是「唯一收口处」之外的额外行为，且无文档可追溯。
- 建议：在决策记录样式契约中补记该条并说明取舍，或若非必要则移除，保持实现与渲染契约文档一致。

## 结论

- 前轮 finding 复核：本轮为 Round 1，无前轮 finding。
- 本轮新发现：1 条（minor）。
- 未进表的提示：
    - 实现源码 `src/frontend/src/lib/mailBody.ts` 458 行，达到「实现源码 ≥400 → minor 建议拆分」阈值且本 task 净增约 6 行；按「文件过大标准」降级规则仅作提示、不进 finding 表；本 task 收敛于唯一收口函数 `buildMailSrcdoc()`，拆分收益低。
    - spec 范围段写 p081 以 `--resolution resolved` 闭环，而 AC-005 写「转办闭环」；实际 `docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` 为 `status: closed / resolution: transferred / fix_ref: t081`。实现符合 AC-005 措辞，属 spec 文本自相矛盾，建议后续对齐文案，不阻断。
- 总体判断：渲染契约真正在 `buildMailSrcdoc()` 唯一收口处落地并覆盖所有 HTML 正文分支；viewport + `width:auto !important` 机制经 E2E 与独立 Chromium 实验复验成立；CSP/sandbox/no-referrer/base/图片代理逐字未变；复用 t080 共享几何层且无第二套 `assertNoOverlap`；`test_cmd` 与 `blackbox_verify` 全绿。仅 1 条 minor 文档一致性问题，无 critical / important，判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`buildMailSrcdoc()` 在 `src/frontend/src/lib/mailBody.ts:416` 唯一收口注入 viewport meta；`MessageReader.tsx:323-334` 为唯一调用点，两处 iframe `srcDoc`（`:635`/`:646`）共用同一 `mailSrcdoc`，纯文本正文不走 iframe；`node run_e2e.mjs mail_body_viewport.spec.ts` 通过，360px 下 iframe `html`/`body` 的 `scrollWidth <= clientWidth + 1`，标题与表格右边界落在屏内。
- AC-002：TICK-VALID，re_verified。`widthStyle`（`mailBody.ts:406`）含 `width:auto !important;max-width:100% !important`；`mailBody.test.ts` 新增用例「injects viewport and fixed-width constraints as the mail document contract」同时断言 viewport、两条宽度字符串及 `default-src 'none'`、`img-src 'self' data: cid:`；`npx vitest run src/lib/mailBody.test.ts` 26/26 通过，`MessageReader.test.tsx` 既有 no-referrer/base/CSP 断言未改。
- AC-003：TICK-VALID，re_verified。决策记录 `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md`（12 行，`:4` 决策、`:10` 不变量）新建；`docs/blueprint/conventions.md:12-13` 增补渲染契约条款；`:10` 明确 CSP/sandbox/no-referrer/base/代理为不变量。
- AC-004：TICK-VALID，re_verified。`assertNoHorizontalOverflow` 加入 t080 共享 `tests/e2e/layoutGeometry.ts:18`，新 spec 直接复用并复用 `setNarrowViewport`（`:5`）；全仓仅一处 `assertNoOverlap` 定义（`layoutGeometry.ts:30`），`mail_body_viewport.spec.ts` 未复制实现；`progress.md`「实施笔记」第 3 条记录复用方式。
- AC-005：TICK-VALID，re_verified。`docs/blueprint/testing.md:49` blackbox 说明、`docs/specs/inbox_ui_and_search.md:4` tasks 列表（已含 t081）与条款（`:21`）同步；`docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` 为 `closed`/`transferred`/`fix_ref: t081`。
- AC-006：TICK-VALID，re_verified。`npm test`（vitest + openapi:check + css:check）、`npx tsc -b`、`npm run build` 全通过；清理残留 server 进程后 `npm run test:e2e` 23/23 通过；git status 无临时 debug spec 残留，新用例无 `.skip`/恒真断言/阈值放宽。

coverage = 6/6

verdict: PASS

## Round 2 (2026-11-20T20:06:32+08:00)

reviewed_scope: b7a8224d6fcf6f17

## Findings

Round 2 零 finding。

## 结论

- 前轮 finding 复核：
    - `t081_code_f001`（`bodyStyle` 新增 `overflow-wrap:anywhere` 未纳入契约文档，minor）：已消除。`git diff bb05825c...` 显示 `src/frontend/src/lib/mailBody.ts:401` 的 `bodyStyle` 已恢复为原 `word-wrap:break-word`，全文件 `grep overflow-wrap` 零命中；为直接移除该声明而非补文档，未引入替代行为，修复过程无新增问题。同意撤回并关闭。
    - Round 1 未进表提示（spec 范围段 p081 用 `resolved` 闭环措辞、与 `transferred` 转办状态及 AC-005「转办闭环」自相矛盾）：已同步修正。`docs/tasks/t081_mail_document_rendering_contract/task.md:15` 现改为「p081 已在立项时以 `transferred` 转办至本 task（fix_ref=t081），本 task 完成后不再二次闭环」，与 `docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` 的 `closed`/`transferred`/`fix_ref: t081` 一致。
- 本轮新发现：0 条。
- 未进表的提示：无。Round 1 的 `mailBody.ts` 文件过大提示仍成立（458 行，唯一收口函数，拆分收益低），非本轮修复引入，按降级规则不进表。
- 总体判断：f001 已按直接移除方式修复，spec 文案同步对齐；相对 `diff_anchor` 的完整交付上，viewport + 宽度约束在 `buildMailSrcdoc()` 唯一收口处落地并覆盖全部 HTML 正文分支，CSP/sandbox/no-referrer/base/图片代理逐字未变，复用 t080 共享几何层且无第二套 `assertNoOverlap`，全部门禁实跑通过（vitest 593/593、tsc/build rc=0、E2E 23/23、敏感扫描 0 违规），无弱化断言与临时补丁残留。无未解决 critical/important，全部 AC 为 `TICK-VALID`，判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/frontend/src/lib/mailBody.ts:416` 唯一收口注入 `<meta name="viewport" content="width=device-width, initial-scale=1">`；`MessageReader.tsx:323-334` 为唯一调用点，两处 iframe `srcDoc`（`:635`/`:646`）共用同一 `mailSrcdoc`，纯文本正文不走 iframe。`npm --prefix src/frontend run test:e2e` 实跑 23/23 通过，其中 `tests/e2e/mail_body_viewport.spec.ts:16` 在 360px 下断言 iframe 内 `html`/`body` 的 `scrollWidth <= clientWidth + 1`。
- AC-002：TICK-VALID，re_verified。`widthStyle`（`mailBody.ts:406`）含 `width:auto !important;max-width:100% !important`；`mailBody.test.ts:51-58` 契约用例同时断言 viewport、两条宽度字符串与 `default-src 'none'`、`img-src 'self' data: cid:`；`npx vitest run src/lib/mailBody.test.ts` 26/26、全量 `npx vitest run` 593/593 通过，`MessageReader.test.tsx:645-672` 既有 CSP/img-src 断言未改且通过，CSP/sandbox/base/no-referrer 字符串未回归。
- AC-003：TICK-VALID，re_verified。决策记录 `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md`（12 行，`:4` 决策、`:10` 安全边界不变量）新建；`docs/blueprint/conventions.md:12-13` 增补邮件文档渲染契约条款并明确不放宽 CSP/sandbox/no-referrer/代理。
- AC-004：TICK-VALID，re_verified。`assertNoHorizontalOverflow` 加入 t080 共享 `tests/e2e/layoutGeometry.ts:18`，新 spec（`:3`）直接 import 并复用 `setNarrowViewport`；全仓仅一处 `assertNoOverlap` 定义（`layoutGeometry.ts:30`），无复制的第二套实现；`progress.md`「实施笔记」第 3 条记录复用方式。
- AC-005：TICK-VALID，re_verified。`docs/blueprint/testing.md:49` blackbox 说明、`docs/specs/inbox_ui_and_search.md:4` tasks 列表（已含 t081）与 `:21` 契约条款同步；`docs/pending/p081_mail_body_iframe_missing_viewport_overflow.md:4-7` 为 `closed`/`transferred`/`fix_ref: t081`；`task.md:15` 措辞已对齐为立项时转办、完成不二次闭环。
- AC-006：TICK-VALID，re_verified。`npm test`（vitest 593 + openapi:check + css:check 全绿）、`npx tsc -b`（rc=0）、`npm run build`（rc=0）、`npm --prefix src/frontend run test:e2e`（23/23）、`python3 scripts/check_doc_sensitive.py docs --check`（0 违规）实跑通过；新用例无 `.skip`/恒真断言/阈值放宽，`git status` 无临时 debug spec 残留。

coverage = 6/6

verdict: PASS
