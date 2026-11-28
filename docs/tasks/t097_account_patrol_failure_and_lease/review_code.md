# Task review t097（reviewer_focus: 代码）

- task：`t097_account_patrol_failure_and_lease`
- spec：`docs/tasks/t097_account_patrol_failure_and_lease/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27`（含未跟踪新文件 `src/mail_core/db/alembic/versions/20261129_0009_account_patrol_state.py`、`tests/mail_core/test_t097_patrol_account_state.py`、`docs/pending/p108_t097_pg_gate_verification.md`）
- round：2
- reviewed_at：2026-11-29T00:35:08+08:00（Round 1）；2026-11-29T00:44:10+08:00（Round 2）

## Findings

### t097_code_f001 - `_set_cooldown` 带令牌结算失败后无条件跌落无令牌 upsert，过期持有者的晚到失败可覆盖/复活新持有者已结算的冷却状态

- 严重度：important
- 锚点：AC-003（「过期持有者的晚到结果无法清除或覆盖新租约」）与 task.md 设计裁决「结算按 lease_token fencing」
- 位置：`src/mail_core/sync/patrol.py:137-192`（跌落点 `:169-192`，注释 `:170-172`）
- 问题：`_set_cooldown(session, account_id, now, lease_token=T)` 先执行 `WHERE lease_token == T` 的 fenced UPDATE；未命中时不区分未命中原因，直接跌落到无令牌 upsert，其冲突更新的 `where` 仅为 `lease_token IS NULL OR lease_expires_at <= now`。该条件挡得住「新持有者 B 尚在租约期内」（`lease_token == B_token` 且未过期），但挡不住 B 已结算完毕的两种状态：
    1. B 以失败结算：`_settle_account_failure` 经同一函数把行写成 `cooldown_until = B_now + 300s, lease_token = None, lease_expires_at = None`。此后过期持有者 A 的晚到失败结算 fenced UPDATE 未命中（令牌已不等于 A），跌落 upsert 因 `lease_token IS NULL` 成立而覆盖该行，把 `cooldown_until` 改写为按 A 的旧时钟计算的 `A_now + 300s`。在 t097 测试采用的交错时序下（`B_now = A_now + 310s`），改写后的冷却 `A_now + 300s` 甚至早于 B 结算时刻——B 刚建立的冷却被实质清除，账号可被立即重探。
    2. B 以成功结算：`_clear_cooldown` 已按 B 的令牌 DELETE 整行。此后 A 的晚到失败结算 fenced UPDATE 未命中（行不存在），跌落 upsert 直接 INSERT 一行新冷却——当前持有者成功后本应为空的状态被过期持有者复活。
        代码注释把跌落理由写为「行已消失（如本持有者在同轮先以成功清除了它）」，但 fenced UPDATE 未命中无法区分「行被自己同轮的成功清除」「行被新持有者清除/改写」「行被新持有者的失败结算消费（令牌置 None）」三种情形，后两种正是 AC-003 要求 fencing 挡住的晚到结算。对比之下，晚到成功路径 `_clear_cooldown`（`patrol.py:195-215`）是严格 DELETE + 令牌等值条件、无跌落，因而安全；失败路径与之不对称，构成真实的 fencing 漏洞。触发条件为：租约在探测期间到期、新巡检认领并先行结算、旧持有者随后以失败结算——正是 AC-003 与测试 `test_ac003_expired_holder_late_settlement_cannot_touch_new_lease` 设定的交错场景，只是该测试只演练了晚到成功一侧（见 review_test 的 t097_test_f001），故未暴露。
- 建议：带令牌结算未命中时不得无条件跌落。需区分未命中原因：例如在同一短事务内复查该行现状——行存在且令牌不等于本令牌（含已被新结算置 None 且 `cooldown_until` 仍在未来）时直接放弃本次结算；行不存在时仅当本轮巡检自身先前以该令牌成功清除过（巡检本地可记录）才允许插入新冷却。无令牌调用（账号此前无冷却、非半开路径的首次失败）维持现有 upsert 语义不变。

### t097_code_f002 - 迁移 downgrade 把已过期冷却也写回旧键，与 task.md 回退口径「可用冷却时间」表述不完全一致（无行为危害）

- 严重度：minor
- 锚点：AC-004 / task.md「风险与回退」（回退可将可用冷却时间恢复到旧键）
- 位置：`src/mail_core/db/alembic/versions/20261129_0009_account_patrol_state.py:96-114`
- 问题：downgrade 对 `cooldown_until IS NOT NULL` 的全部行写回旧键，包括早已过期的冷却。旧读取语义对过期值视为不生效，写回不产生行为差异，其余 config 键与业务数据均完整保留，故仅为口径瑕疵而非缺陷；upgrade 侧把可解析的过期值也搬入新表（测试 `past` 夹具断言如此）对半开认领语义是必要的（过期时刻本身是认领 CAS 的比较基准），不建议改动。
- 建议：可不改代码；若后续修订迁移，在 downgrade 处加一行注释说明过期值写回无害即可。

## 结论

- 本轮新发现：2 条（0 critical，1 important，1 minor）。
- 未进表的提示：
    - `src/mail_core/sync/patrol.py` 现约 620 行且 `schedule_folder_status_patrol` 圈复杂度较高（选择/认领/构建/探测/结算多阶段集中于单函数），本次重写未使其恶化到不可维护程度，后续可考虑按阶段拆分；不构成本轮 finding。
    - 常规视角巡检结论（除 f001 外均未发现问题）：构建缓存 `providers` 仅缓存成功、失败即 `short_circuited` 且只结算一次（`patrol.py` 构建段无任何 `_record_attempt` 调用，AC-001 的零目录写入在代码路径上成立）；探测结算 `_persist_probe_failure` 仅对 AUTH/TRANSPORT 调 `_settle_account_failure` 并短路，UNKNOWN/CONTROL 只写本目录 `_record_attempt`；`_claim_half_open` 的 CAS 条件含 `cooldown_until == expected`、`cooldown_until <= now` 与令牌等值/为空匹配，认领同时把 `cooldown_until` 推到租约到期时刻，使租约期内其他巡检按冷却跳过；AUTH 结算调 `mark_credential_invalid`、TRANSPORT 结算不触 `connectivity_state`；`_end_tx_if_owned`/`_run_short_tx` 在调用方已有事务时不提交调用方事务（t095 兼容语义保留），巡检自有事务在构建/探测前已由 `_end_tx_if_owned()` 结束、认领走独立短事务；迁移 upgrade 按旧读取语义解析（`fromisoformat`、naive 视为 UTC、不可解析跳过）、jsonb `-` 删键保留其余键值，与 ORM 模型（`AccountPatrolState`，FK CASCADE、PK=account_id）及 `baseline.CURRENT_HEAD_REVISION = "20261129_0009"` 一致；文档 spec/blueprint 三处与实现表述一致。
    - 复跑限制：本轮复审环境中实施者所述便携 PostgreSQL 16.6.0 集群（127.0.0.1:54399）已不存在（/tmp 已清、无 docker、无系统 postgres 二进制），无法按等效方法独立复跑 PG 测试；本轮改以逐行代码审查 + 可运行的单元测试复跑（`test_t095_contract_unit.py` + `test_t096_fixes_unit.py` 共 11 passed）+ 对 f001 的确定性代码路径推演完成核查。PG 层面的正式复验仍归 p108 门禁，这与实施者登记一致，不因此单独报 finding；但 f001 是纯代码逻辑漏洞，不依赖 PG 复跑即可成立。
- 总体判断：AC-001、AC-002、AC-004、AC-005 的实现真实落地；AC-003 的晚到成功 fencing 成立，但晚到失败 fencing 存在 f001 的覆盖/复活漏洞，AC-003 不完全成立。存在未解决 important finding，按 verdict 规则判定 FAIL。
- 系统性 follow-up：无（f001 在本 task 内修复即可）。

### AC 复验方式

- AC-001：实现成立，待 p108 正式门禁后打勾（trust_prior + 代码核查）。逐行核对 `patrol.py` 主循环：同账号 Provider 只经 `providers` 缓存构建一次；构建异常分支只调一次 `_run_short_tx(_settle_build_failure)`、置 `short_circuited` 并 `result.failed += 1`，该分支及短路 `continue` 路径均无 `_record_attempt`、无 `probe_folder_status` 调用，其他账号目标不受影响。测试 `test_ac001_build_failure_settles_once_per_account_with_zero_folder_writes` 与 `test_ac001_build_auth_failure_invalidates_credential_once` 的断言（构建计数==1、新鲜 session 查 `FolderPatrolStatus == []`、冷却值≈now+300s、AUTH 时凭据失效）与代码路径一一对应；实施者等效 PG 实跑 9/9 通过的证据与 p108 登记可信，本轮环境无 PG 未能独立复跑。
- AC-002：实现成立，待 p108 正式门禁后打勾（trust_prior + 代码核查）。核对 `_persist_probe_failure`：先按本目录无条件 `_record_attempt(failed=True)`，仅当 `classify_failure(exc).domain in (TRANSPORT, AUTH)` 时才 `_settle_account_failure` 并置短路标记，后续同账号目标在循环顶部 `continue`，其既有 `FolderPatrolStatus` 行不被任何语句触及、缺失行不被创建；`status is None` 与 UNKNOWN/CONTROL 只写本目录。测试 `test_ac002_*` 两例以预置行（`last_probe_at=t0, failures=3`）与缺失行混合预置、在新鲜 session 精确比对兄弟行原值，断言强度足够。
- AC-003：不完全成立（TICK-VOID 方向）。冷却内跳过（选择阶段按 `account_patrol_state.cooldown_until > now` 计 `skipped_not_due`、零构建零探测）、单持有者（`_claim_half_open` CAS + 认领后 `cooldown_until` 推至租约到期）、当前持有者成功清除（`_clear_cooldown` 令牌 DELETE）、晚到成功不清除新租约——四点代码与测试均成立。但晚到失败结算经 f001 的无令牌跌落 upsert 可覆盖新持有者已结算的冷却、或复活已被成功清除的状态，违反「晚到结果无法清除或覆盖新租约」。修复 f001 并补测晚到失败变体后方可判定成立。
- AC-004：实现成立，待 p108 正式门禁后打勾（trust_prior + 代码核查）。逐行核对迁移 `20261129_0009`：upgrade 建表后按 `_parse_legacy_until`（与旧读取语义一致：`fromisoformat`、naive 补 UTC、不可解析/空值跳过）搬入可解析值（含过期值，半开 CAS 需要），随后 `config - 'patrol_cooldown_until'` 删除全部账号旧键、其余键值由 jsonb 语义完整保留；downgrade 以 ISO 文本 `jsonb_set` 写回并删表（f002 仅口径 minor）。测试 `test_ac004_...` 以独立临时库在 0008 上预置 future/past/naive/bad/plain 五类夹具，升级后逐项断言新表值、旧键消失、其余键值精确相等，降级后断言恢复与表删除，覆盖完整。
- AC-005：实现成立，待 p108 正式门禁后打勾（trust_prior + 代码核查）。核对事务边界在生产入口 `schedule_folder_status_patrol` 内：选择查询后 `_end_tx_if_owned()` 先结束只读事务；认领经 `_run_short_tx(_claims)` 独立提交；构建与每次 STATUS 均在任何巡检事务之外执行；每次结算/记账各自走 `_run_short_tx`。调用方已有事务时三个辅助函数均不提交/不回滚调用方事务，t095 兼容用例的存储断言已迁至新表且行为断言保留。测试 `test_ac005_...` 在工厂内断言 `patrol.in_transaction() is False`、独立 session 可见已提交租约、其他连接 `idle in transaction` 计数为 0、巡检中途的 config 编辑提交后存活，断言测在生产入口且强度足够。

coverage = 4 / 5

verdict: FAIL

______________________________________________________________________

# Round 2（2026-11-29T00:44:10+08:00）

独立复核第 1 轮 findings 的修复与三条 minor 撤回，并独立复跑 PG 测试（便携 PostgreSQL 16.6.0 集群 127.0.0.1:54399 本轮仍在运行，scratch 目录 `/tmp/verify_t097` 的测试文件与 worktree 逐字节一致、`src` 为指向 worktree 的软链）：t097 全文件 12 passed；新增三例（两条晚到失败 + 同轮自清后重建）单独复跑 3 passed。

## 第 1 轮 finding 复核

### t097_code_f001（important）— 已修复成立

逐点核对修复实现（`src/mail_core/sync/patrol.py`）：

1. 透传完整：`_set_cooldown` 新增 `self_cleared: bool = False` 参数（`:137-145`）；带令牌 fenced UPDATE 未命中时，`not self_cleared` 一律 `return False` 放弃写入（`:176-181`），仅 `self_cleared` 时走 `pg_insert(...).on_conflict_do_nothing(...).returning(...)` 插入重建（`:182-195`）。两个结算调用点均经 `_settle_account_failure(..., self_cleared=...)` 透传：探测失败路径 `_persist_probe_failure`（`self_cleared=target.account_id in self_cleared`）与构建失败路径 `_settle_build_failure`（`self_cleared=account_id in self_cleared`）；代码中 `_settle_account_failure` 只有这两个调用者、`_set_cooldown` 只有 `_settle_account_failure` 一个调用者，无遗漏调用点。
2. 集合记录时机正确：`self_cleared` 集合在 `schedule_folder_status_patrol` 内按轮次新建；`_persist_success` 仅在 `_clear_cooldown(...)` 返回 True（带本轮令牌的 DELETE 实际命中并返回行）时才 `self_cleared.add(...)`，记录的是「本轮自身以该令牌实际删除过该行」这一事实，与处置表述一致。一个边角：记录发生在 `_run_short_tx` 提交之前，若同一短事务后续步骤异常回滚，DELETE 被撤销而集合已记录——但此时行仍带本轮令牌，后续失败结算的 fenced UPDATE 会直接命中，插入路径不会被触发，故该假阳性无害。
3. self_cleared 插入竞态被正确吞掉：插入瞬间若新一代已重建行（无论其令牌为何），`ON CONFLICT DO NOTHING` 使语句不写任何行、`.returning` 返回 None、函数返回 False，不覆盖新行。
4. 同轮先成功清除、后失败重建的语义与 AC-003 及 t095 既有语义一致：同一持有者、同一租约世代内的失败本就应建立冷却（fencing 只应拒绝异世代的晚到结算）；新增防过度修正测试实跑通过（见 review_test Round 2）。
5. 其他晚到写入路径复核：
    - 构建失败结算与探测失败结算共用同一 fenced `_settle_account_failure`，无第二条无令牌跌落路径；全局检索确认巡检状态写入只经 `_claim_half_open`（CAS）、`_set_cooldown`、`_clear_cooldown` 三处。
    - 无令牌 upsert 路径（`lease_token=None`）：其调用者是「选择阶段该账号无巡检状态行/未走半开认领」的当轮巡检，调用者本身不是过期持有者，不在 AC-003 fencing 的对象范围内；其冲突更新条件（`lease_token IS NULL OR lease_expires_at <= now`）仍拒绝覆盖存活的他人租约。并发下两轮无租约巡检先后失败结算只会以各自 `now+300s` 刷新同一冷却，无世代覆盖问题。此路径不构成 fencing 绕过。
    - 晚到成功/失败对 `folder_patrol_status` 的 `_record_attempt` 写入不按令牌 fencing：这是被实际探测目录自身的探测记账（AC-002 的作用域），第 1 轮已认定该语义成立，本轮维持。
    - AUTH 域的凭据失效副作用不受 fencing 结果约束，另列本轮新发现 t097_code_f003（minor）。

修复后原 f001 的两种攻击时序（覆盖 B 已失败结算的冷却、复活 B 已成功清除的行）均被新测试实跑封堵（修复前见红、修复后转绿的实施者记录与本轮复跑 12 passed 一致）。

### t097_code_f002（minor）— 撤回成立

第 1 轮原文即定性为「无行为危害」「可不改代码」：downgrade 写回已过期冷却与旧读取语义一致地不生效，其余 config 键与业务数据完整保留。实施侧按 reviewer 明示意见撤回，理由与第 1 轮定性一致，撤回成立，不再计为未解决 finding。

## Round 2 新发现

### t097_code_f003 - AUTH 结算的凭据失效副作用不看 fencing 结果，过期持有者的晚到 AUTH 失败仍可使凭据失效并停用同步

- 严重度：minor
- 锚点：AC-003 fencing 的外延（租约/冷却本身已封堵，本条只涉凭据副作用）
- 位置：`src/mail_core/sync/patrol.py:240-265`（`_settle_account_failure`：先无条件 `mark_credential_invalid`，后调用 `_set_cooldown` 且不读其返回值）
- 问题：`_set_cooldown` 返回 False 表示本次结算已被 fencing 拒绝（异世代晚到），但 AUTH 域的 `mark_credential_invalid` 已在同一短事务内先行执行并随事务提交：过期持有者 A 的晚到 PermanentAuthError 在新持有者 B 已成功清除状态之后到达时，冷却行不会被复活（f001 已封堵），但账号仍会被置 `credential_state=INVALID`、`sync_enabled=False`。这是否算缺陷取决于语义裁决：一种读法是「永久认证失败是与租约世代无关的凭据证据（t090『任何来源』），失效是 fail-safe」；另一种读法是「B 已用同一凭据探测成功，A 的晚到认证失败不应推翻当前世代的成功结论」。AC-003 原文只约束「无法清除或覆盖新租约」，凭据状态不在其字面范围内；AC-001/AC-002 只规定实际构建/探测的永久认证失败使凭据失效，未区分租约世代。故本条不定性为 AC 违反，仅记录为未裁决的语义边角：现有晚到交错测试全部使用 TRANSPORT 故障，AUTH 晚到变体无覆盖。
- 建议：不阻断本轮。若后续裁决采用「晚到结算整体不生效」语义，应把 `mark_credential_invalid` 改为仅在 `_set_cooldown` 返回 True（或无令牌路径结算成功）时执行，并补 AUTH 晚到交错用例；若裁决维持 fail-safe，则在 `_settle_account_failure` docstring 写明该意图即可。

## Round 2 结论

- 第 1 轮 finding 复核：t097_code_f001 已修复成立；t097_code_f002 撤回成立。
- 本轮新发现：1 条（0 critical，0 important，1 minor：t097_code_f003）。
- 总体判断：AC-003 的晚到失败 fencing 漏洞已真实修复且有先红后绿的交错测试封堵；其余 AC 的实现判断维持第 1 轮结论（成立）。无未解决 critical/important，按 verdict 规则判定 PASS。task.md 的 AC 仍全部未打勾是因正式 Docker 门禁未跑（pending p108），按任务约定不以此报 finding；下列 TICK 判断为「实现与等效 PG 证据足以支撑成立、待 p108 正式门禁后打勾」。

### AC 复验方式（Round 2）

- AC-001：成立（TICK-VALID 方向，待 p108 打勾）。维持第 1 轮代码核查结论；本轮独立复跑 t097 全文件 12 passed，其中 AC-001 两例通过。
- AC-002：成立（TICK-VALID 方向，待 p108 打勾）。维持第 1 轮结论；本轮复跑 AC-002 两例通过。
- AC-003：成立（TICK-VALID 方向，待 p108 打勾）。第 1 轮不成立的唯一原因（晚到失败经无令牌跌落 upsert 覆盖/复活）已修复：fenced UPDATE 未命中且非 self_cleared 时放弃写入、self_cleared 时 DO NOTHING 插入；两条晚到失败交错用例与一条同轮自清后重建用例本轮复跑通过，原晚到成功用例与当前持有者成功清除用例亦通过。凭据副作用的世代语义见 minor f003，不在本 AC 字面范围内。
- AC-004：成立（TICK-VALID 方向，待 p108 打勾）。维持第 1 轮结论；本轮复跑迁移用例通过（临时库 upgrade/downgrade 往返）。
- AC-005：成立（TICK-VALID 方向，待 p108 打勾）。维持第 1 轮结论；本轮复跑 AC-005 用例通过，修复未触碰事务边界代码路径。

coverage = 5 / 5

verdict: PASS

______________________________________________________________________

# Round 3（2026-11-29T00:52:17+08:00）

聚焦复审：仅核第 2 轮复审落盘后新增的两处登记修复（`REQUIRED_TABLES` 新增 `account_patrol_state` + 窄转换豁免；`AccountPatrolState` 加入 storage 包导出），其余内容维持第 1/2 轮定稿结论，不重开。本轮独立复跑 `KKMAIL_TEST_MODE=unit python -m pytest tests/mail_core/test_baseline_unit.py tests/mail_core/test_storage_exports.py`：21 passed（与实施者所述一致）；另以脚本直接比对 `REQUIRED_TABLES` 与 ORM metadata、`storage.__all__` 与 models 类集合（见下）。

## 逐条复核

### 改动 1：`src/mail_core/db/baseline.py` — `REQUIRED_TABLES` 新增 + 窄转换豁免 — 成立

1. 登记完整且与真源一致：`REQUIRED_TABLES` 现 33 项，与 `_baseline_metadata().tables` 33 项集合相等（本轮脚本实测 `REQUIRED_TABLES == frozenset(_baseline_metadata().tables)` 为 True），`test_required_tables_match_orm_metadata` 通过。插入位置在 `account_sync_activity` 之后、`folders` 之前，与 account\_\* 表成组；`REQUIRED_TABLES` 为 frozenset、无序，位置无功能影响。
2. 豁免不会放过真正应拦截的缺失——拦截链完整，逐路核对：
    - `verify_narrow_legacy_schema` 只在 LEGACY 计划下被调用（`verify_for_plan` 的分发，以及 `apply_narrow_legacy_conversion` 事务内复验），其对象是窄转换夹具/存量库，即 0001 基线形状：该形状本就不含 `folder_patrol_status`（转换创建）与 `account_patrol_state`（0009 才创建）。若不豁免后者，一切合法窄存量库都会被误报缺表、转换永不可达；豁免与既有 `folder_patrol_status` 豁免同构且必要。
    - 已升到 head 的库不经此函数判定：AT_BASELINE 计划走 `verify_baseline_schema`（全量 `compare_metadata` 对 ORM，无任何表级豁免，缺 `account_patrol_state` 必然报 `Missing required table`）；LEGACY 与 UPGRADE_TO_HEAD 两路在转换/升级后都汇入 `upgrade_head_and_verify`——先 `command.upgrade(head)`（0009 在链上创建该表），再跑同一全量比对，升 head 后仍缺该表即抛 `SchemaValidationError`。故豁免只作用于「尚未升 head、本就不该有该表」的时点，head 形状的缺失由上述两处全量比对拦截，无放行窗口。
    - 测试侧另有冗余断言：`tests/mail_core/test_migration_validation.py` 两处 `REQUIRED_TABLES <= table_names_after`（:137）与 `REQUIRED_TABLES <= tables_at_head`（:171），升 head 后的表集合必须覆盖含新表的 `REQUIRED_TABLES`，与上述代码拦截互相印证（该文件为 PG 门禁套件，本轮未复跑，归 p108）。
3. docstring 表述准确：`verify_narrow_legacy_schema` docstring 同步改写为「除 `folder_patrol_status` 与 `account_patrol_state` 外其余基线表须已存在（转换只创建前者，后者由后续 Alembic 迁移 `20261129_0009` 在升 head 时创建，故其余缺失无法靠转换修复）」。与迁移文件实物一致：`20261129_0009_account_patrol_state.py` 的 `revision = "20261129_0009"`、`down_revision = "20261128_0008"`，upgrade 内 `op.create_table("account_patrol_state", ...)`；与函数内注释口径（转换产物为 0001 形状、全量比对在升 head 后）亦一致。
4. `REQUIRED_TABLES` 其他消费点不受损：baseline.py 内另一消费点仅 `plan_migration` 的 `business_tables = state.table_names & REQUIRED_TABLES`（:1025）。新增一项使无版本库的业务表识别更严：仅含 `account_patrol_state` 的无版本库将由 EMPTY_DATABASE 改判 NO_VERSION_WITH_BUSINESS_TABLES（拒绝盲盖章）——这是与「REQUIRED == ORM 表集」语义一致的收紧，不是回归。`verify_baseline_schema` 不消费 `REQUIRED_TABLES`（直接用 ORM metadata），`CORE_CRITICAL_TABLES` 与本改动无关、未被触碰。

### 改动 2：`src/mail_core/mail/storage/__init__.py` — `AccountPatrolState` 导出登记 — 成立

1. 位置/排序与包内惯例一致：import 列表与 `__all__` 均插入 `AccountGroup` 之后、`AccountSyncActivity` 之前，符合该文件通行的字母序（Account < AccountGroup < AccountPatrolState < AccountSyncActivity < AccountSyncLease）；本轮以 AST 脚本核对，两列表 33 项顺序逐项 identical。
2. 与 models 真源无差：本轮脚本实测 `set(storage.__all__)` 与 models 模块内定义的类集合相等（33 == 33、无差集），且 `test_storage_package_exports_every_orm_model` 断言的 `getattr(storage, name) is getattr(models, name)` 恒等关系随 21 passed 一并通过。
3. 无遗漏的第三处登记点：全局检索手工维护的模型/表清单——storage 包内仅 `__init__.py` 一处 `__all__`；Alembic env（`src/mail_core/db/alembic/env.py`）与 baseline 的 `_baseline_metadata` 均以整包 `import mail_core.mail.storage` 消费，无逐模型清单；`patrol.py` 等业务代码直接自 `models` 导入，不经包清单。`src/mail_core/backup/package.py` 的 `_RESTORE_REQUIRED_TABLES` 是恢复校验专用的 6 表最小子集（accounts/messages 等核心表），与 ORM 模型登记无关，不构成第三处登记点。

## Round 3 新发现

### t097_code_f004 - PG 门禁套件中仍有一份硬编码 32 表清单未随新表更新（测试侧，不影响生产拦截）

- 严重度：minor
- 位置：`tests/scripts/test_migrate_to_unified_baseline.py:67-102,276-282`（`EXPECTED_CORE_TABLES` 仍为 32 表、`test_required_tables_matches_expected_core_32_tables` 断言 `len == 32` 且与 `REQUIRED_TABLES` 相等）；附带 `src/mail_core/db/baseline.py` 的 `verify_baseline_schema` docstring（:415）与 `tests/mail_core/test_baseline_unit.py:174` docstring 仍写「32 tables」（仅文字、无断言）。
- 问题：本轮改动后 `REQUIRED_TABLES` 为 33 表，上述硬编码清单成为唯一未同步的表登记副本。该测试模块以 `MAIL_CORE_DATABASE_URL` 未设置即整模块 skip，unit 套件不受影响（与实施者全量 unit 3 failed 的 A/B 结论不冲突）；但在 p108 的 PG 门禁环境下该断言必然失败（33 != 32），会以一条与实现无关的假失败污染门禁结论。
- 建议：不阻断本轮（生产代码拦截链已由改动 1 第 2 点核实完整）。p108 门禁执行前将 `EXPECTED_CORE_TABLES` 补入 `account_patrol_state` 并改 32→33，顺手修正两处 docstring 的表数。

## Round 3 结论

- 两处聚焦改动逐条复核均成立：豁免的拦截链完整（head 缺表由 `verify_baseline_schema` / `upgrade_head_and_verify` 全量比对与 `test_migration_validation` 的超集断言拦截）、docstring 与迁移实物一致、`business_tables` 消费点仅有符合语义的收紧；storage 导出位置/排序/完整性正确且无第三处登记点遗漏。
- 本轮新发现：1 条（0 critical，0 important，1 minor：t097_code_f004，测试侧硬编码清单待在 p108 前同步）。
- 独立复跑：`tests/mail_core/test_baseline_unit.py` + `tests/mail_core/test_storage_exports.py` 共 21 passed（unit 模式，无需 PG），与实施者所述一致；全量 unit 的 3 条既有失败（blob_permissions root 环境、system_health、t093 public surface）不在本轮聚焦范围，维持实施者 A/B 对照结论不重开。
- 总体判断：无未解决 critical/important，按 verdict 规则判定 PASS。

coverage = 2 / 2（本轮聚焦项）

verdict: PASS

### AC 复验方式

本轮聚焦改动（REQUIRED_TABLES / 导出登记补全、f004 测试清单同步）不触及五条 AC 的行为面，AC 判定维持 Round 2 复验结论（trust_prior）：

- AC-001：TICK-VALID，trust_prior。Round 2 复验：独立复跑 t097 全文件 12 passed，AC-001 两例通过。正式 Docker 门禁补跑归 p108。
- AC-002：TICK-VALID，trust_prior。Round 2 复验：AC-002 两例通过。
- AC-003：TICK-VALID，trust_prior。Round 2 复验：晚到失败 fencing 修复成立，两条晚到失败交错用例与同轮自清后重建用例复跑通过。凭据副作用世代语义为 minor f003（遗留 p111），不在本 AC 字面范围内。
- AC-004：TICK-VALID，trust_prior。Round 2 复验：迁移用例通过（临时库 upgrade/downgrade 往返）。
- AC-005：TICK-VALID，trust_prior。Round 2 复验：AC-005 用例通过，修复未触碰事务边界代码路径。

reviewed_scope: 7a814f512aba3e09
