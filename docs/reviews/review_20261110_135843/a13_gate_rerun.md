# A13 门禁复跑证据（review_20261110_135843 adoption 收尾）

- 复跑时间：2026-11-10（Asia/Shanghai）
- 代码基线：main `f3c339c2`（本轮 adoption 19 项中 18 项合入后；A13 为收尾项）
- 执行环境：云端 Linux 机器（无 Docker、无 PostgreSQL、无 IMAP 测试服务）。本机可跑门禁全部实跑；后端完整 PostgreSQL 套件与全栈 E2E 依赖 OrbStack + 专用测试容器，本机不可复跑，见文末「未复跑项」。
- 对照基线：采纳前 main `c5cb8905` 同口径实跑（后端 unit 全量），用于失败归属判定。

## 实跑结果

| 门禁 | 命令 | 结果 |
|---|---|---|
| 模板契约 | `pytest .repo_template/tests -q -m contract` | 257 passed，1 skipped |
| 敏感扫描（已跟踪树） | `python3 scripts/check_doc_sensitive.py docs --check`（干净 worktree 内运行） | 583 个文件（`f3c339c2` 时点），0 违规，PASSED；本证据文件入库后树内文件数为 584，复扫仍 0 违规 |
| 前端单测 | `(cd src/frontend && npm test)` | 54 个文件，583 passed，0 failed |
| 前端类型 | `npx tsc -b` | 通过（exit 0） |
| 前端构建 | `npm run build` | 通过 |
| 前端 lint | `npm run lint` | 0 warnings，0 errors |
| 黑盒 E2E（stubApi） | `npm --prefix src/frontend run test:e2e` | 21 passed |
| 桌面单测 | `(cd src/desktop && npm test)` | 12 个测试文件中 10 个通过；`oauth_integration.test.js` 按设计 skip（未设置测试凭据环境变量）；`postgresManager.test.js` 的真实启停段 skip（无 PG 二进制）；`clipboard.test.js` 本机无法运行：本克隆未安装 electron 依赖（`node_modules/electron` 缺失），属环境缺口 |
| 后端 unit 全量 | `scripts/run-mail-core-tests.sh unit` | 1632 passed，8 failed，534 skipped |

## 后端 unit 失败归属（与基线 `c5cb8905` 全量对照：1731 passed，6 failed，397 skipped）

两边共同失败（采纳前即存在，非本轮引入）：

- `test_account_credentials_unit.py::test_create_and_update_and_delete_account_passes_session_to_credential_store`（单独跑通过、全量套件上下文失败，两基线一致）
- `test_accounts_api_unit.py::test_create_account_serializes_slotted_dto_mock`
- `test_medium_providers_sync_blobs.py::test_build_provider_imap_json_credentials_unpack`

`f3c339c2` 侧独有失败，逐项定性：

- `test_check_doc_sensitive.py::test_repo_docs_gate_passes`：主克隆工作区存在未跟踪残留目录 `docs/reviews/review_20261021_011607/`、`docs/reviews/review_20261021_064335/`（含 7 处扫描命中），干净已跟踪树复扫 583 文件 0 违规（见上表）。残留清理未获授权，未动。
- `test_backup_package.py::test_restored_blob_store_can_be_written_and_backed_up_again`：同代码单独跑与文件级跑均通过，属全量套件上下文失败。
- `test_blob_permissions.py` 3 条（tightens_tree / cli_reports_summary / can_chown）：权限语义在本机 root 沙箱下失真，失败子集随运行上下文变化；基线全量跑失败的是同文件另一条（refuses_unreadable_subtree）。属环境敏感，非采纳回归。

基线侧独有失败（`f3c339c2` 已不失败）：`test_system_health.py::test_system_health_metrics_calculation`、`test_a160_drill_allowed_roots.py::test_a160_repo_internal_docs_path_is_refused`（后者在 /tmp worktree 路径下运行，路径语义受执行位置影响）。

passed/skipped 结构变化（1731→1632 passed、397→534 skipped）：对照区间 `c5cb8905..f3c339c2` 内的 PG 化工作整体所致——既包括区间前段用户侧的 pg-only 修复批（如 `957acb90` baseline 工具链 PostgreSQL-only 化及三个 pg-only 集成 merge），也包括本轮采纳 A1/A2/A16 的 SQLite 分支删除与 PG 门控新增；相关用例在 unit 模式下由 passed 转为 skipped，方向与各组独立审阅结论一致。此 delta 不应单独归因于本轮采纳。

## 与 handoff 既有声称的对齐核查

- 模板契约 257 passed / 1 skipped：本机复跑一致。
- 敏感扫描「581 文件 0 违规」：违规结论一致；文件数现为 583（采纳期间文档新增 2 个），handoff 原数字为其记录时点口径。
- 前端 lint 零警告、`npm test`、`tsc -b`、build 通过：本机复跑一致（前端单测现为 583 条）。
- 桌面 `npm test` 通过：本机因 electron 依赖未安装仅 10/12 文件可跑（见上），未能全量复现。
- 前端 stubApi E2E 21 passed：本机复跑一致。

## 未复跑项（环境验证债）

- 后端完整 PostgreSQL 套件（`scripts/run-mail-core-tests.sh run`）：handoff 记录为用户侧 OrbStack 实测 2142 passed、2 skipped；本机无 Docker/PG 不可复跑，该数字仍无本机证据，须在用户 OrbStack 机器上以本基线 `f3c339c2` 复跑后回填本表。
- 全栈 E2E（`python3 scripts/run_full_stack_e2e.py`）：同上，依赖真实 PG/IMAP，本机未跑。
- A13 决策要求的「真实 PG 复跑全量门禁并登记」因此在本机只完成可跑部分；PG 部分保留为待补项，不以 unit 模式数字替代。
