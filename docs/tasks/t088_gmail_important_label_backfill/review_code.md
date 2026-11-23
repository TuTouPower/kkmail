# Task review t088（reviewer_focus: 代码）

- task：`t088_gmail_important_label_backfill`
- spec：`docs/tasks/t088_gmail_important_label_backfill/task.md`
- diff_anchor：`70a7f843634b3de09b78323136efa3b4799e9514`
- target：`git diff 70a7f843634b3de09b78323136efa3b4799e9514`
- round：1
- reviewed_at：2026-11-23T16:13:47+08:00

reviewed_scope: 087ed41502b63851

## Findings

### t088_code_f001 - provider 构造异常逃出 backfill_account，破坏单账号隔离并泄漏 lease

- 严重度：important
- 锚点：AC-007（并破坏 AC-004 的 lease 生命周期）；单账号 provider 配置错误导致整条命令中止、其它账号不再处理，且已取得的 lease 不释放。
- 位置：`src/mail_core/sync/label_backfill.py:98-100`（`provider_factory(...)` 位于 `try`（:102）与 `finally`（:135）之前）；`src/mail_core/__main__.py:178-179`（账号循环无异常捕获）
- 问题：`backfill_account` 在 `:89-93` 取得并 commit 账号 lease，但 `provider_factory(...)` 在 `:98-100` 于 `try` 块之外调用。`build_provider` 对账号级配置错误会抛异常（`src/mail_core/providers/factory.py:176` 缺 credential_ref、:123 非法 imap_port、:213 非法 imap_host、:232 未知 provider）。复现：两个 Gmail 账号，第一个缺 credential_ref 或 provider 非法，运行 `python -m mail_core --backfill-gmail-labels`：(1) `:135` 的 `finally` 不执行，lease 不释放，持有至 TTL=120s，期间常规同步（`src/mail_core/sync/engine.py:192` 走同一 `acquire_lease`）被阻塞；(2) 异常穿透 `_run_label_backfill` 的 `for` 循环（`__main__.py:178-179` 无 try/except），整条命令 traceback 退出，第二个账号未被处理。AC-007 明确要求「单个账号失败时其它账号继续处理」，当前只在 `try` 内覆盖网络/落库异常（`label_backfill.py:132-134`），未覆盖 provider 构造失败。
- 建议：把 `provider_factory(...)` 移入 `try` 块（lease 取得之后），使异常统一经 `except` 返回 `failed` 并经 `finally` 释放 lease；同时在 `__main__.py:178-179` 的逐账号循环加 try/except 兜底，避免任何单账号异常中断整条命令。

### t088_code_f002 - AC-008 相对规格基准被放宽，diff 内无用户确认证据

- 严重度：important
- 锚点：AC-008（契约区 drift）
- 位置：`docs/tasks/t088_gmail_important_label_backfill/task.md:38`
- 问题：相对基准 `70a7f843634b` 的 AC-008 原文「后端 unit、完整 PG 套件、前端测试与项目门禁全量通过」，当前改为「后端 unit、前端测试与项目门禁全量通过，完整 PG 套件除 p090 记录的 4 条既存 t087 回归外全部通过」，把门禁从「完整 PG 全绿」放宽为「排除 4 条失败」。diff 内唯一支撑是 implementer 自建的 `docs/pending/p090_sync_failure_classification_and_idle_catchup_regression.md`（`status: todo`、`处理：未开`），未见用户确认或决策记录。按 reviewer 共享规则「未经确认的 AC 变更按 blocking finding 处理」，该放宽不得在 code 视角直接判为打勾成立。
- 建议：取得用户对放宽 AC-008 的明确确认并在 `docs/blueprint/decisions/` 记录 ADR，或恢复原 AC-008 措辞并通过正式门禁例外登记这 4 条 t087 回归，再重新打勾与派审。

## 结论

- 前轮 finding 复核：首轮，无。
- 本轮新发现：2 条（important × 2，无 critical）。
- 未进表的提示：文件过大——新增实现 `src/mail_core/sync/label_backfill.py` 146 行、`src/mail_core/__main__.py` 311 行、测试 `tests/mail_core/test_gmail_label_backfill.py` 182 行，均未达阈值，无 finding。圈复杂度——`backfill_account` 约 10、`_run_label_backfill` 约 8，未达 minor 阈值 15，无 finding。范围外观察——`docs/tasks/t088_gmail_important_label_backfill/review_test.md` 为 test reviewer 产物（未跟踪），非本 task 交付文件，不纳入 code 审查范围。
- 总体判断：回填主路径实现与迁移、文档改动完整，但 AC-007 存在可复现的单账号失败隔离缺口并泄漏 lease，AC-008 打勾建立在未经确认的契约放宽之上；两条 blocking finding 未解决，PASS 不成立。
- 系统性 follow-up：无（p090 已记录完整 PG 套件的 4 条 t087 既存回归，由 AC-008 处置承接；本轮不重复报告）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/__main__.py:234-239` 注册 `--backfill-gmail-labels`、`:272-273` 调用；`src/mail_core/sync/label_backfill.py:103-131` 按物理容器分页重放、写 `\Important` view location 并于 :127-130 写完成标记；`tests/mail_core/test_gmail_label_backfill.py::test_backfill_writes_historical_label_location_and_marks_completion` 断言 location 含 view_id、completion 非空、important stats/list。
- AC-002：TICK-VALID，re_verified。`src/mail_core/sync/metadata.py:87-89,113` 按 remote_id 与 `(message_id, folder_id)` 去重；`label_backfill.py:74-75` 默认跳过已完成、force 重走；测试第二例断言二次运行 `skipped_completed`、force 后 messages=1、locations=2。
- AC-003：TICK-VALID，re_verified。`label_backfill.py:72-73` 非 Gmail、`:76-78` 无 important view 均早退且不写完成标记；`test_backfill_is_idempotent_and_skips_completed_and_non_gmail` 与 `test_backfill_skips_account_without_important_view` 断言 status 及 `label_backfill_completed_at is None`。
- AC-004：TICK-VALID，re_verified。`label_backfill.py:89-96` 取 lease、`:108-114` 逐页 heartbeat、`:135-146` finally 释放；常规同步 `src/mail_core/sync/engine.py:192` 走同一 `acquire_lease` 故互斥；`upsert_messages` 不写 checkpoint，测试断言 cursor 与 `full_scan_complete` 不变。异常路径 lease 泄漏另见 f001（锚 AC-007）。
- AC-005：TICK-VALID，re_verified。`label_backfill.py:120` 仅对 `label_view_folders={"\\Important": view_id}` 写 view location，`:83-84` 的 `kind=CONTAINER` 过滤排除 all/important view，All Mail 投影不变；测试断言 `stats["important"]["total_count"]==1` 与 `unified_inbox(..., folder_id=view_id)` 列表。（All Mail 计数未显式断言，属 test reviewer 关注面。）
- AC-006：TICK-VALID，re_verified。新增 `src/mail_core/db/alembic/versions/20261124_0005_account_label_backfill.py` 的 upgrade add_column / downgrade drop_column，`src/mail_core/db/baseline.py:48` head 同步为 `20261124_0005`，`src/mail_core/mail/storage/models.py:129` 为 `Optional[datetime]`；`tests/mail_core/test_migration_validation.py::test_alembic_chain_has_single_head` 与 `::test_orm_schema_drift_and_negative_detection` 覆盖单 head 与零 drift。
- AC-007：TICK-VOID，trust_prior。provider 构造异常逃出 `backfill_account`（f001），单账号失败未被 CLI 隔离且 lease 未释放；`src/mail_core/__main__.py:186-194` 对非 Gmail/已完成账号返回 0（`skipped`），「无权限」场景无明确失败语义。
- AC-008：TICK-VOID，trust_prior。AC-008 文本相对 70a7f843 被放宽且无用户确认（f002）；完整 PG 套件结果仅来自 implementer 声明与 p090，code 视角无法独立复验门禁全绿。
- AC-009：TICK-VALID，re_verified。`docs/blueprint/testing.md:84` 与 `docs/guides/upgrade.md:26-33` 记录回填命令、幂等、`--force`、`--account-id` 与单账号失败续跑语义；`docs/pending/p089_gmail_label_historical_backfill.md` 为 `status: closed`、`fix_ref: t088`。

coverage = 7/9

verdict: FAIL

## Round 2 (2026-11-23T22:03:42+08:00)

reviewed_scope: 0be625430ef68719

## Findings

### t088_code_f003 - backfill_account 把已过期且脱管的 Account 传给 build_provider，生产环境每个账号都失败

- 严重度：critical
- 锚点：AC-001（连带使 AC-002、AC-005 的打勾失去实现支撑）；可观测行为缺陷：`python -m mail_core --backfill-gmail-labels` 对任何真实账号返回 `status=failed`，不写完成标记、不补 `\Important` view location。
- 位置：`src/mail_core/sync/label_backfill.py:68-102`（:93 `session.commit()` 使 `account` 过期，:97-98 `with` 退出后脱管，:100 将 `account` 传给 `provider_factory`）；`src/mail_core/db/session.py:86`（`sessionmaker` 未设 `expire_on_commit=False`）
- 问题：`:69` 由 `session.get` 加载的 `account` 在 `:93` 的 `session.commit()` 后被 SQLAlchemy 标记过期（用项目 `.venv` 的 SQLAlchemy 2.1.5 实测：commit 后 `inspect(account).expired == True`，随后读属性抛 `DetachedInstanceError`），`:97` 的 `with` 块退出使 session 关闭、实例脱管。生产 CLI 走默认 `provider_factory=build_provider`（`label_backfill.py:65`，`__main__.py:179` 未传自定义 factory），`build_provider` 在 `src/mail_core/providers/factory.py:151-152,166,174-175,199,217,232` 读取 `account.provider` / `.config` / `.id` / `.email` / `.credential_ref`，必抛 `DetachedInstanceError`，被 `label_backfill.py:132-134` 吞成 `status=failed`。同仓正确模式见 `src/mail_core/sync/engine.py:197-204`（close 前显式构造 `account_snapshot` 供网络 I/O）。`tests/mail_core/test_gmail_label_backfill.py` 全部以 `provider_factory=lambda *a, **k: _FakeProvider(...)` 注入假 provider，绕开真实构造路径，故测试全绿而生产全败。
- 建议：在 `label_backfill.py:97` 的 `with` 块退出前按 `engine.py:198-204` 构造 `Account` 快照（id/email/provider/credential_ref/config），把快照而非脱管 ORM 实例传给 `provider_factory`；并补一条不注入假 provider 的构造路径用例。

### t088_code_f004 - p090 正文残留与 p091/AC-008 矛盾的「4 条转绿、退避已修」声明

- 严重度：minor
- 锚点：文档与规格一致性（记录诚实性）；不阻断 PASS。
- 位置：`docs/pending/p090_sync_failure_classification_and_idle_catchup_regression.md:17`（对照 :18、`docs/pending/p091_idle_watcher_catchup_backoff_semantics.md:8-11` 与当前 AC-008）
- 问题：p090 正文 `- 处理：... reason=已在 t088 修复失败分类结构信号与 idle catch-up 退避状态，4 条 PG 用例转绿` 与紧随其后的 `:18` 更正（实际只修 2 条失败分类用例，idle watcher 2 条撤回转 p091）、p091:8-11（2 条仍为真实红）及当前 AC-008「除 p091 的 2 条外」直接矛盾。front matter 的 reason 准确（2 条已修、2 条转 p091），但正文残留声明夸大了修复范围；`progress.md` 亦残留「用户确认 AC-008 按此收敛」，与本轮不要求确认声明的处置口径不一致。
- 建议：删除或改写 p090:17 中「idle catch-up 退避状态、4 条 PG 用例转绿」，与 front matter、p091、AC-008 对齐；同步清理 progress.md 的过期确认表述。

## 结论

- 前轮 finding 复核：
    - t088_code_f001（provider 构造异常逃出 / lease 泄漏）：**已消除**。`label_backfill.py:99` 的 `try` 已覆盖 `:100-102` 的 `provider_factory`；异常由 `:132-134` 转 `failed` 并由 `:135-146` 的 `finally` 释放 lease（`release_lease` 再失败也 `rollback`）；`__main__.py:178-185` 逐账号循环虽无 try/except，但 `backfill_account` 现捕获所有 `Exception`，单账号不会中断整条命令。AC-007 的失败隔离在控制流层成立。注意：这次「优雅失败」同时掩盖了 f003——真实环境下 provider 构造对每个账号都失败。
    - t088_code_f002（AC-008 放宽无确认）：**收敛完成，按本轮口径不再作 blocker**。AC-008 已收敛为「除 p091 记录的 2 条既存 idle watcher 回归外全部通过」；p090 记 2 条已修（diff 佐证：`src/mail_core/sync/context.py:137` 新增 `auth_failed`→AUTH 映射、`tests/mail_core/test_sync_backend_handler_isolation.py` 按 t087 契约重写自由文本断言），p091 记剩余 2 条。p090 正文夸大声明另见 f004（minor）。
- 本轮新发现：2 条（critical × 1，minor × 1）。
- 未进表的提示：文件过大——`src/mail_core/sync/label_backfill.py` 146 行、`src/mail_core/__main__.py` 311 行、`tests/mail_core/test_gmail_label_backfill.py` 210 行、`tests/mail_core/test_label_backfill_cli.py` 76 行，均未达阈值。圈复杂度——`backfill_account` 约 10、`_run_label_backfill` 约 8，未达 minor 阈值 15。未跟踪交付文件 `tests/mail_core/test_label_backfill_cli.py` 已读取并纳入 AC-007 判断，无 reviewer 不可见交付文件。范围外观察——`review_test.md` 为 test reviewer 产物，不纳入 code 审查。
- 总体判断：f001/f002 的控制流与记录收敛已核实，但 f003 使回填主路径在生产环境对所有账号失败，AC-001/002/005 打勾失去实现支撑；存在未解决 critical，PASS 不成立。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。`label_backfill.py:93` commit 使 account 过期、:97-98 脱管，:100 传给 `build_provider` 必抛 DetachedInstanceError 并被 :132 吞成 failed；生产不写完成标记与 view location（f003）。
- AC-002：TICK-VOID，re_verified。完成标记在真实路径永不被写入（f003），「已完成跳过 / --force 重跑」状态机不可达；`:115-121` 的 upsert 去重逻辑本身存在但上层不可达。
- AC-003：TICK-VALID，re_verified。`label_backfill.py:72-73` 非 Gmail、`:77-78` 无 important view 均在 provider 构造前早退且不写完成标记。
- AC-004：TICK-VALID，re_verified。`label_backfill.py:89-96` 取 lease/commit、`:108-114` 逐页 heartbeat、`:135-146` finally 释放；`upsert_messages` 不写 checkpoint。
- AC-005：TICK-VOID，re_verified。`:120` 写 `\Important` view location 位于 provider 构造之后，f003 下永不可达。
- AC-006：TICK-VALID，re_verified。迁移 `20261124_0005` upgrade/downgrade、`src/mail_core/db/baseline.py:48` head 更新、`src/mail_core/mail/storage/models.py:129` `Optional[datetime]`；单 head/drift 门禁存在。
- AC-007：TICK-VALID，re_verified。f001 已修：`label_backfill.py:99-102` try 覆盖 provider 构造、`:132-134` 转 failed、`:135-146` 释放 lease；`__main__.py:178-194` 逐账号继续并对 failed/account_not_found 返回 1。
- AC-008：TICK-VALID，trust_prior。AC-008 文本已收敛；p090 的 2 条已修有 diff 佐证（`context.py:137`、测试重写），p091 记剩余 2 条；本机无 PG 服务，完整 PG 全绿结论无法独立复现，依赖实施侧门禁日志。p090 正文夸大声明见 f004。
- AC-009：TICK-VALID，re_verified。`docs/blueprint/testing.md:84`、`docs/guides/upgrade.md:26-33` 记录回填命令与幂等语义；p089 为 closed 且 fix_ref=t088（基线已闭合）。

coverage = 8/9

verdict: FAIL

## Round 3 (2026-11-23T22:08:17+08:00)

reviewed_scope: e8e666e55663153a

## Findings

本轮零 finding。前轮 f003（critical）与 f004（minor）均已消除，修复过程未引入新问题。

## 结论

- 前轮 finding 复核：
    - t088_code_f003（provider 构造使用脱管/过期 account）：**已消除**。`src/mail_core/sync/label_backfill.py:89-98` 把 `provider_factory(account, store or get_credential_store(), traffic_class=traffic_class)` 移入 `try` 且置于 `session.commit()`（:98）之前，`account` 由 :69 `session.get` 加载后仍处于 attached、未过期状态；`src/mail_core/providers/factory.py:127-137,151-152,166,174-175,198-199,217` 读取 `account.provider/.config/.id/.email/.credential_ref` 均在此窗口内完成。签名匹配（account、store 位置参数，traffic_class 关键字参数）。`session.commit()` 在构造之后执行，provider 已持有所需字段，不再出现 `DetachedInstanceError`；`label_backfill.py:102-104` 将构造异常转 `failed` 并 rollback，`:99-101` 的 LeaseBusy 分支同样 rollback，`acquire_lease` 仅 flush 不提交（`src/mail_core/sync/leases.py:61-71,89`），rollback 会回退 lease 写入，无新泄漏。生产路径不再对每个账号返回 failed，AC-001/002/005 打勾恢复实现支撑。
    - t088_code_f004（p090 正文夸大声明）：**已消除**。`docs/pending/p090_sync_failure_classification_and_idle_catchup_regression.md:19-20` 处理文本改为「修复 2 条失败分类回归；其余 2 条 idle watcher 回归转 p091」，并附更正说明；front matter `reason`（:6）同步为同一口径，原「4 条 PG 用例转绿」「idle catch-up 退避状态已修」声明已删除。`docs/pending/p091_idle_watcher_catchup_backoff_semantics.md:1-15` 已登记（status: todo、处理未开）并记 2 条真实红及撤回原因，与当前 AC-008「除 p091 的 2 条外」一致。progress.md 残留「用户确认 AC-008 按此收敛」属 process 文件措辞，不在 code 审查范围，非阻断。
    - t088_code_f001/f002（Round 1，Round 2 已确认收敛）：本轮未回退。`label_backfill.py:89-104` try 覆盖 provider 构造、异常转 failed 并 rollback、`:140-151` finally 释放 lease；AC-008 文本相对基准的收敛保持。
- 本轮新发现：0 条。
- 未进表的提示：文件过大——`src/mail_core/sync/label_backfill.py` 151 行、`src/mail_core/__main__.py` 311 行、`src/mail_core/providers/factory.py` 232 行、`tests/mail_core/test_gmail_label_backfill.py` 210 行、`tests/mail_core/test_label_backfill_cli.py` 76 行，均未达实现源码 400 行阈值。圈复杂度——`backfill_account` 约 10、`_run_label_backfill` 约 8，未达 minor 阈值 15。范围外观察——`review_test.md` 为 test reviewer 产物，不纳入 code 审查。
- 总体判断：f003 的生产失败根因与 f004 的记录矛盾均已按 diff 修复，前轮两条 blocking（f003 critical、f004 对应记录缺口）消除；AC-001~009 在 code 视角均有实现与验证支撑，无未解决 critical/important，PASS 成立。AC-008 的完整 PG 全绿依赖实施侧门禁日志（本机无 PG），按 trust_prior 披露。
- 系统性 follow-up：无（剩余 2 条 idle watcher 回归由 p091 跟踪，AC-008 已排除）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`label_backfill.py:69` 在 session 内加载 account，:89-98 在 account attached 状态构造 provider 后 commit（f003 已修），:111-127 逐页重放 metadata 并以 `label_view_folders` 写 `\Important` view location，:132-135 写 `label_backfill_completed_at`；生产路径不再对真实账号返回 failed。
- AC-002：TICK-VALID，re_verified。`src/mail_core/sync/metadata.py:55-66` 同页 remote_id 去重、:70-104 按 remote_id 与 `(message_id, folder_id)` 查重；`label_backfill.py:74-75` 默认跳过已完成、force 重走；测试二次运行 `skipped_completed`、force 后 messages=1/locations=2。
- AC-003：TICK-VALID，re_verified。`label_backfill.py:72-73` 非 Gmail、:77-78 无 important view 均在 provider 构造与 lease 之前早退且不写完成标记；对应两个用例断言 status 与 `label_backfill_completed_at is None`。
- AC-004：TICK-VALID，re_verified。`label_backfill.py:90-92` 取 lease、:98 commit、:113-119 逐页 heartbeat、:140-151 finally 释放；`upsert_messages` 不写 checkpoint；测试断言 cursor 与 `full_scan_complete` 不变；常规同步 `src/mail_core/sync/engine.py` 走同一 `acquire_lease` 故互斥。
- AC-005：TICK-VALID，re_verified。`label_backfill.py:120-126` 仅对 `label_view_folders={"\\Important": view_id}` 写 view location，:79-87 的 `kind=CONTAINER` 过滤排除视图目录；测试断言 important stats/list 含历史成员、`all` stats 与回填前一致。
- AC-006：TICK-VALID，re_verified。迁移 `20261124_0005` upgrade add_column / downgrade drop_column、`src/mail_core/db/baseline.py:48` head 更新、`src/mail_core/mail/storage/models.py:129` `Optional[datetime]`；单 head 与零 drift 门禁存在。
- AC-007：TICK-VALID，re_verified。`src/mail_core/__main__.py:178-185` 逐账号处理、failed/account_not_found/lease_busy 计入 failures 且不中断循环，:159-163 对非法 UUID 走 `parser.error`，:186-193 对不存在账号返回明确失败；`label_backfill.py:102-104` provider 构造失败转 failed 且 rollback、不写完成标记、可重跑续跑。
- AC-008：TICK-VALID，trust_prior。AC-008 文本已收敛且与 p090/p091 一致；2 条失败分类修复有 diff 佐证（`src/mail_core/sync/context.py:137` 新增 `auth_failed`→AUTH 映射、`tests/mail_core/test_sync_backend_handler_isolation.py` 按 t087 契约重写），剩余 2 条 idle watcher 真实红转 p091 并由 AC-008 排除；本机无 PG，完整套件全绿依赖实施侧门禁日志，无法独立复现。
- AC-009：TICK-VALID，re_verified。`docs/blueprint/testing.md:84`、`docs/guides/upgrade.md:26-33` 记录回填命令、幂等、`--force`、`--account-id` 与失败续跑语义；p089 为 closed 且 fix_ref=t088。

coverage = 8/9

verdict: PASS
