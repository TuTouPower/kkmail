# Task review t093（reviewer_focus: 代码）

- task：`t093_decompose_imap_writeback_idle_and_remote_push`
- spec：`docs/tasks/t093_decompose_imap_writeback_idle_and_remote_push/task.md`
- diff_anchor：`9f7566857e1a767cedf74debf6ec6843f8109101`
- target：`git diff 9f7566857e1a767cedf74debf6ec6843f8109101`
- round：1
- reviewed_at：2026-11-26T21:04:19+08:00

## Findings

### t093_code_f001 - open_idle_session 拆出的模块级辅助函数切断了 ImapProvider 类体，导致 rate_limit_hint 脱离类并破坏公开契约

- 严重度：critical
- 锚点：AC-004（「不改变长期接口契约」）、非范围（「不改变 `ImapProvider`、`BaseProvider` 或 `push_remote_operations` 对外公开签名」）及可观测行为缺陷
- 位置：`src/mail_core/providers/imap.py:1704-1750`（对照 `src/mail_core/providers/base.py:186`）
- 问题：拆解 `ImapProvider.open_idle_session` 时，新增的顶层模块函数 `_collect_imap_capabilities`（`1704` 行）、`_open_idle_mailbox`（`1718` 行）与 `_cleanup_failed_idle_client`（`1733` 行）以 0 缩进插入在 `ImapProvider.open_idle_session`（`1687-1701` 行）与原本位于类末尾的 `rate_limit_hint`（`1749-1750` 行）之间。Python 在 `1704` 行提前结束 `class ImapProvider`（AST 类范围 `820-1701` 行），并将 4 空格缩进的 `def rate_limit_hint(self) -> RateLimitHint:` 解析为 `_cleanup_failed_idle_client` 内部的死嵌套函数。独立实测 `hasattr(ImapProvider, "rate_limit_hint")` 为 `False`，调用 `ImapProvider(...).rate_limit_hint()` 直接抛出 `AttributeError: 'ImapProvider' object has no attribute 'rate_limit_hint'`，破坏了 `MailProvider` 协议契约。
- 建议：将 `_collect_imap_capabilities`、`_open_idle_mailbox` 与 `_cleanup_failed_idle_client` 移出 `class ImapProvider`（放到类定义之前或 `rate_limit_hint` 之后的模块顶层），确保 `def rate_limit_hint(self) -> RateLimitHint:` 恢复为 `ImapProvider` 的类方法。

### t093_code_f002 - imap_writeback.py 与 imap.py 之间存在双向私有依赖耦合

- 严重度：minor
- 锚点：架构与可维护性（循环依赖与跨模块私有耦合）
- 位置：`src/mail_core/providers/imap_writeback.py:14-22`、`src/mail_core/providers/imap_writeback.py:404-409`、`src/mail_core/providers/imap.py:1623`
- 问题：`imap_writeback.py` 在模块顶层反向导入 `imap.py` 的 5 个私有辅助函数（`_copyuid_remote_states`、`_extract_copyuid_texts`、`_get_server_uidvalidity`、`_parse_uids_flags_from_response`、`_quote_mailbox`）并直接调用传入 `ImapProvider` 的私有方法 `_connect_with_permit()` / `_close_client()`，而 `imap.py` 在 `apply_remote_operations` 内通过方法内延迟导入 `imap_writeback` 避免加载期环导入。这种双向私有耦合增加了后续重构与测试替身替换时的脆弱性。
- 建议：将共享 IMAP 写回协议解析/转义原语下沉至独立的无环底层模块（或 `imap_writeback.py`），使 `imap.py -> imap_writeback.py` 维持单向依赖。

## 结论

- 本轮新发现：2 条（critical 1 条，minor 1 条）
- 未进表的提示：
    - 文件行数超新建阈值（400 行，按规则不进 finding 表）：`src/mail_core/providers/imap_writeback.py`（417 行）、`src/mail_core/sync/remote_push_errors.py`（433 行，同时承载了错误分类与 move 目录/位置数据库落库两类职责）；`src/mail_core/providers/imap.py`（1750 行，较基线净减 253 行）与 `src/mail_core/sync/remote_push.py`（741 行，较基线净减 102 行）均为净减少。
    - 圈复杂度 `10 <= CC < 15`（按规则不进 finding 表）：`_validate_single_op`（`imap_writeback.py:87`，CC=12）、`_schedule_retry_or_fail`（`remote_push.py:379`，CC=14）、`push_remote_operations`（`remote_push.py:590`，CC=11）、`get_unconverged_field_intents`（`remote_push.py:701`，CC=11）、`resolve_push_op_failure`（`remote_push_errors.py:165`，CC=11）、`_sync_move_locations`（`remote_push_errors.py:295`，CC=10）；本次新增/修改函数全部满足 `< 15`。
    - 结构与范围外观察：`remote_push.py` 中 `_settle_push_results` 等阶段协调函数透传 7-11 个上下文参数，后续可按阶段上下文 dataclass 收敛；`imap.py` 中非本 task 范围的 `fetch_metadata_page`（CC=50）、`delta_changes`（CC=48）、`list_folder_catalog`（CC=33）、`_parse_message_meta_from_fetch`（CC=24）、`fetch_mime`（CC=22）、`_fetch_flags_for_uids`（CC=21）、`_decode_header`（CC=19）、`wait_for_change`（CC=17）、`reconcile`（CC=15）、`_parse_gm_labels`（CC=15）仍超过 15。
- 总体判断：存在 1 条 critical 阻断缺陷（`ImapProvider.rate_limit_hint` 脱离类体导致 `AttributeError` 与公开接口破坏），本次代码评审判定 FAIL。
- 系统性 follow-up：建议拆解 `src/mail_core/providers/imap.py` 其余高复杂度同步与解析方法（`fetch_metadata_page` / `delta_changes` / `list_folder_catalog` / `fetch_mime` 等，非阻断，建议 slug：`decompose_imap_sync_and_fetch_methods`）

### AC 复验方式

- AC-001：TICK-VALID，re_verified。逐行比对 `src/mail_core/providers/imap_writeback.py` 与基线 `apply_remote_operations` 实现，AST 核验全部 15 个函数 CC < 15（最高 `_validate_single_op` CC=12），`_FLAG_OP_SPECS` 消除 `\Seen`/`\Flagged` 重复验证分支，并独立运行 unit 测试 `test_t093_writeback_idle_and_push_invariants.py`、`test_remote_writeback.py`、`test_imap_remote_id.py` 验证写回校验/pre-FETCH/COPYUID/异常传播语义通过。
- AC-002：TICK-VALID，re_verified。独立核验 `open_idle_session`（CC=2）及其拆出的 `_collect_imap_capabilities`（CC=5）、`_open_idle_mailbox`（CC=4）、`_cleanup_failed_idle_client`（CC=7）逻辑完整保留绕过槽位、能力与 `SELECT` 校验、`settimeout(None)`、容量异常透传与 `FailurePhase.IMAP` 清理语义，并运行 `test_t061_imap_idle_probe.py` 与 `test_t093_writeback_idle_and_push_invariants.py` 通过（辅助函数错位对 `rate_limit_hint` 的破坏另计入 `t093_code_f001` 与 AC-004）。
- AC-003：TICK-VALID，re_verified。逐行比对 `src/mail_core/sync/remote_push.py` 与 `src/mail_core/sync/remote_push_errors.py`（全部 38 个函数 CC < 15，最高 `_schedule_retry_or_fail` CC=14），核验 `_defer_ops_for_capacity` 消除 `build_provider` 与批次执行两处容量退避重复，并保持 `LeaseBusy`、批前 `IN_PROGRESS`+心跳、块间心跳/fencing、CAS 保留 `PENDING`、`RemoteIdentityConflict`、重试/失败结算与 `execution_origin` 继承及模块 patch 锚点不变，unit 回归 `test_remote_push_robustness.py` 等通过。
- AC-004：TICK-VOID，re_verified。虽然 `docs/blueprint/architecture.md:35` 与 `progress.md` 已同步更新且敏感文档扫描（36 files, 0 violations）与 `.repo_template/tests -m contract`（389 passed, 1 skipped）通过，但实测 `hasattr(ImapProvider, "rate_limit_hint")` 为 `False` 且 `ImapProvider(...).rate_limit_hint()` 抛出 `AttributeError`，直接违背 AC-004「不改变长期接口契约」前提（PG/Dovecot/前端/桌面端/E2E 门禁未在本只读复核中重跑）。

coverage = 4 / 4

reviewed_scope: ff3337ed848db9b4

verdict: FAIL

## Round 2 (2026-11-27T01:58:05+08:00)

- target：`git diff 9f7566857e1a767cedf74debf6ec6843f8109101`
- round：2
- reviewed_at：2026-11-27T01:58:05+08:00

### Findings

无（Round 2 零 finding）。

### 结论

- 前轮 finding 复核：
    - `t093_code_f001`（critical）：**已消除**。`src/mail_core/providers/imap.py:1537-1538` 的 `def rate_limit_hint(self) -> RateLimitHint:` 已恢复位于 `class ImapProvider`（AST 范围 `652-1538` 行）末尾；模块级辅助函数 `_collect_imap_capabilities`（`1541-1552` 行）、`_open_idle_mailbox`（`1555-1567` 行）与 `_cleanup_failed_idle_client`（`1570-1584` 行）均已移至类定义之后的模块顶层。独立实测 `hasattr(ImapProvider, "rate_limit_hint")` 与 `"rate_limit_hint" in ImapProvider.__dict__` 均为 `True`，`MailProvider` 全部 11 个协议成员均在 `ImapProvider` 上完整暴露，且 `ImapProvider(...).rate_limit_hint()` 返回 `RateLimitHint(max_requests_per_minute=120, retry_after_seconds=None, reason='imap default')`。
    - `t093_code_f002`（minor）：**已消除**。共享 IMAP 线协议原语已下沉至无环叶模块 `src/mail_core/providers/imap_wire.py`（196 行，仅依赖标准库）；`src/mail_core/providers/imap_writeback.py`（386 行）不再反向导入 `imap.py` 也不直接访问 `_connect_with_permit` / `_close_client`，改为由 `src/mail_core/providers/imap.py:355-370` 在模块顶层单向导入并通过显式参数 `connect_fn=self._connect_with_permit, close_fn=self._close_client`（`src/mail_core/providers/imap.py:1455-1459`）注入连接与释放回调。
- 本轮新发现：0 条
- 未进表的提示：
    - 文件行数：全部新建文件均已收敛至 400 行 / 600 行阈值以下（`src/mail_core/providers/imap_wire.py` 196 行、`src/mail_core/providers/imap_writeback.py` 386 行、`src/mail_core/sync/remote_push_errors.py` 170 行、`src/mail_core/sync/remote_push_move.py` 271 行、`tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 592 行）；`src/mail_core/providers/imap.py`（1584 行，较基线净减 419 行）与 `src/mail_core/sync/remote_push.py`（657 行，较基线净减 186 行）均大幅收敛。
    - 圈复杂度 `10 <= CC < 15`（本次新增及重构函数全部 `< 15`）：`_compute_retry_schedule`（`src/mail_core/sync/remote_push.py:349`，CC=14）、`push_remote_operations`（`src/mail_core/sync/remote_push.py:537`，CC=10）、`_sync_move_locations`（`src/mail_core/sync/remote_push_move.py:130`，CC=10）；`remote_push.py` 已引入 `_PushContext` 收敛阶段协调参数传递。
    - 范围外观察：`src/mail_core/providers/imap.py` 中非本 task 范围的既有同步与解析方法仍 `>= 15`（`fetch_metadata_page` CC=50、`delta_changes` CC=47、`list_folder_catalog` CC=33、`fetch_mime` CC=22、`_parse_message_meta_from_fetch` CC=22、`_fetch_flags_for_uids` CC=21、`_decode_header` CC=19、`wait_for_change` CC=17、`_parse_gm_labels` CC=15、`reconcile` CC=15），维持 Round 1 建议的非阻断 follow-up。
- 总体判断：Round 1 阻断缺陷 `t093_code_f001` 与耦合项 `t093_code_f002` 均已彻底消除，Round 2 审查完整 diff 未发现新增缺陷或语义回归，全部新增/重构函数圈复杂度 `< 15` 且新增模块均 `< 400` 行，本次代码评审判定 PASS。
- 系统性 follow-up：建议拆解 `src/mail_core/providers/imap.py` 其余高复杂度同步与解析方法（`fetch_metadata_page` / `delta_changes` / `list_folder_catalog` / `fetch_mime` 等，非阻断，建议 slug：`decompose_imap_sync_and_fetch_methods`）

### AC 复验方式

- AC-001：TICK-VALID，re_verified。逐行核对 `src/mail_core/providers/imap.py:1451-1459`、`src/mail_core/providers/imap_wire.py`（196 行，13 个函数最高 CC=9）与 `src/mail_core/providers/imap_writeback.py`（386 行，17 个函数最高 CC=8），确认 `_FLAG_OP_SPECS` 消除 `\Seen`/`\Flagged` 重复逻辑且 `imap.py -> imap_writeback.py -> imap_wire.py` 单向无环、输入校验/UIDVALIDITY 门禁/pre-FETCH/COPYUID/容量与非成功异常传播语义一致，并独立运行 unit 用例（`test_t093_writeback_idle_and_push_invariants.py`、`test_imap_remote_id.py`、`test_remote_writeback.py` 等）通过。
- AC-002：TICK-VALID，re_verified。逐行核对 `src/mail_core/providers/imap.py:1521-1584`，确认 `open_idle_session`（CC=2）与已移至 `class ImapProvider` 之后的 `_collect_imap_capabilities`（CC=9）、`_open_idle_mailbox`（CC=4）、`_cleanup_failed_idle_client`（CC=5）完整保留绕过槽位、能力与只读 `SELECT` 检查、`settimeout(None)`、容量异常透传及 `FailurePhase.IMAP` 清理语义，并独立运行 `test_t061_imap_idle_probe.py` 与 `test_t093_writeback_idle_and_push_invariants.py` 通过。
- AC-003：TICK-VALID，re_verified。逐行核对 `src/mail_core/sync/remote_push.py`（657 行，21 个函数最高 `_compute_retry_schedule` CC=14）、`src/mail_core/sync/remote_push_errors.py`（170 行，11 个函数最高 CC=5）与 `src/mail_core/sync/remote_push_move.py`（271 行，8 个函数最高 CC=10），确认 `_PushContext` 与 `_defer_ops_for_capacity` 消除重复容量退避逻辑并严格保留 `LeaseBusy`、批前 `IN_PROGRESS`+心跳、跨块心跳/fencing、CAS 保留 `PENDING`、`RemoteIdentityConflict`、退避结算、`execution_origin` 继承及模块导出/patch 契约，并运行 `test_remote_push_robustness.py` 等 unit 用例通过（PG 集成用例在 `KKMAIL_TEST_MODE=unit` 下按预期跳过）。
- AC-004：TICK-VALID，re_verified。从代码实现层独立核验 `docs/blueprint/architecture.md:35`、新增模块 docstring 与 `progress.md` 的 `specs_index: not_applicable` 登记均已同步，实测 `ImapProvider` 完整保留 `MailProvider` 全部 11 个成员及 `rate_limit_hint()` 返回值，且 `scripts/export_openapi.py --check`（46 paths）、`scripts/check_doc_sensitive.py docs --check`（36 files, 0 violations）与 `.repo_template/tests -q -m contract`（389 passed, 1 skipped）全部通过（PG/Dovecot/前端/桌面端/E2E 运行门禁归属测试评审视角，本次代码复核未运行 Docker/PG）。

coverage = 4 / 4

reviewed_scope: 14664e3b9ecd2c0e

verdict: PASS
