---
tid: "t081"
slug: "mail_document_rendering_contract"
title: "邮件文档渲染契约与移动端视口适配"
status: "done"
branch: "t081_mail_document_rendering_contract"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "bb05825c9de416f92af090b8a258597456ee87f0"
spec_source_sha: "81b6a255979bbd771f16c59e177da1378e04683f"
depends_on: "t080"
conflicts_with: ""
note: "来源 p081；在 buildMailSrcdoc 唯一收口处确立渲染契约；依赖 t080 落地的共享 360px 几何 E2E 模板"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- TDD 红灯：先新增 `tests/e2e/mail_body_viewport.spec.ts`（固定宽度 680px 表格 fixture，360px 视口）与共享 `assertNoHorizontalOverflow`，未改 `buildMailSrcdoc()` 时实测 `html.scrollWidth=680 / clientWidth=309` 失败；临时 debug spec 定位到 `table` 计算宽度仍为 680px，确认是渲染契约缺失而非 fixture 误写，debug spec 已删除。
- 根因修复：`buildMailSrcdoc()` head 注入 viewport meta；style 以 `div,table,td,th{width:auto !important;max-width:100% !important;height:auto}` 收敛固定宽度。仅加 `max-width:100% !important` 时 Chromium 表格布局仍取 680px，必须以 `width:auto !important` 覆盖写死宽度；收敛后 E2E 转绿。
- 复用关系：t081 不复制几何实现，直接在 t080 落地的 `tests/e2e/layoutGeometry.ts` 增加 `assertNoHorizontalOverflow` 并复用 `setNarrowViewport`；E2E 默认目标由 `run_e2e.mjs` 增加 `mail_body_viewport.spec.ts`，blackbox_verify 已覆盖。
- 安全边界未动：CSP、sandbox、`no-referrer`、`<base target=_blank>` 与图片代理重写逻辑保持原样；srcdoc 契约单测同时断言 CSP 不变量。
- 门禁实测：`npm test`（vitest + openapi + css:check）、`npx tsc -b`、`npm run build`、`npm run lint`、`npm run test:e2e` 23 passed 全部通过。
- 工作区 `src/frontend/node_modules` 软链主仓依赖，路径已被 `src/frontend/.gitignore` 忽略，不进入交付 diff。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-20T19:58:00+08:00)

双轴均 PASS（code / test），AC 6/6 全部 TICK-VALID；code finding 1 条 minor，test 零 finding。code f001 已修复并在 Round 2 复审确认。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t081_code_f001|minor|已修|`bodyStyle` 新增 `overflow-wrap:anywhere` 属契约外行为变更且未写入决策记录；该声明非 AC-001/002 所需（仅宽度收敛即可使 scrollWidth=clientWidth），现直接移除，bodyStyle 恢复原有 `word-wrap:break-word`；同时修正 spec 范围段 p081 闭环措辞为「立项时已 transferred，完成后不二次闭环」|src/frontend/src/lib/mailBody.ts:401；docs/tasks/t081_mail_document_rendering_contract/task.md:15|

### Round 2 (2026-11-20T20:05:00+08:00)

双轴均 PASS，reviewed_scope=b7a8224d6fcf6f17，AC 6/6 TICK-VALID，零新 finding；前轮 t081_code_f001 经独立复验确认修复（全文件无 `overflow-wrap`，宽度收敛与安全不变量不变）。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：src/frontend `npm test` 通过（vitest + openapi:check + css:check）、`npx tsc -b`、`npm run build`、`npm run lint` 通过。
- 黑盒：`npm run test:e2e` 23 passed；`mail_body_viewport.spec.ts` 修复前红（`scrollWidth=680 / clientWidth=309`）、修复后绿，复用 t080 共享 360px 几何模板。
- review：full 双轴 2 轮；Round 1 code/test 均 PASS（code minor 1、test 零），Round 2 双轴均 PASS 零 finding；AC 6/6 TICK-VALID。
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 全部 6 条 AC 满足；邮件文档渲染契约落在 `buildMailSrcdoc()` 唯一收口处，viewport 与固定宽度收敛对所有 HTML 正文生效；CSP/sandbox/代理边界不变；复用 t080 共享几何层，无第二套实现。无遗留 finding、无 follow-up。
- specs_index：docs/specs/inbox_ui_and_search.md 的 tasks 已登记 t081，并补入邮件文档渲染契约条款；决策记录 `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md` 已落盘。
