# Task review t098（reviewer_focus: 代码）

- task：`t098_worker_launch_and_readiness_config`
- spec：`docs/tasks/t098_worker_launch_and_readiness_config/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27`
- round：1
- reviewed_at：2026-11-29T00:38:00+08:00

reviewed_scope: a3bc3f2b15788107

## Findings

无（本轮零 finding）。

## 结论

- 本轮新发现：0 条
- 未进表的提示：文件行数均未达阈值（`src/mail_core/__main__.py` 324 行、`src/mail_core/config/loader.py` 173 行、`src/mail_core/liveness.py` 76 行、`src/mail_core/readiness.py` 147 行），无复杂度 ≥15 的新函数；范围外观察一条——`src/mail_core/__main__.py:211` 的 `--no-worker` argparse default 仍自行编码了 env 规则（`default=os.environ.get("MAIL_CORE_EMBEDDED_WORKER") == "0"`，基线既有代码、本 task 未触及），其结果经 `resolve_embedded_worker(cli_no_worker=args.no_worker)` 归一后行为正确，仅属潜在重复，不构成本 task 缺陷。
- 总体判断：实现真实落地四条 AC——启动边界一处合并 CLI/env 并回写生效模式（`src/mail_core/__main__.py:252-253`、`src/mail_core/config/loader.py:49-65`，`load_config` 同源派生于 `loader.py:125`），存活戳路径与必需判定单一来源（`src/mail_core/liveness.py:20-51`，写入 `liveness.py:56`、API 校验 `src/mail_core/readiness.py:135-137`、Worker 健康检查 `src/mail_core/worker/healthcheck.py:27-28`、Worker 写入 `src/mail_core/worker/main.py:965` 全部经 `stamp_path()`），就绪缓存与失效逻辑未被本 diff 破坏（`src/mail_core/api/app.py` 每次重读 DB/schema/LISTEN、失败与 LISTEN 断开均 `invalidate()`）；安全/契约/性能/健壮性视角均已扫过，无外部输入拼接、无凭证落日志、无公开签名破坏（新增函数均为内部配置解析，配置键语义不变）。reviewer 独立复跑 t098+t096+a294+api_health 套件 34 passed。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`__main__.py:252-253` 启动边界以 `resolve_embedded_worker` 合并 CLI/env 并回写 `MAIL_CORE_EMBEDDED_WORKER`，线程启动改判 `embedded_worker`（`__main__.py:289`）；`readiness.py:135` 探针以同一 resolver + `stamp_required` 判定，env=0/CLI 等价且不读残留默认戳，复跑测试通过。
- AC-002：TICK-VALID，re_verified。`readiness.py:135-146` 必需戳缺失/损坏（`read_liveness_stamp` 返回非 dict）或 mtime 陈旧均置 `active=False`，DB 心跳新鲜度独立判定在同函数前段，过期心跳仍 False；503 路径由 `/ready` 强制门禁既有逻辑承接。
- AC-003：TICK-VALID，re_verified。`liveness.py:26-40` 单一优先级（显式 > 数据目录 > 进程默认），`write_liveness_stamp`/`read_liveness_stamp`/healthcheck/Worker 写入共用 `stamp_path()`，无第二套路径解析残留（全仓 grep 核实）。
- AC-004：TICK-VALID，re_verified。本 diff 未改缓存边界：`api/app.py` 的 `/ready` 每次重读 schema/LISTEN、失败早返回与 LISTEN 断开均调用 `invalidate()`，Worker 派生信号仅经 `cached_worker_active()` 短 TTL 复用，`listener.py:24` 断开失效保持不变，回归测试通过。

coverage = 4 / 4

verdict: PASS

## Round 2 (2026-11-29T00:40:22+08:00)

reviewed_scope: 9fe75e57bc375852

## Findings

无（本轮零 finding）。

## 结论

- 前轮 finding 复核：Round 1 代码轴零 finding，无待复核项；本轮按 Round 2 prompt 全量复核（非仅看修复），未发现修复过程引入的新问题——本轮 diff 相对 Round 1 的增量仅为测试文件新增（`tests/mail_core/test_t098_worker_launch_readiness.py` 补两处用例），实现文件与 Round 1 审查内容一致。
- 本轮新发现：0 条
- 未进表的提示：文件行数仍均未达阈值（`src/mail_core/__main__.py` 324 行、`src/mail_core/config/loader.py` 173 行、`src/mail_core/liveness.py` 76 行、`src/mail_core/readiness.py` 147 行、测试文件 399 行），无复杂度 ≥15 的新函数；Round 1 的范围外观察（`src/mail_core/__main__.py:211` 的 `--no-worker` argparse default 自行编码 env 规则，基线既有、本 task 未触及，结果经 `resolve_embedded_worker` 归一后行为正确）本轮复核仍成立，维持范围外提示、不升为 finding。
- 总体判断：实现层四条 AC 仍真实落地——启动边界一处合并 CLI/env 并回写生效模式（`src/mail_core/__main__.py:252-253`，线程启动改判 `embedded_worker` 于 `__main__.py:289`），`load_config` 同源派生（`src/mail_core/config/loader.py:49-65`、`:125`），存活戳路径与必需判定单一来源（`src/mail_core/liveness.py:20-51`；写入 `liveness.py:56`、读取 `liveness.py:72`、API 校验 `src/mail_core/readiness.py:135-137`、Worker 健康检查 `src/mail_core/worker/healthcheck.py:27-28`、Worker 写入 `src/mail_core/worker/main.py:965` 全部经 `stamp_path()`，本轮全仓 grep 复核无第二套解析），就绪缓存边界未被破坏；安全/正确性/契约·Breaking/性能·资源/架构·可维护性/健壮性·可观测各视角均已扫过，无外部输入拼接、无凭证落日志、无吞错、无公开签名破坏。reviewer 独立复跑 t098+t096+a294+api_health 套件 35 passed（较 Round 1 多 1 条，为 test 轴 f002 修复新增的端到端直测）。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`__main__.py:252-253` 启动边界以 `resolve_embedded_worker` 合并 CLI/env 并回写 `MAIL_CORE_EMBEDDED_WORKER`，探针 `readiness.py:135` 以同一 resolver + `stamp_required` 判定，env=0 与 CLI `--no-worker` 等价且不读残留默认戳，本轮复跑含新增端到端直测在内的套件通过。
- AC-002：TICK-VALID，re_verified。`readiness.py:135-146` 必需戳缺失/损坏（`read_liveness_stamp` 返回非 dict）或 mtime 陈旧均置 `active=False`，不可读态经 `liveness.py:71-76` 的 `OSError → None` 与 `readiness.py` 的 `stat()` `OSError` 分支双路收敛为未就绪；DB 心跳过期独立判定仍 False，503 路径由 `/ready` 强制门禁既有逻辑承接。
- AC-003：TICK-VALID，re_verified。`liveness.py:26-40` 单一优先级（显式 > 数据目录 > 进程默认），`write_liveness_stamp`/`read_liveness_stamp`/healthcheck/Worker 写入共用 `stamp_path()`，本轮全仓 grep 复核无第二套路径解析残留。
- AC-004：TICK-VALID，re_verified。本 diff 未改缓存边界：`/ready` 每次重读 DB/schema/LISTEN、失败与 LISTEN 断开均 `invalidate()`，Worker 派生信号仅经短 TTL 缓存复用，本轮回归测试通过。

coverage = 4 / 4

verdict: PASS
