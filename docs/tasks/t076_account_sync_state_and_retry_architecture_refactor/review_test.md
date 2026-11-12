# Task review t076（reviewer_focus: 测试）

- task：`t076_account_sync_state_and_retry_architecture_refactor`
- spec：`docs/tasks/t076_account_sync_state_and_retry_architecture_refactor/task.md`
- diff_anchor：`20b61520c0837db9cd4c44506886bae6a507a1a2`
- target：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`
- round：1
- reviewed_at：2026-11-12T08:49:22+08:00

## Findings

### t076_test_f001 - 重写既有测试时把「账号状态未被污染」守卫就地缩窄为单维断言，丢失 connectivity 覆盖

- 严重度：important
- 锚点：AC-003 / AC-004。失败场景：传输层异常或后台静默同步失败后，`connectivity_state` 被错误写成 `unreachable`/`degraded`（或被错误清空）时，这些测试仍全部 PASS，无法捕获故障域隔离与熔断状态机的回归。
- 位置：`tests/mail_core/test_gmail_sync_strategy_and_timeout.py:168`（`test_worker_transient_network_timeout_does_not_fail_account`，docstring 第 126 行仍写 "keeps account status intact"）；`tests/mail_core/test_sync_inbox_first.py:674`（`test_a21_background_folder_failure_is_isolated_from_inbox`，第 673 行注释明确「旧不该被误标 failed/auth_failed → credential 保持 valid」）；`tests/mail_core/test_t061_idle_watcher.py:418,1002,1049,1092,1193,1426`；`tests/mail_core/test_t061_status_patrol.py:414`；`tests/mail_core/test_sync_hardening_a27_a28_a29.py:138-139`。
- 问题：旧断言 `account.sync_status != "failed"` / `not in (FAILED, AUTH_FAILED)` 覆盖「账号整体不被误标」两个维度，重写后普遍只剩 `assert account.credential_state == "valid"`，`connectivity_state` 维度完全不再断言。按新语义，前台传输异常应断言 `connectivity_state == "degraded"`（AC-004），后台/控制流失败应断言 `connectivity_state == "connected"`（AC-003 不外溢）；实施方在 `tests/mail_core/test_sync_background_lineage.py:358,378,405,424,536` 与 `tests/mail_core/test_worker_loop.py:339,366,410` 都用了 `credential_state == "valid" and connectivity_state == "connected"` 双字段，证明等价断言写法已知，此处缩窄无正当理由。`test_gmail_sync_strategy_and_timeout.py:125` 用 `TimeoutError` 走 Worker 前台路径（生产 `handlers._apply_account_health` 会置 degraded），测试却完全不查 connectivity，最典型。`test_sync_hardening_a27_a28_a29.py:138-139` 另删掉旧 `assert job is not None`，改为 `all(...)` 对查询结果全集断言：集合为空时两条断言真空通过，且旧精确断言 `job.payload.get("detail") == "ProviderHttpError status=500"` 被弱化为 `detail is None`，存在性保证丢失。以上均为「降低行为覆盖/弱化断言」，按危险模式条款最低 important。
- 建议：把上述每处守卫补成双字段断言（前台网络异常写 `degraded`，后台/控制流写 `connected`）；`test_a27_sync_folder_delta_sanitizes_errors` 恢复 `assert jobs` 非空后再做 `all(...)`，或改回对具体 job 的精确断言。

### t076_test_f002 - AC-003 新增测试用 inspect.getsource 断言源码字面量，规避真实交互

- 严重度：important
- 锚点：AC-003。失败场景：把 `schedule_periodic_inbox_sync` 的 payload 构造改为变量赋值（行为正确）该测试假红；把 `{"background": True}` 只写进注释/docstring 而入队 payload 不含该键（行为错误）该测试假绿；两种情况下测试都无法反映真实入队行为。
- 位置：`tests/mail_core/test_account_health_state_machine.py:184-188`（`test_periodic_sync_payload_marks_background`，`source = inspect.getsource(worker_main.schedule_periodic_inbox_sync)` + `assert '"background": True' in source`）。
- 问题：该测试不调用被测函数、不查 DB 入队 job、不断言 payload，只匹配源码字符串，属「凑数」/「规避真实交互」/「测了假行为」，不触达生产实现。AC-003 的真实行为证据在 `tests/mail_core/test_worker_scheduler.py:71-84`（真实 `schedule_periodic_inbox_sync(session, ...)` + 查 `WorkerJob` + `assert job.payload == {"folder_id": ..., "background": True}`），因此本条不构成 AC-003 的唯一支撑、不触发 TICK-VOID，但它作为新增测试制造了虚假覆盖信号。按危险模式「规避真实交互/掩盖失败」条款最低 important，不得标 minor。
- 建议：删除该用例（`test_worker_scheduler.py:84` 已真实覆盖），或改写为调用 `schedule_periodic_inbox_sync` 后读取 DB job 断言 `payload["background"] is True`。

### t076_test_f003 - 熔断双条件负向边界未覆盖

- 严重度：minor
- 锚点：AC-004（覆盖扩展）。
- 位置：`tests/mail_core/test_account_health_state_machine.py:64-78`（`test_connectivity_failure_breaker_escalates_after_five_failures_across_window`）；生产 `src/mail_core/accounts/health.py` 的 `count >= CONNECTIVITY_FAILURE_THRESHOLD and elapsed >= CONNECTIVITY_WINDOW`。
- 问题：仅验证「5 次失败 + elapsed 恰好等于 window → unreachable」，未验证「5 次失败但跨度在窗口内仍 degraded」「不足 5 次但跨度超窗口仍 degraded」两个负向条件；AC 措辞「超过 5 分钟窗口」与实现 `>=` 的边界语义也未锁定。AC-004 正向/复位/单次 degraded 均有真测试，故非阻塞。
- 建议：补 2 个参数化 case 锁定 AND 双条件与边界值。

### t076_test_f004 - AC-002 的 attempts 递增无断言，退避期望自我参照

- 严重度：minor
- 锚点：AC-002（覆盖扩展）。
- 位置：`tests/mail_core/test_account_health_state_machine.py:156-181`（`test_reschedule_job_count_failure_keeps_id_increments_attempts_and_backs_off`）。
- 问题：测试名含 "increments_attempts"，但 `job.attempts=1` 全程未断言；AC-002 明文「递增 `attempts` 与 `failure_attempts`」，测试只断言 `failure_attempts == 1`。`assert job.run_after == _BASE + timedelta(seconds=backoff_seconds(1))` 用被测模块的 `backoff_seconds` 计算期望值，退避算法改错时期望同步变化仍 PASS，属自我参照。AC-002 的「保留原始任务 ID / 计数失败 / 指数退避」主体由 `tests/mail_core/test_sync_retry_queue.py:108-176` 与 `tests/mail_core/test_worker_loop.py:339-366` 真实覆盖，故非阻塞。
- 建议：断言 `attempts` 递增，并用独立硬编码边界或明确公式断言退避窗口，而非调用生产函数生成期望。

### t076_test_f005 - AC-005 列明的 401 / AUTHENTICATIONFAILED 确凿信号无分类测试

- 严重度：minor
- 锚点：AC-005（覆盖扩展）。
- 位置：`tests/mail_core/test_account_health_state_machine.py:128-140`、`tests/mail_core/test_sync_backend_handler_isolation.py:92-104`、`tests/mail_core/test_sync_background_lineage.py:303-330`；生产 `src/mail_core/sync/context.py` 的 `_AUTH_MARKERS`。
- 问题：认证分类测试只覆盖 `PermanentAuthError("invalid_grant")` 与 `{"status": "auth_failed"}`；AC-005 明列的 401、`AUTHENTICATIONFAILED` 既无分类断言也无 `credential_state=invalid` 转换验证，生产 `_AUTH_MARKERS` 甚至不含 `"401"` 字面量。AC-005 的 auth→invalid+disabled 链路（`test_sync_background_lineage.py:443-452`、`test_gmail_sync_strategy_and_timeout.py:176-213`）与非认证异常不改 credential 均有真测试，故非阻塞。
- 建议：为 401 / `AUTHENTICATIONFAILED` / OAuth `invalid_grant` 三种输入补 `is_permanent_auth_error` 与 `account_failure_kind` 参数化断言，并确认 401 分类路径真被识别。

### t076_test_f006 - 重写删除「provider 错误重试保留 priority」断言，注释声称的替代覆盖不存在

- 严重度：minor
- 锚点：AC-002（覆盖回退）。
- 位置：`tests/mail_core/test_sync_inbox_first.py:340-372`（旧 `test_delta_provider_error_requeue_keeps_priority` → 新 `test_delta_provider_error_returns_without_private_requeue`，第 359-360 行注释 "priority is preserved by the framework requeueing the original claimed row (covered by the Worker tests)"）。
- 问题：旧断言 `_pending_job(...).priority == 55` 被删除；`tests/mail_core/test_account_health_state_machine.py:156-181` 的 `SimpleNamespace` job 无 priority 字段也未断言，`tests/mail_core/test_sync_retry_queue.py`、`tests/mail_core/test_worker_loop.py` 的框架重试测试均不查 priority；全仓 grep 的 priority 断言都属于私有 successor 路径（`test_sync_inbox_first.py:291-536`）。`reschedule_job` 生产实现确实不改 priority（行为正确），但注释指向的「Worker 测试覆盖」不成立，属覆盖回退。非 AC 明文行为，故非阻塞。
- 建议：在框架重试测试里补 `retried.priority == 55`，或删除注释里不实的替代声明。

## 结论

- 前轮 finding 复核：无（首轮）。
- 改测方向复核：无典型「让断言迁就当前实现输出」的就地改预期。`tests/mail_core/test_sync_retry_queue.py`、`tests/mail_core/test_sync_background_lineage.py`、`tests/mail_core/test_worker_loop.py`、`tests/mail_core/test_sync_hardening_a27_a28_a29.py`、`tests/mail_core/test_accounts_sync_status_deadcode.py` 的重写均为旧 API/旧字段删除后的规格驱动重写（新语义断言 + 注释说明），`tests/mail_core/test_worker_scheduler.py:84` 就地补 `background: True` 是 AC-003 应有的预期，方向正确。但 f001 所列多处旧守卫被就地缩窄为单维断言，属覆盖回退，非迁就实现。
- 本轮新发现：6 条（2 important / 4 minor）。
- 危险模式扫描：逐条扫过恒真断言、删/反转 expect、注释掉断言、弱化断言、删测试、.skip/.only、静默错误、mock 误用、阈值掩盖、条件跳过、程序赋值替代交互、存在即通过。命中项见 f001（弱化断言、删存在性断言）、f002（规避真实交互、测假行为）。`tests/mail_core/test_medium_providers_sync_blobs.py` 删除 `test_update_account_sync_status`、`tests/mail_core/test_accounts_sync_status_deadcode.py` 删除旧死代码测试，均因对应生产函数 `update_account_sync_status` 已删除，且覆盖分别由 `test_account_health_state_machine.py` 与 `tests/mail_core/test_worker_loop.py:529-572` 脱敏测试补回，属合法删除，不出 finding。其余未命中。
- 未进表的提示：`tests/mail_core/test_worker_loop.py:339`（`test_sync_failure_recovers_after_retry_without_hiding_other_errors`）、`tests/mail_core/test_sync_background_lineage.py:503`（`test_foreground_success_recovers_failed_account`）等测试名，以及 `tests/mail_core/test_gmail_sync_strategy_and_timeout.py:126` docstring「keeps account status intact」、`tests/mail_core/test_worker_loop.py:547-549` 旧架构注释与已无意义的 `job.failure_attempts` 设置，均为过时表述（AC-004 下成功事件确定性复位、网络异常应 degraded），不影响断言有效性。`src/frontend/src/components/Sidebar.test.tsx` 的 `does not raise an alarm for a background silent sync` 只用 `sync_activity=syncing` + 默认健康态，未注入网络异常；「后台异常不报警」实由后端 AC-003 不外溢保证（`tests/mail_core/test_sync_background_lineage.py:381-399`），前端测试名略夸大但非假绿。`tests/mail_core/test_inbox_stats_dead_branch_a218.py:66`、`tests/mail_core/test_baseline_unit.py:85` 的 `inspect.getsource` 源码断言是既存模式（diff 未改），本轮不追责，但 f002 延续了该不良风格。两个既存门禁失败（uv lock 漂移、历史 review 文档敏感词误判）经背景说明在主仓 HEAD 复现、采纳前基线即存在，非本 task 引入，不进 finding 表。
- 总体判断：7 条 AC 均有真实、触达生产逻辑的测试支撑（全 TICK-VALID），但存在 2 条未解决 important（f001 系统性弱化断言丢失 connectivity 覆盖、f002 源码文本假行为测试），按判定式 FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_accounts_sync_status_deadcode.py:19-25` 断言 ORM `Account` 移除 sync_status 且含三列，`tests/mail_core/test_domain_sync_statuses.py:22-32` 断言三枚举值域，既存 `tests/mail_core/test_migration_validation.py:115-200,351-408` 覆盖 Alembic upgrade/downgrade 与零漂移；迁移 DDL 改动见 `src/mail_core/db/alembic/versions/20261107_0001_unified_baseline.py`。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_sync_retry_queue.py:142-176` 经真实 handle_job 断言同一 job 行 PENDING、`failure_attempts==1`、`last_error` 脱敏、无私有 successor；`tests/mail_core/test_account_health_state_machine.py:156-181` 直调 `reschedule_job(count_failure=True)`；`src/mail_core/sync/delta.py:537-551` 已删私有 enqueue。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_worker_scheduler.py:71-84` 真实入队后断言 `payload == {"folder_id":..., "background": True}`；`tests/mail_core/test_account_health_state_machine.py:143-153` 与 `tests/mail_core/test_sync_backend_handler_isolation.py:66-77` 断言顶层 background 标记短路 DB；`tests/mail_core/test_sync_background_lineage.py:381-399` 断言后台 provider 错误后账号健康干净。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_account_health_state_machine.py:49-61,64-78,81-100` 覆盖单次 degraded、5 次+窗口升级 unreachable、成功复位清诊断；`tests/mail_core/test_sync_background_lineage.py:455-475,478-500,503-536` 经真实 handle_job 链路验证 degraded 与成功关闭熔断器；`src/mail_core/worker/handlers.py` 已删 `_recover_account_sync_status`。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_sync_background_lineage.py:443-452` 与 `tests/mail_core/test_gmail_sync_strategy_and_timeout.py:176-213` 断言 PermanentAuthError→`credential_state=invalid`+`sync_enabled=False`；`tests/mail_core/test_account_health_state_machine.py:128-140`、`tests/mail_core/test_sync_backend_handler_isolation.py:92-104` 断言传输/控制流异常归 NONE 不改 credential；`tests/mail_core/test_sync_background_lineage.py:455-475` 断言 foreground 传输异常 credential 保持 valid。
- AC-006：TICK-VALID，re_verified。`tests/mail_core/test_accounts_api_unit.py:84-116,154-205` 断言 DTO/响应含四健康字段；`schemas/openapi.json` 的 AccountOut 移除 sync_status、required 增三字段；既存 `tests/mail_core/test_openapi_contract.py:32-41` 断言提交契约与 app.openapi() 一致；`src/frontend/src/api/generated/schema.ts` 同步四字段。
- AC-007：TICK-VALID，re_verified。`src/frontend/src/components/Sidebar.test.tsx:1187-1245` 覆盖 invalid/unreachable/degraded/connected/syncing 与「同步失败」「请检查账户设置」消失；`src/frontend/src/components/SettingsModal.test.tsx:869-905`、`src/frontend/src/components/settings_redesign.test.tsx:54-85` 覆盖四态标签与筛选；`tests/e2e/settings_workspace.spec.ts:38-41` 断言「同步失败」计数 0；生产 `Sidebar.tsx`/`SettingsModal.tsx` 已移除硬编码文案。

coverage = 7/7

reviewed_scope: c9e5c824345c3cbe

verdict: FAIL

## Round 2 (2026-11-12T09:46:25+08:00)

- round：2
- reviewed_at：2026-11-12T09:46:25+08:00
- target：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`
- 指纹校验：`task.py review-status` 重算当前指纹 = `608ceb911baf7f05`，与注入值一致；`review_code.md` / `review_test.md` 属 `REVIEW_PROCESS_FILES`，追加本轮不改动指纹。落点仓库校验通过（`git rev-parse --show-toplevel` == 本 worktree 根；`HEAD` == `diff_anchor`）。

### Findings

#### t076_test_f007 - a27 重写后 `all(...)` 全集断言缺命中数证据（可选补强，非阻断）

- 严重度：minor
- 锚点：覆盖形式弱点（非 AC 缺测、非危险模式命中）。失败场景：若 `sync_account_folders` / `sync_folder_metadata` 不再为该账号留下任何 `WorkerJob` 行，两条 `all(...)` 在空查询结果上真空通过，A27「无 job 泄漏敏感文本」缺任何实际命中证据。
- 位置：`tests/mail_core/test_sync_hardening_a27_a28_a29.py:132-139`（`test_a27_sync_folder_delta_sanitizes_errors`）。
- 问题：R1 f001 的 a27 子项在本轮 `git diff` 中未改动（该文件对应 hunk 保持 R1 状态）：旧 `assert job is not None` 与 `assert job.payload.get("detail") == "ProviderHttpError status=500"` 仍被 `jobs = list(...)` + `assert all("LEAKED" not in str(j.payload) for j in jobs)` + `assert all(j.payload.get("detail") is None for j in jobs)` 取代，R1 建议的「恢复 `assert jobs` 非空」未采纳。复核判定不升级为 important：新架构已删除私有 successor job，旧「必须存在一个 job」的断言语义随架构删除失效，删除属规格驱动；A27 存在性与精确脱敏覆盖由 `tests/mail_core/test_sync_retry_queue.py:165-171`（`assert len(jobs) == 1`、`"synthetic provider outage" not in retried.last_error`）、`tests/mail_core/test_worker_loop.py:572`（`assert passed_error == "ValueError"`）、`tests/mail_core/test_account_health_state_machine.py:58-60`（`CFG_LAST_CONNECTIVITY_ERROR == safe_provider_summary(...)`）在更高层补回；空集仅在「完全无 job」时出现，此时「无泄漏」结论真实，不产生假绿。属可加固的形式弱点，按「覆盖可更广」标 minor，不阻断。
- 建议：`all(...)` 前补 `assert jobs`（或对查询命中数做显式断言），把负向全集断言锚定到实际命中的行；或改回对具体 job 的精确断言。

### 结论

- 前轮 finding 复核（以 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 与当前工作树为准）：
    - f001（important）：**主体已消除，a27 子项修不彻底但原定性不成立**。双维度守卫逐处核实：`test_gmail_sync_strategy_and_timeout.py:168-169`（前台 TimeoutError → `credential_state == "valid"` + `connectivity_state == "degraded"` + `sync_activity == "syncing"`）、`test_sync_inbox_first.py:675`、`test_t061_idle_watcher.py:421,1005,1052,1095,1196,1429`、`test_t061_status_patrol.py:418`、`test_sync_hardening_a27_a28_a29.py:174-175` 全为 `credential_state == "valid" and connectivity_state == "connected"`；`test_worker_loop.py:342,369,413,430,486`、`test_sync_retry_queue.py:174-175`、`test_sync_background_lineage.py:361,378,394,408,427,539`、`test_sync_engine_failure_unit.py:79-80`、`test_accounts_api_unit.py:202-203` 同型。a27 子项未改，理由见 f007：旧存在性断言语义已失效且覆盖已补回，原 important 定性不成立，残留降为 minor 观察，不阻断。
    - f002（important）：**已消除**。`test_account_health_state_machine.py` 当前 253 行全文无 `test_periodic_sync_payload_marks_background`，本轮 diff 全文亦无 `inspect.getsource(worker_main` / `'"background": True' in source`；AC-003 真实覆盖由 `test_worker_scheduler.py:84` 的 `assert job.payload == {"folder_id": str(folder_id), "background": True}`（真实入队后查 DB）承担。工作树仅剩 `test_inbox_stats_dead_branch_a218.py:66`、`test_baseline_unit.py:85` 两处既存 `inspect.getsource`（diff 未改其语法），R1 已判不追责，R2 维持。
    - f003（minor）：**已消除**。新增 `test_connectivity_breaker_negative_boundaries`（`test_account_health_state_machine.py:234-253`）锁定两个负向条件（2 次失败跨 400s 仍 degraded、5 次失败在 1+2+4+8+16=31s 窗口内仍 degraded）；`test_connectivity_breaker_escalates_across_realistic_backoff:214-231` 用真实 `backoff_seconds` 序列 + 20 分钟周期后升级 unreachable；既存 `:63-77` 用 `now == _BASE + window` 锁定 `>=` 边界语义。
    - f004（minor）：**已消除（退避自参照部分）**。`test_reschedule_job_count_failure_keeps_id_and_counts_failure:155-187` 改用硬编码 `assert job.run_after == _BASE + timedelta(seconds=1)`，不再调用被测 `backoff_seconds` 生成期望；补 `assert job.attempts == 1`、`assert job.priority == 55`、`assert job.last_error`。「AC-002 递增 attempts」仍缺端到端真测试，见下方覆盖缺口。
    - f005（minor）：**已消除**。新增 `test_auth_signals_are_classified_structurally:190-211` 覆盖 401（`ProviderHttpError(status=401)` 与脱敏摘要 `ProviderHttpError status=401`）、`AUTHENTICATIONFAILED`/`PermanentAuthError`、`auth_failed` 结构化 code、`invalid_grant`、`InvalidAuthenticationToken`，并给出 `ConnectionError` / `rate_limited` / `OSError code=101` 传输反例；生产 `src/mail_core/sync/context.py` 的 `_AUTH_MARKERS` 已含 `status=401` / `authenticationfailed` / `invalid_grant` / `invalidauthenticationtoken`，`account_failure_kind` 直接调用 `is_permanent_auth_error`，分类链路真实可达；`test_imap_id_handshake.py:228-250` 新增 IMAP `AUTHENTICATIONFAILED` → `PermanentAuthError`。
    - f006（minor）：**已消除**。`test_account_health_state_machine.py:185` 的 `assert job.priority == 55` 直调 `reschedule_job` 后断言，priority 保持有真测试；`test_sync_inbox_first.py:340-370` 保留 `assert spawned is None`（无私有 successor）+ `"followup_scheduled" not in result`，注释「covered by the Worker tests」指向的覆盖现已存在。
- 改测方向复核：**无「让断言迁就当前实现输出」的就地改预期**。逐处重写均有规格归因且方向为新契约应有的预期：`test_worker_scheduler.py:84` 就地补 `background: True` 是 AC-003 明文要求；`test_sync_retry_queue.py:150-176`（`is True`→`is False`、`DONE`→同一行 `PENDING`、`last_error is None`→脱敏非空）是新架构「不伪造 done、framework 原地 requeue」的等价且更强断言；`test_sync_background_lineage.py:301`（`test_failure_status_classification_is_centralized`）、`test_accounts_api_unit.py`（`test_account_status_is_derived_from_sync_enabled`）、`test_worker_loop.py:4110-4113` 文件头注释、`tests/scripts/test_migrate_from_legacy_db_accounts.py`（`test_existing_account_updates_legacy_owned_fields_and_preserves_runtime_state`）均在注释中写明「旧断言整体重写，禁止就地改预期字符串」；`test_baseline_unit.py:37-38`、`test_migration_validation.py:96,430`、`test_outbox_retention_unit.py:441`、`test_sync_execution_unit.py:56` 单 head 统一更新为 `20261112_0002`（`baseline.py:45` 的 `CURRENT_HEAD_REVISION` 实测同值）属迁移链新增 head 的契约变更，非迁就实现。删除类：`test_medium_providers_sync_blobs.py`（`test_update_account_sync_status`）、`test_accounts_sync_status_deadcode.py`（旧 `test_update_account_sync_status_stores_timestamp_only_in_config`）删除的旧 API 测试由 `test_account_health_state_machine.py`、`test_worker_loop.py:529-572`、`test_sync_retry_queue.py` 补回，R1 已判合法，R2 维持。
- 危险模式扫描：逐条扫过恒真断言、删/反转 expect、注释掉断言、弱化断言、删测试、`.skip`/`.only`/`@Ignore`、静默错误（`# type: ignore`）、mock 误用、阈值掩盖、条件跳过、程序赋值替代交互、存在即通过。新增测试 `test_auth_signals_are_classified_structurally` 全为 `is True`/`is False` 具体值断言，`test_connectivity_breaker_*` 断言具体 `ConnectivityState`，`test_t7_older_baseline_upgrades_in_place_with_data_mapping:562-631` 为真实 PG 升级 + `information_schema.columns` + 数据映射精确断言，`settings_redesign.test.tsx`（`renders each account health dimension in the status column`）用 `toEqual` 精确五态数组；无恒真断言、无 `.skip`、无新增 `# type: ignore`、无 mock 掉被测逻辑。`test_worker_loop.py:560-572`、`test_worker_invalid_payload.py:22,45-46` mock 内部 health 函数与旧测试同型（既存模式），且 `test_account_health_state_machine.py:48-100` 真实覆盖 health 写入，不构成假绿。未命中新增危险模式。
- 本轮新发现：1 条（1 minor，f007）。
- 未进表的提示：`test_t061_idle_watcher.py:20`、`test_sync_inbox_first.py:3903` 等模块/行内注释仍写「整体重写为 credential_state == valid」单维描述，与已补齐的双维断言不一致，属过时表述不影响断言；`test_foreground_success_recovers_failed_account`（`test_sync_background_lineage.py:503`）测试名保留旧「failed_account」措辞；`test_account_health_state_machine.py:187` 的 `assert job.last_error` 为 truthy 断言，精确脱敏由 `test_worker_loop.py:572` 承担。两个既存门禁失败（uv lock 漂移、历史 review 文档敏感词误判）R1 已核实为采纳前基线存在，非本 task 引入，R2 维持不进表。
- 剩余覆盖缺口（均不阻断，minor/可选扩展）：
    - AC-002 明文「递增 `attempts`」缺端到端真测试：`test_account_health_state_machine.py:186` 断言 `attempts == 1`（reschedule 不变），注释称由 `claim_jobs` 下次 claim 递增，但全仓无「claim 后 attempts=2」的断言（`test_jobs_backoff.py:73` 的 `attempts == 25` 为构造输入的不变值）。
    - AC-005 的 401 信号仅验证 `is_permanent_auth_error` 分类与 `PermanentAuthError` → invalid 链路，缺「401 原始结果直接喂 `account_failure_kind` → `mark_credential_invalid` → `sync_enabled=False`」单条端到端用例。
    - AC-007 前端「后台静默同步网络异常不触发侧栏全局报警」仅以 `sync_activity=syncing` + 默认健康态覆盖，未注入网络异常组合；该分支实由后端 AC-003 不外溢保证（`test_sync_background_lineage.py:381`）。
    - `test_a27_sync_folder_delta_sanitizes_errors` 的 `all(...)` 空集形式弱点（f007）。
- 门禁证据说明：实施侧提供定向 PG 263 passed、后端 unit 1650 passed（2 个既存失败）、前端 vitest 586 passed、模板契约 463 passed、黑盒 E2E 21 passed、全栈 E2E 8 passed；最终全量 PG 门禁后台运行中，未纳入本轮独立复验证据。本轮 AC 复验方式为逐条查证 `git diff`、工作树测试断言与生产链路（`context.py` / `health.py` / 迁移脚本 / `schemas/openapi.json`），未重跑全量门禁。
- 总体判断：R1 六条处置后无未解决 critical / important，7 条 AC 均有真实、触达生产逻辑的测试支撑且全 TICK-VALID，按判定式 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_startup_migrations.py:562-631` 真实 PG 旧基线升级后断言三列存在、`sync_status` 消失、`auth_failed`→`("invalid","connected",False)`、`failed`→`("valid","degraded")`；`test_accounts_sync_status_deadcode.py:18-25` 断言 ORM 列布局；`test_domain_sync_statuses.py:25-33` 断言三枚举值域；`test_migration_validation.py:91,96,430`、`test_outbox_retention_unit.py:434,441`、`test_sync_execution_unit.py:56`、`test_baseline_unit.py:37-38` 单 head 统一为 `20261112_0002`（`baseline.py:45` 实测同值）。
- AC-002：TICK-VALID，re_verified。`test_sync_retry_queue.py:150-176` 经真实 `handle_job` 断言同一 job 行 `PENDING`、`retried.id == job_id`、`failure_attempts == 1`、`last_error` 脱敏且不含原文、无私有 successor；`test_account_health_state_machine.py:155-187` 直调 `reschedule_job` 断言 `id` 不变、`failure_attempts == 1`、硬编码 `run_after == _BASE + 1s`、priority/attempts/last_error；`test_worker_loop.py:575-598` 重写后断言 `reschedule_job` 以 `count_failure is True` 调用；`src/mail_core/sync/delta.py` 私有 enqueue 已删。
- AC-003：TICK-VALID，re_verified。`test_worker_scheduler.py:71-84` 真实入队后断言 `payload == {"folder_id":..., "background": True}`；`test_account_health_state_machine.py:142-153`、`test_sync_backend_handler_isolation.py`（`test_explicit_background_marker_and_scope_lineage`）断言顶层 background 标记短路 DB；`test_sync_background_lineage.py:361-399` 断言后台 provider 错误后账号健康干净、同 job 行 requeue。
- AC-004：TICK-VALID，re_verified。`test_account_health_state_machine.py:48-100`（单次 degraded、5 次+窗口升级、成功复位清诊断）、`:214-253`（真实 backoff 序列与双负向边界）；`test_sync_background_lineage.py:455,478,503` 经真实 handle_job 链路验证前景 ConnectionError→degraded、后台成功→connected；`test_worker_loop.py:4164-4179` 手工置 degraded 后成功事件确定性复位；`src/mail_core/worker/handlers.py` 已删 `_recover_account_sync_status`。
- AC-005：TICK-VALID，re_verified。`test_auth_signals_are_classified_structurally:190-211` 覆盖 401/AUTHENTICATIONFAILED/invalid_grant/InvalidAuthenticationToken/auth_failed 与传输反例，`src/mail_core/sync/context.py` 的 `_AUTH_MARKERS` / `is_permanent_auth_error` / `account_failure_kind` 分类链路真实可达；`test_imap_id_handshake.py:228-250` 断言 IMAP 确凿认证失败抛 PermanentAuthError；`test_sync_background_lineage.py:439`、`test_gmail_sync_strategy_and_timeout.py:176-213` 断言 PermanentAuthError→`credential_state=invalid`+`sync_enabled=False`；`test_account_health_state_machine.py:127-140`、`test_sync_backend_handler_isolation.py`（`test_account_failure_kind_is_orthogonal`）断言传输/控制流异常归 NONE 不改 credential。
- AC-006：TICK-VALID，re_verified。`test_accounts_api_unit.py:84-116,154-205` 断言 DTO/响应含四健康字段并移除 `sync_status`；`schemas/openapi.json` 的 AccountOut 增三字段 + `last_connectivity_error`、required 同步、删 `sync_status`；`src/frontend/src/api/generated/schema.ts` 同步四字段；既存 `test_openapi_contract.py` 断言提交契约与 app.openapi() 一致。
- AC-007：TICK-VALID，re_verified。`src/frontend/src/components/Sidebar.test.tsx:1187-1245` 覆盖 invalid/unreachable/degraded/connected/syncing 五态与「同步失败」「请检查账户设置」消失；`src/frontend/src/components/SettingsModal.test.tsx:869-905`、`src/frontend/src/components/settings_redesign.test.tsx:54-85` 精确断言四态标签与筛选；`tests/e2e/settings_workspace.spec.ts:38-41` 断言「同步失败」计数 0；生产 `Sidebar.tsx` / `SettingsModal.tsx` 已移除硬编码文案。

coverage = 7/7

reviewed_scope: 608ceb911baf7f05

verdict: PASS

## Round 3 (2026-11-12T10:13:05+08:00)

- round：3
- reviewed_at：2026-11-12T10:13:05+08:00
- target：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`
- 落点与指纹校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过；`HEAD` == `diff_anchor` == `20b61520c0837db9cd4c44506886bae6a507a1a2`（交付内容全部为工作树未提交改动，diff 为累计视图）。用 `monitoring.review_scope_fingerprint` 与 `review_status.current_scope_fingerprint` 同源重算当前指纹 = `3c71f762ee403df4`，与注入值一致。`git status --short` 中所有交付文件均为 `M` / `A`（已 `git add -N`，全部出现在 diff 中），`??` 仅两份 `review_*.md`（reviewer 产物，属 REVIEW_PROCESS_FILES），无 reviewer 不可见的未跟踪交付文件，结论不作 INCOMPLETE。

### Findings

#### t076_test_f008 - LEGACY 正向升级路径缺真实 0030 形状测试，f006 豁免是否生效无正向证据

- 严重度：minor
- 锚点：AC-001 覆盖缺口（「提供完整的 Alembic 迁移脚本，安全完成历史数据迁移与字段替换」）。失败场景：一个真实 stamp=`20261031_0030` 的旧库（`accounts` 带 `sync_status`、缺三列）经启动升级仍被拒或历史值未映射，现有测试集不报红。
- 位置：`tests/scripts/test_migrate_to_unified_baseline.py:165-207`（`_create_0030_schema`）、`:458-497`（`test_migrate_from_0030_legacy_database_success`）、`:343-359`（`test_conversion_rejects_drifted_legacy_schema_and_rolls_back`）；`tests/mail_core/test_startup_migrations.py:94-138`（`_make_0030_db`）、`:209-227`（`test_t1_narrow_legacy_converts_inline`）、`:562-631`（`test_t7_older_baseline_upgrades_in_place_with_data_mapping`）；`tests/mail_core/test_migration_validation.py:586`（`_pg_build_0030_shape`）；生产 `src/mail_core/db/baseline.py`（`verify_baseline_schema(..., ignore_account_column_drift=True)` 与 `_is_account_column_drift`）。
- 问题：本轮生产在 LEGACY narrow-conversion 路径新增了「忽略 accounts 四列差异」的豁免，但测试端没有任何一条正向用例用真实 0030 形状验证该豁免生效。三个既有「0030」fixture 均从 head DDL 起步再改 stamp：`_create_0030_schema` 由 `_create_full_schema`（当前 ORM `Base.metadata.create_all`，即 0002 head 形状）DROP `folder_patrol_status` 后 stamp 0030；`_make_0030_db` 与 `_pg_build_0030_shape` 用 `_alembic_upgrade(cfg, "head")` 建 0002 head 形状后 stamp 0030。它们构造出的 `accounts` 表**不含 `sync_status`、已含三列**，因此在豁免修复前后都不会触发 `sync_status`/三列的 `add_column`/`remove_column` 差异——`test_migrate_from_0030_legacy_database_success`、`test_t1`、`test_concurrent_narrow_conversion_is_serialized_on_postgres` 无法捕获「真实旧库升级被拒」这一回归。`test_conversion_rejects_drifted_legacy_schema_and_rolls_back` 是既存负向用例（`git show diff_anchor` 已含 `:342`，本 task diff 未改），把 `accounts.email` 改窄后断言仍抛 `SchemaValidationError` 并整体回滚，只能证明豁免「未放宽到其它列」，不能证明豁免「确实让带 `sync_status` 的真实旧库升级成功」。R2 code 轴 f006 明确建议补一条「真实 0030 形状（含 `accounts.sync_status`）的 PG 启动升级用例」，R3 未补。按覆盖规则，AC-001 已有 `test_t7` 真实 PG 覆盖 AT_BASELINE→head 升级 + `auth_failed`/`failed` 历史值映射，LEGACY 正向属「可再加一个 case」，标 minor，不阻断。
- 建议：补一条真实 0030 形状的 PG 用例（显式建含 `sync_status`、缺三列的 `accounts` 并插入历史值行、stamp 0030），跑 `main_module.run_migrations()` 或 `run_migration`，断言 `alembic_version == CURRENT_HEAD_REVISION`、`information_schema.columns` 含三列且不含 `sync_status`、历史行映射到 `invalid`/`degraded` 等；与既有负向 drift 用例配对锁定豁免边界。

### 结论

- 前轮 finding 复核（以 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 与当前工作树为准）：
    - f007（R2 唯一 minor，a27 `all(...)` 空集真空通过）：**已消除**。`test_sync_hardening_a27_a28_a29.py:138` 在两条 `all(...)` 全集断言前补 `assert jobs`，空查询结果不再真空通过；`:132-140` 复核未把修复换成另一种弱化形式（仍为精确 `detail is None` 与 `"LEAKED" not in payload` 全集断言，R2 已说明精确脱敏覆盖由 `test_sync_retry_queue.py:165-171`、`test_worker_loop.py:572` 更高层补回）。
    - f001~f006（R1/R2）：维持 R2 结论（f001 主体消除 / a27 残留降 minor 后由本轮 f007 闭环，f002~f006 已消除），本轮 diff 与工作树未见换形式弱化或重新引入。
- R3 新增测试真实性复核（用户点名清单逐条）：
    - `test_worker_loop.py:746-785` `test_auth_failure_job_completes_and_resets_sync_activity`：**真实可信**。文件末尾纯新增（非改旧预期）；`@pytestmark_db` = `skipif(not MAIL_CORE_DATABASE_URL)`（`:15-18`），门禁定向 PG 275 passed 证明该环境下未 skip、真实 PG 执行；直接 import 并调用生产 `handle_job`，未 mock 掉被测逻辑；构造 `Account` + `CLAIMED` delta job，经 `mark_credential_invalid` 置 `credential_state=invalid`/`sync_enabled=False`（`health.py:44-57` 同时复位 `sync_activity=IDLE`），再用 `set_sync_activity(active=True)` 覆盖为 `syncing`（`health.py:72-78` 无条件写，构造成立）；`handle_job` 的 `try/finally` 在 `job.status in (DONE, FAILED)` 时调 `_finish_activity`（`handlers.py:254-265`），早退分支 `complete_job` 后返回 True（`handlers.py:303-307`）。断言均为具体值（`handle_job(...) is True`、`credential_state == "invalid"`、`sync_activity == "idle"`），非恒真、非弱化。移除该 finally 修复后该用例必然红，能捕获回归，覆盖 code 轴 f007。
    - `test_sync_hardening_a27_a28_a29.py:138` `assert jobs`：见上，f007 闭环。
    - `test_startup_migrations.py:562-631` `test_t7_older_baseline_upgrades_in_place_with_data_mapping`：真实 PG（建 0001 基线 → 插 `auth_failed`/`failed` 两行 → 真 `run_migrations()` → `information_schema.columns` 三列、`sync_status` 消失、两行历史值映射精确断言），R2 报告已引用该用例（非 R3 新增），本轮复核仍成立。
    - `test_conversion_rejects_drifted_legacy_schema_and_rolls_back`：**既存、非 R3 新增**（`git show diff_anchor:tests/scripts/test_migrate_to_unified_baseline.py` 已含 `:342`，本 task diff 未改该文件此用例）。作为 f006 豁免的负向回归证据有效，但正向缺口见 f008。如实披露此清单条目与 `git diff` 不符，不作免审理由。
- 改测方向复核：**无「让断言迁就当前实现输出」的就地改预期**。R3 新增为纯追加；`test_startup_migrations.py:354-370`（`_FakeScript.get_heads`/`walk_revisions` 加 `CURRENT_HEAD_REVISION` 项）、`test_migration_validation.py:96,430`、`test_migrate_to_unified_baseline.py:228,453` 的 `UNIFIED_BASELINE_REVISION`→`CURRENT_HEAD_REVISION` 均为迁移链新增 0002 head 后的 fixture/setup 与单 head 契约更新，断言主体不变（如 `assert upgrades == ["head", "head", "head"]`），非迁就实现；R2 已判此类规格驱动更新合法，R3 维持。
- 危险模式扫描：逐条扫过恒真断言、删/反转 expect、注释掉断言、弱化断言、删测试、`.skip`/`.only`/`@Ignore`、静默错误、mock 误用、阈值掩盖、条件跳过、程序赋值替代交互、存在即通过。R3 新增内容未命中：新测试无 mock、无 `# type: ignore`、无 `.skip`/`.only`、无 `assert True`、无阈值增大；`pytestmark_db` 为既存「PG 未配置才 skip」条件标记，门禁下实际执行。全量测试 diff 中唯一 `toBeVisible()` 命中（`.settings-sync-status` 精确文案 `认证失败`）属 R1/R2 已审前端 E2E，断言的是精确文本渲染而非纯存在性，非 R3 新增。`test_worker_loop.py` 既存 `patch(...record_connectivity_failure)` 与旧测试同型，真实写入由 `test_account_health_state_machine.py:48-100` 覆盖，R2 已判不构成假绿。
- 本轮新发现：1 条（1 minor，f008）。
- 未进表的提示：`test_a27_sync_account_folders_leaves_account_health_untouched`（`test_sync_hardening_a27_a28_a29.py:174-175`）在 `credential_state == "valid" and connectivity_state == "connected"` 后又重复 `assert acc.connectivity_state == "connected"`，冗余不影响断言有效性。`test_auth_failure_job_completes_and_resets_sync_activity` 未直接断言 `job.status == DONE` / 早退分支被命中，但「账号 `sync_enabled=False` + `CLAIMED` delta job + `sync_activity == idle`」组合在该构造下唯一可达路径即早退分支，可接受；补状态断言属可选扩展。门禁证据（定向 PG 275 passed、后端 unit 1654 passed + 2 个既存失败、前端 vitest 586 passed、模板契约 463 passed、黑盒 E2E 21 passed、全栈 E2E 8 passed、最终全量 PG 门禁 PG5 后台运行）为实施侧提供，本轮 AC 复验以 `git diff`、工作树测试断言与生产链路（`health.py` / `handlers.py` / `baseline.py` / 0002 revision）为准，未重跑全量门禁，PG5 未纳入独立复验证据。code 轴 `review_code.md` R2 对 AC-001 判 TICK-VOID（实现层 f006），本报告按测试轴独立判定，不交叉覆盖。
- 剩余覆盖缺口（均不阻断）：① f008：LEGACY 正向升级缺真实 0030 形状用例；② AC-002「`attempts` 递增」仍缺端到端 `claim_jobs` 后 `attempts == 2` 断言（R2 已列，R3 未变）；③ AC-005 的 401 信号缺「`ProviderHttpError(status=401)` 直接喂 `account_failure_kind` → `mark_credential_invalid` → `sync_enabled=False`」单条端到端用例（R2 已列，R3 未变）；④ AC-007 前端「后台静默同步网络异常不触发侧栏报警」仅以 `sync_activity=syncing` + 默认健康态覆盖，未注入网络异常组合（R2 已列，实由后端 AC-003 不外溢保证）。
- 总体判断：R3 新增测试真实可信、f007 已闭环、TDD 铁律无违反、7 条 AC 均有触达生产逻辑的测试支撑且全 TICK-VALID，仅新增 1 条 minor 覆盖缺口；按判定式 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_startup_migrations.py:562-631` 真实 PG 0001 基线→head 升级后断言三列存在、`sync_status` 消失、`auth_failed`→`("invalid","connected",False)`、`failed`→`("valid","degraded")`；`tests/mail_core/test_accounts_sync_status_deadcode.py:18-25` 断言 ORM 列布局、`tests/mail_core/test_domain_sync_statuses.py:25-33` 断言三枚举值域、迁移单 head 常量统一为 `20261112_0002`；R3 新增 `tests/mail_core/test_worker_loop.py:746-785` 真 PG 覆盖 `sync_activity` 早退终态复位。LEGACY 正向缺口见 f008（minor，不影响打勾）。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_sync_retry_queue.py:150-176` 经真实 `handle_job` 断言同一 job 行 `PENDING`、`retried.id == job_id`、`failure_attempts == 1`、`last_error` 脱敏且不含原文、无私有 successor；`tests/mail_core/test_account_health_state_machine.py:155-187` 直调 `reschedule_job` 断言 `id` 不变、`failure_attempts == 1`、硬编码 `run_after == _BASE + 1s`、`priority == 55`、`attempts`、`last_error`；`tests/mail_core/test_worker_loop.py:575-598` 断言 `reschedule_job` 以 `count_failure is True` 调用；`src/mail_core/sync/delta.py` 私有 enqueue 已删。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_worker_scheduler.py:71-84` 真实入队后断言 `payload == {"folder_id":..., "background": True}`；`tests/mail_core/test_account_health_state_machine.py:142-153` 与 `tests/mail_core/test_sync_backend_handler_isolation.py` 断言顶层 background 标记短路 DB；`tests/mail_core/test_sync_background_lineage.py:361-399` 断言后台 provider 错误后账号健康干净、同 job 行 requeue。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_account_health_state_machine.py:48-100`（单次 degraded、5 次+窗口升级、成功复位清诊断）、`:214-253`（真实 `backoff_seconds` 序列与双负向边界）；`tests/mail_core/test_sync_background_lineage.py:455,478,503` 经真实 handle_job 链路验证前景 `ConnectionError`→degraded、后台成功→connected；`src/mail_core/worker/handlers.py` 已删 `_recover_account_sync_status`。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_account_health_state_machine.py:190-211` 覆盖 401 / `AUTHENTICATIONFAILED` / `invalid_grant` / `InvalidAuthenticationToken` / `auth_failed` 结构化信号与传输反例；`tests/mail_core/test_imap_id_handshake.py:228-250` 断言 IMAP 确凿认证失败抛 `PermanentAuthError`；`tests/mail_core/test_sync_background_lineage.py:439`、`tests/mail_core/test_gmail_sync_strategy_and_timeout.py:176-213` 断言 `PermanentAuthError`→`credential_state=invalid`+`sync_enabled=False`；R3 新增早退用例持久化断言 `credential_state == "invalid"`；`tests/mail_core/test_account_health_state_machine.py:127-140`、`tests/mail_core/test_sync_backend_handler_isolation.py` 断言传输/控制流异常归 `NONE` 不改 credential。
- AC-006：TICK-VALID，re_verified。`tests/mail_core/test_accounts_api_unit.py:84-116,154-205` 断言 DTO/响应含四健康字段并移除 `sync_status`；`schemas/openapi.json` 的 `AccountOut` 增三字段 + `last_connectivity_error`、required 同步、删 `sync_status`；`src/frontend/src/api/generated/schema.ts` 同步四字段；既存 `tests/mail_core/test_openapi_contract.py` 断言提交契约与 `app.openapi()` 一致。
- AC-007：TICK-VALID，re_verified。`src/frontend/src/components/Sidebar.test.tsx:1187-1245` 覆盖 invalid/unreachable/degraded/connected/syncing 五态与「同步失败」「请检查账户设置」消失；`src/frontend/src/components/SettingsModal.test.tsx:869-905`、`src/frontend/src/components/settings_redesign.test.tsx:54-85` 精确断言四态标签与筛选；`tests/e2e/settings_workspace.spec.ts:38-41` 断言「同步失败」计数 0；生产 `Sidebar.tsx` / `SettingsModal.tsx` 已移除硬编码文案。

coverage = 7/7

reviewed_scope: 3c71f762ee403df4

verdict: PASS

## Round 4 (2026-11-12T10:39:58+08:00)

- round：4（收尾轮）
- reviewed_at：2026-11-12T10:39:58+08:00
- target：`git diff 20b61520c0837db9cd4c44506886bae6a507a1a2`
- 落点与指纹校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过；`HEAD` == `diff_anchor` == `20b61520c0837db9cd4c44506886bae6a507a1a2`（交付内容为工作树未提交改动，diff 为累计视图）。用 `monitoring.review_scope_fingerprint` / `review_status.current_scope_fingerprint` 同源重算当前指纹 = `043571e6ec6c3d82`，与注入值一致；本小节末写本轮 reviewed_scope 行供脚本取全文最后一条比对。`git status --short`：`M`/`A` 全部为已 `git add -N` 的交付文件（出现在 diff 中），`??` 为 `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md`（流程文件，指纹排除项）与两份 `review_*.md`（reviewer 产物，REVIEW_PROCESS_FILES），无 reviewer 不可见的未跟踪交付文件，不作 INCOMPLETE。`review-status` 的 `review_scope=stale` 系报告末条仍为 R3 指纹 `3c71f762ee403df4`，写入本轮行后即消解。

### Findings

本轮零 finding（clean review）。按用户点名复核的三项逐一结论如下，均无需新增 finding，故 `t076_test_f009` 起编号本轮未触发（clean review 禁止凑数）。

#### f008 处置复核（R3 minor：LEGACY 真实 0030 形状正向 PG 用例缺失）

- **登记合规**。已创建 follow-up `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md`：front matter `pid: p076` / `slug` / `status: todo` 齐备，位于 `docs/pending/` 原位，来源明确标注 `t076 Round 3 测试 reviewer finding t076_test_f008（minor，非阻断遗留）`，正文准确复述缺口（三个 LEGACY 夹具均由 head DDL 改 stamp 而成、`accounts` 不含历史 `sync_status`；`test_conversion_rejects_drifted_legacy_schema_and_rolls_back` 仅负向），并给出最小补齐方案（真实 `20261031_0030` 形状 → narrow conversion → `upgrade 20261112_0002` → 三列/`sync_status`/`folder_patrol_status`/revision/历史值映射断言）。
- **不构成「删旧测试不补语义」**。f008 是「从未存在」的 LEGACY 正向路径可选覆盖（新架构 `baseline.py` narrow-conversion 豁免引入），不是删除既有覆盖：`tests/scripts/test_migrate_to_unified_baseline.py` 的负向 drift 用例为既存、本 task diff 未改（R3 已核实）。主链路覆盖仍在且本轮复核属实：`tests/mail_core/test_startup_migrations.py:562`（`test_t7_older_baseline_upgrades_in_place_with_data_mapping`）真实 PG 0001 基线库升级 + `:602` `alembic_version` + `:609` `information_schema.columns` 三列/`sync_status` 消失 + `auth_failed`/`failed` 历史值映射；`src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py` 的 DDL 与 `tests/mail_core/test_migration_validation.py` 结构探针覆盖字段替换。TDD 铁律约束的是「实现变更致旧测试语义失效 → 新增覆盖新语义、旧测试原样保留或整体删除并说明理由、禁止就地改预期」；此处无旧测试失效，AC-001 正向/复位/迁移主链路均有真测试，缺的只是「可再加一个 case」的 LEGACY 入口端到端证据（R3 已按覆盖规则标 minor、不阻断）。把该 minor 显式登记为 `status: todo` 的 follow-up 而非在本 task 补测试，符合「minor 非阻断可 PASS + 系统性 follow-up 指向 pNNN」的处置，判定合规。

#### R4 新增断言真实性复核（`test_worker_loop.py`）

- `tests/mail_core/test_worker_loop.py:350` `assert account.sync_activity == "syncing"`（退避中）：**真实可信，触达生产 finally 逻辑，非假绿**。diff hunk `@@ -335,15 +339,20 @@` 显示本行是纯 `+` 新增（`:4217-4219` 注释 2 行 + 断言 1 行），同 hunk 其余 `-`/`+` 均为 R1/R2 已审的 `sync_status`→三维字段规格重写，R4 未删改任何旧断言预期。`Account`（`:313`）未显式设 `sync_activity`，用默认 `idle`；`:338` 真实调用 `handle_job`（仅 patch 外部边界 `sync_folder_delta` 抛 `RuntimeError`，未 mock 被测逻辑），触达 `src/mail_core/worker/handlers.py:256-261` 的 `try/finally`：退避路径经 `reschedule_job(count_failure=True)`（`handlers.py:223-230`）把 job 置 `PENDING`（非 DONE/FAILED），finally 的 `if job.status in (DONE, FAILED)` 为 False 不复位；入口 `set_sync_activity(active=True)`（`handlers.py:287-288` → `src/mail_core/accounts/health.py:72-78`）置 `syncing`。`:340` 在 `session.commit()` 后重新 `session.get(Account, account_id)`，反映持久化值。删除入口设置 / 把 finally 改成无条件复位 / 把退避伪报 DONE 任一情形都会令该断言变红，有真实区分力；期望值 `"syncing"` 来自 AC-001 规格语义（退避中任务在途=syncing，仅终态回 idle），非迁就当前实现输出。属补回 R1 f001 曾批评的第三维 + 锁定 finally 条件守卫负向分支，方向正确。
- `tests/mail_core/test_worker_loop.py:788` `assert acc.sync_activity == "idle"`（终态）：R3 纯追加用例 `test_auth_failure_job_completes_and_resets_sync_activity`（diff `:4362-4402`），R4 未动。经真实 `handle_job` 走 `sync_disabled` 早退 `complete_job`（DONE），finally 的 `if` 为 True → `_finish_activity`（`handlers.py:193-195`）→ `set_sync_activity(active=False)` → `idle`，R3 已验证触达 finally。
- **配对结论**：`:350`（非终态不复位，负向）与 `:788`（终态确实复位，正向）均经真实 `handle_job` 触达同一段 finally 条件逻辑，共同锁定 `if job.status in (DONE, FAILED)` 语义；无就地改预期制造假绿。

### 结论

- 前轮 finding 复核（以 `git diff 20b61520c0837db9cd4c44506886bae6a507a1a2` 与当前工作树为准）：
    - f008（R3 唯一 minor）：见上「f008 处置复核」——转 follow-up `p076` 登记合规，不构成删旧测试不补语义，维持 minor 未修代码但已显式留痕，不阻断。
    - f007（R2 minor，a27 `all(...)` 空集真空通过）：**维持闭环**。复核 `tests/mail_core/test_sync_hardening_a27_a28_a29.py:138` `assert jobs` 仍在两条全集断言前，R4 未回退。
    - f001~f006（R1/R2）：维持 R2/R3 结论（f001 主体消除 / a27 残留降 minor 后由 f007 闭环，f002~f006 已消除），本轮 diff 与工作树未见换形式弱化或重新引入。
- 改测方向复核：**无「让断言迁就当前实现输出」的就地改预期**。R4 对测试的唯一变更为 `test_worker_loop.py:348-350` 纯新增 3 行；早退用例行号由 R3 的 `746` 变为现 `749`（+3），与新增 3 行吻合，印证本轮无其它测试改动。p076 为流程文件，非测试代码。
- 危险模式扫描：逐条扫过恒真断言、删/反转 expect、注释掉断言、弱化断言、删测试、`.skip`/`.only`/`@Ignore`、静默错误（`# type: ignore`）、mock 误用、阈值掩盖、条件跳过、程序赋值替代交互、存在即通过。R4 增量（1 条具体值断言 + p076 流程文件）未命中；`@pytestmark_db` 为既存「PG 未配置才 skip」条件标记，非 `.skip`，定向 PG 门禁下实际执行。`test_worker_loop.py` 既存 `patch(...sync_folder_delta)` 为系统边界 patch，真实 health/finally 写入由 `test_account_health_state_machine.py:48-100` 与上述两断言覆盖，不构成假绿。无新增危险模式。
- 本轮新发现：0 条（clean review，无 f009+）。
- 未进表的提示：`test_worker_loop.py:349` 注释「(Round 3 f008)」与早退用例 docstring「(Round 2 f007)」为跨轴/错位 finding 编号引用（f008 实为 LEGACY PG 缺口，f007 指 code 轴早退复位），属过时表述，不影响断言有效性，按 R1/R2/R3 惯例不进 finding 表。`progress.md` 的「Review 处置」表仍为模板占位（`review-status` 报 `missing_disposition` 含 f001~f008）；按职责边界「已修/遗留/撤回」由 implementer 在收尾门禁填写，非测试 reviewer verdict 项，R2/R3 同状判 PASS，本轮维持；f008 的 minor 遗留已通过 p076 显式登记，登记本身合规。门禁证据（定向 PG 134 passed、后端 unit 1654 passed + 2 个既存失败、前端 vitest 586 passed、模板契约 463 passed、黑盒 E2E 21 passed、全栈 E2E 8 passed、最终全量 PG 门禁 PG6 后台运行）为实施侧提供，本轮 AC 复验以 `git diff`、工作树测试断言与生产链路（`handlers.py` / `health.py` / `baseline.py` / 0002 revision）为准，未重跑全量门禁，PG6 未纳入独立复验证据。
- 剩余覆盖缺口（均不阻断，minor / 可指向 p076）：① f008 → p076：LEGACY 正向升级缺真实 `20261031_0030` 形状用例（已登记 follow-up，主链路由 `test_t7` + Alembic 结构探针覆盖）；② AC-002「`attempts` 递增」仍缺端到端 `claim_jobs` 后 `attempts == 2` 断言（R2 已列，R3/R4 未变）；③ AC-005 的 401 信号缺「`ProviderHttpError(status=401)` 直接喂 `account_failure_kind` → `mark_credential_invalid` → `sync_enabled=False`」单条端到端用例（R2 已列，未变）；④ AC-007 前端「后台静默同步网络异常不触发侧栏报警」仅以 `sync_activity=syncing` + 默认健康态覆盖，未注入网络异常组合（R2 已列，实由后端 AC-003 不外溢保证）。
- 总体判断：R4 新增断言真实可信且触达生产 finally 逻辑、f008 处置合规、改测方向与 TDD 铁律无违反、7 条 AC 均有触达生产逻辑的测试支撑且全 TICK-VALID，无未解决 critical / important，指纹一致、无不可见交付文件，按判定式 PASS（无 INCOMPLETE 条件）。
- 系统性 follow-up：p076（`legacy_0030_real_shape_upgrade_gate`，已登记 `status: todo`）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_startup_migrations.py:562-631` 真实 PG 0001 基线→head 升级后断言三列存在、`sync_status` 消失、`auth_failed`→`("invalid","connected",False)`、`failed`→`("valid","degraded")`（本轮复核 `:602` `alembic_version`、`:609` `information_schema.columns` 均在工作树）；`tests/mail_core/test_accounts_sync_status_deadcode.py:18-25` ORM 列布局、`tests/mail_core/test_domain_sync_statuses.py:25-33` 三枚举值域、迁移单 head 统一为 `20261112_0002`；R4 新增 `tests/mail_core/test_worker_loop.py:350` 真 PG 覆盖退避中 `sync_activity == "syncing"` 与 `:788` 终态复位 `idle`。LEGACY 正向缺口见 f008→p076（minor，不影响打勾）。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_sync_retry_queue.py:150-176` 经真实 `handle_job` 断言同一 job 行 `PENDING`、`retried.id == job_id`、`failure_attempts == 1`、`last_error` 脱敏且不含原文、无私有 successor；`tests/mail_core/test_account_health_state_machine.py:155-187` 直调 `reschedule_job` 断言 `id` 不变、`failure_attempts == 1`、硬编码 `run_after == _BASE + 1s`、`priority == 55`、`attempts`、`last_error`；`tests/mail_core/test_worker_loop.py:575-598` 断言 `reschedule_job` 以 `count_failure is True` 调用；R4 新增 `:350` 锁定退避中 job 为 `PENDING` 且账号在途（finally 不复位）；`src/mail_core/sync/delta.py` 私有 enqueue 已删。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_worker_scheduler.py:71-84` 真实入队后断言 `payload == {"folder_id":..., "background": True}`；`tests/mail_core/test_account_health_state_machine.py:142-153` 与 `tests/mail_core/test_sync_backend_handler_isolation.py` 断言顶层 background 标记短路 DB；`tests/mail_core/test_sync_background_lineage.py:361-399` 断言后台 provider 错误后账号健康干净、同 job 行 requeue。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_account_health_state_machine.py:48-100`（单次 degraded、5 次+窗口升级 unreachable、成功复位清诊断）、`:214-253`（真实 `backoff_seconds` 序列与双负向边界）；`tests/mail_core/test_sync_background_lineage.py:455,478,503` 经真实 handle_job 链路验证前景 `ConnectionError`→degraded、后台成功→connected；`src/mail_core/worker/handlers.py` 已删 `_recover_account_sync_status`。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_account_health_state_machine.py:190-211` 覆盖 401 / `AUTHENTICATIONFAILED` / `invalid_grant` / `InvalidAuthenticationToken` / `auth_failed` 结构化信号与传输反例；`tests/mail_core/test_imap_id_handshake.py:228-250` 断言 IMAP 确凿认证失败抛 `PermanentAuthError`；`tests/mail_core/test_sync_background_lineage.py:439`、`tests/mail_core/test_gmail_sync_strategy_and_timeout.py:176-213` 断言 `PermanentAuthError`→`credential_state=invalid`+`sync_enabled=False`；`tests/mail_core/test_worker_loop.py:788` 早退终态持久化断言 `credential_state == "invalid"`；`tests/mail_core/test_account_health_state_machine.py:127-140`、`tests/mail_core/test_sync_backend_handler_isolation.py` 断言传输/控制流异常归 `NONE` 不改 credential。
- AC-006：TICK-VALID，re_verified。`tests/mail_core/test_accounts_api_unit.py:84-116,154-205` 断言 DTO/响应含四健康字段并移除 `sync_status`；`schemas/openapi.json` 的 `AccountOut` 增三字段 + `last_connectivity_error`、required 同步、删 `sync_status`；`src/frontend/src/api/generated/schema.ts` 同步四字段；既存 `tests/mail_core/test_openapi_contract.py` 断言提交契约与 `app.openapi()` 一致。
- AC-007：TICK-VALID，re_verified。`src/frontend/src/components/Sidebar.test.tsx:1187-1245` 覆盖 invalid/unreachable/degraded/connected/syncing 五态与「同步失败」「请检查账户设置」消失；`src/frontend/src/components/SettingsModal.test.tsx:869-905`、`src/frontend/src/components/settings_redesign.test.tsx:54-85` 精确断言四态标签与筛选；`tests/e2e/settings_workspace.spec.ts:38-41` 断言「同步失败」计数 0；生产 `Sidebar.tsx` / `SettingsModal.tsx` 已移除硬编码文案。

coverage = 7/7

reviewed_scope: 043571e6ec6c3d82

verdict: PASS
