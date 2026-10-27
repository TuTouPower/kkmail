> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — perspectives 7 (Tests/Spec) + 8 (Documentation) — TuTouPower/kkmail @ b2956445574ebf171c1e73526421f0d46ccac3a3 2026-10-21

## Summary

- Scope: read-only; `tests/` (77 py incl. `tests/mail_core/`), `frontend/src/**/*.test.ts` (21), `openspec/`, root docs (`README.md`, `DESIGN.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/*`), `.github/workflows/{tests,frontend}.yml`
- Findings: C/H/M/L/Info = 0/4/12/6/4
- Verdict: **REQUEST CHANGES** (no Critical in these two perspectives; multiple High on CI gap, wrong-surface frontend contracts, agent-doc dead paths, SSOT duplication)

## Inventory (evidence base)

|Area|Count / note|
|---|---|
|`tests/*.py` (legacy Flask/UI)|~48 modules + `conftest.py`|
|`tests/mail_core/*.py`|29 modules|
|Frontend Vitest `*.test.ts`|21 (lib 12/13 covered; components 1/8; no pages)|
|Desktop unit tests|`paths.test.js`, `postgresManager.test.js`|
|OpenSpec current specs|7 under `openspec/specs/` (all changes archived; no active change dirs)|
|OpenSpec Purpose TBD|3 (`cloudflare-all-mail-view`, `cloudflare-channel-management`, `email-address-fallback-resolution`)|
|mail_core modules with module-level `skipif` (no `MAIL_CORE_DATABASE_URL`)|16 / 29|
|`assertIn(` density in `tests/*.py`|~956 (mostly legacy template/JS substring contracts)|
|CI `tests.yml`|runs **only** `test_react_spa_routes.py` + `test_frontend_contract.py`|
|CI `frontend.yml`|`npm run build` only (no lint / tsc / vitest)|
|mail-core workflow|template only: `docs/ci/mail-core.workflow.yml` (not under `.github/workflows/`)|

______________________________________________________________________

## Critical / High (必修)

### [H][95] `.github/workflows/tests.yml:20` — CI 几乎不跑后端测试

- **证据**: workflow 仅执行\
    `pytest tests/test_react_spa_routes.py tests/test_frontend_contract.py -q`\
    路径过滤也不含 `mail_core/**`、`frontend/**`。对比 `AGENTS.md:71-82` 声称本地全量「约 770+ 用例」且提交前要跑 pytest 全量。
- **规则**: 视角7 强信号「新路径/核心路径无测试」+ CI 验收假象（验证范围远小于声称）。
- **修复**: `tests.yml` 改为 `pytest -q`（或至少 `tests/` 排除 live fixtures）；path 触发加入 `mail_core/**`、`web_outlook_app.py`、`requirements*.txt`；另 job 调用 `scripts/run-mail-core-tests.sh`（带 Postgres service）。把 AGENTS 中「提交前至少跑」与 CI 对齐，避免文档夸大门禁。

### [H][92] `.github/workflows/frontend.yml:24-25` — 前端 CI 只 build，不跑 vitest/lint/tsc

- **证据**: 仅 `npm install` + `npm run build`。仓库已有 21 个 `*.test.ts` 与 `npm test` / `npm run lint` / `npx tsc -b`（`AGENTS.md:73-76`），CI 全部跳过。
- **规则**: 视角7 覆盖判据 — 有测试但门禁不执行 = 假绿。
- **修复**: 增加 steps：`npm run lint`、`npx tsc -b`、`npm test`，再 `npm run build`；失败阻断。

### [H][90] `tests/test_*_frontend.py` + legacy `templates/`/`static/js` — 主路径 UI 契约测在错误表面上

- **证据**:
    - `tests/test_outlook_graph_send_mail_frontend.py:7-16,29-48` 读取 `templates/partials/index/*.html` 与 `static/js/index/*.js`，用 `assertIn('id="composeGraphMailBtn"', …)` / 函数名子串断言。
    - 同类：`test_account_secret_reveal_frontend.py`、`test_tag_filtering_frontend.py`、`test_account_panel_header_ui.py`、`test_project_management_ui.py`、`test_batch_account_status_frontend.py`（Node `vm` 跑 `static/js/index/08-refresh.js` 等）。
    - 产品主壳是 React SPA（`AGENTS.md:40-41`，`/legacy` 为旧版）；`composeGraphMailBtn` 仅出现在 legacy templates，不在 `frontend/src`。
    - `openspec/specs/group-tree-ui/spec.md:13` 要求二级 20px / 三级 40px 树缩进；`frontend/src/components/Sidebar.tsx:44-98` 按 `group_id` **扁平**列出成员，无 `parent_id` 树渲染/缩进。层级能力仍在 `static/js/index/02-groups.js`。
- **规则**: 视角7「行为可观察 vs 内部/错误表面」；「验证假行为」— React 回归可绿，legacy 子串仍绿。
- **修复**:
    1. 标注 legacy 契约测试为 `@pytest.mark.legacy_ui`，与 SPA 测试分离；
    2. 对 SPA 用 Vitest/RTL/Playwright 覆盖 compose、分组树、批量选择；
    3. 若 React 不实现三级树 UI，在 openspec / known-limitations 标明「仅 /legacy」，避免规格冒充当前主 UI。

### [H][88] `AGENTS.md:1-21` — Trellis 指令指向不存在的权威路径

- **证据**: `TRELLIS:START` 要求读 `.trellis/workflow.md`、`.trellis/spec/`、`.agents/skills/`；仓库根 **无** `.trellis/`、**无** `.agents/`（探测失败）。Agent 按该块加载会空转或编造流程。
- **规则**: 视角8「Agent 指令须位于实际加载路径且正向可判断」；死链/失效权威。
- **修复**: 删除或条件化 Trellis 块；或提交真实 `.trellis`；在块首写明「若目录不存在则忽略，以本节下文为准」。

______________________________________________________________________

## Medium / Low / Info (建议)

### 视角7 — 测试·规格

#### [M][90] `tests/mail_core/*.py` — 默认 pytest 静默跳过核心 mail-core

- **证据**: 至少 16 个文件 `pytestmark = pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), …)`（如 `test_message_mutations_api.py:18-21`、`test_schema_pg.py:37-39`、`test_fts_inbox_api.py:18-20` 等）。无 env / 无 compose 时 `pytest tests/mail_core` 大量 skip。正式 workflow 仅模板 `docs/ci/mail-core.workflow.yml`（`docs/mail-core-status.md:15-23` 自述）。
- **修复**: CI 起 Postgres service + `scripts/run-mail-core-tests.sh`；本地 README/AGENTS 标明「无 PG 则 mail_core 几乎全 skip」。

#### [M][85] `openspec/specs/*/spec.md` Purpose TBD — 归档半完成

- **证据**:
    - `cloudflare-all-mail-view/spec.md:4`
    - `cloudflare-channel-management/spec.md:4`
    - `email-address-fallback-resolution/spec.md:4`\
        文案均为 `TBD - created by archiving change … Update Purpose after archive.`\
        `openspec/changes/` 仅有 `archive/`，无进行中 change。
- **规则**: 规格对齐 / 半实现文档卫生。
- **修复**: 补全 Purpose，或从 specs 移除未维护条目并链到 archive proposal。

#### [M][82] `openspec/specs/group-tree-ui` vs React Sidebar — 规格相对主 UI 半实现/漂移

- **证据**: spec 要求树缩进、折叠持久化、拖拽；后端 `tests/test_hierarchical_groups.py` 覆盖 `parent_id`/`level`/`get_descendant_group_ids`；SPA `Sidebar.tsx` 未消费树结构做缩进（API 类型虽有 `parent_id`/`level` 在 `frontend/src/api/queries.ts:11-13`）。
- **修复**: 实现 SPA 树 UI，或修订 spec / known-limitations：「三级分组 UI 仅 legacy」。

#### [M][80] `docs/known-limitations.md:5-15` + `README.md:779` — Flagged「仅本地」与 mail-core 写回 API 冲突

- **证据**: limitations 写「Flags are not written to Graph, IMAP, or SQLite」。同时 `mail_core/api/mail.py` 有 `POST /messages/{id}/flag`；前端 `mailCore.mutations.test.ts`、`postMailCoreMessageFlag` 已测。`docs/mail-core-status.md:8` 称 flag 写回已完成。
- **规则**: 规格/文档与实现漂移；未来/路径 B 冒充全局当前。
- **修复**: 分节写清：Flask/upstream 路径仍本地-only；`VITE_MAIL_CORE` 开启时走 mail-core flag API（及远端 reconcile 局限）。

#### [M][78] 无 E2E + SPA 组件几乎无测

- **证据**: `docs/known-limitations.md:52`「End-to-end browser tests are not yet in place」；`frontend/src/components/` 有 ComposeModal、LoginPage、MailCoreBridge、MessageList、MessageReader、SettingsModal、Sidebar，仅 `ColumnResize.test.ts`。
- **修复**: 优先 Playwright：登录、列表、读信、mail-core bridge；RTL 覆盖 Sidebar/MessageList 关键交互。

#### [M][70] `frontend/src/lib/mailCoreFlag.test.ts:10-21` — 弱断言 + 条件可空跑

- **证据**: `expect(typeof isMailCoreEnabled()).toBe('boolean')`（存在性/类型级）；第二例 `if (!String(import.meta.env.VITE_MAIL_CORE || '')) { expect… }` — env 一旦设置则 **零断言仍通过**。
- **规则**: 危险模式「恒真/弱化断言」。
- **修复**: 用 `vi.stubEnv` / 显式分支表驱动；禁止可跳过的 expect 块。

#### [M][65] CSRF 相关用例 `skipUnless(CSRF_AVAILABLE)`

- **证据**: `test_error_handlers.py:63,79`、`test_account_reauthorization.py:280`、`test_outlook_graph_send_mail.py:397`、`test_outlook_auto_auth_queue.py:209`。依赖未装 flask-wtf 时安全路径静默 skip。
- **修复**: CI `requirements` 固定含 flask-wtf；或改为缺依赖则 fail（与生产「推荐安装」一致）。

#### [L][60] `assert … is not None` 零散弱断言

- **证据**: `tests/mail_core/test_message_detail_api.py:73`、`test_fts_inbox_api.py:75-77`、`test_imap_sync_loop.py:93` 等。多数同文件另有强断言，单独不 blocking。
- **修复**: 断言具体字段/状态机值。

#### [L][55] `tests/test_frontend_contract.py:4-22` — 路由存在性清单偏薄

- **证据**: 只检查 url_map 是否含路径集合，不测方法/鉴权/响应契约；且为 CI 唯二后端用例之一，放大「存在即合规」风险。
- **修复**: 保留作 smoke，另加 OpenAPI/响应 schema 或关键 POST 鉴权用例。

#### [L][50] `vi.mock('../lib/mailCoreFlag')` in `mailCore.mutations.test.ts:5-8`

- **证据**: mock 特性开关属边界配置，可接受；但会掩盖 flag 解析错误。已有独立 `mailCoreFlag.test.ts` 部分对冲。
- **修复**: 保持；强化 flag 单测（见上）。

#### [Info][80] Strengths — 测试侧

- `tests/conftest.py:10-18` + `test_db_isolation.py` 强制测试库隔离，`SECRET_KEY`/`LOGIN_PASSWORD` 测试默认仅测试进程。
- `fake_frontend_dist` 避免强依赖预构建 dist。
- mail_core 含 chaos lease、backup restore drill、blob crypto/rewrap、IMAP fixture — 设计成熟（但依赖 PG env）。
- 前端 `mailBody`/`mailKey`/`accounts` 等 lib 单测质量高，贴合 AGENTS 安全约定。

### 视角8 — 文档规范

#### [H][90] `README.md` (811 行) ↔ `docs/deployment.md` — 部署双权威 / 非最短入口

- **证据**: README「快速开始」完整复制 Docker/`LOGIN_PASSWORD=***`/`SECRET_KEY` compose 片段（如 `README.md:69-70,106-107,139-140`），与 `docs/deployment.md:30-31,96-97,125` 同内容平行维护。视角8：README 应最短入口 + 相对链接；同一流程仅一处完整定义。
- **修复**: README 保留 10–20 行最短路径 + 链接 `docs/deployment.md`；删除重复 compose 长块。

#### [M][85] 弱默认口令 `***` 作为文档示例默认值

- **证据**: `README.md`、`docs/deployment.md`、`.env.example:11`、`AGENTS` 测试 env 多处 `LOGIN_PASSWORD=***`。skill：示例脱敏且无弱默认 secret；部署文档表「默认 `***`」易被照抄进生产。
- **修复**: 示例改为 `LOGIN_PASSWORD='<change-me>'` 或强制首次随机；明确「示例不可用于公网」。

#### [M][88] `docs/mail-core-status.md` — 会话/代理口吻残留

- **证据**: L9「无法由代理单独完成，需要你本人操作」；L37「代理不会代你申请」；L59-61「再说一声即可继续对接」。面向最终读者的产品文档混入 coding-agent 会话语境。
- **规则**: 视角8 删除试错/会话口号；正文面向人类维护者。
- **修复**: 改为「维护者待办 / 外部依赖」中性清单，去掉「代理/再说一声」。

#### [M][75] `DESIGN.md` 命名 vs 系统架构文档

- **证据**: 根目录 `DESIGN.md` 实为前端设计系统 token（frontmatter colors/typography）；系统架构权威在 `docs/mail-core-architecture.md`（776 行）。新人易把 DESIGN 当系统设计和 SSOT。
- **修复**: README 目录表写清「DESIGN.md = UI design system；架构见 docs/mail-core-architecture.md」；或改名为 `DESIGN_SYSTEM.md`（需改引用）。

#### [M][70] OpenSpec Purpose TBD（同视角7）— 文档占位符未清理

- 见上；占位符进现行 specs 违反「清理无定义占位符」。

#### [M][70] Flagged / mail-core 文档三态不清（同视角7）

- `known-limitations` + README 未按「当前 Flask / 当前 mail-core / 未来」分节。

#### [L][60] `docs/api.md` 体量 3077 行

- 风险：手维巨型 API 文易与实现漂移。未在本视角跑全文 diff；建议标明生成方式或拆 Flask vs mail-core。
- **修复**: 若有 OpenAPI，改「生成配置」；禁止只手改生成产物。

#### [L][55] `AGENTS.md:71`「770+ 用例」可能过时

- 未在本机重跑计数；作为可验证断言应标日期或改为「见 pytest 收集数」。
- **修复**: 改为「运行 `pytest --collect-only -q`」或更新数字。

#### [L][50] `BRANCH_PROTECTION.md` / `RELEASE.md` / `CHANGELOG.md` 并存

- Info/Low：多入口可接受若互相链接；未发现明显互相矛盾（未全文审 CHANGELOG 84282 bytes）。

#### [Info][75] Strengths — 文档侧

- `docs/known-limitations.md` 显式记录未完成产品规则（方向正确，内容需随 mail-core 更新）。
- `docs/mail-core-status.md` 试图只列「需用户介入」项（结构好，语气需中性化）。
- `AGENTS.md` 非 Trellis 段对安全约定（mailBody、mailKey、CSRF、测试库隔离）清晰，适合代理。
- `.env.example` 存在且多为占位（除 \*\*\*）。

______________________________________________________________________

## Spec Compliance（openspec + 产品限制）

|Spec / 文档|状态|说明|
|---|---|---|
|`account-reauthorization`|大体对齐|有 `tests/test_account_reauthorization.py`；Purpose 完整|
|`hierarchical-groups`|后端对齐 / SPA UI 缺口|API+DB 测试在；React 未树形展示|
|`group-tree-ui`|**相对主 UI 半实现**|缩进/拖拽落在 legacy；openspec 未声明 surface|
|`refresh-management-batch-actions`|legacy 有 vm 测试|`test_batch_account_status_frontend.py`；SPA 侧未见表征测试|
|`cloudflare-*` / `email-address-fallback`|实现侧有测试文件|Purpose TBD；归档卫生差|
|Flagged（known-limitations）|**漂移**|mail-core 已提供 flag API|
|E2E|缺失|已记录|

______________________________________________________________________

## Strengths

- 测试库隔离与 frontend dist fixture 设计扎实。
- mail_core 测试矩阵（状态机、lease chaos、backup drill）在有 PG 时有深度。
- 前端 lib 层单测与 XSS/mailKey 约定绑定好。
- 文档体系分区（deployment/security/api/mail-core-\*）存在，优于无 docs 的仓。

## Appendix — Traceability

- Skill: `/workspace/intensive-review/SKILL.md` §视角7 / §视角8（DOCUMENTATION_STANDARD 本机缺失，按 skill 启发式）
- SHA: `b2956445574ebf171c1e73526421f0d46ccac3a3`
- OUTDIR: `docs/reviews/review_20261021_011116`
- Key paths: `.github/workflows/tests.yml:20`, `.github/workflows/frontend.yml`, `AGENTS.md:1-21,71-82`, `tests/test_outlook_graph_send_mail_frontend.py:7-48`, `frontend/src/components/Sidebar.tsx:44-98`, `openspec/specs/group-tree-ui/spec.md:13`, `docs/known-limitations.md:5-15`, `docs/mail-core-status.md:9-61`, `README.md:69-174`, `tests/mail_core/test_message_mutations_api.py:18-21`

## Counts

- Findings total: **26** (C0 / H4 / M12 / L6 / Info4)
- Perspective 7: 14 findings (H2 + M7 + L3 + Info1 strengths-as-info + shared)
- Perspective 8: 12 findings (H2 + M5 + L3 + Info2) — shared TBD/flag counted once each in totals above
