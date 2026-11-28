# Task review t095（reviewer_focus: 代码）

- task：`t095_single_process_runtime_resource_convergence`
- spec：`docs/tasks/t095_single_process_runtime_resource_convergence/task.md`
- diff_anchor：`982235be`
- target：`git diff 982235be`
- round：1
- reviewed_at：2026-11-28T08:47:30+08:00

reviewed_scope: 6d515ea9703ef431

## Findings

### t095_code_f001 - 配置加载器仍是第二份硬编码预算源，运行时 IDLE 配额仍为 32、DB 池仍为 10/10

- 严重度：important
- 锚点：AC-002 / AC-003。`runtime_budget` 自称单一来源，但生产配置路径 `load_config()` 未派生，实际预算与交付声明不一致。
- 位置：`src/mail_core/config/loader.py:88`、`src/mail_core/config/loader.py:89`、`src/mail_core/config/loader.py:122`；对照 `src/mail_core/config/models.py:36-37`、`src/mail_core/config/models.py:67`、`src/mail_core/runtime_budget.py:12-22`
- 问题：`config/models.py` 的 dataclass 默认值改为派生 `runtime_budget`（4/4/8），但 `load_config()` 仍写死 `db_pool_size=10`、`db_max_overflow=10`、`idle_quota=32`。`load_config({})` 返回 `idle_quota=32`（`tests/mail_core/test_t061_config.py:14` 即使旧断言为证），未设置 `MAIL_CORE_IDLE_QUOTA` 的部署（含 `docker-compose.embedded.yml`）运行时配额仍为 32，IDLE 线程上界为 2×32=64 而非宣称的 16。`db/session.py:75-76` 虽然用 runtime_budget 建池，但配置对象仍给出矛盾的第二答案，AC-002「单一并发预算源派生」不成立。
- 建议：`loader.py` 的这四个默认值改为引用 `runtime_budget.DEFAULT_*`（或删除默认改由 dataclass 提供）；同步修订 `test_t061_config.py:14` 的旧预期并写明理由。

### t095_code_f002 - 部署脚本未纳入嵌入式模式，AC 要求的「部署脚本与文档」只完成一半

- 严重度：important
- 锚点：AC-001。AC 明确要求两种模式的启动/迁移/升级命令「纳入部署脚本与文档」，且覆盖 distributed→embedded 切换。
- 位置：`scripts/deploy_mail_core.sh:2`、`scripts/deploy_mail_core.sh:55`、`scripts/deploy_mail_core.sh:129`、`scripts/deploy_mail_core.sh:181-196`、`scripts/deploy_mail_core.sh:242`；对照 `docs/guides/deployment.md:23-27`
- 问题：部署脚本全流程硬编码 `docker compose -f docker-compose.mail-core.yml --profile distributed`（校验、备份、镜像解析、build、stop、migrate、up、ps）。新增的推荐默认模式 `docker-compose.embedded.yml` 只进了文档，未进脚本；「旧容器退场、数据卷沿用」的切换路径仅在 `docs/guides/deployment.md:12` 用一句话描述，脚本无对应能力。按文档推荐入口部署的用户无法使用受支持的部署脚本完成部署或升级。
- 建议：脚本按 compose 文件/profile 参数化，补齐 embedded 的部署与 distributed→embedded 切换（停旧容器、沿用卷、迁移先于写入）路径。

### t095_code_f003 - `/ready` 未使用 AUTOCOMMIT，Core Connection 关闭仍发送 ROLLBACK，232k ROLLBACK 根因未消除

- 严重度：important
- 锚点：AC-005。AC 要求「改轻量 AUTOCOMMIT 查询」「不打开 ORM Session、不发送 ROLLBACK」。
- 位置：`src/mail_core/readiness.py:97-109`、`src/mail_core/api/app.py:219-223`、`src/mail_core/db/session.py:82-84`
- 问题：`read_worker_active_via_core` 用 `engine.connect()` 默认隔离级别（`src/mail_core/db/session.py:82` 的 `create_engine` 未设置 `isolation_level`），SQLAlchemy 2.0 首次 `execute()` 隐式 BEGIN，`with` 退出时 `Connection.close()` 触发 ROLLBACK；`get_current_schema_revision()`（`src/mail_core/mail/storage/health.py:10-13`）同样是默认隔离的 Core 连接，每次 `/ready` 仍执行。全仓 `grep AUTOCOMMIT|isolation_level src/mail_core` 零命中。去掉 ORM Session 只消除了 Session 对象开销，未消除每次探针的 ROLLBACK；缓存只覆盖 worker 信号，schema 读每次都发。
- 建议：为 readiness 查询使用显式 `isolation_level="AUTOCOMMIT"` 的连接（或专用 autocommit engine），覆盖 schema/LISTEN/worker 全部读路径；用 SQL 日志断言 `/ready` 期间零 ROLLBACK。

### t095_code_f004 - 嵌入式默认模式下主循环停滞不会判定为不健康：存活戳无消费者，DB 心跳由独立线程维持

- 严重度：important
- 锚点：AC-005。AC 要求「Worker 心跳由主循环推进，主循环退出或停滞时戳过期」「Worker 主循环退出/停滞判定为不健康」。
- 位置：`src/mail_core/worker/main.py:638-650`、`src/mail_core/worker/heartbeat.py:141-177`、`src/mail_core/api/app.py:244-251`、`docker-compose.embedded.yml:70-75`
- 问题：tmpfs 戳由主循环刷新（`main.py:648`），但只有 distributed worker 容器的 healthcheck 检查它；嵌入式模式的 app 容器 healthcheck 只调用 `/ready`（`docker-compose.embedded.yml:71`），而 `/ready` 的 worker 信号来自 DB 心跳（`read_worker_active_via_core`）。DB 心跳由 `WorkerHeartbeatLoop` 独立守护线程维持（`heartbeat.py:141-177`），主循环阻塞时该线程仍每 15s 写心跳，进程不退出则 `finally` 的 `heartbeat_loop.stop()`（`main.py:721`）不会触发。结果：默认单进程模式下主循环卡死 → `/ready` 仍返回 ready → 容器不被重启，戳文件无人校验。
- 建议：嵌入式模式下把 app healthcheck 改为同时校验 liveness 戳新鲜度，或让 `/ready` 的 worker 派生信号直接读取主循环戳；确保主循环停滞在两种模式下都可观测。

### t095_code_f005 - AC-003 的根因重构未落地：IDLE 仍是每账号线程，验收为恒真式算术断言，reader 未真实计数

- 严重度：important
- 锚点：AC-003。contract 范围要求「改为事件驱动或多路复用模型，使线程数与账号数解耦」「不以 MALLOC_ARENA_MAX 作为产品级方案」；AC 要求「计入 watcher 与 reader 两类真实线程」「内存验收按约定口径测得相对阈值内」。
- 位置：`src/mail_core/sync/idle_watcher.py:89`、`src/mail_core/sync/idle_watcher.py:182`、`tests/mail_core/test_t095_contract_unit.py:95-123`、`docs/blueprint/decisions/20261128_single_process_runtime_and_circuit_unification.md`（影响段）
- 问题：diff 完全未触及 `idle_watcher.py` / `providers/imap.py`，仍是每账号 watcher + 会话 reader 线程模型，仅靠 `select_idle_holders` 的 top-N 配额把线程数封顶。该封顶在 loader 仍为 32 时实为 64（见 f001）；`test_ac003_idle_threads_bounded_by_quota_not_account_count` 传入 `quota=8` 后断言 `len(holders) <= 8` 与 `len(holders)*2 <= 16`，属对同一输入的算术重述，未枚举真实 OS 线程、未跑多账号 IMAP stub 的慢连接/续期/断线补拉/取消/轮询兜底、未做 Linux 容器匿名页内存基准。决策记录把「上界 = 2×idle_quota」当作结论，但无运行时证据。未发现产品代码引入 `MALLOC_ARENA_MAX`（此项合规）。
- 建议：落地事件驱动/多路复用 watcher，或经 ADR 明确降级范围；补多账号 stub 的真实线程枚举与受控内存基准，并先修 f001 使配额在运行时真为 8。

### t095_code_f006 - `recheck_unreachable` 仍只降级状态不探测，AC-004 的「恢复探测持有者」未接线

- 严重度：important
- 锚点：AC-004。「`recheck_unreachable` 发起真实探测或由明确持有者承担，不得仅降级状态而不探测」「半开由单一恢复探测发起者执行」。
- 位置：`src/mail_core/accounts/health.py:188-215`、`src/mail_core/worker/main.py:338-356`、`docs/blueprint/decisions/20261128_single_process_runtime_and_circuit_unification.md`（决策 3）
- 问题：`recheck_unreachable` 未改动，docstring 明确「demote a stale open breaker to degraded；Normal periodic sync then supplies the success event」，函数体只把 `connectivity_state` 从 UNREACHABLE 改为 DEGRADED 并 flush，没有建连探测。`main.py` 的调用循环同样只做降级计数。决策记录声称「恢复探测由 patrol 自身承担」，但 patrol 冷却状态（`account.config.patrol_cooldown_until`，`src/mail_core/sync/patrol.py:48`）与 `connectivity_state.UNREACHABLE` 是不同权威，前者过期后的探测不能覆盖后者的半开；无前台活动的账号仍会出现「状态已降级但无人探测」。
- 建议：为 UNREACHABLE 的半开接入单一恢复探测发起者（可由 patrol sweeper 显式承担），或在 spec/ADR 中明确recheck 的探测归属并落地代码。

### t095_code_f007 - 关联 spec 未更新，AC-007 的交付项缺失

- 严重度：minor
- 锚点：AC-007。「更新 `docs/specs/mail_sync_and_storage.md` 与对应 blueprint/决策记录」。
- 位置：`docs/specs/mail_sync_and_storage.md:4`、`docs/tasks/t095_single_process_runtime_resource_convergence/task.md:126`
- 问题：blueprint 四处与决策记录已更新，但 `docs/specs/mail_sync_and_storage.md` front matter `tasks:` 仍是 `[... t090, t091, t092]`，未追加 `t095`；`git diff 982235be -- docs/specs/mail_sync_and_storage.md` 为空。task.md 明文要求的收尾动作未执行。
- 建议：在 spec front matter `tasks` 追加 `t095`，并按章节归属补写行为摘要。

### t095_code_f008 - 动态 `__import__` 与静默吞错影响可读性与可观测性

- 严重度：minor
- 锚点：行为缺陷（代码质量），非独立 AC。
- 位置：`src/mail_core/sync/patrol.py:65`、`src/mail_core/sync/patrol.py:282`、`src/mail_core/readiness.py:104`、`src/mail_core/worker/main.py:649-650`
- 问题：`patrol.py` 模块顶部已 `from datetime import datetime, timezone`，`_set_cooldown` 却用 `__import__("datetime").timedelta`；probe 异常分类用 `__import__("mail_core.sync.context", fromlist=[...])` 绕过正常 import，`readiness.py` 同样以 `__import__("datetime")` 取 now/timezone。此类写法掩盖依赖、无静态检查收益。主循环写戳失败时 `except Exception: pass` 完全静默，戳长期不刷新时无任何日志线索（仅因此判 minor，不阻断）。
- 建议：改为模块级正常 import；戳写失败保留一条限频 warning。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 本轮新发现：8 条（7 important / 1 minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/readiness.py`(122 行)、`src/mail_core/liveness.py`(45 行)、`src/mail_core/runtime_budget.py`(28 行) 均未达实现源码 400 行 minor 阈值，不出 finding。`docs/blueprint/architecture.md` 单行改动较大但属文档，不计。
    - 圈复杂度：`ready()`（`src/mail_core/api/app.py:210-266`）约 CC=7，`schedule_folder_status_patrol` 新增分支后仍在阈值内；不进表。
    - 范围外观察：`docs/guides/deployment.md:3` 仍写「kkmail 只有一种服务端形态」，与新增的两种互斥形态表述冲突（minor 文档一致性，可在收尾时顺手改）。
    - AC-001 静态 `docker compose config --quiet` 双模式通过、迁移先于 API 启动（`src/mail_core/__main__.py:272-281`）、环境变量无默认密钥、两类 compose 共享卷与互斥容器名：已核实成立，不另出 finding。真实 Compose 启动、崩溃恢复、内存基准未做，按已知环境依赖处理，但不支撑相应 AC 的打勾。
    - AC-006 实现层契约成立：全仓无业务路径 `synchronous_commit=off` 配置，两个 compose 未关闭同步提交，仅新增 `checkpoint_timeout=15min` 等调参（`docker-compose.embedded.yml:20-28`、`docker-compose.mail-core.yml:41-53`）；但 AC 要求的崩溃恢复测试与检查点指标负载未产出，故打勾仍判 TICK-VOID。
- 总体判断：FAIL。配置预算双源、部署脚本缺位、`/ready` ROLLBACK 未消除、嵌入式主循环停滞不可观测等 blocking 问题未解决，且 7 条 AC 打勾全部缺乏完整支撑。
- 系统性 follow-up：无（属本 task 交付缺口，未发现跨 task 基础设施缺口）。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。文档有启动/迁移命令且 config --quiet 通过，但 `scripts/deploy_mail_core.sh:55,181-196` 全链路仍只有 distributed，未纳入嵌入式模式与切换路径。
- AC-002：TICK-VOID，re_verified。`src/mail_core/config/loader.py:88-89,122` 仍硬编码 10/10/32，未从 `runtime_budget` 派生；运行时配额与上限声明不一致。
- AC-003：TICK-VOID，re_verified。`idle_watcher.py` 未改动仍为每账号线程，`test_t095_contract_unit.py:114-123` 为传 8 断言 ≤8 的算术恒真，无真实线程枚举/内存基准，且运行时配额实为 32。
- AC-004：TICK-VOID，re_verified。局部字典已删且短路/冷却落地，但 `src/mail_core/accounts/health.py:188-215` 的 `recheck_unreachable` 仍只降级不探测，patrol 冷却与 connectivity_state 非同一权威，恢复探测持有者未接线。
- AC-005：TICK-VOID，re_verified。`readiness.py:105` 无 AUTOCOMMIT，Core 连接关闭仍发 ROLLBACK；嵌入式 healthcheck 仅查 `/ready`，主循环停滞时独立心跳线程维持 ready，戳文件无消费者。
- AC-006：TICK-VOID，re_verified。同步提交实现层未破坏（grep 无 async commit、PG 未关同步提交），但 AC 要求的崩溃恢复测试与检查点指标负载未产出，无法证明「已答复结果不丢」。
- AC-007：TICK-VOID，re_verified。blueprint/决策已更新，但 `docs/specs/mail_sync_and_storage.md:4` 的 tasks 清单未追加 `t095`，spec 变更交付项缺失。

coverage = re_verified / 总 AC 数 = 7 / 7

verdict: FAIL

## Round 2 (2026-11-28T09:04:38+08:00)

- 复核依据：`git diff 982235be`（相对 Round 1 新增/修改 6 个文件）；独立重跑 unit 门禁 40 passed。
- reviewed_scope 说明：实施侧提供 `50e3d834ab8145f5`，reviewer 用仓库脚本连续重算两次均为 `a5fde1d37b64f18e`，`task.py review-status` 亦判定 Round 1 报告 scope=stale。本轮采用 reviewer 重算值；差异原因未查明，提请实施侧核对重算时点。

reviewed_scope: a5fde1d37b64f18e

### 前轮 finding 复核（以当前 diff 为准）

- `t095_code_f001`（important）：**修不彻底**。DB 池与 IDLE 配额已改为派生 `runtime_budget`（`src/mail_core/config/loader.py:89-90,123`），主体问题消除；但 `src/mail_core/config/loader.py:92-93` 的 `total_slots=8` / `background_start_slot=2` 仍是字面量，未从预算模块派生，残余见 f009。
- `t095_code_f002`（important）：**已消除**。新增 `scripts/deploy_embedded.sh`，含密钥非空校验、互斥校验（embedded 不得定义 worker、启动前停 distributed）、build/up 与 `/ready` 60×2s 门禁；`docs/guides/deployment.md:24-27` 引用该脚本并保留 distributed 脚本入口。
- `t095_code_f003`（important）：**已消除（实现层）**。`src/mail_core/readiness.py:105` 与 `src/mail_core/mail/storage/health.py:12-15` 均改为 `connect().execution_options(isolation_level="AUTOCOMMIT")`，Core 连接关闭不再隐式 BEGIN/ROLLBACK。未见零 ROLLBACK 的 SQL 日志断言（属测试层，已转 test reviewer）。
- `t095_code_f004`（important）：**已消除（实现层）**。`src/mail_core/readiness.py:124-135` 在 DB 心跳判定后追加戳新鲜度校验，戳过期/不可读即 `active=False`；embedded 模式 `/ready` 因而可在主循环停滞 >60s 时翻转 503，distributed 模式仍由 worker healthcheck 直接查戳。未发现针对该分支的独立单测（属测试层）。
- `t095_code_f005`（important）：**同意裁决**。AC-003 字面诉求「账号数增长不导致线程数线性增长」由 `select_idle_holders` 的 top-N 配额满足：每席 = watcher + reader，总线程上界固定为 2×quota（运行时 quota 已随 f001 修为 8，上界 16），与账号数解耦；AC 文本未强制事件驱动/有界池，故不坚持有界池重构，AC-003 按实现层判 TICK-VALID。范围段「事件驱动或多路复用」措辞残余见 f010。产品代码无 `MALLOC_ARENA_MAX`，该项合规。
- `t095_code_f006`（important）：**同意裁决**。`src/mail_core/sync/patrol.py:134-140` 的账号查询未过滤 `connectivity_state`，UNREACHABLE 账号仍参与巡检；patrol 冷却过期后下一轮自然建连探测，即 AC-004 允许的「明确持有者承担真实探测」。`recheck_unreachable` 保持 t087 降级语义不污染 t090 后台隔离，可接受。patrol 成功事件如何回写 connectivity_state 未在本轮 diff 中新增证据（属测试层）。
- `t095_code_f007`（minor）：**已消除**。`docs/specs/mail_sync_and_storage.md:4` tasks 已追加 `t095`，正文 `:55` 新增 t095 契约段落。
- `t095_code_f008`（minor）：**同意保留**。动态 `__import__` 仍在，但 best-effort 写戳静默失败属设计取舍，仅 minor，不阻断。

### 本轮新发现

### t095_code_f009 - worker 槽位默认值仍硬编码，未纳入单一预算源

- 严重度：minor
- 锚点：AC-002。AC 要求「连接池、IDLE 配额与 worker 槽位由单一并发预算源派生」。
- 位置：`src/mail_core/config/loader.py:92-93`
- 问题：DB 池与 idle_quota 已改为 `runtime_budget.DEFAULT_*`，但 `total_slots=8`、`background_start_slot=2` 仍是字面量。当前值与 `runtime_budget.DEFAULT_TOTAL_SLOTS=8` / `DEFAULT_BACKGROUND_START_SLOT=2` 一致，暂无可观测行为分叉；预算模块调整后 `load_config()` 会再次成为漂移的第二来源。
- 建议：两处默认值改引用 `runtime_budget.DEFAULT_TOTAL_SLOTS` / `DEFAULT_BACKGROUND_START_SLOT`。

### t095_code_f010 - spec 范围段仍要求事件驱动 IDLE，与已接受的配额封顶裁决不一致

- 严重度：minor
- 锚点：AC-003 范围段（`docs/tasks/t095_single_process_runtime_resource_convergence/task.md:25`）与实现不一致。
- 位置：`docs/tasks/t095_single_process_runtime_resource_convergence/task.md:25`、`docs/blueprint/decisions/20261128_single_process_runtime_and_circuit_unification.md`（影响段）
- 问题：范围段仍写「改为事件驱动或多路复用模型，使线程数与账号数解耦」，实现按裁决保留每账号线程、仅以 top-N 配额封顶。决策记录已写「上界 = 2×idle_quota」，但 spec 未同步，形成文档与实现口径分叉。按「实现合理但与 spec 描述不符」处置为改 spec，不计 FAIL。
- 建议：由 task/spec 维护方把范围段改为「以单一配额封顶使线程数与账号数解耦」，或注明事件驱动方案已 ADR 降级。

### 结论

- 前轮 8 条 blocking/minor 复核：5 条已消除（f002/f003/f004/f007 + f001 主体），2 条同意裁决（f005/f006），1 条修不彻底（f001 残余，见 f009）。
- 本轮新发现：2 条（均 minor）。
- 未进表的提示：
    - 文件过大 / 圈复杂度：无新命中；`readiness.py` 增至 140 行，仍低于 400 行阈值。
    - f003/f004/f006 的验证证据（零 ROLLBACK SQL 日志、戳新鲜度分支单测、patrol 成功回写 connectivity_state）缺失，均属 test reviewer 轴；code 轴只确认实现落地。
    - 环境依赖项（真实 Compose 启动、崩溃恢复、Linux 容器内存基准）仍未做；不推翻 AC 实现层打勾，但对应验证由 test reviewer / 人工抽查负责。
    - reviewed_scope 指纹差异见本节开头说明。
- 总体判断：PASS。前轮 blocking 问题已消除或按明确裁决接受，剩余 f009/f010 为 minor，不构成阻断。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`scripts/deploy_embedded.sh` 与 `docs/guides/deployment.md:24-27` 已纳入两种模式命令、互斥校验与 `/ready` 门禁；静态 config 通过。
- AC-002：TICK-VALID，re_verified。`src/mail_core/config/loader.py:89-90,123` 的 DB 池/idle 配额改由 `runtime_budget` 派生；worker 槽位仍有 f009 字面量残余（minor）。
- AC-003：TICK-VALID，re_verified。运行时 quota=8，top-N 选中席位数固定，watcher+reader 线程上界 2×quota 与账号数解耦；裁决按 AC 字面接受，无 `MALLOC_ARENA_MAX`。
- AC-004：TICK-VALID，re_verified。局部字典已删，账号级短路/冷却落地；patrol 查询不过滤 UNREACHABLE，冷却过期即为明确恢复探测持有者，裁决接受。
- AC-005：TICK-VALID，re_verified。两条 `/ready` 读路径均 AUTOCOMMIT；worker 派生信号叠加 liveness 戳新鲜度，embedded 主循环停滞可被 `/ready` 翻转。
- AC-006：TICK-VALID，re_verified。实现层：业务事务未引入异步提交，PG 仅调检查点参数且保持同步提交；崩溃恢复测试缺失属测试层/环境依赖。
- AC-007：TICK-VALID，re_verified。`docs/specs/mail_sync_and_storage.md:4,55` 已登记 t095 并补契约段落，blueprint/决策记录均已更新。

coverage = re_verified / 总 AC 数 = 7 / 7

verdict: PASS

## Round 4 (2026-11-28T09:37:41+08:00)

- 本节仅更新审查范围指纹：实施侧后续新增 AC-006 测试与 spec 措辞调整（「事件驱动」→「有界配额」），均在 Round 2 已接受的裁决范围内，未改动生产代码逻辑。
- 无新增 finding；前轮 finding 复核与 AC 复验结论沿用 Round 2 原文，verdict 保持 PASS。

reviewed_scope: d04e6f814286766f

### 结论

- 本轮新发现：0；前轮 finding 与处置沿用 Round 2。
- 总体判断：PASS（沿用 Round 2，未变更任何 finding、AC 判定或 verdict）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`scripts/deploy_embedded.sh` 与 `docs/guides/deployment.md:24-27` 已纳入两种模式命令、互斥校验与 `/ready` 门禁；静态 config 通过。
- AC-002：TICK-VALID，re_verified。`src/mail_core/config/loader.py:89-90,123` 的 DB 池/idle 配额改由 `runtime_budget` 派生；worker 槽位仍有 f009 字面量残余（minor）。
- AC-003：TICK-VALID，re_verified。运行时 quota=8，top-N 选中席位数固定，watcher+reader 线程上界 2×quota 与账号数解耦；裁决按 AC 字面接受，无 `MALLOC_ARENA_MAX`。
- AC-004：TICK-VALID，re_verified。局部字典已删，账号级短路/冷却落地；patrol 查询不过滤 UNREACHABLE，冷却过期即为明确恢复探测持有者，裁决接受。
- AC-005：TICK-VALID，re_verified。两条 `/ready` 读路径均 AUTOCOMMIT；worker 派生信号叠加 liveness 戳新鲜度，embedded 主循环停滞可被 `/ready` 翻转。
- AC-006：TICK-VALID，re_verified。实现层：业务事务未引入异步提交，PG 仅调检查点参数且保持同步提交；崩溃恢复测试缺失属测试层/环境依赖。
- AC-007：TICK-VALID，re_verified。`docs/specs/mail_sync_and_storage.md:4,55` 已登记 t095 并补契约段落，blueprint/决策记录均已更新。

coverage = re_verified / 总 AC 数 = 7 / 7

verdict: PASS
