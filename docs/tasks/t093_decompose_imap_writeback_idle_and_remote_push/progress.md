---
tid: "t093"
slug: "decompose_imap_writeback_idle_and_remote_push"
title: "重构 IMAP 写回、IDLE 会话与远端推送并发控制职责拆分"
status: "done"
branch: "t093_decompose_imap_writeback_idle_and_remote_push"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "9f7566857e1a767cedf74debf6ec6843f8109101"
spec_source_sha: "9f7566857e1a767cedf74debf6ec6843f8109101"
depends_on: ""
conflicts_with: ""
note: "来源 p098（t091 遗留）：拆解 apply_remote_operations (CC=90)、open_idle_session (CC=17) 与 push_remote_operations (CC=97) 高复杂度分支及重复逻辑并保持协议与并发契约完整"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- Round 1 实现与架构拆解：
    - 将 `ImapProvider.apply_remote_operations` 写回执行拆解至 `src/mail_core/providers/imap_writeback.py`（通过 `_FLAG_OP_SPECS` 消除 `\Seen`/`\Flagged` 重复 STORE+FETCH 核验逻辑，入口及全部新增函数 CC < 15）。
    - 将 `ImapProvider.open_idle_session` 拆解为 `_collect_imap_capabilities`、`_open_idle_mailbox` 与 `_cleanup_failed_idle_client`（全部 CC < 15）。
    - 将 `src/mail_core/sync/remote_push.py` 拆解为阶段协调函数（通过 `_defer_ops_for_capacity` 消除 `build_provider` 与批执行两处重复 `CAPACITY_ERRORS` 退避逻辑），并将错误分类与移动写回落库拆至 `src/mail_core/sync/remote_push_errors.py`。
- Round 1 评审闭环修复与架构进一步收敛：
    - 修复 `t093_code_f001` / `t093_test_f001`：将 `_collect_imap_capabilities` 等模块顶层辅助函数移至 `ImapProvider.rate_limit_hint`（`imap.py:1537`）之后，并在 `test_t093_writeback_idle_and_push_invariants.py` 增加类成员位置静态校验与 `MailProvider` 全接口表面核验。
    - 修复 `t093_code_f002` 并消除新文件超 400 行：将共享底层原语（`format_imap_remote_id`/`parse_imap_remote_id`/`_quote_mailbox`/`_get_server_uidvalidity`/`_copyuid_remote_states`/`_parse_uids_flags_from_response` 等）下沉至 `src/mail_core/providers/imap_wire.py`（196 行），由 `imap.py` 单向依赖 `imap_wire.py` 与 `imap_writeback.py`（386 行）并显式传入 `connect_fn`/`close_fn`；将 `remote_push` 的数据库 move/location 落库职责从 `remote_push_errors.py`（170 行）进一步拆出至 `src/mail_core/sync/remote_push_move.py`（271 行），并用 `_PushContext` 收敛 `remote_push.py`（657 行）阶段参数传递，所有拆分与修改函数 CC 均 `< 15`。
    - 修复 `t093_test_f002`~`f005`：补全 `open_idle_session` 成功路径（`capability()` 发现、`readonly=True` 选中、真实 OS socket `settimeout(None)` 与 `ImapIdleSession.close()`）、`STORE Seen/Flagged` 与 `SELECT` 失败/空批/`is_flagged=False`/`StructuredFailure` 断言、`get_retry_after_seconds` 边界及真实 PostgreSQL 下 `lease_busy`、超过 100 条分块心跳 `FencingMismatch` 中断、认领 `assert_fencing` / `heartbeat_lease` 与容量退避 `FencingMismatch`、以及 `IMAP` 无 `COPYUID` 冲突拒落库测试。
    - 最终验证：全量 PG + 真实 Dovecot IMAP（2297 passed, 2 skipped，最后一次代码/文档/测试改动后通过）、模板契约（389 passed, 1 skipped）、OpenAPI/敏感文档/依赖锁检查通过；此前在最后一次 `src/` 与 `docs/blueprint/` 改动后前端（56 files / 599 tests + tsc + build + oxlint + 26 Playwright E2E）与桌面端（全部通过，PG binary skip 说明如前）已通过，仅测试文件 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 之后追加完善断言并由全量 2297 套件重验通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-26T21:05:50+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t093_code_f001|critical|已修|将 `_collect_imap_capabilities`/`_open_idle_mailbox`/`_cleanup_failed_idle_client` 移出类体至 `rate_limit_hint` 之后，恢复 `ImapProvider.rate_limit_hint` 并增补公开表面与 AST 类成员断言|src/mail_core/providers/imap.py:1537-1583|
|t093_code_f002|minor|已修|抽离共享底层原语至 `imap_wire.py`，改为 `imap.py -> imap_writeback.py` 单向依赖并通过 `connect_fn`/`close_fn` 显式传参消除双向私有耦合|src/mail_core/providers/imap_wire.py:1-196|
|t093_test_f001|important|已修|修复 `ImapProvider.rate_limit_hint` 类归属并在测试验证 `MailProvider` 全部协议方法与 `rate_limit_hint()` 返回值|tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:59-105|
|t093_test_f002|important|已修|新增 `open_idle_session` 成功路径测试，断言 `select(..., readonly=True)`、`capability()` 回退、与真实 socket `gettimeout() is None` 并显式关闭会话|tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:262-316|
|t093_test_f003|important|已修|新增并实测通过真实 PG 下 `lease_busy` 退出、105 条分块心跳 `FencingMismatch` 中断与认领/容量退避 `FencingMismatch` 用例|tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:449-585|
|t093_test_f004|minor|已修|启用 `fail_seen_store`/`fail_flagged_store`，补充空批/缺失 `remote_id`/`select` 失败/`is_flagged=False`/非传输异常及 `StructuredFailure` 断言|tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:114-260|
|t093_test_f005|minor|已修|新增 `get_retry_after_seconds` 边界单测及 `provider="imap"` 跨夹无 `COPYUID` 冲突拒绝与 `last_error` 断言|tests/mail_core/test_t093_writeback_idle_and_push_invariants.py:345-445|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：全量 PostgreSQL + 真实 Dovecot IMAP 后端测试（`scripts/run-mail-core-tests.sh`：2297 passed, 2 skipped）；模板契约测试（389 passed, 1 skipped）；前端 Vitest/tsc/build/oxlint（56 test files / 599 tests + tsc + build + oxlint）、桌面端测试、依赖锁（ok）、OpenAPI（ok, 46 paths）与敏感文档扫描（36 files, 0 violations）全部通过（前端/桌面门禁在最后一次 `src/` 与 `docs/blueprint/` 修改后通过，后续仅补强 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py` 断言并经全量 2297 套件重验通过）
- 黑盒：Playwright E2E 冒烟（`npm --prefix src/frontend run test:e2e`：26 passed，最后一次 `src/` 与 `docs/blueprint/` 改动后全量通过）
- review：Round 2 独立代码审阅与测试审阅均 `PASS`（Round 1 全部 finding 已修，Round 2 零新 finding；`task.py review-status` `overall=PASS`，`reviewed_scope=14664e3b9ecd2c0e`）
- AC 判定：见 `task.md` 行内打勾（`AC-001` ~ `AC-004` 均已打勾并通过核验）

### 结果摘要

- 完成 `ImapProvider.apply_remote_operations` 写回职责拆解至 `src/mail_core/providers/imap_writeback.py`（386 行）与底层共享原语 `src/mail_core/providers/imap_wire.py`（196 行），并以 `_FLAG_OP_SPECS` 消除 `\Seen`/`\Flagged` 重复 STORE+FETCH 核验分支；`imap.py` 单向依赖两者且显式传递 `connect_fn`/`close_fn`。
- 完成 `ImapProvider.open_idle_session` 拆解为 `_collect_imap_capabilities`、`_open_idle_mailbox` 与 `_cleanup_failed_idle_client`，恢复并回归锁定 `ImapProvider.rate_limit_hint` 与 `MailProvider` 公开接口契约；`imap.py` 由 2003 行收敛至 1584 行。
- 完成 `src/mail_core/sync/remote_push.py`（657 行）协调状态机拆解，引入 `_PushContext` 与 `_defer_ops_for_capacity` 消除两处重复 `CAPACITY_ERRORS` 退避重入逻辑，并将错误分类与移动写回 DB 落库拆出至 `src/mail_core/sync/remote_push_errors.py`（170 行）与 `src/mail_core/sync/remote_push_move.py`（271 行）；全部拆分及修改函数 AST 圈复杂度 `< 15`。
- 同步更新 `docs/blueprint/architecture.md` 模块架构分工说明；新增 `tests/mail_core/test_t093_writeback_idle_and_push_invariants.py`（592 行）覆盖 AST/类成员/接口契约、IMAP 写回与 IDLE 边界、及真实 PG 下 `lease_busy`/CAS/`RemoteIdentityConflict`/分块心跳与认领容量退避 `FencingMismatch`。

### 长期文档闭环

- specs_index: not_applicable: 纯内部代码职责拆解（新增 `imap_wire.py`、`imap_writeback.py`、`remote_push_errors.py`、`remote_push_move.py` 与 IMAP IDLE 辅助函数并同步更新 `docs/blueprint/architecture.md`），未变更任何长期功能或协议规格。
