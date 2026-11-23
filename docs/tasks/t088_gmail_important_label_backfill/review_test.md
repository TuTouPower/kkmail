# Task review t088（reviewer_focus: 测试）

- task：`t088_gmail_important_label_backfill`
- spec：`docs/tasks/t088_gmail_important_label_backfill/task.md`
- diff_anchor：`70a7f843634b3de09b78323136efa3b4799e9514`
- target：`git diff 70a7f843634b3de09b78323136efa3b4799e9514`
- round：1
- reviewed_at：2026-11-23T16:10:29+08:00

reviewed_scope: 087ed41502b63851

## Findings

### t088_test_f001 - CLI 入口零测试，AC-007 的命令层行为无覆盖

- 严重度：important
- 锚点：AC-007（"命令对不存在或无权限的 `--account-id` 给出明确失败"、"单个账号失败时其它账号继续处理"）
- 位置：`src/mail_core/__main__.py:148`（`_run_label_backfill`）；`tests/mail_core/test_gmail_label_backfill.py:167-182`（失败用例只调用 `backfill_account`）
- 问题：新增 4 条测试全部直接调用 `backfill_account`，没有任何测试触达 CLI 入口 `_run_label_backfill` 或 `main([... "--backfill-gmail-labels"])`。全仓 `tests/` 无 `backfill-gmail-labels` / `_run_label_backfill` / `--account-id` 引用（已 grep 确认）。因此以下 AC-007 行为零覆盖：`--account-id` 不存在账号时的 `account_not_found` 输出与返回码 1（`__main__.py:186-193`）、多账号循环中首个失败后其它账号继续处理并返回 1（`:177-194`）、gate 互斥与迁移前置。测试策略明确要求"命令层: CLI 参数、`--force`、失败续跑与非 Gmail 跳过的可观察输出与标记状态"，未落地。测试策略未把 CLI 列入"有意不测"。
- 建议：增补 CLI 测试：构造不存在 UUID 的 `--account-id` 断言返回 1 且输出含 `account_not_found`；构造两账号且首个 provider 失败，断言第二个仍被处理、进程整体返回 1。

### t088_test_f002 - AC-005"所有邮件视图不变"零断言

- 严重度：important
- 锚点：AC-005（"「所有邮件」视图计数与消息集合不变"）
- 位置：`tests/mail_core/test_gmail_label_backfill.py:123-125`
- 问题：回填用例只断言 `stats["important"]["total_count"] == 1` 与 important 列表包含历史成员，对 AC-005 后半句"所有邮件视图计数与消息集合不变"没有任何断言。测试策略把"All Mail 不变"列为必测 PG case，但无对应 assertion。回填若把 `\Important` 映射误写成 `\All` 成员、或额外插入 message，此缺口无法发现。
- 建议：同一测试内记录回填前 all view 的 `total_count` 与 `unified_inbox` 项集合，回填后断言二者不变。

### t088_test_f003 - AC-004 lease 互斥路径零断言

- 严重度：important
- 锚点：AC-004（"回填期间持有账号 lease，与常规同步互斥"）
- 位置：`tests/mail_core/test_gmail_label_backfill.py:120-122`；实现 `src/mail_core/sync/label_backfill.py:89-96`
- 问题：测试只覆盖 AC-004 后半句 checkpoint 不变（`:120-122`），对前半句 lease 互斥无任何断言：既不预占 lease 验证 `lease_busy` 短路，也不验证并发同步被阻塞。实现中 `acquire_lease` 抛 `LeaseBusy` 后返回 `status="lease_busy"`、不写完成标记、不发 FETCH 的路径（`label_backfill.py:94-96`）在测试里从未被触发。互斥是回填不扰动常规同步的核心安全保证。
- 建议：seed 一个已被其它 owner 持有 lease 的账号，调用 `backfill_account` 断言 `status == "lease_busy"`、完成标记未写、provider 未被调用。

## 结论

- 前轮 finding 复核：无（Round 1，无前轮）。
- 改测方向复核：无。diff 仅新增 `tests/mail_core/test_gmail_label_backfill.py`，未修改或删除既有测试，不存在"迁就实现"的改测。
- 本轮新发现：3 条（critical 0、important 3、minor 0）。
- 未进表的提示：
    - p090 既存回归经 `.scratch/t088_full_pg.log` 核实为真实断言失败（`4 failed, 2231 passed, 2 skipped`），失败用例位于 t088 未触碰的 `test_sync_backend_handler_isolation.py` / `test_sync_background_lineage.py` / `test_t061_idle_watcher.py`，属 t087 的 `account_failure_kind` 与 idle watcher 领域；AC-008 收敛方向诚实。但"main 基线同样复现"目前只有 p090 文字声明，无可核对 artifact，建议补一份基线日志路径。
    - `progress.md` 记"完整 PG 2224 passed"，而 `.scratch/t088_full_pg.log` 记 `2231 passed`，差 7；属收尾数字核对，非测试可信问题。
    - 危险模式扫描无命中：`pytest.mark.skipif(MAIL_CORE_DATABASE_URL)` 是 PG 集成测试环境门，实测带库 `-k test_gmail_label_backfill` 为 `4 passed`（非跳过），非危险 `.skip`；`_FakeProvider` 位于 provider 边界，注入真实 `upsert_messages` 路径，非 mock 被测逻辑；断言均为具体值，无恒真/弱化/删断言/条件跳过。
    - AC-006 由既有 `test_migration_validation.py:94`（单 head）、`:357`（ORM drift）、`:152`（可逆降级）覆盖，随新 revision `20261124_0005` 自动生效，非本 diff 新增但有效。
- 总体判断：核心回填逻辑测试可信（真 PG、具体断言、运行通过），但 CLI 层、All Mail 不变、lease 互斥三处 AC 明确要求的覆盖缺失，3 条 important 未解决 → FAIL。
- 系统性 follow-up：无（p090 已登记 t087 回归，本轮不重复报告）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_backfill.py:105-125` 断言 view location 与完成标记；实测 `-k test_gmail_label_backfill` 4 passed。
- AC-002：TICK-VALID，re_verified。`test_backfill_is_idempotent_and_skips_completed_and_non_gmail`（:128-151）断言重复+force 后 messages=1、locations=2。
- AC-003：TICK-VALID，re_verified。非 Gmail 跳过（:140-142）与无 important view 跳过（:154-164）均断言完成标记未写。
- AC-004：TICK-VOID，re_verified。checkpoint 不变有断言（:120-122），但 lease 互斥零断言（t088_test_f003），打勾缺有效测试。
- AC-005：TICK-VOID，re_verified。important 视图有断言（:123-125），但"所有邮件不变"零断言（t088_test_f002），打勾缺有效测试。
- AC-006：TICK-VALID，re_verified。`test_migration_validation.py:94/357/152` 覆盖单 head、零 drift、可逆降级；迁移 `20261124_0005` up/down 对称，head 由 `baseline.py:48` 同步更新。
- AC-007：TICK-VOID，re_verified。失败不写标记+续跑有断言（:167-182），但多账号失败续跑与 CLI `--account-id` 明确失败零测试（t088_test_f001）。
- AC-008：TICK-VOID，re_verified。覆盖声明"PG 集成测试覆盖 AC-001~005 / 失败续跑覆盖 AC-007"与 f001-f003 冲突；p090 4 条回归虽真实且属 t087 未触碰代码、收敛诚实，但覆盖声明不成立。
- AC-009：TICK-VALID，re_verified。`docs/guides/upgrade.md:23+` 与 `docs/blueprint/testing.md:81+` 已写入命令与幂等语义；`docs/pending/p089_*.md` 的 `fix_ref: "t088"` 指向本 task。

coverage = 5/9

verdict: FAIL

## Round 2 (2026-11-23T22:04:26+08:00)

reviewed_scope: 0be625430ef68719

## Findings

### t088_test_f004 - AC-007 多账号续跑 CLI 行为仍无测试，`--account-id` 失败输出未断言

- 严重度：minor
- 锚点：AC-007（"单个账号失败时其它账号继续处理"；"命令对不存在或无权限的 `--account-id` 给出明确失败"）
- 位置：`tests/mail_core/test_label_backfill_cli.py:39-76`；实现多账号分支 `src/mail_core/__main__.py:170-172`
- 问题：前轮 f001 新增的 4 条 CLI 测试全部显式传入 `account_id`（`:49`、`:57`、`:69`、`:76`），只走 `requested is not None` 单账号分支；无 `--account-id` 缺省的多账号循环零覆盖，即"首个账号失败后其它账号继续处理、整体返回 1"仍无断言。测试替身 `_Session`（`:19-32`）仅有 `get`、无 `scalars`，多账号路径一旦被触及即 `AttributeError`，侧面证明其从未被测。另 `test_missing_account_returns_failure`（`:54-58`）只断言返回码 1，未断言输出含 `account_not_found`。AC-007 其余子句已有可信测试，属"可再加一个 case"，不阻断。
- 建议：增补一条不传 `account_id` 的 CLI 测试，`_Session` 补 `scalars` 返回两个账号，首个 `backfill_account` 返回 `failed`、第二个返回 `completed`，断言二者均被调用且整体返回 1；missing 用例捕获 stdout 断言含 `account_not_found`。

## 结论

- 前轮 finding 复核：
    - t088_test_f001（CLI 入口零测试）：修不彻底。新增 `tests/mail_core/test_label_backfill_cli.py` 4 条，直接调用生产 `_run_label_backfill`，仅在 DB 会话工厂与 `backfill_account` 协作者边界 mock，实测 `KKMAIL_TEST_MODE=unit` 下 `4 passed`；`--account-id` 不存在（返回 1）、失败（返回 1）、非法 UUID（`SystemExit`）、force 路由（`calls == [(TARGET, True)]`）均已覆盖。但"多账号首个失败后其余继续"仍零覆盖，残余降为 minor f004。
    - t088_test_f002（All Mail 不变零断言）：已消除。`test_gmail_label_backfill.py:117` 回填前快照 `all_before`，`:151` 断言 `stats["all"] == all_before`，为真 PG 派生统计的具体等值断言。
    - t088_test_f003（lease 互斥零断言）：已消除。`_LeaseAwareProvider.fetch_metadata_page`（`:120-133`）在回填网络调用点用生产 `acquire_lease` 以另一 owner 探针，命中 `LeaseBusy` 记 True，`:153` 断言 `lease_checks and all(lease_checks)`；非空断言杜绝空列表假绿，探针位于系统边界、未 mock 被测 lease 逻辑。
- 改测方向复核：`tests/mail_core/test_sync_backend_handler_isolation.py` 的既有测试 `test_account_failure_kind_is_orthogonal` 被重写为 `test_account_failure_kind_uses_structural_signals`（删除自由文本 `OSError code=101` 的 TRANSPORT 预期，改测 `auth_failed`/`ConnectionError` 结构性信号）。有归因：`classify_failure` docstring 明示"自由文本刻意忽略"，p090 记录 t087 结构性分类契约，测试内注释说明旧自由文本 case 为伪契约而删除——属"测试写错/规格变了"的合法改测，非迁就实现；断言仍为具体值，无删 expect/弱化。其余无迁就实现的改测。
- 本轮新发现：1 条（critical 0、important 0、minor 1）。
- 未进表的提示：
    - p091 记录经当前 worktree 复跑核实为准确：`test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling` 与 `test_t073_ac003_stop_during_catchup_retry_returns_promptly` 2 条失败，`test_blocked_watch_deregisters_and_retries_after_expiry` 与 `test_ac003_manager_recovers_after_disconnect` 2 条通过——与 p091 正文完全一致。`.scratch/t088_full_pg_final.log` 的 2 条失败名对应状态调整中间态、早于撤回，属陈旧产物，非当前状态证据；建议补一份撤回后的全量 PG 日志作 AC-008 归档。
    - p090 关闭记录与 AC-008 收敛方向诚实：2 条失败分类回归已修（`auth_failed` 结构化映射 + 结构性断言），2 条 idle watcher 转 p091 与本 task 无关。
    - 新增 CLI 测试文件 `tests/mail_core/test_label_backfill_cli.py` 与 `docs/pending/p091_*.md` 处于未跟踪状态（未 `git add -N`），未进 `git diff`；reviewed_scope 指纹含未跟踪交付文件，reviewer 已直接读取审阅，但后续仅看 diff 的复核会漏掉 CLI 测试。
    - 危险模式扫描无命中：无恒真/弱化/删断言、无 `.skip`/`.only`、无条件跳过；`pytest.mark.skipif(MAIL_CORE_DATABASE_URL)` 为 PG 环境门，带库定向运行 4 passed 非跳过；`_FakeProvider`/`_LeaseAwareProvider` 位于 provider 边界，真实 `upsert_messages` 与 `acquire_lease` 路径未被 mock。
- 总体判断：前轮 3 条 important 全部消除且有实测证据（CLI 4 passed、带库 backfill 4 passed、迁移 13 passed），残余仅 1 条 minor；AC 打勾真实可信，无未解决 critical/important → PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_backfill.py:113-153` 断言历史 `\Important` 成员写入 view location、完成标记与 important 视图，带库 `-k test_gmail_label_backfill` 实测 4 passed。
- AC-002：TICK-VALID，re_verified。`test_backfill_is_idempotent_and_skips_completed_and_non_gmail`（:156-179）断言重复/force 后 messages=1、locations=2、completed 跳过，全部通过。
- AC-003：TICK-VALID，re_verified。非 Gmail 跳过（:168-170）与无 important view 跳过（:182-192）均断言完成标记未写。
- AC-004：TICK-VALID，re_verified。`_LeaseAwareProvider`（:120-133）在 FETCH 内用真实 `acquire_lease` 探针验证回填持锁互斥（:153 `lease_checks and all`），checkpoint 不变断言 :146-148；f003 已消除。
- AC-005：TICK-VALID，re_verified。回填前 `all_before`（:117）与回填后 `assert stats["all"] == all_before`（:151）、important stats/列表（:150、:152）；f002 已消除。
- AC-006：TICK-VALID，re_verified。迁移 `20261124_0005` 在定向 PG run 中 up 成功，`-k test_migration_validation` 实测 13 passed（单 head/零 drift/可逆降级）。
- AC-007：TICK-VALID，re_verified。CLI 4 条（`test_label_backfill_cli.py:39-76`）unit 模式实测 4 passed，失败续跑（:195-210）通过；多账号续跑 case 仍缺（f004，minor，不否决打勾）。
- AC-008：TICK-VALID，re_verified。定向 PG backfill 4 passed、迁移 13 passed、CLI 4 passed；复跑 p091 4 条 idle watcher 恰好其记录的 2 条失败、另 2 条通过，收敛声明成立；`t088_full_pg_final.log` 为中间态陈旧产物已在提示说明。
- AC-009：TICK-VALID，re_verified。`docs/guides/upgrade.md:23+` 与 `docs/blueprint/testing.md:81+` 含回填命令与幂等语义；`docs/pending/p089_*.md` 的 `fix_ref: "t088"` 指向本 task。

coverage = 9/9

verdict: PASS

## Round 3 (2026-11-23T22:10:49+08:00)

reviewed_scope: e8e666e55663153a

## Findings

### t088_test_f005 - 本轮修复的生产关键路径（session 内构造 provider）零测试守护

- 严重度：minor
- 锚点：AC-001/002/005（生产回填真实可用）的回归守护；属「可再加一个 case」，不阻断 PASS
- 位置：`src/mail_core/sync/label_backfill.py:100-103`（provider 移入 session、commit 前以 attached `account` 构造）；`tests/mail_core/test_gmail_label_backfill.py:135,161-162,166-169,189,203,209`（全部注入 `provider_factory=lambda *a, **k: ...`）
- 问题：本轮生产改动把 `provider_factory(account, store or get_credential_store(), traffic_class=...)` 从脱管/过期实例改为 session 内 attached 实例、commit 前构造，修复 code 视角 critical f003（真实环境对每个账号 `DetachedInstanceError`→`failed`）。但 4 条 PG 测试全部经 `provider_factory` 注入假 provider，假工厂 `*a, **k` 完全忽略 `account` 实参。后果：若把 provider 构造再移回 session 外/commit 后、或传入脱管 account，现有测试仍全绿，无法发现该生产回归；`store or get_credential_store()` 与 `traffic_class` 实参路径同样零覆盖。当前实现正确（本轮实测 4 passed），属回归守护缺口而非现存缺陷。code reviewer 在 f003 建议中已提示「补一条不注入假 provider 的构造路径用例」，测试侧尚未承接。
- 建议：增补一条不传自定义 `provider_factory`、走默认 `build_provider` 的集成用例（配最小合法 account/config），断言回填返回 `completed` 而非 `failed`，锁定 attached-account 构造契约。

## 结论

- 前轮 finding 复核：
    - t088_test_f004（AC-007 多账号续跑 CLI 行为仍无测试）：仍存在。`tests/mail_core/test_label_backfill_cli.py` 本轮未改，4 条仍全部显式传 `account_id`，`--account-id` 缺省的多账号循环零覆盖。minor，不阻断。
- 改测方向复核：本轮无测试文件改动（仅生产代码 provider 构造位置 + p090 文案），不存在「迁就实现」的改测。Round 1 对 `test_sync_backend_handler_isolation.py` 的重写已在上轮核实为合法改测，本轮未再触碰。
- 本轮新发现：1 条（critical 0、important 0、minor 1）。
- 未进表的提示：
    - 实测复核（本轮重跑）：CLI unit `tests/mail_core/test_label_backfill_cli.py` 4 passed（`KKMAIL_TEST_MODE=unit`）；带库 `-k test_gmail_label_backfill` 4 passed；带库 `-k "test_migration_validation or test_sync_backend_handler_isolation"` 19 passed。生产改动未引入测试回归，4 条 PG 用例与 CLI/migration 集合稳定。
    - p090 文案更正已核实：`docs/pending/p090_sync_failure_classification_and_idle_catchup_regression.md:19-20` 把旧夸大声明改为「修复 2 条失败分类回归；其余 2 条 idle watcher 回归转 p091」，与 front matter（`reason`）、p091、当前 AC-008 一致；code 视角 f004 的文档矛盾已消除。
    - AC 漂移：相对 `70a7f843634b` 契约区除打勾与 AC-008 收敛（前两轮已记录并经处置）外无文本变化，本轮无新增漂移。
    - 危险模式扫描无命中：无恒真/弱化/删断言、无 `.skip`/`.only`、无条件跳过、无阈值掩盖；`pytest.mark.skipif(MAIL_CORE_DATABASE_URL)` 为 PG 环境门，带库定向 4 passed 非跳过；`_FakeProvider`/`_LeaseAwareProvider`/`_Broken` 位于 provider 边界，真实 `upsert_messages` 与 `acquire_lease`/`heartbeat_lease`/`release_lease` 路径未被 mock。
    - AC-008 完整 PG 套件本轮仅做定向复跑（未重跑全量）；p091 记录的 2 条 idle watcher 回归位于本轮未触碰的 idle watcher 代码，收敛声明不受影响。
- 总体判断：本轮生产小改未引入测试回归、无 AC 漂移；AC-001~009 打勾在测试视角仍成立，残余仅 1 条 minor（f005）与前轮 minor（f004），无未解决 critical/important → PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_backfill.py:113-153` 断言历史 `\Important` 成员写入 view location、完成标记与 important stats/list，本轮带库 `-k test_gmail_label_backfill` 实测 4 passed。
- AC-002：TICK-VALID，re_verified。`test_backfill_is_idempotent_and_skips_completed_and_non_gmail`（:156-179）断言二次运行 `skipped_completed`、`--force` 重跑 `completed`、非 Gmail `skipped_not_gmail`，messages=1/locations=2，实测通过。
- AC-003：TICK-VALID，re_verified。非 Gmail 跳过（:168-170）与无 important view 跳过（:182-192）均断言完成标记未写，实测通过。
- AC-004：TICK-VALID，re_verified。`_LeaseAwareProvider`（:120-133）在 FETCH 内用真实 `acquire_lease` 探针，`:153` `lease_checks and all(lease_checks)` 非空断言；checkpoint 不变断言 :146-148，实测通过。
- AC-005：TICK-VALID，re_verified。回填前 `all_before`（:117）、`assert stats["all"] == all_before`（:151）、important stats/list（:150、:152），实测通过。
- AC-006：TICK-VALID，re_verified。本轮带库 `-k "test_migration_validation or test_sync_backend_handler_isolation"` 实测 19 passed；迁移 `20261124_0005` up 成功，单 head/零 drift/可逆降级门禁通过。
- AC-007：TICK-VALID，re_verified。CLI 4 条（`test_label_backfill_cli.py:39-76`）unit 模式实测 4 passed；失败续跑（:195-210）通过。多账号续跑 case 仍缺（f004，minor，不否决打勾）。
- AC-008：TICK-VALID，re_verified。本轮定向复跑：backfill 4 passed、迁移+分类 19 passed、CLI 4 passed，全通过；p091 记录的 2 条 idle watcher 回归未被本轮改动触碰，收敛声明成立（全量套件本轮未重跑）。
- AC-009：TICK-VALID，re_verified。`docs/guides/upgrade.md:30-33` 与 `docs/blueprint/testing.md:84` 含回填命令与幂等语义；`docs/pending/p089_*.md` 的 `fix_ref: "t088"` 指向本 task。

coverage = 9/9

verdict: PASS
