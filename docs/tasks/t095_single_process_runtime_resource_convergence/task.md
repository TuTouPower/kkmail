# Task spec

## 背景

生产 Docker 全栈审计（2026-11-28）：三容器常驻 ~624 MiB（`worker` 312 MiB RSS + 33 MiB Swap/23 线程、`pg` 213 MiB/29 进程、`api` 98 MiB/8 线程），空闲合计 ~8.4% CPU，累计 232,762 次事务 `ROLLBACK`；worker 日志每数秒刷出同一批异常账号各文件夹 `patrol probe failed`，每探一个失败目录即 `UPDATE folder_patrol_status` 写盘。

核实结论（2026-11-28）：病根不是配置值偏大，而是权威状态机被旁路路径架空。全局已存在按 endpoint 的熔断 `EndpointBulkhead`（`src/mail_core/net/bulkhead.py:45`）与账号级 `ConnectivityState.UNREACHABLE`（`src/mail_core/mail/domain/enums.py:44`），但 `patrol.py:196` 自造局部 `provider_errors`，且仅在 factory 构建失败时写入，`probe_folder_status` 异常（`patrol.py:221-233`）根本不写——同一账号每个失败目录继续逐个建连碰壁并逐行写盘。IDLE 采用「每账号一个 `threading.Thread`」模型（`idle_watcher.py:262,477`），32 配额下的 glibc arena 碎片高水位靠 `MALLOC_ARENA_MAX` 缓解而非根除。`/ready`（`api/app.py:210-245`）每次打开两个 ORM 只读 Session，关闭即 `ROLLBACK`。默认 `--profile distributed` 把多机扩展能力强加给单机主场景（`docker-compose.mail-core.yml:137`）。

按开发铁律（架构至上、拒绝妥协、零兼容性负担）：调 `idle_quota`、`MALLOC_ARENA_MAX`、healthcheck interval 均属症状修补。必须收敛为单进程默认编排、统一并发预算源、事件驱动 IDLE、全局熔断门禁与解耦探针，彻底删除旁路实现。

## 契约区

### 范围

- **单机默认编排收敛**：默认以 `MAIL_CORE_EMBEDDED_WORKER=1` 单进程嵌入式运行，仅一个 Python 业务容器；`--profile distributed` 降为可选，仅面向多机/高吞吐扩展；迁移与启动路径适配单进程。
- **统一并发预算与 PG 调优**：建立单一并发预算配置源，由其派生 DB 连接池（`db/session.py:72-73` 当前 `pool_size=10/max_overflow=10`）、IDLE 配额与 worker 槽位；针对单机负载调 PG 参数（`shared_buffers`、`work_mem`、`max_connections`、`checkpoint_timeout`），对心跳/后台同步写事务用 `SET LOCAL synchronous_commit=off` 消除刷盘抖动。
- **IDLE 并发模型根因重构**：将 `idle_watcher` 从「每账号一个阻塞线程」改为事件驱动或多路复用模型，使线程数与账号数解耦，从根消除大体积 MIME 解析下的 glibc arena 碎片；不以 `MALLOC_ARENA_MAX` 作为产品级方案。
- **熔断状态机统一**：删除 `patrol.py:196` 局部 `provider_errors`；所有 provider 网络调用统一经 `EndpointBulkhead.raise_if_open` 与 `Account.connectivity_state` 门禁；账号级传输/认证故障直接写全局连通性状态，短路同账号剩余目录并纳入退避冷却；`UNREACHABLE` 账号在冷却窗口内零建连、零写盘。
- **探针与业务读解耦**：`/ready` 移除 ORM Session，改轻量 `AUTOCOMMIT` 查询并短 TTL 内存缓存；存活性探针改由常驻心跳线程原子刷新 tmpfs 本地戳文件，探针仅校验新近度、不冷启解释器查库；postgres/api/worker 三类 healthcheck.interval 统一放宽。
- **测试与文档**：覆盖上述行为的单元/集成/compose 静态解析测试；更新 spec 与 blueprint；因旧模型失效的测试按规范重写并注明理由，不就地篡改正确语义断言。

### 非范围

- 不开发多机分布式吞吐扩展功能，distributed 仅保留为可选 profile。
- 不改 IMAP IDLE 协议交互语义、`ConnectivityState` 枚举定义或账号级三维健康状态机。
- 不执行生产环境部署或线上参数变更。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：默认 `docker compose config` 解析结果中只有一个 Python 业务容器且启用嵌入式 worker；distributed 模式下 api 与 worker 分离仅在显式 profile 下生效。
- [ ] AC-002：连接池、IDLE 配额与 worker 槽位由单一并发预算配置源派生，不存在三处独立默认值各自漂移；单进程运行态下 PostgreSQL idle 后端数收敛至个位数，且不再出现 `idle in transaction` 归还前暂留。
- [ ] AC-003：IDLE watcher 线程数不再随账号数线性增长；构造多账号大体积 MIME 解析负载时，worker 匿名页高水位不随账号数线性增长，且产品代码中不以 `MALLOC_ARENA_MAX` 作为内存收敛手段。
- [ ] AC-004：`patrol.py` 不存在局部熔断字典；`UNREACHABLE` 账号在退避窗口内对其全部目录零网络建连、零 `folder_patrol_status` 写盘；探测失败自动写入全局连通性状态并短路同账号剩余目录，退避结束后按半开探测恢复。
- [ ] AC-005：`/ready` 不打开任何 ORM Session、不向 PostgreSQL 发送 `ROLLBACK`；存活性探针只读本地心跳戳、不冷启 Python 解释器；postgres/api/worker 三类 healthcheck.interval 统一为 30s。
- [ ] AC-006：全量门禁（后端 PostgreSQL 测试、前端构建与单测、桌面端测试、E2E、模板门禁）通过；更新 `docs/specs/mail_sync_and_storage.md` 与对应 blueprint/决策记录。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 通过 `docker compose config` 静态解析验证；AC-002 通过配置派生单测与真实 PostgreSQL 连接数观测验证；AC-003 通过线程枚举测试与负载下 RSS 相对增长断言验证；AC-004 通过 IMAP stub 与真实 PostgreSQL 集成测试验证；AC-005 通过 `/ready` 请求期间 SQL 日志断言与探针脚本行为测试验证；AC-006 通过全量门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p103（2026-11-28 核实并转办；生产审计 624 MiB 常驻、232,762 次 ROLLBACK、patrol 局部 `provider_errors` 与全局 `EndpointBulkhead`/`ConnectivityState` 并存；核实修正：`idle_quota=32`、`pool_size=10/max_overflow=10`、7 类 healthcheck 命令均仍在代码中）

### 有意不测

- 生产 624 MiB / 8.4% CPU 绝对值不进 CI，改用可断言的相对指标（容器数、线程数、idle 后端数、`ROLLBACK` 次数、失败账号探测次数与写盘次数）。
- 真实外网 IMAP 故障账号不接入测试，改用 IMAP stub 模拟认证/传输级失败与恢复。

### 测试策略

- 编排与配置：`docker compose config` 断言默认单进程、profile 分离；配置派生单测断言连接池/配额/槽位同源；集成环境观测 PG idle 后端数与事务状态。
- IDLE 模型：枚举活动线程并断言账号数增长不导致线程数线性增长；构造大体积 MIME 解析负载断言 RSS 相对增长受控。
- 熔断统一：IMAP stub 对同一账号多目录返回认证失败，断言只建连一次、只写一次全局状态、其余目录零探测零写盘；冷却后半开探测恢复。
- 探针：`/ready` 请求期间捕获 SQL 日志断言零 `ROLLBACK`；心跳戳文件时间戳断言；healthcheck 配置解析断言统一 interval。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。熔断组件、连通性状态、线程模型、连接池默认值与探针命令均已在 2026-11-28 源码与生产审计核实。

### 风险与回退

- 风险：IDLE 模型重构影响实时收件箱延迟，须回归 t059/t061/t071 相关行为；熔断统一后若退避窗口配置不当可能过度跳过，窗口须可校准；单进程模式故障影响面大于双进程，依赖容器 restart 策略与嵌入式 worker 自恢复。
- 回退：编排与配置变更通过 revert 实现 commit 回退；IDLE 与熔断改动保留渐变开关仅用于回滚，不作为产品级兼容层；生产部署前依赖标准封存备份。

### 依赖与约束

- 依赖：无前置未合并 task，基于当前 `main`（含 t093）立项；`review_level: full`。
- 约束：遵循开发铁律删除局部熔断与 ORM 探针路径，不保留调参补丁；不改 IMAP 协议语义；PG 参数须在单机容器内可验证；不写生产数据。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新单机嵌入式默认编排、统一并发预算源与 IDLE 事件驱动模型描述。
- `docs/blueprint/domain.md`：更新 `ConnectivityState` 作为所有 provider 调用统一门禁的语义。
- `docs/blueprint/conventions.md`：确立存活性/就绪性分离与「探针不依赖业务读模型」约定。
- `docs/blueprint/decisions/20261128_single_process_runtime_and_circuit_unification.md`：记录单进程默认、IDLE 模型重构与熔断统一的架构决策。
- `docs/blueprint/testing.md`：记录 compose 静态解析、连接数与探针零 ROLLBACK 门禁覆盖要求。

______________________________________________________________________

- 关联 spec 登记：实施收尾时在 `docs/specs/mail_sync_and_storage.md` front matter `tasks` 清单追加 `t095`。
