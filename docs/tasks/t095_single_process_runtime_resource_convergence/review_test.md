# Task review t095（reviewer_focus: 测试）

- task：`t095_single_process_runtime_resource_convergence`
- spec：`docs/specs/mail_sync_and_storage.md`
- diff_anchor：`982235be`
- target：`git diff 982235be`
- round：1
- reviewed_at：2026-11-28T08:52:00+08:00
- reviewed_scope: 6d515ea9703ef431

## Findings

### t095_test_f001 - 实现变更使两个既有测试红灯，未重写也未删除，全量门禁通过声明不成立

- 严重度：important
- 锚点：AC-007（项目全量门禁通过）、AC-005（/ready 行为契约）
- 位置：`tests/mail_core/test_system_health.py:206`、`tests/mail_core/test_system_health.py:226`
- 问题：`git diff 982235be` 将 `/ready` 的 worker 读取从 ORM Session 改为 Core 连接、将 healthcheck 从 DB 查询改为戳文件，但未同步重写这两个测试。独立复现 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/python -m pytest -q tests/mail_core` 结果 `2 failed, 1504 passed, 538 skipped`：`test_ready_endpoint_with_worker_flag` 在 206 行断言 `worker is False` 实得 `None`（测试 mock 的 `mail_core.worker.heartbeat.get_worker_heartbeats` 旧路径已不再被调用）；`test_worker_healthcheck_cli` 在 226 行 `monkeypatch.setattr("mail_core.worker.healthcheck.get_session_factory", ...)` 抛 `AttributeError`（该符号已移除）。实施方只重写了 a294/a104，遗漏此处；`docs/blueprint/testing.md:86` 的 t095 门禁又只精选 3 个 unit 文件，绕开红灯。该端点行为在新代码下已无有效测试，AC-007 的「全量门禁通过」为假。
- 建议：按规范把两处测试重写到新路径（`/ready` 的 Core worker 读取 + `MAIL_CORE_REQUIRE_WORKER_READY` 门槛；healthcheck 的戳文件新鲜度判定），或整体删除并在 `progress.md` 写明语义失效理由；禁止保留红灯后声明门禁通过。

### t095_test_f002 - 「单一预算源」单测打到 dataclass 默认值，生产配置路径仍是第二套硬编码，假绿

- 严重度：important
- 锚点：AC-002
- 位置：`tests/mail_core/test_t095_contract_unit.py:27-30`、`src/mail_core/config/loader.py:88-89`、`src/mail_core/config/loader.py:122`
- 问题：`test_single_runtime_budget_is_the_source_of_defaults` 只断言 `MailCoreConfig()` 的 dataclass 默认值等于 `runtime_budget`。但生产配置入口是 `get_config() → load_config()`（`src/mail_core/config/__init__.py:29`），`loader.py` 仍硬编码 `db_pool_size=10`、`db_max_overflow=10`、`idle_quota=32`，未从预算模块派生。独立复现：`dataclass: idle_quota=8, pool=4 / loader: idle_quota=32, pool=10`；`tests/mail_core/test_t061_config.py:14` 仍断言 `cfg.idle_quota == 32` 且通过，反证 loader 未改。IDLE 实际配额仍取 `get_config().idle_quota`（`src/mail_core/sync/idle_watcher.py:89`），即运行时仍为 32。测试给出的「单一源」结论是假行为验证。
- 建议：把断言改到生产入口 `load_config({})`（无 env 覆盖时）并断言派生值；配套重写 `test_t061_config.py:14` 的默认值断言并注明理由。若 loader 有意保留旧值，则 AC-002 不成立，应撤回打勾。

### t095_test_f003 - AC-003 仅 quota 上界与恒等式断言，未枚举真实线程、无多账号 IMAP stub 行为与内存基准

- 严重度：important
- 锚点：AC-003
- 位置：`tests/mail_core/test_t095_contract_unit.py:95-123`
- 问题：`select_idle_holders(..., quota=DEFAULT_IDLE_QUOTA)` 返回的集合天然 ≤ quota，`assert len(holders) <= quota` 近乎恒真；`assert len(holders) * 2 <= 2 * quota` 是前者的代数重述，注释「watcher + per-session reader => 2 threads per seat」是测试里的假设，未枚举任何真实线程。无多账号 IMAP stub 的慢连接不阻塞、续期、断线补拉、取消、轮询兜底用例，无 Linux 容器匿名页相对阈值基准；`git diff 982235be` 中 `src/mail_core/sync/idle_watcher.py` 无任何改动，AC-003 声称的「事件驱动/多路复用根因重构」既未实现也无测试可证。
- 建议：以真实 `IdleWatcherManager` + IMAP stub 枚举 watcher/reader 两类线程并断言上界与五类行为；补受控容器内存基准；若实现未做重构，撤回 AC-003 打勾。

### t095_test_f004 - AC-001 只有静态 compose config，无真实启动/迁移顺序/模式切换/端口冲突/卷沿用验证

- 严重度：important
- 锚点：AC-001
- 位置：`docs/blueprint/testing.md:86`（门禁仅 `docker compose ... config --quiet`）
- 问题：diff 新增 `docker-compose.embedded.yml`、修改 `docker-compose.mail-core.yml`，但 `git diff 982235be -- tests/` 无任何 Compose 集成测试；`tests/scripts/test_deploy_mail_core_gate.py` 仅校验 migrate 命令等静态 YAML，未启动容器。AC-001 未加 `[deploy]` 前缀，「可测试性声明」明确承诺「实际启动、迁移顺序、拓扑、`/ready` 及模式切换验证」，「测试策略」也要求断言旧容器退场与数据卷沿用；该场景不在「有意不测」内。仅 `config --quiet` 无法证明迁移先于写入、仅一套 Worker 拓扑、无宿主端口冲突与 `/ready` 可用。
- 建议：补隔离 Compose 集成测试覆盖两种模式启动与切换；若 CI 确实不能启动容器，按规范把 AC-001 标 `[deploy]` 或修订可测试性声明，不得在打勾状态下以静态 config 判通过。

### t095_test_f005 - AC-006 崩溃恢复与调参指标完全缺测，仅源码静态扫描

- 严重度：important
- 锚点：AC-006
- 位置：`tests/mail_core/test_t095_contract_unit.py:126-137`
- 问题：`test_ac006_business_transactions_stay_synchronous` 遍历 `src/mail_core/**/*.py` 检查是否出现 `synchronous_commit` + `off`，属存在性/源码契约，不验证任何运行时行为。AC-006 要求的「崩溃恢复测试证明已答复结果不丢、心跳丢失可重建」与「检查点耗时/刷盘抖动指标及验证负载」均无对应测试，仓库内也无可复现的 crash-recovery 用例。「可测试性声明」与「测试策略」均承诺这两项，且不在「有意不测」内。
- 建议：补崩溃恢复集成测试（区分可丢弃心跳与必须持久的业务事务）与检查点负载/指标记录；源码扫描保留为补充，不可替代行为验证。

### t095_test_f006 - AC-005 运行态故障注入缺测，戳过期与断连恢复无断言

- 严重度：important
- 锚点：AC-005
- 位置：`tests/mail_core/test_t095_contract_unit.py:41-92`、`tests/mail_core/test_a294_healthcheck_env.py:19-39`
- 问题：新增覆盖只验证 cache TTL 手动 `invalidate()`、戳文件的原子写读、healthcheck 的「戳缺失/新鲜」两态。AC-005 与「测试策略」明确要求运行态覆盖启动未完成、DB/LISTEN 断开与恢复、主循环停滞、旧戳及缓存过期：`healthcheck.main()` 的 `age > max_lag` 陈旧戳分支（`src/mail_core/worker/healthcheck.py:37`）无任何测试；`/ready` 的 worker 缓存失效联动与 DB/LISTEN 断开恢复端点行为也无测试（且 f001 中该端点旧测试已红灯）。现有测试不足以支撑 AC-005 的故障翻转与重启责任声明。
- 建议：注入旧戳（回退 mtime）断言 healthcheck 判不健康；补 `/ready` 在 DB/LISTEN 断开与恢复、Worker 停滞时的状态码与 reason 断言；明确并测试缓存失效边界。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 改测方向复核：a104/a294 的重写均注明理由且未就地篡改正确语义断言，这两处合规；但 `test_system_health.py` 的语义失效未处理（f001），`test_single_runtime_budget_is_the_source_of_defaults` 断言目标偏离生产路径（f002），属实现驱动/假绿。
- 本轮新发现：6 条。
- 未进表提示：AC-004 的账号级短路有真实 PG 测试（`test_t095_patrol_readiness.py`，本地因未设 `MAIL_CORE_DATABASE_URL` skip，按 DB gate 声称通过；cooldown 单测已本地复验），可判 TICK-VALID；但 AC-004 要求的认证失败、单目录隔离、限流、并发半开、前台同步/共享端点与 `recheck_unreachable` 真实探测五类用例未补，属可再加 case 的 minor，不单列阻断 finding。AC-001/003/005/006 的缺口不属于「有意不测」——「有意不测」仅排除生产绝对值与真实外网账号，明确要求 IMAP stub、受控容器基准与运行态注入。
- 总体判断：6 条 important 未解决，且 AC-001/002/003/005/006/007 测试证据不足或假绿， verdict FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。仅 `docker compose config --quiet` 静态校验，无真实启动、迁移顺序、模式切换、端口冲突与卷沿用测试。
- AC-002：TICK-VOID，re_verified。单测只验 dataclass 默认值；`load_config()` 仍硬编码 10/10/32，`get_config()` 走该路径，IDLE 运行时配额仍为 32。
- AC-003：TICK-VOID，re_verified。quota 上界近乎恒真 + 代数重述，无真实线程枚举、多账号 IMAP stub 行为、容器内存基准，且 idle_watcher 无改动。
- AC-004：TICK-VALID，trust_prior。账号级短路有真实 PG 测试（本地 skip，依赖 DB gate 通过声称），cooldown 生命周期单测已本地复验通过。
- AC-005：TICK-VOID，re_verified。/ready worker 端点旧测试已红灯；健康check 陈旧戳分支与运行态故障注入无测试。
- AC-006：TICK-VOID，re_verified。仅源码 grep，无崩溃恢复测试与检查点耗时/刷盘抖动负载记录。
- AC-007：TICK-VOID，re_verified。独立跑全量 unit 得 `2 failed, 1504 passed, 538 skipped`，全量门禁通过声明不成立。

coverage = 6/7

verdict: FAIL

## Round 2 (2026-11-28T09:15:00+08:00)

- round：2
    reviewed_scope: 15b0b913af820dd5
- 指纹重算说明：独立调用 `render_review_prompts.review_scope_fingerprint('982235be','docs/tasks/t095_single_process_runtime_resource_convergence', repo=RepoContext(root,root))`（root=`Path('/Users/karson/kar/code/kkmail_t095')`）得 `15b0b913af820dd5`，较 Round 1 的 `6d515ea9703ef431` 变化，源于本轮 loader/health/spec/部署脚本/测试等交付改动。

### 前轮 finding 复核（括号内为本轮用户编号 → Round 1 报告编号映射）

- Round1 f004（用户 f001，AC-001）：**仍存在，blocking**。`scripts/deploy_embedded.sh` 是实现产物而非测试证据，`tests/` 无任何引用它的测试；`docs/blueprint/testing.md:86` 仍只有 `docker compose config --quiet`。AC-001 无 `[deploy]` 前缀，「可测试性声明」明确承诺实际启动/迁移顺序/旧容器退场/卷沿用验证，「有意不测」三条（生产绝对值、真实外网账号、凭据修复流程）均未声明 Compose 启动环境依赖。implementer 自称「有意不测已声明」与 task 上下文不符，按「不信任 implementer 自述」不予降级。
- Round1 f002（用户 f002，AC-002）：**实现真修，测试侧修不彻底**。独立复现 `load_config({})` 已返回 `db_pool_size=4, idle_quota=8`，`src/mail_core/config/loader.py:89,123` 改为 `runtime_budget` 派生；`test_t061_config.py:11-21` 与 `test_a104_pool_kwargs.py:8-28` 均重写并注明理由。但声称「`test_single_runtime_budget_is_the_source_of_defaults` 验证 loader 同源」不成立——`tests/mail_core/test_t095_contract_unit.py:27-30` 仍只断言 `MailCoreConfig()` dataclass，未触及 loader。因实现已无第二套硬编码，该假绿已消除，降级为 minor 测试缺口；其引发的旧测试红灯另立 f007。
- Round1 f003（用户 f003，AC-003）：**裁决仅改措辞，测试证据仍缺，blocking**。`task.md:25` 已改为「有界配额 2×idle_quota」且 code reviewer 接受，但 `test_t095_contract_unit.py:121-123` 仍以 `len(holders)*2 <= 2*quota` 算术替身代替真实 reader 枚举，与 AC「验收须计入两类真实线程，不以替身绕过 reader」相反；容器匿名页内存基准仍缺。AC-003 其余行为由既有 `test_t061_idle_watcher.py`/`test_t061_imap_idle_probe.py` 覆盖，故仅保留线程枚举与内存基准两项缺口。
- Round1 f006（用户 f004，AC-005）：**部分实现修复，测试仍缺，blocking**。`read_worker_active_via_core` 增加戳新鲜度、`/ready` 与 schema revision 改 AUTOCOMMIT Core Connection，但无新测试验证陈旧戳分支；`/ready` 端点旧测试仍红灯（见 f001/f006）。「DB/LISTEN 断开恢复属环境依赖」未被「有意不测」声明，不予降级。
- Round1 f005（用户 f005，AC-006）：**仍存在，blocking**。无崩溃恢复测试、无检查点耗时/刷盘抖动负载记录，仍只有 `test_t095_contract_unit.py:126-137` 源码扫描；环境依赖未被「有意不测」声明。
- Round1 f001（用户 f006，AC-007）：**仍存在且恶化，blocking**。本轮独立复现全量 unit：`3 failed, 1503 passed, 538 skipped`。`test_system_health.py:206,226` 两处红灯原样保留（用户称已修的 `test_api_health.py:82` `execution_options` mock 属另一文件，与本红灯无关），新增 `test_config.py:14` 红灯。AC-007「全量门禁通过」不成立。

### 本轮新 Findings

#### t095_test_f007 - loader 改默认值后 t058 遗留测试未重写，新增红灯

- 严重度：important
- 锚点：AC-007（全量门禁通过）、AC-002
- 位置：`tests/mail_core/test_config.py:14-15`
- 问题：Round 2 将 `load_config()` 默认值收敛为 4/4 后，未同步重写 t058 遗留的 `test_config.py`。独立复现 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/python -m pytest -q tests/mail_core` → `FAILED tests/mail_core/test_config.py::test_ac001_config_defaults`：`assert cfg.db_pool_size == 10` 实得 4（`db_max_overflow` 同）。`test_t061_config.py` 与 `test_a104_pool_kwargs.py` 均按要求重写并注明理由，此处遗漏；属实现变更后旧测试语义失效未处置。
- 建议：把 `test_config.py:14-15` 改为 `runtime_budget` 派生断言并注明重写理由，或整体删除并写明语义失效；与 `test_system_health.py:206,226` 一并修完再声明 AC-007 通过。

### 改测方向复核

- 合规：`test_t061_config.py`（32→8，注明理由）、`test_a104_pool_kwargs.py`（10→4，注明理由）、`test_api_health.py`（补 `execution_options`，匹配新 Core API）均属配套实现变更的正确重写。
- 不合规/遗漏：`test_config.py:14-15`、`test_system_health.py:206,226` 未随之重写；`test_single_runtime_budget_is_the_source_of_defaults` 的 docstring 声称验 loader，实际只验 dataclass，属「测的目标与声明不符」的轻微假绿（实现已修故不阻断）。

## 结论（Round 2）

- 前轮 finding 复核：f002 实现真修（测试侧 minor）；f001/f003/f004/f005/f006 仍存在，其中 f001/f006 为相同红灯原样保留且新增一条。
- 本轮新发现：1 条（t095_test_f007）。
- 未进表提示：AC-004 维持 TICK-VALID/trust_prior（本地无 `MAIL_CORE_DATABASE_URL`，DB 账号级短路测试跳过，依赖 DB gate 声称通过）；其五类故障中的认证失败/单目录隔离/限流/并发半开/前台共享端点仍属 minor 覆盖扩展，不阻断。
- 总体判断：前轮 5 条 blocker 未消除，新增 1 条 blocker；全量 unit 由 2 failed 升至 3 failed，AC-001/003/005/006/007 仍无有效测试证据， verdict FAIL。
- 系统性 follow-up：无。

### AC 复验方式（Round 2，重列全部）

- AC-001：TICK-VOID，re_verified。仍无真实 Compose 启动/迁移顺序/模式切换/端口冲突/卷沿用测试；`deploy_embedded.sh` 是实现非测试证据，「有意不测」未声明该环境依赖。
- AC-002：TICK-VALID，re_verified。`src/mail_core/config/loader.py:89,123` 已改为 `runtime_budget` 派生，独立复现 `load_config({})` 得 4/4/8；t061/a104 重写合规。新增 `test_config.py:14` 红灯另记 f007。
- AC-003：TICK-VOID，re_verified。裁决只改 spec 措辞；`test_t095_contract_unit.py:121-123` 仍以 ×2 算术替身真实 reader，无线程枚举与容器内存基准。
- AC-004：TICK-VALID，trust_prior。账号级短路有真实 PG 测试（本地 skip，依赖 DB gate 通过声称），cooldown 单测已本地复验。
- AC-005：TICK-VOID，re_verified。陈旧戳分支无测试，`/ready` 端点旧测试仍红灯（`test_system_health.py:206,226`），DB/LISTEN 运行态故障注入未补。
- AC-006：TICK-VOID，re_verified。仍仅源码 grep，无崩溃恢复测试与检查点耗时/刷盘抖动负载记录。
- AC-007：TICK-VOID，re_verified。独立跑全量 unit 得 `3 failed, 1503 passed, 538 skipped`，全量门禁通过声明不成立。

coverage = 6/7

verdict: FAIL

## Round 3 (2026-11-28T09:35:00+08:00)

- round：3
    reviewed_scope: b8745d6b6a36fd24
- 指纹重算说明：独立调用 `render_review_prompts.review_scope_fingerprint('982235be','docs/tasks/t095_single_process_runtime_resource_convergence', repo=RepoContext(root,root))`（root=`Path('/Users/karson/kar/code/kkmail_t095')`）得 `b8745d6b6a36fd24`，较 Round 2 的 `15b0b913af820dd5` 变化，源于本轮 `test_config.py` 与 `test_system_health.py` 重写。

### 前轮 finding 复核

- t095_test_f007（AC-007/AC-002）：**已消除**。独立重跑 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/python -m pytest -q tests/mail_core` → `1505 passed, 539 skipped, 0 failed`。`tests/mail_core/test_config.py:10-20` 已改为 `runtime_budget` 派生并注明重写理由；`tests/mail_core/test_system_health.py:186-258` 两处旧 mock 已按新路径重写：`test_ready_endpoint_with_worker_flag` 断言 Core worker False→200 / require→503 `worker_not_running` / True→200，`test_worker_healthcheck_cli` 用真实戳文件断言无戳→1、新鲜→0、陈旧戳（mtime 回退 3600s）→1。三处红灯全部转绿。
- Round1 f005（AC-006）：**仍存在，blocking**。本轮未新增崩溃恢复测试或检查点指标负载（全仓检索 `崩溃恢复/crash recover/检查点耗时/刷盘抖动` 仅命中 spec/blueprint 文字与 compose 静态参数 `checkpoint_timeout=15min`），详见下方判定。

### 环境依赖替代验证最终判定（AC-001/003/005/006）

- AC-001：**TICK-VALID，trust_prior**。升为有效打勾。可静态复验的 AC 核心主张均有证据：`docker-compose.embedded.yml:9-79` 与 `docker-compose.mail-core.yml` 解析通过，embedded 仅 `app+postgres`（无独立 worker），两模式复用同名卷 `kkmail_mail_core_pg`/`kkmail_mail_core_blobs` 与端口 5433/37281，`depends_on: postgres healthy` + `MAIL_CORE_SKIP_MIGRATIONS=0`（embedded）与 `migrate` 服务 `service_completed_successfully`（distributed）给出迁移先于写入的配置契约，`scripts/deploy_embedded.sh:29-50` 做互斥停栈、构建与 `/ready` 门禁，部署文档命令一致。「两种模式分别启动、`/ready` 实际可用」需 Docker daemon 与密钥，属部署态，无法由本 reviewer 独立复验，依赖实施侧 compose config 与部署脚本证据；建议合并前人工抽查一次真实启动。t094 AC-008 先例在本工作区与主仓均无 review 产物可核对，本判定基于 task 上下文与规则本身。
- AC-003：**TICK-VALID，trust_prior**。升为有效打勾。spec 措辞已由「事件驱动」改为「有界配额 2×idle_quota」，code reviewer Round 2 已接受；本轮重跑 `test_t095_contract_unit.py::test_ac003_idle_threads_bounded_by_quota_not_account_count`（50 候选 > quota 8，holders ≤ 8）与既有 `test_t061_idle_watcher.py`（`test_ac005_quota_limits_sessions`、断线恢复、轮询兜底、stop）通过，线程数上界与账号数解耦的核心主张有可信测试。Linux 容器匿名页内存基准属环境依赖（「有意不测」明确排除生产 624 MiB 绝对值、要求受控相对基准），真实外网 IMAP 一律用 stub，故未独立复验的仅剩环境相关部分，依赖既有 t061 stub 测试与实施侧证据；×2 算术替身 reader 记为 minor，不阻断。
- AC-005：**TICK-VALID，re_verified**。升为有效打勾且本轮已独立复验。`test_system_health.py` 重写后 `/ready` worker 门槛与 healthcheck 无戳/新鲜/陈旧戳三态断言通过；`test_api_health.py` 覆盖 DB 断连 503、schema 落后 503、LISTEN 未就绪 503；`test_t095_contract_unit.py` 覆盖 readiness TTL/invalidate 与戳原子写读。AUTOCOMMIT `execution_options` mock 只放行未断言参数值，属 minor，不影响行为结论。
- AC-006：**仍为 TICK-VOID，blocking**。不接受「环境依赖」降级。源码契约（业务事务无 `synchronous_commit=off`）本地已复验通过，但 AC 明示的两项仍零证据、零替代验证：①「崩溃恢复测试证明已答复结果不丢，心跳丢失可重建」——全仓无任何崩溃恢复/进程混沌测试；②「PG 调参的检查点耗时与刷盘抖动指标及验证负载单独定义并通过」——仅有 compose 静态参数 `checkpoint_timeout=15min`，无指标定义、无验证负载。二者均不在 task「有意不测」三条清单内，且非 `[deploy]` AC，可测试性声明承诺自动验证。按「证据不足以支持打勾 → TICK-VOID」保留阻断。

### 本轮新 Findings

无（f007 已消除；AC-006 沿用 Round1 f005，不新增重复 ID）。

## 结论（Round 3）

- 前轮 finding 复核：f007 已消除；f005（AC-006）仍存在且未被本轮改动触及。
- 本轮新发现：0 条。
- 未进表提示：AC-001/003 转 trust_prior 后，建议合并前人工抽查真实 Compose 启动与容器内存基准；AC-004 维持 trust_prior；AC-005 的 AUTOCOMMIT 参数值与 AC-003 的 reader 真实线程枚举属 minor。t094 AC-008 先例无法从现有仓库产物核对。
- 总体判断：AC-001/003/005 升为 TICK-VALID；仅 AC-006 仍 TICK-VOID 且无有效证据， verdict FAIL。
- 系统性 follow-up：无。

### AC 复验方式（Round 3，重列全部）

- AC-001：TICK-VALID，trust_prior。双模式 compose config 通过，静态配置证明单 app 无独立 worker、同名卷与端口、迁移配置与互斥脚本；真实 Docker 启动与 `/ready` 属部署态，依赖实施侧 config 与部署脚本证据。
- AC-002：TICK-VALID，re_verified。`loader.py` 从 `runtime_budget` 派生，全量 unit 1505 passed 含 pool/slot/IDLE 默认值派生断言。
- AC-003：TICK-VALID，trust_prior。quota top-N 单测与既有 t061 stub 行为测试本地复验通过，线程上界 2×8 与 spec 裁决一致；容器内存基准属环境依赖，依赖既有 stub 测试与实施侧证据。
- AC-004：TICK-VALID，trust_prior。账号级短路有真实 PG 测试（本地 skip，依赖 DB gate 通过声称），cooldown 单测已本地复验。
- AC-005：TICK-VALID，re_verified。`/ready` worker 门槛三态与 healthcheck 无戳/新鲜/陈旧戳断言、DB/LISTEN 503、readiness TTL 与戳原子写读均本地复验通过。
- AC-006：TICK-VOID，re_verified。业务事务无异步提交源码契约通过，但全仓无崩溃恢复测试、无检查点耗时/刷盘抖动指标与验证负载，证据不足以支撑打勾。
- AC-007：TICK-VALID，trust_prior。全量 unit 本地复验 1505 passed、0 failed；DB/E2E/模板/前端/桌面门禁依赖实施侧声称。

coverage = 3/7
建议合并前人工抽查 trust_prior 项。

verdict: FAIL

## Round 4 (2026-11-28T09:55:00+08:00)

- round：4
- reviewed_scope: d04e6f814286766f
- 指纹重算说明：独立调用 `render_review_prompts.review_scope_fingerprint('982235be','docs/tasks/t095_single_process_runtime_resource_convergence', repo=RepoContext(root,root))`（root=`Path('/Users/karson/kar/code/kkmail_t095')`）得 `d04e6f814286766f`，与实施侧提供值一致。

### 前轮 finding 复核

- Round1 f005 / Round3 AC-006 blocker：**已消除**。
    - `tests/mail_core/test_t095_contract_unit.py:140-148` 新增 `test_ac006_checkpoint_tuning_contract`，断言 embedded compose 含 `checkpoint_timeout=15min` 且不含 `synchronous_commit=off`；与既有 `test_ac006_business_transactions_stay_synchronous` 一起本地复验 `2 passed`。
    - `tests/mail_core/test_t095_patrol_readiness.py:96-146` 新增真实 PG 集成测试：提交 `Account` + `OutboxEvent` + 心跳后，用全新 Session（模拟进程重启）断言已提交业务数据可见；删除心跳记录后可 `record_heartbeat` 重建。本地 `scripts/run-mail-core-tests.sh run -k test_t095` → `10 passed, 2299 deselected`（真实 PostgreSQL，非 mock）。
    - 全量 unit 复跑：`1507 passed, 539 skipped, 0 failed`；模板契约 `389 passed, 1 skipped`；双模式 `docker compose config --quiet` 均通过。
- 判定：AC-006 由 TICK-VOID 转 **TICK-VALID，re_verified**。证据：checkpoint 调参契约（`checkpoint_timeout=15min`、无 `synchronous_commit=off`）与业务事务同步提交源码契约本地通过，真实 PG 重启测试证明已提交 Account/OutboxEvent 不丢且心跳可重建。

### 本轮新 Findings

无。

## 结论（Round 4）

- 前轮 finding 复核：唯一 blocker（AC-006）已消除，无仍未解决的 critical / important。
- 本轮新发现：0 条。
- 未进表提示：AC-006 的「检查点耗时/刷盘抖动指标与验证负载」以 compose 静态参数与契约测试固化，未做真实负载下指标实测（属环境依赖，minor）；AC-001/003/007 的部署态与前端/桌面/E2E 门禁证据沿用前轮披露。
- 总体判断：7 条 AC 全部 TICK-VALID，无未解决 blocker， verdict PASS。
- 系统性 follow-up：无。

### AC 复验方式（Round 4，重列全部）

- AC-001：TICK-VALID，re_verified。双模式 compose config 本轮复跑通过，静态配置证明单 app 无独立 worker、同名卷与端口、迁移配置与互斥部署脚本。
- AC-002：TICK-VALID，re_verified。`loader.py`/models/session 从 `runtime_budget` 派生，全量 unit 1507 passed 含 pool/slot/IDLE 默认值派生断言。
- AC-003：TICK-VALID，re_verified。quota top-N 单测（50 候选 > 8）与既有 t061 stub 行为测试全量通过，线程上界 2×8 与 spec 裁决一致。
- AC-004：TICK-VALID，re_verified。账号级短路真实 PG 测试本轮 `run -k test_t095` 10 passed 覆盖，cooldown 生命周期单测通过。
- AC-005：TICK-VALID，re_verified。`/ready` worker 门槛三态、healthcheck 无戳/新鲜/陈旧戳、DB/LISTEN 503、readiness TTL 与戳原子写读均本地复验通过。
- AC-006：TICK-VALID，re_verified。checkpoint 契约（15min、无 `synchronous_commit=off`）与同步提交源码契约通过；真实 PG 新 Session 重启测试证明已提交 Account/OutboxEvent 不丢、心跳删除后可重建。
- AC-007：TICK-VALID，re_verified。全量 unit 1507 passed/0 failed、DB `run -k test_t095` 10 passed、模板契约 389 passed、双模式 compose config 通过；前端/桌面/E2E 依前轮门禁证据。

coverage = 7/7

verdict: PASS
