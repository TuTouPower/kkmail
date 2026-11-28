# Task review t099（reviewer_focus: 代码）

- task：`t099_unified_migration_executor`
- spec：`docs/tasks/t099_unified_migration_executor/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27..e653b16f`
- round：2
- reviewed_at：2026-11-29T00:48:09+08:00

reviewed_scope: 53a4393166336e35

## Findings

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t099_code_f001|minor|遗留|离线入口 AT_BASELINE 校验失败文案与基线不等价：基线 `run_migration` 抛 `"Database schema verification failed for unified baseline:\n  - " + detail`（无尾句），新执行器统一追加 `"\nThe database was not modified."`（`baseline.py:execute_migration` 校验失败分支）；启动入口原文案本就含该尾句、未变，拒绝语义与异常类型（SchemaValidationError）亦未变，但 progress.md「既有错误文案不变」的表述对这一条路径不准确。|src/mail_core/db/baseline.py execute_migration|
|t099_code_f002|minor|遗留|离线入口 UPGRADE_TO_HEAD 行为变化未在实施笔记中登记：基线 `run_migration` 在检查连接内对所有计划先跑 `stamp_unified_baseline(conn, dry_run=True)`，其 `_stamp_targets` 对「已知较旧 revision（非 0001、非 head、非窄转换 legacy）」会抛 `Refusing to overwrite alembic_version …`，即旧离线入口（含 dry-run）对如 0007 的库实际拒绝；新执行器删除该预检，离线与启动一致地走 `upgrade_head_and_verify` 升级。此变化与 AC-001「已知较旧 Alembic revision 可继续增量升级」的统一意图一致、且属修复旧入口潜在误拒，但确为可观察行为 delta。|src/mail_core/db/baseline.py execute_migration（对比基线 run_migration）|
|t099_code_f003|minor|遗留|写分派对 LEGACY 采用消去法：`execute_migration` 在 EMPTY/AT_BASELINE/UPGRADE_TO_HEAD 分支 return 后，剩余代码默认即 LEGACY 而无显式 `plan.action is LEGACY` 判断；未来新增 MigrationAction 若忘记加分支会静默落入窄转换路径。现有缓解：`apply_narrow_legacy_conversion` 在写事务内重读 revision 并拒绝非窄转换 revision，故不会误写；仍建议显式分支＋未知 action 抛错。|src/mail_core/db/baseline.py execute_migration 写分派段|

## 逐项核查（无 finding 部分）

- **执行器真正统一**：`src/mail_core/__main__.py:run_migrations` 只余 URL 解析（`baseline.alembic_config()` + `database_url()` 兜底）与 policy/mode 选择后调 `baseline.execute_migration`，无 create_engine、无状态读取、无写分派；`baseline.run_migration` 只余 URL 解析/日志与 `execute_migration(OFFLINE_POLICY, DRY_RUN|WRITE)` 调用。检查（`read_only_connection` + `read_database_state` + `plan_migration` + `verify_for_plan`）、连接释放、写分派全部只在 `execute_migration` 一处。离线脚本 `scripts/migrate_to_unified_baseline.py` 未改、仍经 `run_migration` 进入。
- **MigrationPolicy 只承载入口差异**：仅 4 字段（`initialize_empty_database`、`legacy_verification_error`、`wrap_conversion_errors`、`replay_chain_at_baseline`），执行器内所有按入口分支都只读这 4 字段与 `mode`/`plan.action`；分类、校验、拒绝集 `_REFUSAL_ACTIONS`、转换后 `upgrade_head_and_verify` 均为双入口共用，未发现把分歧塞回入口适配层的代码（两适配层均无条件分支于 plan）。
- **错误文案与类型等价性**（除 f001/f002）：拒绝类（MULTIPLE/NO_VERSION/UNKNOWN/NEWER/LEGACY_UNSUPPORTED）双入口均以 plan.message 抛出，启动侧由基线的 RuntimeError 改为 SchemaValidationError——后者是 RuntimeError 子类（`baseline.py:265`），既有 `except RuntimeError` 调用方不受影响，文案逐字不变；LEGACY 校验失败双入口措辞经 policy 函数逐字复刻基线两份原文（启动版含 revision 与「matching historical release」段、离线版含「offline tool cannot reconstruct」段，已与基线源码逐字比对）；转换错误重包装仅启动入口（`wrap_conversion_errors=True` 时 SchemaValidationError → RuntimeError「…failed and was rolled back: … The database was not modified.」且 `from exc` 保留因果链），离线原样透传，与基线一致；AT_BASELINE 校验失败文案启动侧逐字不变。
- **AT_BASELINE 双写动作等价**：启动 `replay_chain_at_baseline=True` → `command.upgrade(cfg, "head")`（与基线启动一致，cfg 在执行器内以本次 URL 重设 `sqlalchemy.url`，与基线 `alembic_config()` 同源）；离线走 `_stamp_at_baseline`（新引擎 + `engine.begin()` + `stamp_unified_baseline(dry_run=False)` + dispose），与基线离线尾段逐行等价。
- **check 连接释放（含异常路径）**：`execute_migration` 的全部写分派都在 `with read_only_connection(...)` 块退出之后；`read_only_connection` 以 try/finally 保证 `conn.rollback()` 与 `engine.dispose()`，校验失败/分类拒绝在块内抛错时同样先回滚、销毁引擎再向上传播，且抛错路径不可能到达写分派。结构上不存在写连接先于检查连接释放打开的路径（另经 review_test 的真实 PG PID 观测与变异实验复证）。
- **窄转换事务内重验未动**：`apply_narrow_legacy_conversion` 本体未改（advisory lock 内重读 revision、从零 `verify_narrow_legacy_schema`、失败整事务回滚），执行器不复用检查结果。
- **范围**：改动文件限于 task 范围（`baseline.py`、`__main__.py` 迁移调用点、三份测试、t099 PG 测试新增）与契约声明的收尾项（blueprint architecture/testing 各 1 条、spec tasks 登记 t099、pending p109 登记官方 harness 复跑）；未动已支持版本名单、Alembic revision、schema 与 Worker 启动模式，无范围外改动。
- **既有测试处置正当性（代码侧）**：`test_sidecar_detection.py` 仅把 MULTIPLE fake 的 patch 点改指 `mail_core.db.baseline.create_engine`（`read_only_connection` 实际使用的作用域）并给 FakeConn 补 `rollback()`（只读管理器无条件调用），断言未动——属 patch 点随实现作用域迁移，非预期改写，处置正当（测试侧详见 review_test.md）。

## 结论

- 本轮新发现：3 条，均为 minor（f001 文案尾句、f002 离线升级行为 delta 未登记、f003 写分派消去法）；无 critical / important。
- 总体判断：统一执行器真实成立——单一检查/释放/分派、policy 只承载入口差异、关键错误文案与 AT_BASELINE 双写动作与基线等价、检查连接释放在结构上先于任何写连接。三条 minor 均为登记/健壮性层面，不改变契约行为，判定 PASS。
- 系统性 follow-up：f002 建议在 progress.md 实施笔记补记该行为 delta；f001/f003 可在后续 task 顺手收口，不阻塞本 task。

### AC 复验方式（实现层）

- AC-001：TICK-VALID，re_verified。核对 `execute_migration` EMPTY→`command.upgrade(head)`（仅 startup policy 放行）、LEGACY→窄转换→`upgrade_head_and_verify`、UPGRADE_TO_HEAD→`upgrade_head_and_verify` 三条写路径齐备，离线空库由 `initialize_empty_database=False` 以 plan.message 拒绝；测试证据见 review_test.md。
- AC-002：TICK-VALID，re_verified。核对写分派全部位于 `read_only_connection` 上下文退出之后且该上下文 finally 必 dispose（见上）；真实 PG PID 证据见 review_test.md。
- AC-003：TICK-VALID，re_verified。核对 CHECK_ONLY/DRY_RUN 在检查后直接 `return plan`、零写分派；漂移拒绝在检查段内抛出且双入口共用同一校验（LEGACY 走 policy 措辞、其余走统一基线文案）。
- AC-004：TICK-VALID，re_verified。核对窄转换本体未改、整事务语义保留，启动入口对 SchemaValidationError 的重包装保留 `__cause__`；回滚证据见 review_test.md。

coverage = 4 / 4

verdict: PASS

## Round 2 复核（2026-11-29T00:48:09+08:00，对象 c39baa66）

reviewed_scope: 53a4393166336e35

复核范围：仅 Round 1 的 4 条 minor finding 的修复属实性与回归（`git diff e653b16f..c39baa66`），不重审其余部分。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t099_code_f001|minor|已修属实|progress.md 实施笔记已改：删除原「既有错误文案不变」表述，新增 delta（1）如实登记离线入口 AT_BASELINE 校验失败文案与启动统一、尾部多出「The database was not modified.」一句。与代码核对一致：现 `execute_migration` 非 LEGACY 校验失败分支（`baseline.py:1289`）统一拼 `"\nThe database was not modified."`；基线离线 `run_migration` 同文案无尾句、基线启动入口 `__main__.py` 原文案本含该尾句，均与记载吻合；记载另注该句属实（校验失败在任何写入之前），成立。|docs/tasks/t099_unified_migration_executor/progress.md 实施笔记；src/mail_core/db/baseline.py execute_migration|
|t099_code_f002|minor|已修属实|progress.md 实施笔记新增 delta（2）：基线离线流程检查段内的 `stamp_unified_baseline(dry_run=True)` 预检对 0007 类已知较旧 revision 会误拒、统一后删除、离线与启动一致增量升级。与代码核对一致：基线 `run_migration` 对所有计划在检查连接内跑该预检，其 `_stamp_targets` 对非空、非 head、非窄转换 revision 抛 `Refusing to overwrite alembic_version …`；现 `execute_migration` 检查段已无此预检（`stamp_unified_baseline` 仅余 AT_BASELINE 写动作 `_stamp_at_baseline` 与窄转换事务内调用），UPGRADE_TO_HEAD 直达 `upgrade_head_and_verify`。记载的「属修旧误拒、与 AC-001 意图一致」定性成立。|docs/tasks/t099_unified_migration_executor/progress.md 实施笔记；src/mail_core/db/baseline.py execute_migration（对比基线 run_migration / \_stamp_targets）|
|t099_code_f003|minor|已修属实|写分派已改显式分支：`if plan.action is MigrationAction.LEGACY:` 包裹窄转换＋`upgrade_head_and_verify`，其后新增兜底 `raise AssertionError(f"no write dispatch for migration action {plan.action!r}")`。分派等价性核对：EMPTY/AT_BASELINE/UPGRADE_TO_HEAD 三分支与 Round 1 逐一对应且顺序、调用不变；LEGACY 分支内 `wrap_conversion_errors` 的重包装文案与 `from exc`、日志与升级调用均原样保留，仅缩进进显式分支；拒绝类 action 在检查段已抛错、非 WRITE 模式在分派前 return，故兜底对现有 action 不可达、不改变任何既有行为。复跑执行器单元测试 `test_baseline_unit.py`：26 passed。|src/mail_core/db/baseline.py execute_migration 写分派段|

- t099_test_f001（测试侧 finding）：代码核对见 review_test.md Round 2，本文件不重复判定。
- 本轮新 finding：无（未产生 t099_code_f004 及后续编号）。
- 本轮 overall：PASS。3 条代码侧 minor 修复全部属实、无回归；AC 判定维持 Round 1 结论。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。
- AC-002：TICK-VALID，re_verified。
- AC-003：TICK-VALID，re_verified。
- AC-004：TICK-VALID，re_verified。

（维持 Round 1 判定依据：本轮 diff 未触碰 AC-001/002 的写路径与连接释放结构，f003 分派等价性已逐分支核对且单元测试复跑通过；AC-003/004 证据链的 `_snapshot` 增强见 review_test.md Round 2。）

coverage = 4 / 4

verdict: PASS
