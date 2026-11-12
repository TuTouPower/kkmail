# Task review t076（reviewer_focus: 代码）

- task：`t076_account_sync_state_and_retry_architecture_refactor`
- spec：`docs/tasks/t076_account_sync_state_and_retry_architecture_refactor/task.md`
- diff_anchor：`20b61520c0837db9cd4c44506886bae6a507a1a2`
- target：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`
- round：1
- reviewed_at：2026-11-12T08:52:23+08:00

reviewed_scope: c9e5c824345c3cbe

## Findings

### t076_code_f001 - 改写统一基线 DDL 而非新增迁移，已有数据库升级后无法启动且无历史数据迁移

- 严重度：critical
- 锚点：AC-001 + 可观测行为缺陷（已有库升级后 schema 校验失败、应用拒绝启动）
- 位置：`src/mail_core/db/alembic/versions/20261107_0001_unified_baseline.py:85-87`、`src/mail_core/__main__.py:82-90`、`src/mail_core/db/baseline.py:647-648`、`src/mail_core/db/baseline.py:896-904`
- 问题：本 task 只把统一基线 `upgrade()` 中 `accounts` 表的 `sync_status` 列替换为三个新列（`src/mail_core/db/alembic/versions/20261107_0001_unified_baseline.py:85-87`），未新增任何 Alembic revision，也没有 `ALTER TABLE` / 旧值映射 / `downgrade()` 更新，也没有把 `auth_failed`→`credential_state=invalid, sync_enabled=false`、`failed`→`connectivity_state=degraded` 之类的历史数据迁移落地。Alembic 对 `alembic_version` 已标记 `20261107_0001` 的库不会重跑 `upgrade()`；而 `run_migrations` 对 `AT_BASELINE` 库在升级前强制 `verify_for_plan`→`verify_baseline_schema`，用新 ORM metadata 比对现有 catalog（`src/mail_core/__main__.py:82-90`，`src/mail_core/db/baseline.py:432-441`），旧库仍带 `accounts.sync_status` 且缺 `credential_state/connectivity_state/sync_activity`，必然报 `remove_column`/`add_column` 并抛 `RuntimeError("Database schema verification failed ... The database was not modified.")`，应用直接拒绝启动。`LEGACY` 库的 narrow conversion 在事务内同样会于 `verify_baseline_schema` 失败并整体回滚（`src/mail_core/db/baseline.py:896-904`），而 `verify_narrow_legacy_schema` 不检查 `accounts` 列（`src/mail_core/db/baseline.py:572-576`），所以转换无法通过。仅 `EMPTY_DATABASE` 走 `command.upgrade(cfg, "head")` 用新 DDL 建表成功——即实施侧给出的「upgrade head 成功、0 drift」证据只覆盖空库。AC-001 与 spec「范围」明确要求「提供完整的 Alembic 迁移脚本，安全完成历史数据迁移与字段替换」，spec「风险与回退」要求可回退恢复旧字段，实现三者皆无。附：`docs/blueprint/architecture.md`、`conventions.md`、`guides/troubleshooting.md` 已按新模型改写，但文档不能替代库结构升级路径。
- 建议：新增独立 Alembic revision 承载 `ALTER TABLE accounts`（drop `sync_status`、add 三列 + `server_default`）与历史 `sync_status` 值映射，并同步把 `UNIFIED_BASELINE_REVISION`、`baseline.py` 分类层与单 head 硬断言（`tests/mail_core/test_baseline_unit.py:37-38`、`tests/mail_core/test_migration_validation.py:93` 等）更新为新 head；这正是项目「拒绝妥协/从根因修正」应做的底层重构，不应以改写基线规避。若产品契约确实只支持空库重建，则必须在 `plan_migration`/`run_migrations` 显式拒绝已存在的 `20261107_0001` 库并给出重建指引，同时同步改写 AC-001 与 blueprint 的迁移约定，不能只改 DDL 而留下启动即失败的升级路径。补一条「已有 AT_BASELINE 库升级」的 PG 门禁用例。

### t076_code_f002 - 熔断器 unreachable 在真实指数退避下永不可达，AC-004 状态机是死分支

- 严重度：important
- 锚点：AC-004 + 可观测行为缺陷（`connectivity_state` 永远不会变成 `unreachable`）
- 位置：`src/mail_core/accounts/health.py:102-135`、`src/mail_core/sync/jobs.py:46-54`、`src/mail_core/sync/jobs.py:17`、`tests/mail_core/test_account_health_state_machine.py:64-78`
- 问题：`record_connectivity_failure` 仅在 `count >= 5 and elapsed >= 300s` 时置 `UNREACHABLE`（`health.py:129-131`），但 `count` 在 `(now - first) > 300s` 时被重置为 1（`health.py:122-126`），且 `first` 固定为首次失败时刻，两者互斥。真实链路中 `record_connectivity_failure` 由每次 job 失败触发，重试间隔由 `backoff_seconds(failure_attempts)` 给出（1,2,4,8,16,32,64,128s），`DEFAULT_MAX_ATTEMPTS=8`（`src/mail_core/sync/jobs.py:17`），第 8 次失败即 `reschedule_job(count_failure=True)` 命中 cap 转 `fail_job` 终态。独立按该序列复算：累计时长最大 127s（t=0,1,3,7,15,31,63,127），`count` 最高 8，`elapsed` 始终 < 300s，8 次全部 `DEGRADED`；即便把 cap 调大，第 10 次起 `now-first > 300s` 触发 `count=1` 重置，仍不可能同时满足两个条件。结果 `unreachable` 是死状态：`Sidebar.tsx:194-198`、`SettingsModal.tsx:20-27`、`MessageList.tsx:195/229`、`queries.py:507-514` 与 blueprint/troubleshooting 中依赖 `unreachable` 的分支永不生效。支撑打勾的测试 `test_connectivity_failure_breaker_escalates_after_five_failures_across_window` 手工喂 `now=(0,60,120,180,300)` 伪造了生产不可能出现的均匀 60s 失败节奏（`test_account_health_state_machine.py:67-75`），未触达真实 backoff 时序，属于假绿，不足以支撑 AC-004 打勾。
- 建议：把「连续失败计数」与「持续时长」解耦（超窗时不要重置已累计的连续失败次数，或改用滑动窗口计数/独立时间戳），保证 `unreachable` 在 `DEFAULT_MAX_ATTEMPTS` 的 backoff 序列内可达；补一条按真实 `backoff_seconds` 序列推进 `now`、断言第 N 次失败升级为 `unreachable` 的测试，替换手工均匀时序。

### t076_code_f003 - 401 / AUTHENTICATIONFAILED / invalid_grant 在周期同步主路径无法识别为认证失效

- 严重度：important
- 锚点：AC-005 + 可观测行为缺陷（确凿认证失效不置 `credential_state=invalid`、不置 `sync_enabled=false`）
- 位置：`src/mail_core/sync/context.py:73-104`、`src/mail_core/sync/delta.py:537-550`、`src/mail_core/sync/reconcile.py:216-227`、`src/mail_core/security/redact.py:58-86`、`src/mail_core/providers/oauth.py:374-384`
- 问题：AC-005 点名三种信号。`_AUTH_MARKERS`（`context.py:73-81`）只有 `auth_failed/authenticationfailed/invalid_grant/invalid credentials/basic auth disabled/unauthorized/permanentautherror`，**没有 `401`**，也没有 `InvalidAuthenticationToken` 等 Graph 401 错误码。更关键的是 `delta.py`（周期 inbox sync 的主路径，由 `worker/main.py:279` 入队）与 `reconcile.py` 把 provider 异常经 `safe_provider_summary(exc)` 压成受控摘要后返回 `{"status": "provider_error", "error": <摘要>}`（`delta.py:537-550`、`reconcile.py:216-227`）；`safe_provider_summary`/`safe_error` 明确丢弃 HTTP body 与错误消息，只保留「异常类名 + status」（`redact.py:58-86`、`:162-173`），于是 HTTP 401 变成 `ProviderHttpError status=401`、IMAP `AUTHENTICATIONFAILED` 变成 `IMAP4.error`、token endpoint 的 `invalid_grant` 变成 `ProviderHttpError status=400`。`_apply_account_health`→`account_failure_kind` 对这种 dict 走 `is_permanent_auth_error` 的 dict 分支（`context.py:97-101`），上述摘要均不含任何 auth marker，也不含 transient marker，分类恒为 `NONE`：账号 `credential_state` 保持 `valid`、`sync_enabled` 保持 `true`，job 只是按 `reschedule_job(count_failure=True)` 重试到 cap 后 `FAILED`，前端永不渲染「凭据已失效，请重新授权」。只有异常对象恰好是 `PermanentAuthError`（类名含 `permanentautherror` marker）时才能命中；`engine.py` 的 `raise` 路径能靠异常对象 `str` 命中 `authenticationfailed`/`invalid_grant`，但 401 的 body 典型为 `InvalidAuthenticationToken`，仍不匹配。支撑打勾的 `test_account_failure_kind_classifies_transport_auth_and_control_flow` 用 `PermanentAuthError("invalid_grant")` 构造（`test_account_health_state_machine.py:132-137`），未覆盖任何真实 401 / `AUTHENTICATIONFAILED` / `invalid_grant` 信号形态。
- 建议：在 provider 层把 401、`AUTHENTICATIONFAILED`、不可刷新的 `invalid_grant` 统一收敛成 `PermanentAuthError`（或携带结构化 `error_code` 的异常），让 `is_permanent_auth_error` 基于异常类型/结构化字段判定而不是脱敏后的文本；`_AUTH_MARKERS` 至少补 `401` 与 `InvalidAuthenticationToken`；避免 `delta.py`/`reconcile.py` 把认证信号压成类名后再分类。补一条以真实 `ProviderHttpError(status=401)` 经 `sync_folder_delta` 全链路断言 `credential_state == invalid` 的测试。

### t076_code_f004 - 终态失败路径不复位 sync_activity，账号永久停在 syncing

- 严重度：important
- 锚点：AC-001（`sync_activity` 的 idle/syncing 语义）+ 可观测行为缺陷（状态不一致）
- 位置：`src/mail_core/worker/handlers.py:283-284`、`src/mail_core/worker/handlers.py:193-195`、`src/mail_core/worker/handlers.py:224-232`、`src/mail_core/worker/handlers.py:461-467`、`src/mail_core/sync/jobs.py:465-467`
- 问题：每个账号同步 job 开始时无条件 `set_sync_activity(active=True)`（`handlers.py:283-284`），而复位 `set_sync_activity(active=False)` 的 `_finish_activity` 只在 `_evaluate_result` 的三个分支调用（`handlers.py:210`、`:236`、`:242`）。`provider_error` 分支（`handlers.py:224-232`）与 generic except 分支（`handlers.py:461-467`）在 `reschedule_job(count_failure=True)` 后直接 `return False`，都不调用 `_finish_activity`；当 `failure_attempts` 达 cap 时 `reschedule_job` 内部直接 `fail_job` 置 job 为 `FAILED` 终态后 return（`jobs.py:465-467`），链路同样跳过 `_finish_activity`。结果：job 已终态、不再有在途同步，账号 `sync_activity` 仍为 `syncing`，`SettingsModal.tsx:accountHealth` 因此持续显示「同步中」，直到该账号恰好有一个成功 job 或用户重新授权/禁用才复位。全仓 `sync_activity` 写入点仅 health.py / service.py / handlers.py（已 grep 确认），无巡逻任务兜底复位。
- 建议：在 `handle_job` 层做统一收尾（`finally` 或按 `job.status` 是否为终态判断）调用 `_finish_activity`，保证 DONE/FAILED 都复位；或在 `reschedule_job(count_failure=True)` 的 cap→`fail_job` 分支内一并复位，并补一条「重试耗尽后 `sync_activity == idle`」的断言。

### t076_code_f005 - reschedule_job(count_failure=True) 与 fail_job 重试逻辑重复且已产生行为分叉

- 严重度：minor
- 锚点：行为缺陷（同一重试语义两套实现，`retry_after_seconds` 处理分叉）
- 位置：`src/mail_core/sync/jobs.py:460-487`、`src/mail_core/sync/jobs.py:523-556`
- 问题：`count_failure=True` 分支重新实现了一遍 `fail_job` 已有的逻辑：`failure_attempts+1`、`safe_error`、`backoff_seconds`、`_backoff_until` stamp、`PENDING` + `locked_by/locked_at` 清空、`settle_job_bindings(outcome="retriable")`（`jobs.py:463-487` vs `jobs.py:526-555`）。重复已产生分叉：`fail_job` 会读取 `error.retry_after_seconds` 并放大 delay（`jobs.py:534-540`），`reschedule_job` 分支忽略该字段；`job.last_error` 在 `error is None` 时前者写 `safe_error(error) or None`、后者保留旧值。当前调用点（generic except 已在 `is_capacity_error` 处拦截 capacity/rate-limit、其余传脱敏字符串或普通异常）使分叉暂未造成可观测故障，但属明确的修复遗漏风险，后续任一侧改动都会让重试调度行为不一致。
- 建议：`count_failure=True` 直接委托 `fail_job`（其已完整实现计数/退避/`retry_after_seconds`/cap/终态/绑定结算），`reschedule_job` 只保留控制流 deferral 语义，消除重复与分叉。

## 结论

- 本轮新发现：5 条（1 critical / 3 important / 1 minor）
- 未进表的提示：
    - 文件过大：`src/mail_core/accounts/health.py`（161 行）、`src/mail_core/sync/context.py`（148 行）、`tests/mail_core/test_account_health_state_machine.py`（188 行）均远低于 400/600 阈值，无命中。
    - 圈复杂度：`_evaluate_result`、`record_connectivity_failure`、`is_permanent_auth_error`、`is_transient_network_error` 手算均 < 10，无命中。
    - 字符串启发式误判风险（`context.py:73-81`）：`is_permanent_auth_error` 仅靠文本 marker，且 `unauthorized` 与 `is_transient_network_error` 的 `connection` 可能同现于非认证错误文本，理论上会把网络错误误判为 AUTH 并置 `sync_enabled=false`，违反 AC-005 反向约束；未找到具体生产输入，低置信度，仅提示。
    - `health.py:53`、`:130` 在 `mark_credential_invalid` / `record_connectivity_failure` 失败路径也写 `cfg["last_synced_at"]`，「最后同步时间」语义不准，仅提示。
    - `resolve_sync_context` 对顶层 `background` 提前 `return True, None` 丢弃 `request_id`（`context.py:61-62`）；现有两个调用点均忽略该返回值（`handlers.py:170`、`:282`），无回归，仅提示后续若复用 `request_id` 需留意。
    - `docs/blueprint/architecture.md`、`conventions.md` 在 task 执行期即更新（spec 标注为 Finalization 时更新），属流程轻微提前，内容与实现一致，不评缺陷。
    - API 破坏性变更（`AccountOut` 移除 `sync_status`、加四字段）已同步 `schemas/openapi.json`、`src/frontend/src/api/generated/schema.ts` 与 guides/blueprint，前端 `sync_status` 残留均为 Folder 级与对应 schema，契约闭环。
    - 既存门禁失败（`test_check_dep_locks`、`test_check_doc_sensitive`）与 p075 真实邮箱脱敏属背景说明范围，未计入本轮 finding。
    - 新增文件 `src/mail_core/accounts/health.py`、`tests/mail_core/test_account_health_state_machine.py` 已以 `git add -N` 出现在 diff 中，`git status --short` 无 reviewer 不可见的未跟踪交付文件。
- 总体判断：FAIL，4 条 blocking finding（f001 critical / f002 f003 f004 important）未解决，AC-001 / AC-004 / AC-005 打勾作废。
- 系统性 follow-up：无（本轮阻塞均属本 task 交付范围，应由实施方修复后走完整下一轮审阅）。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。`models.py:111-123` 与基线 DDL 确实移除 `sync_status` 并加三列带 server_default，但只改写统一基线、无新增 revision/历史数据迁移/回退脚本，已有库经 `__main__.py:82-90` 校验必然启动失败；且 f004 的 `sync_activity` 终态不复位破坏该列语义。
- AC-002：TICK-VALID，re_verified。`delta.py:537-550` 删除私有 `enqueue_job` + 伪 done，`handlers.py:224-232` 与 `:461-467` 统一 `reschedule_job(count_failure=True, ...)`，`jobs.py:463-487` 保留原 job ID、递增 `failure_attempts`、按 `backoff_seconds` 退避、cap 转 `fail_job`；`attempts` 由 `claim_jobs` 在 `jobs.py:287` 下次认领递增（框架既有机制）。
- AC-003：TICK-VALID，re_verified。`worker/main.py:279` 周期任务 payload 注入 `{"background": True}`，`context.py:61-62` 识别并返回 `(True, None)`，`account_failure_kind` 对 background+transport 返回 `NONE`（`context.py:146-147`），不外溢账号状态。
- AC-004：TICK-VOID，re_verified。`health.py:102-135` 的 `count>=5 且 elapsed>=300s` 两个条件在 `DEFAULT_MAX_ATTEMPTS=8` 的真实 backoff 序列（累计 127s）下互斥，`unreachable` 为死分支；`test_account_health_state_machine.py:64-78` 用手工均匀 60s 时序伪造通过。
- AC-005：TICK-VOID，re_verified。`_AUTH_MARKERS` 无 `401`，且 `delta.py`/`reconcile.py` 经 `safe_provider_summary` 把 401/`AUTHENTICATIONFAILED`/`invalid_grant` 压成 `ProviderHttpError status=401`/`IMAP4.error` 后恒分类为 `NONE`，周期同步主路径不置 `credential_state=invalid`、不置 `sync_enabled=false`。
- AC-006：TICK-VALID，re_verified。`api/accounts.py:65-68` 的 `AccountOut` 含四字段且无 `sync_status`，`api/accounts.py:247` 用 `AccountOut(**asdict(a))` 透传 `health_fields` 投影，`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 已同步。
- AC-007：TICK-VALID，re_verified。`Sidebar.tsx:190-201`、`:1171` 与 `SettingsModal.tsx:20-33`、`:488` 移除硬编码「同步失败，请检查账户设置」（grep 确认 `src/` 下无残留），仅 `invalid` 渲染红标、degraded/unreachable 渲染网络态；后台 transport 因 `account_failure_kind` 返回 `NONE` 不写 `connectivity_state`，故不触发侧栏报警。

coverage = 7 / 7

verdict: FAIL

______________________________________________________________________

## Round 2 (2026-11-12T09:41:11+08:00)

reviewed_scope: 608ceb911baf7f05

- 复核基线：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`（含 `git add -N` 的 `src/mail_core/accounts/health.py`、`src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py`、`tests/mail_core/test_account_health_state_machine.py`）；落点校验 `git rev-parse --show-toplevel` 通过；`git status --short` 中两份 `review_*.md` 为 reviewer 产物，无 reviewer 不可见的未跟踪交付文件。

## Findings

### t076_code_f006 - LEGACY 库升级路径仍会在转换事务内被新 ORM 的基线校验拒绝（f001 残留）

- 严重度：important
- 锚点：AC-001（「提供完整的 Alembic 迁移脚本，安全完成历史数据迁移与字段替换」）+ 可观测行为缺陷（stamp 在 `20261031_0030` / `20261107_0031` 的已有库经 `python -m mail_core` 启动即抛 RuntimeError，schema 未升级）
- 位置：`src/mail_core/db/baseline.py:905`、`src/mail_core/db/baseline.py:1019-1039`、`src/mail_core/__main__.py:119-127`、`src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py:26-49`
- 问题：Round 1 f001 的两条升级路径只修了第一条。新增的 `UPGRADE_TO_HEAD` 分支（`baseline.py:1020-1030`）仅覆盖 `current in context.known_revisions or current == UNIFIED_BASELINE_REVISION`，即 stamp=`20261107_0001` 的库；`test_startup_migrations.py::test_t7` 真实 PG 验证的正是这条路径（建 0001 基线 → 插 `auth_failed`/`failed` 两行 → `run_migrations()` → 断言 head、列与数据映射），证据成立。但 `NARROW_CONVERSION_LEGACY_REVISIONS`（`baseline.py:98-101`）的 `20261031_0030` / `20261107_0031` 不在 `known_revisions`，`plan_migration` 落入 `LEGACY`（`baseline.py:1041-1050`），`__main__.py:119-127` 调 `apply_narrow_legacy_conversion`。该函数在事务内 `:905` 无条件 `verify_baseline_schema(conn)`，而 `_baseline_metadata()`（`baseline.py:314-325`）取当前 ORM `Base.metadata`，即已移除 `sync_status`、新增三列的**新** schema；LEGACY 库 catalog 按 `baseline.py:94-97` 注释是「统一基线减 `folder_patrol_status`」，即 `20261107_0001` DDL 的 `accounts.sync_status` 形状（该基线 DDL `:85` 仍建 `sync_status`）。`compare_metadata` 会报 `add_column` 三列 + `remove_column accounts.sync_status`，`_is_ignored_baseline_diff`（`baseline.py:354-361`）只忽略 `message_search.document` 与若干索引，三类均不被忽略 → 抛 `SchemaValidationError` → 事务整体回滚 → `__main__.py:121-125` 抛「Legacy conversion ... failed and was rolled back」，应用拒绝启动，0002 的 `ALTER TABLE` 与历史值映射根本没机会执行。门禁未覆盖此路径：`test_migration_validation.py:586-628` 的 `_pg_build_0030_shape` 用 `command.upgrade(cfg, "head")` 建的是 0002 新 schema 再把 stamp 改成 0030，故 `test_concurrent_narrow_conversion_is_serialized_on_postgres`（`:706-737`）能通过，与真实 0030 库形状不符。
- 建议：让 LEGACY 转换路径与 0002 增量升级衔接：转换后的 post-conversion 校验按 0001 基线形状比对（或把 accounts 三列的 add/remove 列为该阶段允许差异），stamp 到 0001 后由 `command.upgrade(cfg, "head")` 执行 0002；或把 LEGACY 也纳入「跳过预校验、直接 upgrade head」的分类并先跑一个把旧 schema 对齐到 0001 的 revision。补一条真实 0030 形状（含 `accounts.sync_status`）的 PG 启动升级用例。

### t076_code_f007 - 凭据失效后残留的重试 job 命中 sync_enabled 早退分支，sync_activity 永久停在 syncing（f004 残留）

- 严重度：important
- 锚点：AC-001（`sync_activity` 的 idle/syncing 语义）+ 可观测行为缺陷（job 已终态、账号已禁用，`accounts.sync_activity` 仍为 `syncing` 且被持久化）
- 位置：`src/mail_core/worker/handlers.py:285-286`、`src/mail_core/worker/handlers.py:298-302`、`src/mail_core/worker/handlers.py:224-234`、`src/mail_core/accounts/health.py:44-57`
- 问题：f004 的终态修复只覆盖 `_evaluate_result` 的 `provider_error` 分支与 generic except（`:232-233`、`:470-471` 在 `job.status == FAILED` 后调 `_finish_activity`），主路径已复位。但账号认证失效的完整链路会绕过它们：前台 job 抛确凿认证异常 → `_apply_account_health` 调 `mark_credential_invalid`（`health.py:50-52`）置 `credential_state=invalid`、`sync_enabled=False` 并复位 `sync_activity=IDLE` → `_evaluate_result` 的 `provider_error` 分支 `reschedule_job(count_failure=True)` → `fail_job`（`src/mail_core/sync/jobs.py:520-544`）在 `failure_attempts < cap` 时把**同一 job 行**重新置为 `PENDING` 退避重试；账号已禁用，该重试 job 下次被认领时 `_handle_job_impl` 先在 `:285-286` 无条件 `set_sync_activity(active=True)`，随后 `:298-302` 因 `not acc.sync_enabled` 直接 `complete_job` + `return True`，**不经过 `_evaluate_result`、不调 `_finish_activity`**；`handle_job` 返回后由 worker 主循环提交，`sync_activity` 永久停在 `syncing`，直到该账号恰好产生一次成功 job。前端 `src/frontend/src/components/SettingsModal.tsx:30-36` 与 `src/frontend/src/components/Sidebar.tsx:192-199` 因 `credential_state === 'invalid'` 优先级最高，UI 显示「认证失败」而非误导性的「同步中」，故未造成可见误报；但 API 的 `sync_activity` 字段值与真实执行态不一致，违反 AC-001 该列语义，且 `reset_credential`（`health.py:60-69`）不复位该列，重新授权后仍沿用脏值。
- 建议：把 `_finish_activity` 提到 `_handle_job_impl` 的统一收尾（`finally` 或按 `job.status` 终态判定），覆盖所有 return 分支；至少在 `:298-302` 早退分支补一次 `_finish_activity(session, job)`，并补断言「认证失效后残留重试 job 完成，`sync_activity == idle`」。

## 结论

- 前轮 finding 复核：
    - f001（critical）：**修不彻底 / 仍存在**。主路径（空库、stamp=0001 的 AT_BASELINE 库、已升级库）已由新增 revision 0002 + `UPGRADE_TO_HEAD` + `_stamp_targets` head noop（`baseline.py:691-693`）+ 离线工具指引（`baseline.py:1138-1148`）+ `test_t7` 真实 PG 修复；统一基线文件恢复原样（diff 不再含 `20261107_0001_unified_baseline.py`），单 head 硬断言同步到 `tests/mail_core/test_baseline_unit.py:37-38`、`tests/mail_core/test_migration_validation.py:96`、`tests/mail_core/test_outbox_retention_unit.py:441`。但 LEGACY narrow-conversion 路径仍失败，见 f006。前轮 blocker 未完全消除。
    - f002（important）：**已消除**。`health.py:130-141` 失败计数单调累计、仅 `record_connectivity_success`（`:92-95`）清零、`first` 不因超窗重置；`tests/mail_core/test_account_health_state_machine.py:214-231` 按 `backoff_seconds` 序列推进 8 次后跨 20 分钟窗口断言 UNREACHABLE，`:234-253` 覆盖次数/窗口两个负向边界，死分支消除。
    - f003（important）：**已消除（主链路）**。`context.py:87-114` 识别 `PermanentAuthError`、`status==401`、`error_code="auth_failed"` 及 `invalid_grant`/`InvalidAuthenticationToken` 等结构化信号；`delta.py:554-555` / `reconcile.py:229-230` 在脱敏摘要外携带 `error_code`；`imap.py:814-841` 把 EXPIRED/AUTHENTICATIONFAILED/AUTHORIZATIONFAILED/INVALID CREDENTIALS 转 `PermanentAuthError` 并排除「too many login attempts」等临时锁定；`test_auth_signals_are_classified_structurally`（`:190-211`）与 IMAP 参数化用例（`tests/mail_core/test_imap_id_handshake.py:216-236`）覆盖正负形态。残留低置信度风险见下方提示。
    - f004（important）：**主路径已消除，遗漏分支见 f007**。`handlers.py:232-233`、`:470-471` 在 `job.status == FAILED` 后调 `_finish_activity`，`:238`、`:244` 覆盖 complete/fail 终态；`fail_job`（`jobs.py:546-549`）确实在同一 job 对象上置 `FAILED` 并 flush，判定成立。但 `:298-302` 早退分支未覆盖。
    - f005（minor）：**已消除**。`jobs.py:460-465` 的 `count_failure=True` 直接委托 `fail_job`，`retry_after_seconds` 放大（`jobs.py:522-528`）、cap 终态、绑定结算、`_backoff_until` stamp 全部收敛到单一实现，保留 `now` 注入；`test_reschedule_job_count_failure_keeps_id_and_counts_failure`（`:155-187`）验证保留 job ID 与 `failure_attempts`。
- 本轮新发现：2 条（2 important / 0 critical / 0 minor）。
- 未进表的提示：
    - 落点校验 `git rev-parse --show-toplevel` 输出精确等于 worktree 根，通过；新交付文件均已 `git add -N` 出现在 diff 中。
    - 文件过大（依降级规则不进 finding 表，仅列路径与行数；均为既存大文件、本 task 净增 4~48 行）：`src/mail_core/providers/imap.py` 1797、`src/frontend/src/components/Sidebar.tsx` 1519、`src/frontend/src/components/Sidebar.test.tsx` 1373、`src/mail_core/db/baseline.py` 1188、`src/frontend/src/components/SettingsModal.test.tsx` 1222、`src/mail_core/sync/jobs.py` 659、`src/frontend/src/components/SettingsModal.tsx` 648、`src/mail_core/mail/storage/models.py` 612、`src/mail_core/mail/application/queries.py` 537。`src/mail_core/worker/handlers.py` 472 行净减 3 行、`src/mail_core/sync/delta.py` 663 行净减 9 行、`src/mail_core/sync/engine.py` 782 行净减 31 行，未命中。
    - 圈复杂度：`record_connectivity_failure`、`is_permanent_auth_error`、`is_transient_network_error`、`_evaluate_result`、`_apply_account_health` 手算均 < 10，无命中。
    - 文本启发式残留（低置信度）：`_AUTH_MARKERS`（`context.py:73-84`）含 `"unauthorized"` / `"status=401"`，任何非邮箱凭据来源的 401（如中间代理认证）会被判 AUTH 并置 `sync_enabled=False`，与 AC-005「仅在远端服务商确凿返回」的反向约束存在张力；`safe_provider_summary` / `safe_error`（`src/mail_core/security/redact.py:58-86`、`:89-174`）丢弃响应体，OAuth token endpoint 的 `invalid_grant` 仅在 `str(exc)` 内字面出现该串时才命中（RFC 6749 常规 JSON body 命中，但 body 为空或错误码仅在结构化字段时可能漏判）。未找到确定生产输入，仅提示。
    - 状态机可达性张力（非缺陷）：`account_failure_kind` 对 background+transport 返回 `NONE`（`context.py:156-157`），后台周期同步（t076 主链路）的网络抖动不写 `connectivity_state`；`unreachable` 实际可达依赖前台任务重复失败跨 5 分钟窗口。属 AC-003 故障域隔离与 AC-004 熔断的既定取舍，未出 finding。
    - 维护风险：`CURRENT_HEAD_REVISION`（`baseline.py:43`）为硬编码常量，新增 revision 时须同步更新该常量与 `tests/mail_core/test_outbox_retention_unit.py:441`、`tests/mail_core/test_sync_execution_unit.py:56` 的硬编码 head；`revision_context` 的 `heads` 动态取自 `ScriptDirectory`（`baseline.py:944-949`），不依赖该常量，当前无行为缺陷，仅提示。
    - 契约闭环：`schemas/openapi.json:217-221`、`:298`、`:379`、`:393-395` 与 `src/frontend/src/api/generated/schema.ts` 已含四字段并从 `AccountOut` 移除 `sync_status`（`:113`、`:144` 的残留属 Folder 级 schema）；后端 `sync_status` 残留全为 Folder 级（`models.py:141` 等），`_recover_account_sync_status` 全仓零引用，AC-004 废除扫表补丁成立。
    - 既存门禁失败（uv lock 漂移、历史 review 文档敏感误判）与实施侧「最终全量 PG 门禁后台运行中」均非 reviewer 独立复验证据；本轮 AC 判定以 diff、代码、测试断言本身与定向 PG 用例 `test_t7` 为准。
- 总体判断：FAIL。f001 未完全消除（LEGACY 升级路径仍拒绝启动），且本轮新增 2 条 important（f006 / f007）；AC-001 打勾作废。非 INCOMPLETE：本报告指纹 `608ceb911baf7f05` 与当前 worktree 一致（已用 `monitoring.review_scope_fingerprint` 与 `review_status.current_scope_fingerprint` 双重重算），无 reviewer 不可见的未跟踪交付文件，AC 覆盖完整。附：`task.py review-status` 当前报 `review_scope=stale` 系 `review_test.md` 仍是 Round 1 指纹（未出 Round 2），与本 code 报告无关，待 test reviewer 追加后自然消除；按 `evaluate_review` 判定 FAIL 时不因 stale 升级为 INCOMPLETE。
- 系统性 follow-up：无（f006 / f007 均落在本 task 交付范围，应由实施方修复后走完整下一轮审阅）。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。`models.py:111-123` 与 0002 revision 完成三列替换、`auth_failed`/`failed` 历史值映射与 `downgrade()` 回退，`test_t7` 真实 PG 验证；但 f006 的 LEGACY 库升级路径仍被 `baseline.py:905` 校验拒绝、f007 的 `sync_activity` 早退分支不复位，迁移/状态语义不完整。
- AC-002：TICK-VALID，re_verified。`delta.py:537-550` 删除私有 `enqueue_job` + 伪 done，`handlers.py:224-234`、`:463-469` 统一 `reschedule_job(count_failure=True)`，`jobs.py:460-465` 委托 `fail_job` 保留原 job ID、递增 `failure_attempts`、按 `backoff_seconds` 退避并 honour cap；`attempts` 由 `claim_jobs` 下次认领递增。
- AC-003：TICK-VALID，re_verified。`worker/main.py:2287` 周期 payload 注入 `{"background": True}`，`context.py:61-62` 识别返回 `(True, None)`，`account_failure_kind` 对 background+transport 返回 `NONE`（`context.py:156-157`），不外溢账号状态。
- AC-004：TICK-VALID，re_verified。`health.py:130-141` 单调计数 + `first` 保持 + 仅成功清零使 UNREACHABLE 不再死分支，`test_connectivity_breaker_escalates_across_realistic_backoff` 按真实 backoff 序列验证；`record_connectivity_success`（`:81-99`）恢复 connected；`_recover_account_sync_status` 全仓零引用。
- AC-005：TICK-VALID，re_verified。`context.py:87-114` + `delta.py:554-555`/`reconcile.py:229-230` 结构化 `error_code` + `imap.py:814-841` 转 `PermanentAuthError` 并排除临时锁定，`mark_credential_invalid`（`health.py:44-57`）置 invalid 与 `sync_enabled=False`；非认证 transport 经 `is_transient_network_error` 不触碰 `credential_state`。
- AC-006：TICK-VALID，re_verified。`api/accounts.py:65-68` 的 `AccountOut` 含四字段且无 `sync_status`，`api/accounts.py:247` 用 `AccountOut(**asdict(a))` 透传 `health_fields` 投影，`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 同步。
- AC-007：TICK-VALID，re_verified。`SettingsModal.tsx:30-36`、`:488` 与 `Sidebar.tsx:192-199`、`:1171` 移除硬编码「同步失败，请检查账户设置」（`src/` 下无残留），invalid 优先渲染凭据失效、degraded/unreachable 渲染网络态；后台 transport 因 `account_failure_kind` 返回 `NONE` 不写 `connectivity_state`，不触发侧栏报警。

coverage = 7 / 7

verdict: FAIL

______________________________________________________________________

## Round 3 (2026-11-12T10:22:39+08:00)

reviewed_scope: 3c71f762ee403df4

- 复核基线：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过；`HEAD` == `diff_anchor` == `20b61520c0837db9cd4c44506886bae6a507a1a2`（交付内容全部为工作树未提交改动，`git diff <anchor>` 为累计视图）；指纹经 `monitoring.review_scope_fingerprint` 重算 = `3c71f762ee403df4`，与注入值一致（`review_code.md` / `review_test.md` 属 `REVIEW_PROCESS_FILES`，写入不计入指纹）。`git status --short` 所有交付文件为 `M` / `A`（已 `git add -N`，含 `20261112_0002_account_health_states.py`、`health.py`、状态机测试），`??` 仅两份 `review_*.md`（reviewer 产物），无 reviewer 不可见的未跟踪交付文件，不作 INCOMPLETE。审查对象为 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 全量累计视图（79 文件，+1780/-576）。

## Findings

### t076_code_f008 - 统一终态收尾未完全落地：`_evaluate_result` 残留 3 处 `_finish_activity`，retriable 分支 `sync_activity` 取值分叉

- 严重度：minor
- 锚点：行为缺陷（同一 PENDING 退避重试态下 `sync_activity` 不一致 + 控制流重复），非 AC 违反；不阻断
- 位置：`src/mail_core/worker/handlers.py:210`、`:236`、`:242` 与 `:256-264`（尤其 `:263-264`）；对照 `:224-232`、`:241-242`
- 问题：本轮修复自述为「`handle_job` 在 `finally` 中当 `job.status in (DONE, FAILED)` 统一调 `_finish_activity`；移除 `_evaluate_result` 与 generic except 两处零散终态检查」。实际交付：generic except（`:443-475`）确无 `_finish_activity`，`handle_job` 的 `finally`（`:256-264`）已落地；但 `_evaluate_result` 仍保留 3 处**无条件** `_finish_activity`（`:210` capacity+followup 完成、`:236` ok/sync_disabled/skipped/rate_limited 完成、`:242` `fail_job` fall-through），与 `finally` 对 DONE/FAILED 重复调用（`set_sync_activity` 幂等，仅多一次 UPDATE）。可观测分叉在 `:241-242`：`fail_job`（`src/mail_core/sync/jobs.py:520-544`）在 `failure_attempts < cap` 时把同一 job 置 PENDING 退避重试，`:242` 无条件复位 `sync_activity=idle`；而 `:224-232` 的 `provider_error` 经 `reschedule_job(count_failure=True)` → `fail_job` 同样得到 PENDING，却不复位、`finally` 因非终态也不动作，`sync_activity` 保持 `syncing`。`lease_busy` / `fencing_mismatch` / `cursor_invalid` / `scan_generation_mismatch` 等状态（`delta.py` / `engine.py` / `reconcile.py` 返回）走 `:241`，与 `provider_error` 同为「PENDING 退避中」却一个 idle、一个 syncing。f007 的永久 stuck 已由早退分支经 `finally` 复位解决（新 PG 用例 `tests/mail_core/test_worker_loop.py:746-785` 覆盖），此为残留清洁度问题。
- 建议：移除 `_evaluate_result` 三处 `_finish_activity`，只保留 `handle_job` `finally` 一处；PENDING 统一语义（保持 `syncing`，或在 `finally` 对 PENDING 一并复位，二者择一），消除重复与分叉。非阻断，implementer 在 `progress.md` 处置表登记即可。

## 结论

- 前轮 finding 复核（以 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 与工作树代码为准，不采信处置表自称「已修」）：
    - **f006（R2 important）：已消除（根因修复）**。`apply_narrow_legacy_conversion`（`src/mail_core/db/baseline.py:908-957`）的转换事务内 post-conversion 校验改为 `verify_baseline_schema(conn, ignore_account_column_drift=True)`（`:949`）；`verify_baseline_schema`（`:404-449`）新增 `ignore_account_column_drift` 形参并在 `:446-447` 仅对 `_is_account_column_drift` 命中项跳过；`_is_account_column_drift`（`:460-485`）豁免范围严格限定 `diff[2]=="accounts"` 且列为 `sync_status` / `credential_state` / `connectivity_state` / `sync_activity`（`_ACCOUNT_HEALTH_COLUMNS`，`:452-457`）的 `add_column` / `remove_column` / `modify_nullable` / `modify_type`。独立用真实 Alembic `compare_metadata`（`compare_type=True`）探针复验：0001 形状（带 `sync_status`）→0002 ORM 产生 3×`add_column` + 1×`remove_column`，4 条均 `len=4`、`diff[2]=="accounts"`、`diff[3]` 为 `Column`（`.name` 命中四列）→ 全部豁免；`accounts.email` 改 `VARCHAR(64)` 产生 `modify_type`（`len=7`、`diff[3]=='email'`）→ 不豁免 → 报错回滚。豁免正/负边界均成立。转换仍 `stamp_unified_baseline`（`:956`）盖 0001，`src/mail_core/__main__.py:127` 紧随 `command.upgrade(cfg,"head")` 执行 0002 完成列替换与历史值映射；0002 失败时下次启动由 `plan_migration`（`baseline.py:1063-1074`）的 UPGRADE_TO_HEAD 重新升级，可恢复。真实 0030 形状的端到端正向 PG 用例仍缺（test 轴 `t076_test_f008` 已出 minor，code 轴不重复报告），本轮以代码链路 + Alembic 结构探针替代该正向证据。
    - **f007（R2 important）：已消除（根因修复）**。`handle_job`（`src/mail_core/worker/handlers.py:246-264`）在 `trace_scope` 内 `try/finally`，`finally` 对 `job.status in (DONE, FAILED)` 统一调 `_finish_activity`（`:193-195` → `health.py:72-78`）；`_handle_job_impl` 的 `sync_enabled=False` / 账号缺失早退分支（`:303-307`）经 `complete_job`（`jobs.py:370,406` 置 `locked_job.status=DONE`，该查询命中 session identity map 中的同一 `job` 对象）使 `finally` 必触发，早退不再漏复位。generic except（`:443-475`）与 `_evaluate_result` `provider_error` 分支（`:224-232`）的零散终态检查已移除 / 收敛。`tests/mail_core/test_worker_loop.py:746-785` 真 PG 构造 `mark_credential_invalid` + `set_sync_activity(active=True)` + CLAIMED delta job，断言 `handle_job(...) is True`、`credential_state=="invalid"`、`sync_activity=="idle"`，直接命中该早退分支，非 mock 被测逻辑。残留重复见 f008（minor）。
    - f001（R1 critical）：**已完全消除**。其 R2 残留即 f006，本轮闭环；0002 revision + UPGRADE_TO_HEAD + LEGACY 转换 + 离线工具 UPGRADE_TO_HEAD 指引（`baseline.py:1185-1191`）齐备，空库 / 0001 库 / 已升级库 / LEGACY 库四条路径均可达 head。
    - f002 / f003 / f004 / f005（R1）：维持 R2「已消除」结论；f004 的 R2 残留即 f007，本轮闭环。本轮 diff 未见换形式弱化或重新引入。
- 本轮新发现：1 条（0 critical / 0 important / 1 minor，f008）。
- 未进表的提示：
    - 落点 / 指纹 / 可见性：见本节首段；`task.py review-status` 当前报 `code_verdict=FAIL` / `ac_review=void` / `review_scope=stale`，系本 `review_code.md` 仍停在 R2（`608ceb911baf7f05`、TICK-VOID:AC-001）的旧值，追加本 R3（PASS、全 TICK-VALID、指纹 `3c71f762ee403df4`）后应与 test 轴 R3（PASS、同指纹）合并为 fresh；test 轴报告已含 R3 同指纹，不构成本轴 INCOMPLETE。
    - 文件过大（降级规则，仅列路径 / 行数，不进 finding 表；均为既存大文件）：`src/mail_core/db/baseline.py` 1232（本 task 净增约 76 行）、`src/mail_core/worker/handlers.py` 475（净增约 3 行）、`tests/scripts/test_migrate_to_unified_baseline.py` 717（仅 3 行 fixture 常量更新）、`tests/mail_core/test_worker_loop.py` 785（净增约 107 行）、`tests/mail_core/test_startup_migrations.py` 631（净增约 79 行）。`src/mail_core/sync/context.py` 158、`src/mail_core/__main__.py` 253、`src/mail_core/accounts/health.py` 163、0002 revision 67 均未超阈值。
    - 圈复杂度：`_handle_job_impl`（约 13 个 job_type 分支 + try/except，手算 CC ≥ 15）为既存分发函数且本 task 净减分支（`lease_busy` 特判删除、generic except 简化），按「≥15 需本 task 仍增加分支」不命中；`plan_migration`（本轮 +1 分支，手算 CC < 10）、`handle_job`、`_evaluate_result`、`_is_account_column_drift` 手算均 < 10。复杂度本身不 blocking，仅提示。
    - 文本启发式残留（低置信度，R2 已列）：`src/mail_core/sync/context.py:73-84` `_AUTH_MARKERS` 含 `"unauthorized"` / `"status=401"`，非邮箱凭据来源的 401（如中间代理）理论上会判 AUTH 并置 `sync_enabled=False`，与 AC-005 反向约束有张力；`safe_provider_summary` 丢弃响应体，OAuth `invalid_grant` 仅在字面串出现时命中。未找到确定生产输入，仅提示。
    - 状态机可达性张力（既定取舍，非缺陷）：`account_failure_kind` 对 background+transport 返回 NONE（`context.py:156-157`），`unreachable` 实际可达依赖前台任务重复失败跨 5 分钟窗口；属 AC-003 故障域隔离与 AC-004 熔断的既定权衡。
    - 维护风险：`CURRENT_HEAD_REVISION`（`baseline.py:45`）硬编码，`_stamp_targets`（`:726-740`）与测试的单 head 常量依赖它，而 `revision_context`（`:977-994`）的 heads 动态取自 `ScriptDirectory`；新增 revision 时须同步该常量。当前无行为缺陷，仅提示。
    - 契约闭环：`src/mail_core/api/accounts.py:65-68` `AccountOut` 四字段无 `sync_status`，`src/mail_core/mail/application/accounts.py:171` 经 `**health_fields(acc)` 投影；`schemas/openapi.json`、`src/frontend/src/api/generated/schema.ts` 同步；`src/` 下 grep 无「同步失败，请检查账户设置」残留，`_recover_account_sync_status` / `account_sync_failure_status` / `_apply_account_sync_failure` 全仓零引用；后端 `sync_status` 残留均为 Folder 级（`models.py:141` 等）。
    - 门禁证据（定向 PG 275 passed、后端 unit 1654 passed + 2 既存失败、前端 vitest 586 + tsc/build/lint/openapi:check/css:check、模板契约 463、桌面单测、黑盒 E2E 21、全栈 E2E 8、PG5 后台运行）为实施侧自述，非本轴独立复验证据；本轮独立复验为 `git diff` 全量代码链路、Alembic `compare_metadata` diff 结构探针（正 / 负豁免边界）、`KKMAIL_TEST_MODE=unit` 下 3 条 `handle_job` / `_evaluate_result` 定点单测（3 passed）及代码 / 测试断言本身。`test_conversion_rejects_drifted_legacy_schema_and_rolls_back` 为既存负向用例（`git show <anchor>` 已含，本 task diff 未改该用例），经 R3 新豁免路径执行仍断言拒绝 + 整体回滚，证明豁免未放宽到其它列；如实披露与自述「回归测试」措辞的出入，不作免审理由。
- 总体判断：PASS。R2 两条 important（f006 / f007）均从根因消除并以代码 / 探针 / 定点单测独立复核，R1 critical f001 完全闭环，本轮仅 1 条 minor（f008，非阻断），7 条 AC 全 TICK-VALID；非 INCOMPLETE（指纹一致、AC 覆盖完整、无 reviewer 不可见的未跟踪交付文件）。
- 系统性 follow-up：无（f008 落在本 task 交付范围，implementer 在处置表登记即可；LEGACY 正向 PG 用例缺口已由 test 轴 `t076_test_f008` 跟踪）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`models.py:114-123` 三列 `String(32)` + server_default 替换 `sync_status`；`20261112_0002_account_health_states.py:24-49` add 三列 + `auth_failed`→invalid/`sync_enabled=false`、`failed`→degraded 历史值映射 + drop `sync_status`，`:52-67` 提供 downgrade 回退；`__main__.py:82-86` UPGRADE_TO_HEAD 与 `:127` 转换后 `command.upgrade(cfg,"head")` 衔接 0002；f006 豁免经 `baseline.py:949` + `_is_account_column_drift`（`:460-485`）独立 Alembic diff 结构探针验证仅豁免 accounts 四列，既存 drift 拒绝用例证明其它列仍拒绝；`test_t7` 真 PG 验证 0001→head 与数据映射；f007 早退分支经 `handlers.py:256-264` finally 复位 `sync_activity`（新 PG 用例覆盖）。
- AC-002：TICK-VALID，re_verified。`delta.py:537-555` 删私有 `enqueue_job` + 伪 `followup_scheduled` / `done`，改返回 `provider_error` + 结构化 `error_code`；`handlers.py:224-232`、`:463-474` 统一 `reschedule_job(count_failure=True)`，`jobs.py:460-465` 委托 `fail_job`（`:499-562`）保留原 job ID、递增 `failure_attempts`、按 `backoff_seconds` 退避、cap 转 FAILED；`attempts` 由 `claim_jobs`（`jobs.py:284`）下次认领递增。
- AC-003：TICK-VALID，re_verified。`worker/main.py:279` payload 注入 `{"background": True}`；`context.py:50-70` 顶层 background 短路返回 `(True, None)`，`account_failure_kind`（`:143-158`）对 background+transport 返回 NONE，不外溢账号状态。
- AC-004：TICK-VALID，re_verified。`health.py:130-151` 单调计数 + `first` 保持 + 仅成功清零，UNREACHABLE 不再死分支；`:81-99` 成功恢复 connected；`_recover_account_sync_status` 全仓零引用（grep 确认）；`test_account_health_state_machine.py` 按真实 `backoff_seconds` 序列与双负向边界验证。
- AC-005：TICK-VALID，re_verified。`context.py:87-114` 结构化识别 `PermanentAuthError` / `status==401` / `error_code=auth_failed` / `invalid_grant` / `InvalidAuthenticationToken`；`delta.py:554-555` / `reconcile.py:229-230` 在脱敏摘要外携带 `error_code`；`imap.py` 转 `PermanentAuthError` 并排除临时锁定；`health.py:44-57` 置 invalid + `sync_enabled=False` + 复位 `sync_activity`；非认证 transport 经 `is_transient_network_error` 不触碰 `credential_state`。
- AC-006：TICK-VALID，re_verified。`api/accounts.py:65-68` `AccountOut` 四字段无 `sync_status`，`:247` / `:278` / `:305` 经 `mail/application/accounts.py:171` `**health_fields(acc)` 投影；`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 同步四字段并移除 `sync_status`。
- AC-007：TICK-VALID，re_verified。`Sidebar.tsx:193-199`、`:1171` 与 `SettingsModal.tsx:31-34` 按 invalid / unreachable / degraded / syncing 分支渲染，`src/` 下 grep 无「同步失败，请检查账户设置」残留；后台 transport 因 `account_failure_kind` 返回 NONE 不写 `connectivity_state`，不触发侧栏报警。

coverage = 7 / 7

verdict: PASS

______________________________________________________________________

## Round 4 (2026-11-12T10:45:56+08:00)

reviewed_scope: 043571e6ec6c3d82

- 复核基线：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过；`HEAD` == `diff_anchor` == `20b61520c0837db9cd4c44506886bae6a507a1a2`，交付内容全部为工作树未提交改动，`git diff <anchor>` 为累计全量视图（79 文件，+1781/-577）。指纹经 `repo_task.monitoring.review_scope_fingerprint` 独立重算 = `043571e6ec6c3d82`，与 Round 4 prompt 注入值一致；`monitoring.py:232` 排除 `docs/pending` / `docs/findings`，`REVIEW_PROCESS_FILES`（`:56`、`:243`）排除 `review_*.md` 与 `progress.md` 正文，故写本报告不改指纹。`git status --short` 中 3 个 `??` 为 `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md`（pending 流程文件，指纹排除）与两份 `review_*.md`（reviewer 产物），无 reviewer 不可见的未跟踪交付文件，不作 INCOMPLETE。审查对象为 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 全量累计视图（含 `git add -N` 的 `20261112_0002_account_health_states.py`）。

## Findings

本轮无新 finding（0 条，clean review）；`t076_code_f009` 起未启用。R3 唯一 minor `t076_code_f008` 已按建议消除，复核见下「前轮 finding 复核」与「regression 独立复核」。

## 结论

- 前轮 finding 复核（以 `git diff <anchor>` 全量累计视图与工作树代码为准，不采信处置表自称「已修」）：
    - **f008（R3 minor）：已消除（按建议落地）**。`_evaluate_result`（`src/mail_core/worker/handlers.py:198-240`）内三处无条件 `_finish_activity` 全部移除；累计 diff 中 `_finish_activity` 仅剩定义（`:193-195`）与 `handle_job` `finally` 调用（`:261`）两处（`git diff ... handlers.py | grep -c _finish_activity` = 2，逐行核对为定义与 finally 调用），`handle_job` 的 `try/finally`（`:253-261`）成为唯一终态复位点。原分叉消除：`:239` `fail_job` fall-through（R3 时 `:242` 无条件复位）与 `:223-231` `provider_error` 现同为 PENDING 退避态、均保持 `syncing`；DONE/FAILED 由 finally 统一复位 `idle`。`tests/mail_core/test_worker_loop.py:350` 新增 `assert account.sync_activity == "syncing"`（可重试失败 / PENDING 段），`:788` 保留 `assert acc.sync_activity == "idle"`（`test_auth_failure_job_completes_and_resets_sync_activity` / DONE 早退段）。
    - f001（R1 critical）/ f002 / f003 / f004 / f005（R1）/ f006 / f007（R2）：维持 R3「已完全消除」结论；本轮 diff 未见换形式弱化或重新引入。本轮增量仅落在 `handlers.py` 的 `_evaluate_result` 与 `test_worker_loop.py` 的断言/注释，不触及迁移、`context.py`、`health.py`、`jobs.py` 等前轮修复面。
- regression 独立复核（本轮重点）：
    1. **`_evaluate_result` 被单测直接调用时不经 finally 的路径**：生产侧 `_evaluate_result` 仅在 `_handle_job_impl` 内 8 处调用（`handlers.py:325/347/358/368/382/413/428/436`），`_handle_job_impl` 唯一生产入口为 `handle_job`（`src/mail_core/worker/main.py:419`），finally 必覆盖，生产路径无遗漏。测试侧直调 4 处：`tests/mail_core/test_worker_capacity_retry_after_a18.py:55`、`tests/mail_core/test_worker_loop.py:668`、`tests/mail_core/test_sync_retry_queue.py:47`、`:82`（另 `:139-145` monkeypatch 包装 `_evaluate_result` 后仍经 `handle_job`）；四者均用 `MagicMock()` session 且 patch `complete_job` / `fail_job` / `reschedule_job`，断言只关于控制流与调用参数（outcome、`assert_called_once_with`、`assert_not_called`），**不触及真实 `sync_activity` 持久化**，移除内部复位不改变断言结果，亦不构成「测试假绿」（这些用例本就不承担 `sync_activity` 复位语义）。独立复跑：`KKMAIL_TEST_MODE=unit pytest ... -k evaluate_result` → 4 passed；`pytest test_worker_loop.py test_worker_capacity_retry_after_a18.py test_sync_retry_queue.py -q` → 37 passed, 15 skipped（PG 标记用例因 `MAIL_CORE_DATABASE_URL` 未设置 skip）。结论：无 regression。
    2. **complete / fail / capacity 各分支 job.status 与 `_finish_activity` 一致性**：`complete_job`（`src/mail_core/sync/jobs.py:308-313`）用 `session.scalar(select(...).with_for_update())` + `session.refresh(locked_job)` 命中 identity map 同一对象，`locked_job.status=DONE`（`:370`、`:406`）反映到 `job.status`；`fail_job`（`:520`、`:546`）直接改 `job.status`（PENDING / FAILED）并 flush；`reschedule_job(count_failure=True)`（`:460-465`）委托 `fail_job`，纯 delay 分支（`:468-475`）置 PENDING。逐分支矩阵：`complete_job`→DONE→finally 复位 idle；`fail_job` 达 cap→FAILED→复位 idle；`fail_job` 未达 cap / `reschedule_job`→PENDING→finally 不动作、保持 syncing；`capacity_unavailable`+`followup_scheduled`（`handlers.py:208-210`）→complete_job→DONE→idle；无 followup（`:211-218`）→reschedule→PENDING→syncing。`_finish_activity`（`:193-195`）内再判 `account_id` 与 `_ACCOUNT_SYNC_JOB_TYPES`，辅助 job（archive / push / gc / backup / OUTBOX_DISPATCH_WAKE / unknown）不写。generic except（`:440-472`）`session.rollback()` 后 `fail_job` 重新赋值并 flush，finally 读到新值；4 个 account sync job 路径在网络 I/O 前均有 `session.commit()`（`:313/:333/:355/:400`），`set_sync_activity(active=True)`（`:287-288`）已持久化，rollback 不撤销，退避态保持 syncing。结论：job.status 与复位动作一一对应，无分叉、无遗漏终态。
    3. **看似分叉实为语义**：AUTH 失败经 generic except → `mark_credential_invalid`（`src/mail_core/accounts/health.py:44-57`，`:52` 置 `sync_activity=IDLE` 且 `sync_enabled=False`）→ `reschedule_job(count_failure=True)`→PENDING → finally 不复位 → 账号保持 idle。与普通 PENDING 退避保持 syncing 取值不同，但账号已禁用、不再有在途同步，idle 是正确终态（即 f007 修复目标），非 f008 所指「同为 PENDING 退避中态却一个 idle 一个 syncing」的缺陷。
- 本轮新发现：0 条（0 critical / 0 important / 0 minor）。7 条 AC 全 TICK-VALID，无未解决 critical / important。
- 未进表的提示：
    - **FAILED 终态断言缺口（test 轴，code 轴不进表）**：`tests/mail_core/test_worker_loop.py:356-377` 的 FAILED 终态段新增 `assert job.last_error is not None`，但**未**直接断言 `account.sync_activity == "idle"`；全文件唯一 idle 断言为 `:788` 的 DONE 早退用例。生产链路可证 `finally` 在 FAILED 时复位（`handlers.py:260-261` → `health.py:72-78`），但缺一条针对 FAILED cap 终态的直接断言。如实披露与用户「终态用例仍断言 idle」措辞的出入：断言存在但落在 DONE 早退用例，非 FAILED cap 段。属测试覆盖建议，按职责边界不进 code 轴 finding 表。
    - **定向 PG 用例无法独立复跑**：`MAIL_CORE_DATABASE_URL` 未设置，`tests/mail_core/test_worker_loop.py` 的 15 条 `@pytestmark_db` 用例（含 `:331-350` 退避态、`:356-377` FAILED 终态、`:749-788` 早退复位）在本会话 skip；实施侧「定向 PG 134 passed（f008 修复后）」为背景证据，非本轴独立复验证据。本轴独立复验为 `git diff <anchor>` 全量代码链路、`jobs.py`/`handlers.py`/`health.py` 状态一致性矩阵、指纹独立重算、unit 模式 37 passed（15 skipped）与 4 个 `_evaluate_result` 直调用例定点复跑。
    - 文件过大（降级规则，仅列路径 / 行数，不进 finding 表；均为既存大文件）：`src/mail_core/db/baseline.py` 1232、`src/mail_core/sync/jobs.py` 659、`src/mail_core/worker/handlers.py` 472（本轮净减 3 行）、`tests/mail_core/test_worker_loop.py` 788；`src/mail_core/sync/context.py` 158、`src/mail_core/accounts/health.py` 163、`src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py` 67 未超阈值。
    - 圈复杂度：`_handle_job_impl`（约 13 个 job_type 分支 + try/except，手算 CC ≥ 15）为既存分发函数且本 task 净减分支（`lease_busy` 特判删除、generic except 简化），按「≥15 需本 task 仍增加分支」不命中；`_evaluate_result`、`handle_job`、`_finish_activity`、`_apply_account_health` 手算均 < 10。复杂度本身不 blocking。
    - 文本启发式残留（低置信度，R2/R3 已列）：`src/mail_core/sync/context.py:73-84` `_AUTH_MARKERS` 含 `"unauthorized"` / `"status=401"`，非邮箱凭据来源的 401（如中间代理）理论上判 AUTH 并置 `sync_enabled=False`，与 AC-005 反向约束有张力；`safe_provider_summary` 丢弃响应体，OAuth `invalid_grant` 仅在字面串出现时命中。未找到确定生产输入。
    - 状态机可达性张力（既定取舍，非缺陷）：`account_failure_kind` 对 background+transport 返回 NONE（`context.py:156-157`），`unreachable` 实际可达依赖前台任务重复失败跨 5 分钟窗口；属 AC-003 故障域隔离与 AC-004 熔断的既定权衡。
    - 维护风险：`CURRENT_HEAD_REVISION`（`src/mail_core/db/baseline.py:45`）硬编码，新增 revision 须同步该常量与测试单 head 常量；`revision_context` 的 heads 动态取自 `ScriptDirectory`。当前无行为缺陷。
    - 死代码 / 契约闭环：`_recover_account_sync_status` / `_apply_account_sync_failure` / `account_sync_failure_status` / `update_account_sync_status` 在 `src/` 下零引用（grep 确认）；`SyncStatus` 残留全为 Folder 级（`src/mail_core/mail/storage/models.py:141`、`src/mail_core/mail/domain/enums.py:24-36` 注释明确「retained exclusively for folders.sync_status」），符合零兼容性负担。`src/` 下 grep 无「同步失败，请检查账户设置」残留；`_finish_activity` 仍被 finally 调用、`set_sync_activity` import 仍用于 `:195` / `:288`，无新增死代码。`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 经 diff 确认含四字段并从 `AccountOut` 移除 `sync_status`。
    - 门禁证据（定向 PG 134 passed、后端 unit 1654 passed + 2 既存失败 uv lock 漂移 / 历史 review 文档敏感误判、前端 vitest 586 + tsc/build/lint/openapi:check/css:check、模板契约 463、桌面单测、黑盒 E2E 21、全栈 E2E 8、PG6 后台运行中）为实施侧自述，非本轴独立复验证据；如实披露。
- 总体判断：**PASS**（非 INCOMPLETE）。R3 唯一 minor f008 已按建议从根因消除；将 `_finish_activity` 收敛到 `handle_job` finally 的改动经生产入口唯一性、identity map 状态传播、job.status 分支矩阵、unit 定点复跑四路独立复核，未引入 regression；7 条 AC 全 TICK-VALID；指纹 `043571e6ec6c3d82` 与当前 worktree 一致、AC 覆盖完整、无 reviewer 不可见的未跟踪交付文件。附：`task.py review-status` 派审前报 `review_scope=stale` / `round=3` 系本 `review_code.md` 仍停在 R3（`3c71f762ee403df4`），追加本 R4（PASS、全 TICK-VALID、指纹 `043571e6ec6c3d82`）后与 test 轴 R3（PASS、同指纹）合并为 fresh；test 轴报告状态不构成本轴 INCOMPLETE。
- 系统性 follow-up：无（f008 已闭环；LEGACY 正向 PG 用例缺口已由 test 轴 `t076_test_f008` 与 `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` 跟踪，属流程文件、非本轴交付缺口）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/mail/storage/models.py:114-122` 三列 `String(32)` + server_default（valid/connected/idle），账号级 `sync_status` 移除；`src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py:26-49` add 三列 + `auth_failed`→invalid/`sync_enabled=false`、`failed`→degraded 历史值映射 + drop `sync_status`，`:52-67` downgrade 回退；`src/mail_core/__main__.py:82-86` UPGRADE_TO_HEAD 与 `:127` 转换后 `command.upgrade(cfg,"head")` 衔接 0002，f006 的 `_is_account_column_drift` 豁免经 R3 Alembic 结构探针验证；f007/f008 修复后 `handle_job` finally（`handlers.py:253-261`）在 DONE/FAILED 复位 `sync_activity`，PENDING 退避保持 syncing，列语义一致。
- AC-002：TICK-VALID，re_verified。`src/mail_core/sync/delta.py:537-556` provider 异常段返回 `provider_error` + 结构化 `error_code=auth_failed`，无私有 `enqueue_job` successor、无伪 `done`；`handlers.py:223-231`、`:463-471` 统一 `reschedule_job(count_failure=True)`，`src/mail_core/sync/jobs.py:460-465` 委托 `fail_job`（`:499-562`）保留原 job ID、递增 `failure_attempts`、按 `backoff_seconds` 退避、cap 转 FAILED；`attempts` 由 `claim_jobs` 下次认领递增。
- AC-003：TICK-VALID，re_verified。`src/mail_core/worker/main.py:279` 周期 payload 注入 `{"background": True}`；`src/mail_core/sync/context.py:61-62` 顶层 background 短路返回 `(True, None)`，`account_failure_kind`（`:143-158`）对 background+transport 返回 NONE，不外溢账号状态。
- AC-004：TICK-VALID，re_verified。`src/mail_core/accounts/health.py:130-151` 单调计数 + `first` 保持 + 仅成功清零使 UNREACHABLE 不再死分支；`:81-99` 成功恢复 connected；`_recover_account_sync_status` 全仓零引用（grep 确认）；`tests/mail_core/test_account_health_state_machine.py` 按真实 `backoff_seconds` 序列与双负向边界验证。
- AC-005：TICK-VALID，re_verified。`context.py:87-114` 结构化识别 `PermanentAuthError` / `status==401` / `error_code=auth_failed` / `invalid_grant` / `InvalidAuthenticationToken`；`delta.py:554-555`、`src/mail_core/sync/reconcile.py:229-230` 携带 `error_code`；`src/mail_core/providers/imap.py:814-841` 转 `PermanentAuthError` 并排除临时锁定；`health.py:44-57` 置 invalid + `sync_enabled=False`；非认证 transport 经 `is_transient_network_error` / `account_failure_kind` 不触碰 `credential_state`。
- AC-006：TICK-VALID，re_verified。`src/mail_core/api/accounts.py:65-68` `AccountOut` 四字段无 `sync_status`，经 `src/mail_core/mail/application/accounts.py:171` `**health_fields(acc)` 投影；`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 经 diff 确认同步四字段并移除 `sync_status`。
- AC-007：TICK-VALID，re_verified。`src/frontend/src/components/Sidebar.tsx:193-199`、`:1171` 与 `SettingsModal.tsx:21-34` 按 invalid / unreachable / degraded / syncing 分支渲染，`src/` 下 grep 无「同步失败，请检查账户设置」残留；后台 transport 因 `account_failure_kind` 返回 NONE 不写 `connectivity_state`，不触发侧栏报警；`Sidebar.test.tsx:1187-1237` 覆盖 invalid / unreachable / degraded / 后台静默同步四类。

coverage = 7 / 7

verdict: PASS
