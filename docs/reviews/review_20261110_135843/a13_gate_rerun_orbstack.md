# A13 全量门禁复跑证据（本机 OrbStack 真实 PostgreSQL，2026-11-11）

- 复跑时间：2026-11-11（Asia/Shanghai）
- 代码基线：main `adf93f62`（`f3c339c2` 之后；review_20261110_135843 adoption 与本轮本地审阅修复全部合入后的 main 树）
- 执行环境：本机 macOS + OrbStack (arm64)。专用测试 PostgreSQL 16.15 绑定 `127.0.0.1:15433`、Dovecot IMAP 绑定 `127.0.0.1:1143`；业务 Compose（5433）与业务卷未触碰，测试密码由本机 `.env.test` 提供、未入库
- 口径：`docs/blueprint/testing.md` 的 `test_cmd`、`blackbox_verify`、「本地分层门禁矩阵」、全栈端到端测试，以及 `## doctor_cmd` 的前置项。后端全量为 `scripts/run-mail-core-tests.sh run`（带覆盖率、真实 PG、每轮独立 owned 库 + Alembic upgrade head）
- 对照：`a13_gate_rerun.md` 是云端机器（无 Docker/PG）的复跑证据，其文末「未复跑项（环境验证债）」由本文件结清

## 实跑结果（全部真实执行，未沿用历史记录）

|门禁|命令|结果|
|---|---|---|
|后端完整 PostgreSQL 套件|`scripts/run-mail-core-tests.sh run`|**2172 passed，1 failed，2 skipped**（收集 2175；1936.50s / 32:16；覆盖率 86%，17440 语句 / 5736 分支）。专用 IMAP 服务启动后 `test_imap_protocol_suite.py` 4 例由 ConnectionRefused 转为通过|
|模板契约|`pytest .repo_template/tests -q -m contract`|257 passed，1 skipped（4.54s）|
|敏感文档扫描（已跟踪树）|`python3 scripts/check_doc_sensitive.py docs --check`|584 文件 0 违规（本证据文件入库后为 585，复扫仍 0 违规）|
|前端单测|`npm test`（src/frontend）|54 个文件，583 passed，0 failed|
|前端类型 / 构建 / lint|`npx tsc -b`、`npm run build`、`npm run lint`|`tsc -b` 通过、build 产出真实 dist（vite 8.3.4）、oxlint `--deny-warnings` 0 warnings|
|OpenAPI 双向|`export_openapi.py --check`、`npm run openapi:check`|后端 46 paths 一致；前端生成 schema.ts 一致|
|桌面单测|`npm test`（src/desktop）|12 个 node 测试文件逐项带 120s 超时实测：11 项 rc=0（含 `postgresManager.test.js` 真实启停 ok、`oauth_integration.test.js` 按设计 SKIP）；详见下节|
|黑盒 E2E（stubApi）|`npm --prefix src/frontend run test:e2e`|21 passed（55.9s）|
|全栈端到端 E2E|`python3 scripts/run_full_stack_e2e.py`|8 passed（24.6s），真实 FastAPI + PG + Worker + 生产 SPA + Playwright，测试库用后清理|

## 1 个失败（如实登记，不冒充全绿）

`tests/scripts/test_check_dep_locks.py::test_check_dep_locks_script_passes`：`check_dep_locks.py --check` 报 `requirements-mail-core.lock` 与 `requirements-mail-core.txt` 不同步。只读比对（`uv pip compile ... --universal --python-version 3.13 --generate-hashes` 生成临时 lock 后 diff）显示差异仅 36 行，全部是 uv 上游解析漂移：`annotated-doc` 0.0.5→0.0.6、`fastapi` 0.162.2→0.162.4 及注释行。该失败在采纳前基线 `040b4003` 上即存在，非本轮 adoption 或本轮修复引入；重新生成 lock 会顺带升级生产依赖（与本任务无关），故未修，按「不许冒充全绿」如实登记。其余 2172 个后端用例全部通过。

## 2 个 skip（环境/设计，按口径单独报告）

- `tests/mail_core/test_backup_restore_cross_volume.py:207`：`/dev/shm` 在本机不可写
- `tests/mail_core/test_microsoft_oauth.py:303`：需 owned PG + 生产 SPA + 显式 Electron 集成模式

## 桌面单测的挂起项（超时类，暂时不管、如实登记）

`clipboard.test.js` 逐项运行时已打印 `desktop clipboard integration: ok`（含权限拒绝、Media 权限、桌面日志等断言），但 Electron 子进程未退出，导致进程在 120s 超时后仍挂起；整条串行 `npm test` 因此无法以单命令正常收尾。11 个可正常退出的文件均 rc=0，`oauth_integration.test.js` 输出 `SKIP Electron OAuth integration: set KKMAIL_OAUTH_TEST_ORIGIN and KKMAIL_OAUTH_TEST_PASSWORD`（设计内跳过）。按补充指示，超时类 flaky 暂时不管、如实登记，不掩盖其余 11 项真实通过。

## 与 handoff 旧声称的对齐

`docs/handoff.md`「验证」段记录的「2142 passed, 2 skipped, 0 failed」及「581 文件」等数字是上一轮 A1–A22 时点的声称、仓库内无留存证据。本机本次真实复跑为 2172 passed / 1 failed / 2 skipped（不同基线、不同时点、含 IMAP 真实协议用例），敏感扫描为 584 文件（含后续文档增长）。不一致处据实在 `docs/blueprint/testing.md` 结果表与本文件并列登记，不回改历史记录。

## 证据产物

后端全量 run_uuid `e605c590c0784910b325d75f62ee1c2f`：每轮 `junit.xml`、`coverage.xml`、`coverage.json`、`test_summary.json`、ownership 记录由门禁脚本保留在 `.scratch/test_runs/<UUID>/`（gitignored 运行数据，不入库）。定向 PG 套件在本轮修复后另跑一次为 76 passed / 0 failed（71.11s），用于逐项验证 A16/A14/A1 修复。
