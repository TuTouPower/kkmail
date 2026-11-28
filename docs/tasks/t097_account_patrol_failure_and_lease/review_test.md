# Task review t097（reviewer_focus: 测试）

- task：`t097_account_patrol_failure_and_lease`
- spec：`docs/tasks/t097_account_patrol_failure_and_lease/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27`（含未跟踪新文件 `tests/mail_core/test_t097_patrol_account_state.py` 等）
- round：2
- reviewed_at：2026-11-29T00:35:08+08:00（Round 1）；2026-11-29T00:44:10+08:00（Round 2）

## Findings

### t097_test_f001 - AC-003 交错结算测试的 docstring 声称覆盖「晚到失败」变体，实际只演练晚到成功，晚到失败路径零覆盖（且实现该路径有缺陷）

- 严重度：important
- 锚点：AC-003 覆盖完整性（「过期持有者的晚到结果无法清除或覆盖新租约」含成功与失败两类晚到结算）
- 位置：`tests/mail_core/test_t097_patrol_account_state.py:404-500`（`test_ac003_expired_holder_late_settlement_cannot_touch_new_lease`，docstring 在 `:405-408`）
- 问题：docstring 明写「and (second variant) A's late failure must not overwrite it either」，但函数体只构造了一种交错：A 的慢探测最终返回成功，断言 B 已结算的 `cooldown_until == expected_cooldown` 不被清除。全文没有任何用例让过期持有者在新持有者结算之后以失败（TRANSPORT/AUTH 探测失败或构建失败）晚到结算。这不是无害的文档夸大：经代码审查（review_code 的 t097_code_f001），`src/mail_core/sync/patrol.py:169-192` 的 `_set_cooldown` 在带令牌 fenced UPDATE 未命中后跌落无令牌 upsert，当 B 已失败结算（`lease_token` 被置 None）时 A 的晚到失败会真实覆盖 B 的冷却、当 B 已成功清除（行被 DELETE）时会真实复活一行冷却——即未覆盖的变体恰是实现不成立的变体，测试的「全绿」对 AC-003 构成假绿保护。
- 建议：补两条交错用例（可复用现有线程 + Event 屏障骨架）：（1）B 认领后失败结算 → A 晚到失败结算 → 断言新 session 中 `cooldown_until` 仍精确等于 B 的结算值；（2）B 认领后成功清除 → A 晚到失败结算 → 断言 `account_patrol_state` 行仍不存在。同时把 docstring 改为与实际变体一一对应。在实现修复（t097_code_f001）前，这两条用例应先红。

### t097_test_f002 - AC-001 的「STATUS 调用为零」只由构造间接保证，未显式计数

- 严重度：minor
- 锚点：AC-001 可观察断言完整性（「STATUS 调用和目录状态写入均为零」）
- 位置：`tests/mail_core/test_t097_patrol_account_state.py:139-205`
- 问题：两条 AC-001 用例断言了构建计数==1、`res.failed == 1` 与新鲜 session 中目标账号 `FolderPatrolStatus == []`，但坏账号一侧不存在 Provider 对象（工厂直接抛错），STATUS 为零是构造上的必然，而非被计数的断言；若未来重构让构建失败后仍对同账号目录逐个构造替身 Provider 并探测，现有断言中只有 `fps_rows == []` 与 `res.probed` 能间接报警（探测成功会计入 probed、探测失败会写行），覆盖实际成立但不直接。属可接受的间接覆盖，仅记录提示。
- 建议：可不改；若顺手修订，在坏账号工厂抛错前记录「若返回 Provider 则其 probe 计数」的哨兵，或在用例注释中写明 STATUS 为零由构造保证。

### t097_test_f003 - AC-003 单持有者的真并发 CAS 竞争在 t097 新文件中只以串行交错验证，竞争覆盖依赖 t095 旧用例

- 严重度：minor
- 锚点：AC-003（「过期后并行巡检只有一个有效持有者」）
- 位置：`tests/mail_core/test_t097_patrol_account_state.py:404-500` 与 `tests/mail_core/test_t095_patrol_and_idle_fixes.py`（`test_patrol_half_open_expired_cooldown_single_holder_across_workers`）
- 问题：t097 新文件的单持有者证据是「A 持租约期间 B 被冷却跳过 → A 租约到期后 B 串行认领」的时序交错，没有两个巡检在同一过期状态上同时发起 `_claim_half_open` 的真竞争。真竞争由 t095 旧用例覆盖（双线程屏障同启、断言仅一个探测者），且该用例的预置已正确迁到新表（以 `AccountPatrolState(cooldown_until=expired)` 预置、结果断言改查新表），故合并覆盖成立；但 t097 的回归入口（testing.md 新增行以 `test_t097` 为首）若单独运行时不含该竞争用例，存在入口级盲区。
- 建议：不阻断本轮；在 testing.md 的 t097 回归命令中已包含 `test_t095_patrol`（实际命令为 `-k "test_t097 or test_t095_patrol or test_t096_migration_and_patrol or test_migration_validation"`），与该行一致执行即可。后续可在 t097 文件内补一条双认领竞争的轻量用例以自包含。

## 结论

- 改测方向复核：旧测试改动全部属于契约强制的存储迁移，未发现迁就实现的行为弱化。逐项核对：`test_t095_patrol_and_idle_fixes.py`、`test_t095_patrol_readiness.py`、`test_t096_migration_and_patrol.py` 中原 `Account.config["patrol_cooldown_until"]` 存在/不存在断言改为「config 无旧键 + `AccountPatrolState` 行存在/不存在/被清除」的等价或更强断言（如 auth 用例新增对兄弟账号 `AccountPatrolState is None` 的断言、UNKNOWN/CONTROL 用例新增 `AccountPatrolState is None` 断言），其余行为断言（凭据失效、connectivity 隔离、config 其余键保留、失败计数、短路计数、调用方事务不被提交等）逐行未动；半开用例的预置由 config 旧键改为新表行，属夹具随存储迁移的必然调整。`test_t095_contract_unit.py` 删除 `test_patrol_cooldown_lifecycle` 整例：该例只测已删除的私有函数 `_cooldown_active`/`_set_cooldown(acc, now)`（旧签名以 Account 为载体，新实现签名已改为以 session+account_id+令牌为载体，无法原样保留），其生命周期语义（置冷却→期内有效→过期失效）在 t097 PG 测试的 AC-001 冷却内不重建、AC-003 冷却内跳过与过期认领中以生产入口 + 真实 PG 等价覆盖，删除理由成立；同文件其余改动仅为随之移除的未用导入。
- 本轮新发现：3 条（0 critical，1 important，2 minor）。
- 未进表的提示：本轮复审环境无可用 PostgreSQL（实施者的便携集群已随 /tmp 清理消失、无 docker），未能独立复跑 t097 PG 测试与红灯对照；已复跑不依赖 PG 的 `test_t095_contract_unit.py` + `test_t096_fixes_unit.py`（11 passed），其余 PG 证据为对实施者记录的 trust_prior：p108 登记内容具体（t097 9/9、t095 patrol 15/15、旧实现同批行为测试 7/8 失败、环境产物失败项新旧同失败的 A/B 说明），与代码/断言逐项对读未发现矛盾。红灯对照口径核查：旧实现跑「同一批行为测试 7/8 失败」中分母 8 与新文件 9 例的差额为迁移用例（旧实现无 0009 迁移、需在旧 head 上单独构造，不计入行为对照），口径自洽。模板契约 A/B（worktree 与主仓同为 30 failed / 359 passed / 1 skipped）未独立复跑，属云端既有失败、与本改动无关的结论与 diff 范围（未触模板文件）一致，采信。
- 总体判断：新测试全部经生产入口 `schedule_folder_status_patrol` + 真实 PG + 新鲜 session 比对持久化结果，断言强度整体足够，无恒真断言、无 skip 掩盖（`_PG_SKIP` 仅在未配置数据库时跳过，与仓库既有 PG 测试惯例一致）；但 AC-003 的晚到失败变体被 docstring 声称覆盖而实际缺失、且该路径实现有缺陷（t097_code_f001），构成 1 条未解决 important 测试 finding，判定 FAIL。
- 系统性 follow-up：无（PG 正式门禁补跑已由 p108 登记，不重复登记）。

### AC 复验方式

- AC-001：覆盖成立（trust_prior）。两例分别以 ValueError（缺凭据引用）与 PermanentAuthError 覆盖构建失败的普通与认证两类，断言构建计数、新鲜 session 目录行为空、冷却落新表、凭据状态分流；STATUS 为零为构造必然（见 f002，minor 不阻断）。
- AC-002：覆盖成立（trust_prior）。TRANSPORT 与 AUTH 两例均以「预置行 + 缺失行」混合夹具、在新鲜 session 精确比对兄弟行 `last_probe_at`/`last_probe_failures` 原值与缺失行仍缺失，并断言 connectivity/credential 分流；UNKNOWN/CONTROL 单目录语义由 t095 旧用例（已迁存储断言）补足。
- AC-003：覆盖不完全（TICK-VOID 方向）。冷却内跳过零探测零写入、租约期内单持有者、当前持有者成功清除、晚到成功不清除新租约四点均有真实交错用例（线程 + Event 屏障、双 session 可见性）；但晚到失败变体缺失且 docstring 虚报（f001），真并发 CAS 竞争靠 t095 旧用例补足（f003）。须补晚到失败两变体并待实现修复后复验。
- AC-004：覆盖成立（trust_prior）。迁移用例自建独立临时库、走真实 Alembic upgrade/downgrade，五类存量夹具（tz-aware 未来/过去、naive、不可解析、无键）逐项断言新表值（含 naive 补 UTC、过期值保留）、旧键全删、其余键值精确相等、降级恢复与删表，是本批中覆盖最完整的一条。
- AC-005：覆盖成立（trust_prior）。用例测在生产入口：工厂回调内断言巡检 session 不在事务中、独立 session 可见已提交租约令牌、`pg_stat_activity` 其他连接 idle-in-transaction 计数为 0、探测回调内同样不在事务中、巡检中途并发 config 编辑提交后完整存活（且原有键保留、旧冷却键不回写）；t095 的调用方已有事务兼容用例保留并已迁存储断言，补足「不提交调用方事务」一侧。

coverage = 4 / 5

verdict: FAIL

______________________________________________________________________

# Round 2（2026-11-29T00:44:10+08:00）

独立复核第 1 轮三条测试 finding 的处置，并独立复跑：便携 PostgreSQL 16.6.0 集群（127.0.0.1:54399）本轮仍在运行，scratch 目录 `/tmp/verify_t097` 的 t097 测试文件与 worktree 逐字节一致（diff 无差异）、`src` 为指向 worktree src 的软链。复跑结果：t097 全文件 12 passed；新增三例单独复跑 3 passed；t095 单持有者真并发用例（参数化 2 例）单独复跑 2 passed。

## 第 1 轮 finding 复核

### t097_test_f001（important）— 已修复成立

新增三条测试逐条核对（`tests/mail_core/test_t097_patrol_account_state.py`）：

1. `test_ac003_expired_holder_late_failure_cannot_overwrite_new_settlement`：与原晚到成功用例同一交错骨架（A 线程进探测后以 `entered_probe`/`release_probe` 两个 Event 屏障挂起、B 在主线程以显式时钟 `b_now = now0 + 310s` 串行完成认领+失败结算、再释放 A），但 A 的慢探测最终抛 `ConnectionError` 走晚到失败结算。断言强度足够：释放 A 前先在新鲜 session 断言 B 的结算值 `cooldown_until == b_now + 300s` 且 `lease_token is None`；A 结束后断言 `a_result["res"].failed == 1`（证明 A 的晚到失败结算确实被尝试执行，而非被短路跳过）且同一新鲜 session 中冷却值仍精确等于 B 的结算值。修复前该断言必然见红（旧跌落 upsert 会把冷却改写为 `now0 + 300s`，与期望值相差 310s，不可能误绿）。
2. `test_ac003_expired_holder_late_failure_cannot_resurrect_cleared_state`：B 改走成功探测并清除整行（释放 A 前断言新鲜 session 中状态行为 None），A 晚到失败后断言状态行仍为 None。修复前旧跌落 upsert 会 INSERT 新行，该断言必然见红。
3. `test_ac003_holder_same_sweep_success_then_failure_reestablishes_cooldown`（防过度修正）：单轮内以轮转顺序构造「先成功探测（清除已过期行）→ 后账号级 TRANSPORT 失败」，断言 `probed == 1 and failed == 1` 且冷却被重建为 `now0 + 300s`、令牌为 None。该例封堵了「把 self_cleared 插入路径一并砍掉」的过度修正方向。
4. 时序真实性：三例均为真实线程 + Event 屏障的并发交错（非串行伪造的事后调用），A/B 两轮巡检各用独立 session、显式时钟驱动租约过期，结算结果均在新鲜 session 中比对持久化状态。
5. 原用例 docstring 已修正：`test_ac003_expired_holder_late_settlement_cannot_touch_new_lease` 的 docstring 改为只声称晚到成功变体，并注明「A's late FAILURE is covered by the two variants below」，与实际覆盖一一对应，虚假声称消除。
6. 红灯证据：实施者记录修复前两条新用例实跑 2 failed、修复后 t097 全文件 12 passed；本轮独立复跑修复后版本 12 passed（全文件）与新增三例 3 passed，与记录一致。红灯阶段已过，本轮无法重演见红，但由第 1 条断言分析，旧实现下两例不可能误绿，红灯记录可信。

### t097_test_f002（minor）— 撤回成立

第 1 轮原文即定性为「覆盖实际成立但不直接」「可不改」：构建失败时坏账号一侧不存在 Provider 对象，STATUS 为零是构造必然；且现有断言（`fps_rows == []`、`res.probed` 只计好账号、构建计数 == 1）对「构建失败后仍逐目录探测」的假想重构能间接报警。实施侧按 reviewer 明示意见撤回，理由与第 1 轮定性一致，撤回成立。

### t097_test_f003（minor）— 撤回成立

本轮实地核对合并覆盖确实存在：`tests/mail_core/test_t095_patrol_and_idle_fixes.py::test_patrol_half_open_expired_cooldown_single_holder_across_workers`（参数化 `recovery_succeeds` True/False）为真并发竞争——worker1 线程在探测内以 Event 挂起持租，worker2 在其持租期间并发发起完整巡检，断言全程 `probe_calls` 恰为 1 次、w2 零探测零失败；其预置已迁至新表（`AccountPatrolState(cooldown_until=expired)`）、结果断言改查新表且含 config 其余键保留。本轮独立复跑该用例 2 passed。`docs/blueprint/testing.md` 的 t097 回归命令为 `-k "test_t097 or test_t095_patrol or test_t096_migration_and_patrol or test_migration_validation"`，包含该文件，入口级盲区亦不存在。撤回成立。

## Round 2 新发现

无新的测试 finding。提示（不进表）：晚到交错用例的故障域全部为 TRANSPORT；AUTH 域晚到结算对凭据状态的副作用语义未裁决、亦无用例覆盖，已在 review_code Round 2 记为 minor t097_code_f003，若后续裁决改变该语义需同步补 AUTH 晚到用例。

## Round 2 结论

- 第 1 轮 finding 复核：t097_test_f001 已修复成立；t097_test_f002、t097_test_f003 撤回成立。
- 本轮新发现：0 条。
- 总体判断：AC-003 的测试覆盖缺口（晚到失败两变体）已补齐且断言强度、交错真实性均达标，假绿保护消除；其余 AC 的覆盖判断维持第 1 轮结论。无未解决 critical/important，按 verdict 规则判定 PASS。正式 Docker 门禁仍待 p108，AC 打勾按约定留待门禁后处理，不影响本轮测试复审结论。

### AC 复验方式（Round 2）

- AC-001：TICK-VALID，re_verified。本轮复跑两例通过；STATUS 为零的构造性保证维持 f002 撤回结论。
- AC-002：TICK-VALID，re_verified。本轮复跑 TRANSPORT/AUTH 两例通过，兄弟行原值与缺失行保持缺失的精确断言未变。
- AC-003：TICK-VALID，re_verified。第 1 轮不完全项本轮补齐：冷却内跳过、租约期内单持有者、当前持有者成功清除、晚到成功、晚到失败覆盖新结算、晚到失败复活已清除行、同轮自清后重建，共七个侧面均有真实交错/生产入口用例；单持有者真并发由 t095 旧用例合并覆盖且本轮复跑 2 passed。
- AC-004：TICK-VALID，re_verified。本轮复跑迁移用例通过（自建临时库、五类夹具、upgrade/downgrade 往返）。
- AC-005：TICK-VALID，re_verified。本轮复跑用例通过（生产入口、事务外构建/探测、认领已提交可见、并发 config 编辑存活）。

coverage = 5 / 5

verdict: PASS

reviewed_scope: 7a814f512aba3e09
