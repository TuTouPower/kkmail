# Task review t093（reviewer_focus: 测试）

- task：`t093_decompose_imap_writeback_idle_and_remote_push`
- spec：`docs/tasks/t093_decompose_imap_writeback_idle_and_remote_push/task.md`
- diff_anchor：`9f7566857e1a767cedf74debf6ec6843f8109101`
- target：`git diff 9f7566857e1a767cedf74debf6ec6843f8109101`
- round：1
- reviewed_at：2026-11-26T21:05:50+08:00

## Findings

### t093_test_f001 - `ImapProvider.rate_limit_hint` 因 IDLE 助手缩进错位丢失，测试未校验 `ImapProvider` 协议面致 `AttributeError` 漏测

- 严重度：important
- 锚点：行为缺陷（`ImapProvider` 丢失 `MailProvider.rate_limit_hint` 方法并抛出 `AttributeError`，违反非范围契约「不改变 `ImapProvider` 对外公开签名」与 `AC-002` `imap.py` 拆解不破坏公开契约）
- 位置：`src/mail_core/providers/imap.py:1704-1750`、`src/mail_core/providers/base.py:186`、`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:47-68,190-226`、`tests/mail_core/test_provider_stub.py:4-12`
- 问题：`t093` 将 `open_idle_session` 辅助函数 `_collect_imap_capabilities`、`_open_idle_mailbox`、`_cleanup_failed_idle_client` 放在 `src/mail_core/providers/imap.py:1704-1747` 模块顶层（第 0 列）且直接插在 `def rate_limit_hint(self)` 之前，导致第 1749 行 `    def rate_limit_hint(self) -> RateLimitHint:` 缩进落入 `_cleanup_failed_idle_client` 函数体内部成为死局部函数。独立执行 `ImapProvider("h", 993, "u", "p").rate_limit_hint()` 直接抛出 `AttributeError: 'ImapProvider' object has no attribute 'rate_limit_hint'`，`ImapProvider` 不再满足 `MailProvider` Protocol。既有 `tests/mail_core/test_provider_stub.py` 仅校验 `StubProvider.rate_limit_hint()`，新增 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 仅校验函数名静态复杂度（且 `ast.walk` 未校验函数是否仍属于 `ImapProvider` 类）与 `open_idle_session` 异常分支，全量产物 `coverage.json` 显示 `imap.py:1750` 为 0 覆盖，致使公开接口破坏逃逸 2292 条测试。
- 建议：将 `_collect_imap_capabilities` 等模块级函数移至 `rate_limit_hint` 方法之后使 `ImapProvider.rate_limit_hint` 恢复类成员缩进，并在 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 增加对 `ImapProvider` 满足 `MailProvider` 公开方法（含 `rate_limit_hint()` 返回值）的回归测试。

### t093_test_f002 - `AC-002` 明确要求的缓冲读端 `sock.settimeout(None)` 未被任何测试断言或触发

- 严重度：important
- 锚点：`AC-002`（明确要求保持「缓冲读端 `settimeout(None)`」语义不变；上下文区「有意不测」为「无」）
- 位置：`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:190-226`、`src/mail_core/providers/imap.py:1723-1730`、`tests/mail_core/test_t061_imap_idle_probe.py:119-127,166-208`、`tests/mail_core/test_net_resilience.py:62-77`
- 问题：`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 的 `test_t093_open_idle_session_error_attribution_and_cleanup` 仅测试 `select` 返回 `"NO"` 和抛出 `EndpointCircuitOpenError` 两条失败路径（均在 `imap.py:1723-1725` 提前抛错，未走到 `imap.py:1726-1730` 的 `sock.settimeout(None)`），且测试桩 `_Sock.settimeout` 为空实现 `pass`、未记录调用。既有 `test_t061_imap_idle_probe.py` 配置 `timeout=10.0` 而所有 `wait_for_change` 耗时均 `<= 1.2s`，`test_net_resilience.py` 配置 `timeout=30.0` 并立即推送变更，全仓库无任何测试断言 `sock.settimeout(None)`（或验证超过 `provider.timeout` 时仍不超时），也未断言 `client.select(..., readonly=True)`。即使删除 `imap.py:1726-1730` 的 `sock.settimeout(None)`，全部 2292 条测试仍会假绿通过。
- 建议：在 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 中补充 `open_idle_session` 成功路径断言，验证 `client.select` 以 `readonly=True` 调用、当能力来自显式 `capability()` 响应或握手时正确放行、且 `sock.settimeout(None)` 被明确调用（或验证实际 socket 的 `gettimeout() is None`）。

### t093_test_f003 - `test_t093_remote_push_cas_identity_conflict_and_fencing` 名不副实，且 `AC-003` 的 `LeaseBusy` 与多处 `FencingMismatch`/跨块心跳中断分支在全套测试中 0 覆盖

- 严重度：important
- 锚点：`AC-003`（明确要求保持 `LeaseBusy` 退出、批前 `IN_PROGRESS` 与 `heartbeat_lease`、跨块心跳与 fencing 校验不变；上下文区「有意不测」为「无」）
- 位置：`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:229-287`、`src/mail_core/sync/remote_push.py:112-113,186-187,204-206,274-275,323-325,355,367-375,620,641`
- 问题：
    1. `test_t093_remote_push_cas_identity_conflict_and_fencing` 函数名含 `_and_fencing` 且 docstring 明确宣称验证 `chunk heartbeat break preserves behavior`，但该用例仅创建 2 条 `RemoteOperation`（`op_cas`、`op_conflict`），远小于 `remote_push.py:355` 的 `chunk_size = 100`，`_heartbeat_between_chunks`（`remote_push.py:305`）从未执行，且用例全程未构造或断言任何 `FencingMismatch`。
    2. 核对前序全量 PG 产物 `.scratch/test_runs/2cf7f02f81e34bafa177550cd5708c6a/coverage.json` 可见，即使在 2292 条全量测试中，`AC-003` 明确要求的下列并发/租约安全分支依然是 0 覆盖：
        - `push_remote_operations` 在租约被占用时走 `LeaseBusy` 返回 `{"status": "lease_busy"}`（`remote_push.py:112-113,620`，全仓库无任何 `push_remote_operations` 测例命中）；
        - `_heartbeat_between_chunks` 遇 `FencingMismatch` 时返回 `False` 并 `break` 中止后续分块执行（`remote_push.py:323-325,375`，分支 `[368, 375]`，`test_t064_batched_remote_writeback.py:664` 仅覆盖跨块心跳成功路径）；
        - `_claim_ops_in_progress` 认领前 `assert_fencing` 或认领后 `heartbeat_lease` 遇 `FencingMismatch` 返回 `{"status": "fencing_mismatch"}`（`remote_push.py:186-187,204-206,641`）；
        - `_defer_ops_for_capacity` 在容量退避事务中失去 fencing 返回 `{"status": "fencing_mismatch"}`（`remote_push.py:274-275`）。
- 建议：在 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 中拆出并补全真实 PG 测试：1) 另一 worker 持有有效租约时调用 `push_remote_operations` 返回 `{"status": "lease_busy"}` 且不修改操作状态；2) 提交超过 100 条（例如 105 条）分块推送并在首块后递增租约 `fencing_token`（或使块间 `heartbeat_lease` 触发 `FencingMismatch`），断言第二块不再调用 provider、返回 `{"status": "fencing_mismatch", "pushed": 0, "failed": 0}` 且操作保留 `IN_PROGRESS`；3) 补充认领阶段或容量回退阶段失锁时的 `fencing_mismatch` 回归断言。

### t093_test_f004 - `imap_writeback.py` 测试含未使用故障开关且若干边界路径未覆盖

- 严重度：minor
- 锚点：`AC-001`（边界分支覆盖完整性）
- 位置：`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:83-84,101-102,106-107,167-177`、`src/mail_core/providers/imap_writeback.py:92-93,228,234,344-357,369-371,394`
- 问题：`test_t093_imap_writeback_flag_symmetry_validation_and_exception_boundaries` 的 `_ImapClient` 定义了 `self.fail_seen_store` 与 `self.fail_flagged_store`（第 83-84、101-102、106-107 行）但从未置为 `True` 触发，导致 `imap_writeback.py:228,234`（`STORE Seen/Flagged failed`）在前序全量产物 `coverage.json` 中为 0 覆盖；同时 `imap_writeback.py:369-371`（`select {folder} failed`）、`394`（空输入 `operations=[]`）、`92-93`（`require_remote_id` 缺失直调 `apply_remote_operations`），以及 `-FLAGS (\Flagged)`（`is_flagged=False`）、首目录无成功时非传输异常（如 `RuntimeError`）不重抛、以及多目录隔离失败结果携带 `StructuredFailure`（第 177 行仅断言 `success is False`）均未验证。
- 建议：在 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 中启用 `fail_seen_store`/`fail_flagged_store`、补充 `select` 返回 `"NO"`、空批 `[]`、缺失 `remote_id`、`is_flagged=False` 及 `mixed[id_fail].failure` 断言，消除假客户端中的死开关。

### t093_test_f005 - `remote_push_errors.py` 中 `IMAP` 缺 `COPYUID` 冲突与 `get_retry_after_seconds` 未覆盖

- 严重度：minor
- 锚点：`AC-003`（移动身份冲突与重试延迟边界覆盖）
- 位置：`src/mail_core/sync/remote_push_errors.py:151-162,217-226`、`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:248-286`
- 问题：根据 `.scratch/test_runs/2cf7f02f81e34bafa177550cd5708c6a/coverage.json`，`remote_push_errors.py:217-226`（`provider_type == "imap"` 跨目录移动成功但缺失 `COPYUID` 目标 UID 时抛出 `RemoteIdentityConflict`）与 `remote_push_errors.py:153-162`（`get_retry_after_seconds` 解析异常 `retry_after_seconds` 与 `[1, 86400]` 夹逼及非法值回落）在全量 2292 测试中均未命中；此外 `test_t093_remote_push_cas_identity_conflict_and_fencing:285` 仅断言 `refreshed_conflict.status == FAILED`，未断言 `last_error` 包含 `RemoteIdentityConflict`。
- 建议：补充覆盖 `provider_type="imap"` 跨夹移动无 `COPYUID` 时拒绝结算为 `DONE` 的测试、`get_retry_after_seconds` 边界单测，并在冲突用例增加 `last_error` 断言。

## 结论

- 改测方向复核：无（相对 `diff_anchor` 未修改任何既有测试文件，仅新增 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py`）
- 本轮新发现：5 条（important 3 条、minor 2 条）
- 未进表的提示：1）`tests/mail_core/test_t064_batched_remote_writeback.py` 使用文件级 `pytestmark = skipif(not MAIL_CORE_DATABASE_URL)`，导致其不依赖数据库的 `RecordingImapClient` 单测（含批量写回、`UIDVALIDITY` 失配隔离与 `COPYUID`）在 `KKMAIL_TEST_MODE=unit` 下整文件被跳过，建议后续将 `skipif` 下沉至需库用例；2）`src/mail_core/providers/imap.py` 仍有未在 `t093` 范围拆解的高复杂度历史方法（如 `fetch_metadata_page` CC=50、`delta_changes` CC=48、`list_folder_catalog` CC=33），仅作规模观察记录。
- 总体判断：存在 3 条 important 阻断性问题且 `AC-002`、`AC-003` 打勾复核为 `TICK-VOID`，判定 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立重跑 `KKMAIL_TEST_MODE=unit` 下 `test_t093_writeback_idle_and_push_invariants.py`（AST 校验 `imap_writeback.py` 全部函数及 `apply_remote_operations` CC < 15 并验证写回单测）、`test_imap_store_move_missing_uid.py`、`test_imap_folder_mismatch_rejection.py`、`test_imap_remote_id.py`、`test_remote_writeback.py` 与 `test_uidvalidity_rebuild.py` 均通过（另参前序 PG/Dovecot 产物 `test_t064_batched_remote_writeback.py` 与 `test_imap_protocol_suite.py`）。
- AC-002：TICK-VOID，re_verified。独立运行单元测试与 Python 调用复验确认两项阻断问题：1）`src/mail_core/providers/imap.py:1704-1750` 拆出模块级辅助函数导致 `ImapProvider.rate_limit_hint` 缩进错位丢失并触发 `AttributeError`，测试未校验 `ImapProvider` 公开契约面（`t093_test_f001`）；2）`AC-002` 明确要求的缓冲读端 `sock.settimeout(None)` 未被任何测试断言或触发（`t093_test_f002`）。
- AC-003：TICK-VOID，trust_prior。本会话未启动 PostgreSQL（仅 `test_t093_complexity_budget_under_15` 与 `test_remote_push_robustness.py` 在 unit 模式复跑通过，`test_t093_remote_push_cas_identity_conflict_and_fencing` 等 PG 用例均 skip），PG 执行依赖 `.scratch/test_runs/2cf7f02f81e34bafa177550cd5708c6a/` 的 `junit.xml` 与 `coverage.json`；但审查测试代码与该 `coverage.json` 证实 `test_t093_remote_push_cas_identity_conflict_and_fencing` 宣称验证跨块心跳中断与 fencing 却仅推 2 条操作且从未触发 fencing，且 `LeaseBusy` 退出、块间心跳 `FencingMismatch` 中断、认领与容量回退 `FencingMismatch` 在全量 2292 测试中均为 0 覆盖（`t093_test_f003`）。
- AC-004：TICK-VALID，trust_prior。本会话独立复验了 `docs/blueprint/architecture.md` 与 `progress.md` 更新、`python3 scripts/check_doc_sensitive.py docs --check`（36 文件 0 违规）及模板契约门禁（`pytest .repo_template/tests -q -m contract`：389 passed, 1 skipped）；后端全量 PG + Dovecot IMAP（2292 passed, 2 skipped）与 E2E 冒烟依赖 `.scratch/test_runs/2cf7f02f81e34bafa177550cd5708c6a/test_summary.json`、`junit.xml` 及 `.scratch/e2e_artifacts/.last-run.json` 前序产物，未修改的前端与桌面端单测/构建仅依赖 `progress.md` 实施前序声明（注意全量门禁虽通过但未覆盖 `t093_test_f001` 回归）。

coverage = 2 / 4
建议合并前人工抽查 trust_prior 项

reviewed_scope: ff3337ed848db9b4
verdict: FAIL

## Round 2 (2026-11-27T01:57:02+08:00)

- task：`t093_decompose_imap_writeback_idle_and_remote_push`
- spec：`docs/tasks/t093_decompose_imap_writeback_idle_and_remote_push/task.md`
- diff_anchor：`9f7566857e1a767cedf74debf6ec6843f8109101`
- target：`git diff 9f7566857e1a767cedf74debf6ec6843f8109101`
- round：2
- reviewed_at：2026-11-27T01:57:02+08:00

## Findings

无（前轮全部 5 条 finding 均已消除，本轮复核未发现新的测试可信度、覆盖缺失或危险模式问题）。

## 结论

- 前轮 finding 复核：
    - `t093_test_f001`（important）：**已消除**。`src/mail_core/providers/imap.py:1537-1584` 已将 `_collect_imap_capabilities`、`_open_idle_mailbox`、`_cleanup_failed_idle_client` 移至 `ImapProvider.rate_limit_hint` 之后，恢复 `rate_limit_hint` 为类成员；`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:59-105` 已改为按 `imap_cls.body` 校验类方法归属（`apply_remote_operations`、`open_idle_session`、`rate_limit_hint`），并用 `typing.get_protocol_members(MailProvider)` 逐项断言 `ImapProvider` 协议表面及 `rate_limit_hint()` 返回值。
    - `t093_test_f002`（important）：**已消除**。`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:262-343`（`test_t093_open_idle_session_success_attribution_and_cleanup`）新增两条成功路径断言：`capability()` 回退识别（`client_cap.capabilities = ()`）、`client.capability()` 抛错时回退握手 `capabilities`、两次 `select(..., readonly=True)` 参数校验、`sock.settimeout(None)` 调用与真实 OS socket `gettimeout()` 从 `2.5` 清为 `None`，且 `finally` 中调用 `close()` 与 `_reader.join(timeout=1.0)` 无线程泄漏。
    - `t093_test_f003`（important）：**已消除**。`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:358-592` 拆出并落实真实 PG 用例：`test_t093_remote_push_cas_and_identity_conflicts`（CAS 冲突与身份冲突）、`test_t093_remote_push_lease_busy_returns_without_mutating_ops`（`lease_busy` 退出且不改 `attempts`/状态）、`test_t093_remote_push_chunk_heartbeat_fencing_break`（105 条操作在首块 100 条后抢占租约触发 `_heartbeat_between_chunks` 中断，断言 `chunks_seen == [100]`、返回 `fencing_mismatch` 且 105 条全留 `IN_PROGRESS`）与 `test_t093_remote_push_claim_and_capacity_fencing_mismatch`（覆盖容量退避、`heartbeat_lease` 与过期租约 `assert_fencing` 三处 `FencingMismatch`）；核对 `.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/junit.xml` 与 `coverage.json`，4 个 PG 用例均已执行通过且前述分支全部命中。
    - `t093_test_f004`（minor）：**已消除**。`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:114-260` 已启用 `fail_seen_store`、`fail_flagged_store` 与 `fail_select_folders`，并补齐空批 `[]` 与全无效批零建连（`connect_calls == 0`）、`is_flagged=False`、非传输 `RuntimeError` 隔离与 `StructuredFailure` 类型断言；`.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/coverage.json` 显示 `src/mail_core/providers/imap_writeback.py` 190 条语句 0 遗漏（98.88%）。
    - `t093_test_f005`（minor）：**已消除**。`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:345-445` 已补充 `test_t093_get_retry_after_seconds_bounds_and_fallback`（`[1, 86400]` 夹逼与非法值回落），并在 `test_t093_remote_push_cas_and_identity_conflicts` 中通过 `push_remote_operations` 与 `persist_move_remote_state` 覆盖 `provider_type="imap"` 跨夹移动缺 `COPYUID` 拒绝结算及 `last_error` 包含 `RemoteIdentityConflict` 断言。
- 改测方向复核：无（相对 `diff_anchor` 未修改任何既有测试文件，仅完善新增测试文件 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py`）
- 本轮新发现：0 条
- 未进表的提示：1）`tests/mail_core/test_t064_batched_remote_writeback.py` 仍使用文件级 `pytestmark = skipif(not MAIL_CORE_DATABASE_URL)`，致使纯内存 client 用例在 `unit` 模式下跳过（全量 PG 下 14 例已全部执行通过）；2）`.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/coverage.json` 中 `src/mail_core/providers/imap_wire.py` 的 `_copyuid_remote_state` 单 UID 兼容包装器（第 136-140 行）与 `_uid_sequence_index`/`_uid_sequence_value` 异常处理分支未命中，仅作覆盖细节记录。
- 总体判断：前轮 5 条 finding 均经代码与真实测试产物核实消除，未引入新阻断缺陷或危险模式，4 条 AC 全部成立，判定 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立重跑 `KKMAIL_TEST_MODE=unit` 下 `test_t093_writeback_idle_and_push_invariants.py`（5 passed, 4 PG skipped）、`test_imap_remote_id.py`（15 passed）、`test_uidvalidity_rebuild.py`（3 passed, 1 PG skipped）、`test_imap_store_move_missing_uid.py`（9 passed）、`test_imap_folder_mismatch_rejection.py`（4 passed）、`test_remote_writeback.py`（4 passed）及 AST 复杂度检验（`imap_wire.py` max CC=9、`imap_writeback.py` max CC=8、`ImapProvider.apply_remote_operations` CC < 15），并核对 `.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/` 中 `imap_writeback.py` 语句 100% 覆盖与 `test_t064_batched_remote_writeback.py`（14 passed）、`test_imap_protocol_suite.py`（4 passed）、`test_imap_provider_live.py`（1 passed）全部通过。
- AC-002：TICK-VALID，re_verified。独立重跑 `test_t093_writeback_idle_and_push_invariants.py` 与 `test_t061_imap_idle_probe.py`（10 passed）确认 `ImapProvider` 满足 `MailProvider` 全接口（含 `rate_limit_hint()`）、`open_idle_session` 与其 3 个模块辅助函数 CC < 15、绕过连接槽位预算、`IDLE` 能力与 `SELECT(..., readonly=True)` 检查、真实 socket `settimeout(None)` 清除、容量异常透传及非容量异常附加 `FailurePhase.IMAP` 与 socket 清理。
- AC-003：TICK-VALID，trust_prior。本会话独立复跑了 AST 复杂度检验（`remote_push.py` max CC=14、`remote_push_errors.py` max CC=5、`remote_push_move.py` max CC=10）、`test_t093_get_retry_after_seconds_bounds_and_fallback` 与 `test_remote_push_robustness.py`（4 passed）并逐行复核 4 个新增 PG 用例断言；真实 PG 并发执行依赖 `.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/` 的 `test_summary.json`、`junit.xml` 与 `coverage.json`（`test_t093_*` 9 例、`test_t064_*` 14 例、`test_t090_execution_origin.py` 6 例、`test_t091_pg_worker_diagnostics_integration.py` 6 例均 0 failed / 0 skipped，且 `lease_busy`、105 条跨块心跳中断与 3 处 `FencingMismatch` 均命中）。
- AC-004：TICK-VALID，trust_prior。本会话独立复验了 `docs/blueprint/architecture.md` 更新、`pytest .repo_template/tests -q -m contract`（389 passed, 1 skipped）、`scripts/check_doc_sensitive.py docs --check`（36 文件 0 违规）及 `scripts/export_openapi.py --check`（46 paths ok）；后端全量 PG + 真实 Dovecot IMAP（2297 passed, 2 skipped）依赖最后一次改动后的 `.scratch/test_runs/bd55a7aee4634aeb91c6fbf0ae1bddc0/` 产物，Playwright E2E 冒烟依赖最后一次 `src/`/`docs/` 改动后的 `.scratch/e2e_artifacts/.last-run.json`（passed），前端与桌面端单测/构建依赖 `progress.md` 前序声明。

coverage = 2 / 4
建议合并前人工抽查 trust_prior 项

reviewed_scope: 14664e3b9ecd2c0e
verdict: PASS
