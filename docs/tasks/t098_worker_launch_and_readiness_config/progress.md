---
tid: "t098"
slug: "worker_launch_and_readiness_config"
title: "统一 Worker 启动模式与就绪配置"
status: "done"
branch: "t098_worker_launch_and_readiness_config"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7746212f8d96870d0b7e75fd1868c159993d1a27"
spec_source_sha: "7746212f8d96870d0b7e75fd1868c159993d1a27"
depends_on: ""
conflicts_with: ""
note: "p105: 启动入口等价、存活戳路径和就绪矩阵"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 复现（先红）：`.scratch/repro_t098.py` 以同一新鲜模拟 DB 心跳、无本地戳走生产启动与就绪入口，实测 `--no-worker` 时探针返回未就绪、`MAIL_CORE_EMBEDDED_WORKER=0` 返回就绪，与 task 背景的 `060e0893` 复现一致。
- 生效模式单一来源：`config/loader.py` 新增 `resolve_embedded_worker(source, cli_no_worker=...)`（CLI 优先、其次 env `!= "0"`），`load_config` 改用它；`__main__.py` 在启动边界（parse_args 后）合并并把生效值回写 `MAIL_CORE_EMBEDDED_WORKER`，线程启动改用生效值——只动本契约的入口调用，未触 `run_migrations`（t099 并行面）。直接 ASGI 与独立 Worker 的 env 入口不变。
- 存活戳单一规则：`liveness.py` 新增 `explicit_stamp_path()` 与 `stamp_required(embedded_worker=...)`，`stamp_path()` 保持显式 > 数据目录 > 进程默认的唯一解析；`readiness.py` 改用 `resolve_embedded_worker()` + `stamp_required()` + 同一 `stamp_path()` 做 stat，删除内联 env 解析与随之无用的 `os`/`Path` 导入。readiness 读戳保持无参调用 `read_liveness_stamp()`（其内部同样走 `stamp_path()`），以不破坏 t095 既有测试的打桩接缝；行为等价。
- 测试：新增 `tests/mail_core/test_t098_worker_launch_readiness.py`（14 项：解析矩阵、真实 `main()` 入口三态、/ready 200/503 与 CLI 端到端、显式戳缺失/损坏/不可读/陈旧矩阵、路径优先级与隔离、healthcheck 同规则、TTL/invalidate 与失败/LISTEN 恢复重读）；清理 `test_t096_fixes_unit.py` 未用 `SimpleNamespace` 导入。首轮全量 unit 扫出 t095 finding7 测试因打桩签名（0 参 lambda）失败，定性为接缝兼容问题后按上条调整恢复，未改旧测试预期。
- 云端环境边界：无 Docker，`scripts/test_pg_runtime.py` 的 guard 强制 owned Docker 容器身份，便携 PG 16.2 二进制（`~/workspace/.pg-runtime`）无法合规替代，PG 全量套件与双 Compose 配置检查未跑，登记 p107 待 Docker 主机复验。基线对照（未改动 main 同命令）：后端 unit 3 条失败（blob_permissions/system_health/t093 public surface）、模板契约 30 条失败、桌面 electron 缺失失败，均为云端环境既存，与本 task 无关。
- finish 首跑被 review_test.md 的 Markdown 格式漂移拦下，已用 `md_format.py --changed` 机械规范化（Round 2 小节 2 行列表缩进，语义不变）；`task.py review-status` 复核 overall=PASS、review_scope=ok、next_action=finalize，确认该格式化不改变交付指纹、Round 2 结论仍有效。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-29T00:37:39+08:00)

code review PASS 零 finding；test review PASS，2 条 minor。AC-001..AC-004 两轴 TICK-VALID（reviewed_scope: a3bc3f2b15788107）。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t098_test_f001|minor|已修|AC-002「不可读」戳原仅经缺失态 OSError 分支间接覆盖，现补目录占位致读失败的独立断言|tests/mail_core/test_t098_worker_launch_readiness.py（test_ac002_explicit_stamp_gates_readiness_in_standalone_mode）|
|t098_test_f002|minor|已修|AC-001 的 /ready 200 原仅直测 env 模式，现补真实 `--no-worker` 进程入口启动后直查 /ready 的端到端用例|tests/mail_core/test_t098_worker_launch_readiness.py（test_ac001_ready_200_end_to_end_after_cli_no_worker_launch）|

两条修复均为测试新增、无实现改动；修复后相关集合复跑 38 passed / 4 skipped。因交付内容在 review 后变更，按规矩派 Round 2 复审确认新指纹。code 报告另有一条未进表提示：`__main__.py` 的 `--no-worker` argparse default 仍自行编码 env 规则（基线既有、经 resolver 归一后行为正确），reviewer 明示不构成缺陷，本 task 不扩大范围处理。

### Round 2 (2026-11-29T00:40:49+08:00)

Round 2 零 finding。code 与 test 两轴均 PASS（reviewed_scope: 9fe75e57bc375852）；t098_test_f001 / t098_test_f002 经 diff 复核确认已闭环；AC-001..AC-004 全部 TICK-VALID（coverage 4/4）。reviewer 独立复跑相关集合 35 passed。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（PG 侧复跑与双 Compose 配置检查因云端无 Docker 未执行，登记 p107，不涉及 AC 打勾）
- 测试：flock 串行全量门禁（2026-11-29）：后端 unit 全量 1775 passed / 3 failed / 646 skipped，3 条失败与未改动 main 基线逐条一致（test_blob_permissions、test_system_health、test_t093 public surface，云端环境既存）；t098 新增 13 项与 t095/t096/a294/api_health 相关集合 45 passed / 4 skipped（PG 门控跳过）；模板契约（Python 3.14 venv）359 passed / 30 failed / 1 skipped，与 main 基线数字完全一致；前端 npm test 56 文件 599 passed、tsc -b 与生产 build 均 exit 0；桌面 npm test 因 electron 未安装失败（main 基线同）；敏感文档扫描 38 文件 0 违规；doctor collect 390 项可收集、md_kx 在位
- 黑盒：`npm --prefix src/frontend run test:e2e`（stubApi 快速 E2E）26 passed
- review：full 级两轮。Round 1（2026-11-29T00:37:39+08:00）code PASS 零 finding、test PASS 2 条 minor（t098_test_f001/f002），均已修；Round 2（2026-11-29T00:40:49+08:00）双轴 PASS 零 finding，两条 minor 确认闭环，AC-001..AC-004 全部 TICK-VALID，reviewed_scope: 9fe75e57bc375852
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 生效 Worker 模式收敛到 `resolve_embedded_worker()` 单一裁决并在启动边界回写环境，CLI `--no-worker` 与 `MAIL_CORE_EMBEDDED_WORKER=0` 对线程启动与 `/ready` 探针完全等价；存活戳路径与必需判定收敛到 `liveness.stamp_path()` / `stamp_required()`，Worker 写入、API 校验、健康检查共用。
- 遗留：p107（PG 全量套件与双 Compose 配置在 Docker 主机复验）。

### 长期文档闭环

- specs_index: `docs/specs/mail_sync_and_storage.md` front matter `tasks` 已登记 t098。
- blueprint：`docs/blueprint/conventions.md` 第十四节新增第 6 条（生效模式与存活戳路径单一来源）并修正第 2 条模式表述；`docs/blueprint/testing.md` 门禁覆盖清单新增 t098 就绪矩阵行。
