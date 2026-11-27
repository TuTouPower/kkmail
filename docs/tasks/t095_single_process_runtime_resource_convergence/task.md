# Task spec

## 背景

生产 Docker 全栈审计（2026-11-28）：三容器常驻 ~624 MiB（`worker` 312 MiB RSS + 33 MiB Swap/23 线程、`pg` 213 MiB/29 进程、`api` 98 MiB/8 线程），空闲合计 ~8.4% CPU，累计 232,762 次事务 `ROLLBACK`；worker 日志每数秒刷出同一批异常账号各文件夹 `patrol probe failed`，每探一个失败目录即 `UPDATE folder_patrol_status` 写盘。

核实结论（2026-11-28）：病根不是配置值偏大，而是权威状态机被旁路路径架空。全局已存在按 endpoint 的熔断 `EndpointBulkhead`（`src/mail_core/net/bulkhead.py:45`）与账号级 `ConnectivityState.UNREACHABLE`（`src/mail_core/mail/domain/enums.py:44`），但 `patrol.py:196` 自造局部 `provider_errors`，且仅在 factory 构建失败时写入，`probe_folder_status` 异常（`patrol.py:221-233`）根本不写——同一账号每个失败目录继续逐个建连碰壁并逐行写盘。IDLE 采用「每账号一个 watcher 线程，会话内另有 reader 线程」模型（`idle_watcher.py:262,477,524-568`、`providers/imap.py:109-139`），32 配额下的 glibc arena 碎片高水位靠 `MALLOC_ARENA_MAX` 缓解而非根除。`/ready`（`api/app.py:210-254`）每次打开 ORM 只读 Session，关闭即 `ROLLBACK`。默认 `--profile distributed` 把多机扩展能力强加给单机主场景（`docker-compose.mail-core.yml:137`）。

2026-11-28 静态规格审阅（基线 67735d62）指出原规格六处缺口：巡检健康隔离与既有状态维度冲突、异步提交缺耐久性承诺、部署模式互斥与部署入口遗漏、探针可假阳性通过、IDLE 漏计真实 reader 且内存基准缺失、连接预算边界缺失。本规格逐条裁决并收口。

按开发铁律（架构至上、拒绝妥协、零兼容性负担）：调 `idle_quota`、`MALLOC_ARENA_MAX`、healthcheck interval 均属症状修补。必须收敛为单进程默认编排、统一并发预算源、事件驱动 IDLE、账号级健康门禁与解耦探针，彻底删除旁路实现。

## 契约区

### 范围

- **单机默认编排收敛**：
    - 默认以 `MAIL_CORE_EMBEDDED_WORKER=1` 单进程嵌入式运行，仅一个 Python 业务容器；`--profile distributed` 降为可选，仅面向多机/高吞吐扩展。
    - 给出嵌入式与分布式两种模式的确切启动、迁移与升级命令，纳入部署脚本与部署文档；两种模式互斥，禁止同时启用内嵌 Worker 与独立 Worker，禁止宿主端口冲突；Compose 调用显式指定 `-f`。
    - 覆盖已有库从 distributed 切换为嵌入模式的升级路径：旧容器退场、数据卷沿用、迁移先于业务写入。
- **统一并发预算**：
    - 建立单一并发预算配置源，由其派生 DB 连接池（`db/session.py:72-73` 当前 `pool_size=10/max_overflow=10`）、IDLE 配额与 worker 槽位；预算须为 API、后台、维护任务及 Outbox/Job LISTEN 直连分别预留，给出客户端连接上限。
    - 明确网络等待期不持有 DB 事务，或给出「无超过规定时长的空闲事务」可观察边界；规定负载下验证池等待与超时，避免把连接压力转成 API 等待或 Worker 心跳超时。
- **IDLE 并发模型根因重构**：
    - 将 `idle_watcher` 从「每账号一个阻塞 watcher 线程 + 会话内 reader 线程」改为事件驱动或多路复用模型，使线程数与账号数解耦；验收须计入两类真实线程，不以替身绕过 reader。
    - 覆盖慢连接不阻塞其他账号、续期、断线补拉、取消与轮询兜底；不以 `MALLOC_ARENA_MAX` 作为产品级方案。
    - 内存验收规定 Linux 容器、并发槽位、账号与邮件样本、预热流程、匿名页口径与相对阈值；归档链路的高水位作为单独可证伪假设，不由 IDLE 重构间接推断。
- **巡检健康门禁统一（裁决）**：
    - 保留 t090 的后台传输失败隔离语义，不改其归属；巡检另建账号级短路：同一账号首个传输/认证级失败写全局健康状态并跳过本轮剩余目录，跨轮冷却由账号级健康状态持有，半开由单一恢复探测发起者执行，避免并发半开。
    - 永久认证失败走凭据状态（需用户修复），不作为链路恢复的半开成功用例；临时传输故障走连通性降级与退避；单目录错误只影响该目录、不短路账号；限流/容量错误不标记账号不可达，仅放慢轮转。
    - 明确前台立即同步、已持有 IDLE 连接与共享端点行为：前台同步不受巡检退避阻断；IDLE 连接失败走既有断线补拉；共享端点上其他账号不受单账号认证失败牵连。
    - 删除 `patrol.py:196` 局部字典；`recheck_unreachable` 须发起真实探测或明确由恢复探测发起者承担，不得仅降级状态而不探测。
- **探针与业务读解耦**：
    - 分别定义 API、Worker、PG 的存活与就绪信号，心跳须由实际组件进度推进：Worker 心跳由主循环推进，主循环退出或停滞时戳过期；API 未监听时不得判定为健康。
    - `/ready` 移除 ORM Session，保留现有 DB、schema head、LISTEN 及有效 Worker 校验，改轻量 `AUTOCOMMIT` 查询并短 TTL 内存缓存，定义缓存上限与失效行为（DB/LISTEN 断开立即失效）；存活性探针改由常驻心跳线程原子刷新 tmpfs 本地戳文件，探针仅校验新近度、不冷启解释器查库。
    - 明确故障由谁重启；postgres/api/worker 三类 healthcheck.interval 统一放宽。
- **提交耐久性与 PG 调参（裁决）**：
    - 只有独立心跳等可丢弃状态允许异步提交；邮件入库、checkpoint、Outbox、同步请求结算及带远端副作用的业务事务保持同步提交，保证崩溃后不丢已答复结果。
    - 单独定义 PG 调参要改善的指标（检查点耗时、刷盘抖动）与验证负载，不以 `synchronous_commit=off` 代替检查点调优。
- **测试与文档**：覆盖上述行为的单元/集成/compose 隔离环境测试；更新 spec 与 blueprint；因旧模型失效的测试按规范重写并注明理由，不就地篡改正确语义断言。

### 非范围

- 不开发多机分布式吞吐扩展功能，distributed 仅保留为可选 profile。
- 不改 IMAP IDLE 协议交互语义、`ConnectivityState` 枚举定义或账号级三维健康状态机；不改 t090 后台传输失败隔离归属（属 t094 写域边界的协调项）。
- 不把业务事务改为异步提交。
- 不执行生产环境部署或线上参数变更。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：嵌入式与分布式两种模式有确切启动/迁移/升级命令并纳入部署脚本与文档；隔离 Compose 环境验证两种模式分别启动、迁移先于业务写入、仅一套 Worker 执行拓扑、无宿主端口冲突、`/ready` 可用；已有库从 distributed 切为嵌入模式时旧容器退场且数据卷沿用。
- [ ] AC-002：连接池、IDLE 配额与 worker 槽位由单一并发预算源派生，并为 API、后台、维护与 LISTEN 直连预留，给出客户端连接上限；规定负载下池等待与超时可观测且无 API 等待或心跳超时退化；网络等待期不持有 DB 事务，或无超过规定时长的空闲事务。
- [ ] AC-003：IDLE 验收计入 watcher 与 reader 两类真实线程，账号数增长不导致线程数线性增长；多账号 IMAP stub 下慢连接不阻塞其他账号，续期、断线补拉、取消与轮询兜底均通过；内存验收按约定 Linux 容器、槽位、样本、预热与匿名页口径测得相对阈值内，归档高水位作为单独断言；产品代码不以 `MALLOC_ARENA_MAX` 作为内存收敛手段。
- [ ] AC-004：`patrol.py` 不存在局部熔断字典；首个账号级传输/认证失败写全局健康状态并跳过本轮剩余目录，跨轮冷却由账号级状态持有、半开单一持有者执行；临时传输故障、永久认证失败、单目录错误、限流与并发半开分别验证且互不混淆；前台同步、已持有 IDLE 连接与共享端点上其他账号行为符合约定；`recheck_unreachable` 发起真实探测或由明确持有者承担。
- [ ] AC-005：API、Worker、PG 各有存活与就绪信号，Worker 主循环退出/停滞或 API 未监听时判定为不健康；`/ready` 保留 DB、schema head、LISTEN 与有效 Worker 校验但不打开 ORM Session、不发送 `ROLLBACK`，缓存上限与失效行为明确（DB/LISTEN 断开立即失效）；运行态覆盖启动未完成、断开与恢复、主循环停滞、旧戳及缓存过期，故障重启责任明确；healthcheck.interval 统一为 30s。
- [ ] AC-006：仅独立心跳允许异步提交；邮件、checkpoint、Outbox、同步请求结算与带远端副作用的业务事务保持同步提交；崩溃恢复测试证明已答复结果不丢，心跳丢失可重建；PG 调参的检查点耗时与刷盘抖动指标及验证负载单独定义并通过。
- [ ] AC-007：项目全量门禁（后端 PostgreSQL 测试、前端构建与单测、桌面端测试、E2E、模板门禁）通过；更新 `docs/specs/mail_sync_and_storage.md` 与对应 blueprint/决策记录。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 通过隔离 Compose 环境的 `docker compose config` 静态解析与实际启动、迁移顺序、拓扑、`/ready` 及模式切换验证；AC-002 通过配置派生单测与规定负载下的 PostgreSQL 连接/事务状态观测验证；AC-003 通过多账号 IMAP stub 的线程枚举、行为用例与 Linux 容器受控内存基准验证；AC-004 通过 IMAP stub 构造五类故障与真实 PostgreSQL 集成测试验证；AC-005 通过运行态故障注入、`/ready` SQL 日志断言与探针行为测试验证；AC-006 通过崩溃恢复测试与检查点指标负载测试验证；AC-007 通过全量门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p103（2026-11-28 核实并转办；生产审计 624 MiB 常驻、232,762 次 ROLLBACK、patrol 局部 `provider_errors` 与全局 `EndpointBulkhead`/`ConnectivityState` 并存；核实修正：`idle_quota=32`、`pool_size=10/max_overflow=10`、healthcheck 命令均仍在代码中）；2026-11-28 静态规格审阅意见（基线 67735d62）逐条裁决六处缺口。

### 有意不测

- 生产 624 MiB / 8.4% CPU 绝对值不进 CI，改用受控基准的相对指标（容器数、线程数、idle 后端数、`ROLLBACK` 次数、失败账号探测与写盘次数）。
- 真实外网 IMAP 故障账号不接入测试，改用 IMAP stub 模拟传输/认证级失败、限流与恢复。
- 凭据真实修复流程不纳入半开用例，避免与链路恢复混淆。

### 测试策略

- 编排与配置：隔离 Compose 环境分别启动两种模式，断言迁移先于写入、仅一套 Worker 拓扑、端口无冲突、`/ready` 可用；从 distributed 切嵌入验证旧容器退场与数据卷沿用；部署脚本与文档命令一致性检查。
- 连接预算：配置派生单测断言预算单一来源与各项预留；规定负载下观测池等待/超时、API 延迟、Worker 心跳与空闲事务时长。
- IDLE 模型：多账号 IMAP stub 枚举 watcher 与 reader 两类线程，覆盖慢连接、续期、断线补拉、取消与轮询兜底；Linux 容器受控样本测匿名页相对阈值；归档高水位单独构造大邮件样本断言。
- 巡检门禁：IMAP stub 对同一账号多目录返回传输失败、认证失败、单目录错误、限流，断言账号级短路一次建连/一次写盘、其余目录零探测；并发半开断言单一持有者；前台同步与共享端点其他账号不受牵连。
- 探针：运行态注入启动未完成、DB/LISTEN 断开与恢复、Worker 主循环退出/停滞、旧戳与缓存过期，断言健康状态正确翻转与重启责任；`/ready` 请求期间 SQL 日志断言零 `ROLLBACK`。
- 耐久性与调参：崩溃恢复测试区分可丢弃心跳与必须持久的业务事务；检查点耗时与刷盘抖动负载测试单独记录。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。熔断组件、连通性状态、线程模型、连接池默认值、探针命令与部署入口均已在 2026-11-28 源码与生产审计核实；审阅指出缺口已在本规格中以显式裁决收口。

### 风险与回退

- 风险：IDLE 模型重构影响实时收件箱延迟，须回归 t059/t061/t071 相关行为；账号级短路若退避窗口配置不当会过度跳过，窗口须可校准；异步提交放宽到业务事务会造成崩溃丢数据，须由事务白名单封死；探针缓存上限过大会掩盖 DB/LISTEN 断开；单进程模式故障影响面大于双进程，依赖容器 restart 策略与嵌入式 Worker 自恢复。
- 回退：编排、配置与探针变更通过 revert 实现 commit 回退；IDLE 与巡检改动保留渐变开关仅用于回滚，不作为产品级兼容层；生产部署前依赖标准封存备份。

### 依赖与约束

- 依赖：无前置未合并 task，基于当前 `main`（含 t093）立项；`review_level: full`。
- 写域协调：t095 拥有 Worker 心跳、巡检、IDLE 与容量预算段（`worker/main.py` 心跳/调度外围、`sync/idle_watcher.py`、`sync/patrol.py`、`net/bulkhead.py`、`db/session.py`）及编排配置；t094 拥有 Worker 周期调度与队列回收段及 `worker_jobs`/`outbox`/`message_search` 索引与迁移。两者共同更新 `docs/specs/mail_sync_and_storage.md`，按章节归属分工；建议顺序执行，本项完成后补一条组合回归：断线后轮询回落、过期游标 `resync` 与嵌入 Worker 恢复同时成立。
- 约束：遵循开发铁律删除局部熔断与 ORM 探针路径，不保留调参补丁；不改 IMAP 协议语义；业务事务保持同步提交；PG 参数须在单机容器内可验证；不写生产数据。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新单机嵌入式默认编排、统一并发预算源与 IDLE 事件驱动模型描述。
- `docs/blueprint/domain.md`：更新 `ConnectivityState` 作为巡检账号级门禁的语义及与凭据状态的分工。
- `docs/blueprint/conventions.md`：确立存活性/就绪性分离、探针不依赖业务读模型与提交耐久性白名单约定。
- `docs/blueprint/decisions/20261128_single_process_runtime_and_circuit_unification.md`：记录单进程默认、IDLE 模型重构、巡检健康门禁与提交耐久性的架构决策。
- `docs/blueprint/testing.md`：记录 Compose 双模式、连接预算、探针零 ROLLBACK 与崩溃恢复门禁覆盖要求。

______________________________________________________________________

- 关联 spec 登记：实施收尾时在 `docs/specs/mail_sync_and_storage.md` front matter `tasks` 清单追加 `t095`。
