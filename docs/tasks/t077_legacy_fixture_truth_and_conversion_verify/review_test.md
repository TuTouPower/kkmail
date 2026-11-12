# Task review t077（reviewer_focus: 测试）

- task：`t077_legacy_fixture_truth_and_conversion_verify`
- spec：`docs/tasks/t077_legacy_fixture_truth_and_conversion_verify/task.md`
- diff_anchor：`bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`
- target：`git diff bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`
- round：1
- reviewed_at：2026-11-12T12:07:30+08:00

reviewed_scope: aede7f7baa26f098

## Findings

### t077_test_f001 - AC-001「豁免针对的四列差异不被豁免」缺专门负向回归测试

- 严重度：minor
- 锚点：AC-001（覆盖补强，非阻断；AC 主体已有真实测试且实现无豁免分支）
- 位置：`tests/scripts/test_migrate_to_unified_baseline.py:285-351`（`verify_baseline_schema` 系列）、`src/mail_core/db/baseline.py:404-449`
- 问题：AC-001 要求「对 `accounts` 任意列差异（含 `sync_status` / 三维列）均不豁免，返回对应差异」。现有 6 个 `verify_baseline_schema` 用例覆盖的是 `display_name` 删除、`email` 类型、`recipient_addresses`/`remote_id` 缺列、唯一约束、空库、全形状 0 drift，均不触及 `sync_status` / `credential_state` / `connectivity_state` / `sync_activity` 四列——正是 f006 豁免补丁针对的列。t077 后全量校验归位到 `upgrade head` 之后，库恒为 head 形状（三列齐、`sync_status` 消失），正常路径不再产生这四列差异；若豁免逻辑日后复活，上述用例、两个正向用例（head 形状 0 drift）、drift 用例（`email`）仍全绿，无法捕获回归，与 p076「豁免补丁绕过校验致假绿」同型。实现层删除已由 `baseline.py:404-449`（无豁免分支，仅 `_is_ignored_baseline_diff` 处理全表通用 raw-SQL 对象）与全仓代码零引用证实，故不阻断，仅缺回归防护。
- 建议：补一条真实 PG 用例，在 head 库上人为制造四列之一的差异（如 `ALTER TABLE accounts ADD COLUMN sync_status VARCHAR(32)` 或 `DROP COLUMN credential_state`），断言 `verify_baseline_schema` 返回并锚定该列名。

### t077_test_f002 - AC-003 offline 入口 UPGRADE_TO_HEAD 分支无直接真实用例

- 严重度：minor
- 锚点：AC-003（覆盖补强）
- 位置：`tests/scripts/test_migrate_to_unified_baseline.py`（`run_migration` 调用点 `373/387/435/578/671/693`）、`tests/mail_core/test_startup_migrations.py:584`（startup 侧已有）
- 问题：AC-003 要求两个入口的 LEGACY / UPGRADE_TO_HEAD 路径都在 `upgrade head` 后执行 `verify_baseline_schema`。真实 PG 覆盖已含 startup LEGACY（`test_t8_real_0030_legacy_shape_upgrades_via_startup`，无 mock）、startup UPGRADE_TO_HEAD（`test_t7_older_baseline_upgrades_in_place_with_data_mapping`，无 mock）、offline LEGACY（重写正向用例 + drift 用例）；但 offline 入口（`run_migration` / `main`）的所有调用针对 EMPTY / UNKNOWN / NO_VERSION / LEGACY / LEGACY_UNSUPPORTED / AT_BASELINE，没有一条构造 stamp=`20261107_0001` 的库走 UPGRADE_TO_HEAD 分类。该分支与 offline LEGACY 共用 `upgrade_head_and_verify`（已被真实覆盖），分类→`needs_upgrade` 链路在 offline 侧仅间接成立；上下文区「所有迁移入口分支均有真实 PG 或单元覆盖」与此略有出入。按「可以补一个 case」不阻断。
- 建议：补一条 offline 正向用例，构造 stamp=`UNIFIED_BASELINE_REVISION` 的 0001 形状库，调 `run_migration(db_url)`，断言升到 `CURRENT_HEAD_REVISION`、三列与数据映射生效。

### t077_test_f003 - 两个测试文件模块 docstring 仍描述被修复的旧做法

- 严重度：minor
- 锚点：行为缺陷（文档误导）；关联 AC-002 / AC-003
- 位置：`tests/mail_core/test_startup_migrations.py:13-21`、`tests/mail_core/test_migration_validation.py:8-14`
- 问题：`test_startup_migrations.py` 模块 docstring 仍称「0030 legacy shape is derived from ... alembic upgrade head」「A16's post-conversion check is a full compare_metadata」「deriving the shape from the baseline does not weaken them」「pre-A16 worry ... no longer applies」；`test_migration_validation.py` 模块 docstring 同样称「A16 derives the 0030 narrow-legacy fixtures from ... alembic upgrade head」。而 t077 根因正是「由 head 派生夹具=假绿」且 post-conversion 校验已删除、改到 upgrade head 之后。函数级 docstring 已同步，模块级仍保留为错误做法辩护的论述，易误导后续维护者/评审者。属注释，不改变测试行为。
- 建议：两处模块 docstring 同步为「夹具由 `upgrade(cfg, "20261107_0001")` 派生、全量校验在 upgrade head 之后」。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 改测方向复核：无「迁就实现」的改测。逐处核对：三夹具（`_pg_build_0030_shape` / `_make_0030_db` / `_create_0030_schema`）改的是构造源头（head→`UNIFIED_BASELINE_REVISION`）并新增形状护栏，测试体断言一字未改；`test_t7_older_baseline...` 的 columns 查询加 `AND table_schema = current_schema()` 是增强而非迁就；两个语义失效旧测试均为**整体重写**（改名 + 换不变式 + docstring 写明理由），`test_conversion_rejects_drifted_legacy_schema_after_upgrade` 还把 `pytest.raises` 加了 `match="does not match the unified baseline"`（增强），`test_real_0030_shape_upgrades_to_head_with_forward_data_mapping` 以完整 head 升级契约替代旧 `version == UNIFIED_BASELINE_REVISION`；无就地改预期。红灯归因两处均写明「规格变了：全量校验移到 upgrade 后 / 离线入口重放 0002」。
- 危险模式逐项扫描（恒真断言 / 删或反转 expect / 注释断言 / 弱化断言 / 删测试 / `.skip`·`.only` / 静默错误 / mock 误用 / 阈值增大 / 条件跳过 / 程序赋值替代交互 / 存在即通过）均未命中。`_mock_upgrade` 新增 stub `mail_core.db.baseline.verify_upgraded_schema -> []` 属协作方隔离：编排用例（t1/t2/t4/t5/both_entries/t8_drifted）被测的是 plan→conversion→upgrade 调用序列，`command.upgrade` 被 stub 后库仍停在 0001，若跑真实校验会误报大量 drift，故 stub 必要；`verify_upgraded_schema`→`verify_baseline_schema` 的真实成功/失败行为由 4 个无 mock PG 用例独立承担：startup LEGACY（t8）、startup UPGRADE_TO_HEAD（t7_older）、offline LEGACY 正向（重写用例）、offline LEGACY drift（`test_conversion_rejects_drifted_legacy_schema_after_upgrade`）。`test_t8_drifted_baseline_refused_by_all_three_entries` 走 AT_BASELINE 的 `verify_for_plan`→`verify_baseline_schema`（未被 stub），drift 真实捕获，stub 对其无影响。未发现 mock 掉被测逻辑或假绿。
- 本轮新发现：3 条（均 minor）。
- 未进表的提示：`test_conversion_rejects_drifted_legacy_schema_after_upgrade` 末尾 `assert verify_baseline_schema(conn)` 为 truthy 断言（受控环境下语义为「库不被接受为健康」，spec 已批准该不变式，非恒真），后续可锚定 drift 具体列名再增强；生产 `src/mail_core/db/baseline.py:526-548` `verify_narrow_legacy_schema` docstring 仍称 post-conversion 事务内全量校验，属生产代码注释、code reviewer 职责，本轴不进表。本轮未重跑 PG 测试，避免与后台全量门禁争用共享 public-schema 库；`re_verified` 基于对 diff、生产校验函数、各测试断言本身与静态事实（常量值、revision DDL、grep 零引用）的独立查证，门禁数字不作为判定依据。
- 重点核实结论：形状护栏三处均查询 `information_schema.columns` 并断言 `sync_status` 存在、三列不存在；若把 `upgrade(..., UNIFIED_BASELINE_REVISION)` 改回 `head`，`assert "sync_status" in account_columns` 立即变红，能防「由 head 伪造」退化。`table_schema = current_schema()` 在三处 schema 隔离下成立：`_pg_build_0030_shape` 走 `get_engine()` 的 public，`_make_0030_db` / `_create_0030_schema` 的 URL 均带 `options=-csearch_path=<schema>`，upgrade 与护栏查询落在同一 schema。两个正向用例从护栏保证的真实 0001 形状（0001 revision `accounts.sync_status` 有 `server_default 'idle'`，故夹具 seed INSERT 不含该列仍成立；`email` 为 `VARCHAR(320)`）出发，真跑 `main_module.run_migrations()` / `main([...])` 无 mock，断言 `CURRENT_HEAD_REVISION`、三列、`sync_status` 消失、`folder_patrol_status` 重建、`auth_failed→invalid/false`、`failed→valid/degraded`（与 `20261112_0002_account_health_states.py:41-48` 一致）。负向 drift 用例注入 `email TYPE VARCHAR(64)`，因 `verify_narrow_legacy_schema`（`baseline.py:526-673`）不检查 `email` 类型，drift 保留到 upgrade 后被 `verify_baseline_schema` 捕获，`pytest.raises` 的 match 锚定 `upgrade_head_and_verify` 抛错；`verify_baseline_schema` 全量 `compare_metadata`（`compare_type=True`）配置未削弱，既有 stamp / dry_run / 并发序列化 / 回滚测试（`test_migration_validation.py:661`、`:718` 及 `test_startup_migrations.py:317`）测试体断言原样保留，未被削弱。
- 总体判断：三夹具护栏、两处 TDD 整体重写、正向 PG 覆盖均真实触达生产逻辑，无假绿/就地改预期/mock 被测逻辑，3 条 minor 为覆盖补强与文档同步，无阻断项，PASS。
- 系统性 follow-up：无（3 条 minor 均可在当前 task 内闭环，无需另立 task）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`baseline.py:404-449` 读得 `verify_baseline_schema` 无任何 accounts 豁免分支，三个豁免符号全仓代码零引用（仅 docs 历史描述命中），6 个 `verify_baseline_schema` 真实用例覆盖列/类型/约束/缺列差异；针对四列的专门负向测试缺失见 f001（minor，不阻断打勾）。
- AC-002：TICK-VALID，re_verified。三夹具 `test_migration_validation.py:597`、`test_startup_migrations.py:117`、`test_migrate_to_unified_baseline.py:180` 均 `upgrade(cfg, UNIFIED_BASELINE_REVISION)`（`=20261107_0001`），构造后立即断言 `sync_status` 存在、三列不存在，且各以 `current_schema()` 限定 schema；改回 head 会令护栏变红。
- AC-003：TICK-VALID，re_verified。`__main__.py:105/148` 与 `baseline.py:1225` 在 `upgrade head` 后校验；startup LEGACY（t8）、startup UPGRADE_TO_HEAD（t7_older）、offline LEGACY 正向（重写用例）三个无 mock PG 用例真实跑校验 0 drift，drift 用例 `pytest.raises(SchemaValidationError, match="does not match the unified baseline")` 证失败抛错；offline UPGRADE_TO_HEAD 直接用例缺失见 f002（minor）。
- AC-004：TICK-VALID，re_verified。`test_t8_real_0030_legacy_shape_upgrades_via_startup` 与 `test_real_0030_shape_upgrades_to_head_with_forward_data_mapping` 从护栏保证的真实 0001 形状出发、真跑 `run_migrations()`/`main()` 无 mock，断言 `CURRENT_HEAD_REVISION`、三列存在、`sync_status` 消失、`folder_patrol_status` 重建、历史值映射，与 0002 revision DDL 一致。
- AC-005：TICK-VALID，re_verified。重写 drift 用例注入 `email TYPE VARCHAR(64)`（0001 为 `VARCHAR(320)`），前置 `verify_narrow_legacy_schema` 不检查该列，drift 保留到 upgrade 后被全量比较捕获，`pytest.raises` match 锚定 post-upgrade 抛错；`verify_baseline_schema` 全量配置未削弱，系列用例覆盖其余表/键/索引。
- AC-006：TICK-VALID，re_verified。diff 显示 `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` 改为 `status=closed` / `resolution=resolved` / `fix_ref=t077`，`docs/specs/mail_sync_and_storage.md` front matter 登记 `t077`；diff 未触及 `docs/tasks/t076_*`，无新增 pending。

coverage = 6 / 6

verdict: PASS

## Round 2 (2026-11-12T12:58:13+08:00)

reviewed_scope: d53ff8ef015acd4a

### 前轮 finding 复核（Round 1）

- `t077_test_f001`（minor，豁免负向护栏）：**已消除**。`tests/scripts/test_migrate_to_unified_baseline.py:785` 新增 `test_verify_baseline_schema_never_exempts_health_columns`，`command.upgrade(cfg, UNIFIED_BASELINE_REVISION)` 构造 0001 形状 catalog 后断言 `verify_baseline_schema(conn)` 的 errors 含 `sync_status` 与三列四列名。独立查证：`src/mail_core/db/baseline.py:367-404` `_describe_diff` 对 `add_column`/`remove_column` 输出含列名的字符串；`_BASELINE_ONLY_COLUMNS`（`baseline.py:336-339`）仅含 `("message_search","document")`，四列不被 `_is_ignored_baseline_diff` 吞；`verify_baseline_schema`（`baseline.py:448-451`）循环无豁免分支。纯 mock 定点验证（patch `compare_metadata` 返回四列 diff，项目 venv、不连 PG）复现四列名全部进入 errors。反事实复刻 f006 旧 `_is_account_column_drift`（累积 diff 中已删除的实现）对四个 diff 均返回 True——若豁免重新接入比较循环，四列差异被全部跳过，该用例四个断言必红。边界：若「复活」严格复刻为「`ignore_account_column_drift` 形参默认 False、仅 conversion 调用点传 True」，该用例（直接调用、不传豁免参数）不敏感；但 AC-003 已删除 `apply_narrow_legacy_conversion` 内的 post-conversion `verify_baseline_schema` 调用（`baseline.py:940-955`），conversion 路径已无该豁免调用点，`upgrade_head_and_verify`→`verify_upgraded_schema`→`verify_baseline_schema(conn)` 均不传豁免参数，且 f001 原始建议本身同型，按 f001 验收本意判定已消除；边界列入「剩余覆盖缺口」。非「换形式弱化」。
- `t077_test_f002`（minor，offline UPGRADE_TO_HEAD 正向）：**已消除**。`tests/scripts/test_migrate_to_unified_baseline.py:809` 新增 `test_offline_upgrade_to_head_from_0001_baseline`，构造 stamp=`UNIFIED_BASELINE_REVISION`(`20261107_0001`) 的库，经离线 `main(["--database-url", db_url]) == 0`，断言 `scalar_one() == CURRENT_HEAD_REVISION`(`20261112_0002`)、`verify_baseline_schema(conn) == []`、三列存在、`sync_status` 消失。`verify_for_plan`（`baseline.py:692-696`）对 UPGRADE_TO_HEAD 返回 `[]`，`run_migration` 的 `needs_upgrade` 分支（`baseline.py:1217-1226`）真跑 `upgrade_head_and_verify` 重放 0002 + 全量校验，全程无 mock。断言为精确值/集合断言，非 truthy。
- `t077_test_f003`（minor，模块 docstring）：**已消除**。`tests/mail_core/test_startup_migrations.py:13-21` 与 `tests/mail_core/test_migration_validation.py:5-14` 模块 docstring 均改为「夹具由 `alembic upgrade 20261107_0001` 历史 DDL 派生、全量 compare_metadata 在升级到 head 之后」，删除为「由 head 派生 + post-conversion 校验」辩护的旧论述。

### Round 2 生产改动对测试的影响

- `src/mail_core/__main__.py:85`（UPGRADE_TO_HEAD）与 `:127`（LEGACY）由 `command.upgrade(cfg, "head")` 改为 `baseline.upgrade_head_and_verify(db_url)`；`tests/mail_core/test_startup_migrations.py:215-228` 的 `_mock_upgrade` 仍同时桩 `alembic.command.upgrade`（记录 calls）与 `mail_core.db.baseline.verify_upgraded_schema`（返回 `[]`）。
- `upgrade_head_and_verify`（`src/mail_core/db/baseline.py:466-485`）内部 `from alembic import command; command.upgrade(cfg,"head")` 与模块内 `verify_upgraded_schema(database_url)` 分别命中上述两桩。纯 mock 定点验证（项目 venv、不连 PG）：桩下调用 `upgrade_head_and_verify` 记录 `['head']` 且正常返回、不抛 `SchemaValidationError`。
- 编排类用例调用序列断言逐个复核仍成立：`test_t1_narrow_legacy_converts_inline`（`:240` `["head"]`）、`test_t2_unsupported_legacy_rejected_with_zero_changes`（`:283` `[]`）、`test_t4_failed_conversion_rolls_back_and_rerun_is_idempotent`（`:344/348/353` 为 `[]`/`["head"]`/`["head","head"]`）、`test_t5_empty_head_and_incremental_never_stamp`（`:363/373/392/408`）、`test_both_entries_delegate_to_single_planner`（`:533`）、`test_t8_drifted_baseline_refused_by_all_three_entries`（`:579` `[]`，走 `verify_for_plan`→`verify_baseline_schema` 未被桩）。根因：生产改动把「入口直接 `command.upgrade`」换成「收敛点内部一次 `command.upgrade`」，对桩而言仍是一次 `("head")` 调用；`verify_upgraded_schema` 桩避免库停在 0001 时误报大量 drift。
- 真实校验由无 mock 的真实 PG 用例承担：`test_t8_real_0030_legacy_shape_upgrades_via_startup`（startup LEGACY）、`test_t7_older_baseline_upgrades_in_place_with_data_mapping`（startup UPGRADE_TO_HEAD）、`test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`（offline LEGACY）、`test_offline_upgrade_to_head_from_0001_baseline`（offline UPGRADE_TO_HEAD，本轮新增）、`test_conversion_rejects_drifted_legacy_schema_after_upgrade`（offline LEGACY drift，`pytest.raises(SchemaValidationError, match="does not match the unified baseline")`）、`test_t8_drifted_baseline_refused_by_all_three_entries`（AT_BASELINE drift）。`_mock_upgrade` 桩的是协作方（Alembic chain / 校验收敛点内部协作），被测的 `run_migrations` 编排与 `apply_narrow_legacy_conversion` 真实执行，未 mock 掉被测逻辑。

### 改测方向与 TDD 铁律复核

- 无「迁就实现」的就地改预期。两处语义失效旧测试为整体重写并写明理由（`test_conversion_rejects_drifted_legacy_schema_and_rolls_back`→`test_conversion_rejects_drifted_legacy_schema_after_upgrade`；`test_migrate_from_0030_legacy_database_success`→`test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`），红灯归因写明「规格变了：全量校验移到 upgrade 后 / 离线入口重放 0002」。其余既有断言（6 个 `verify_baseline_schema` 用例、stamp / dry_run / 并发序列化 / 回滚）原样保留，`test_t7_older_baseline...` 的 columns 查询加 `AND table_schema = current_schema()` 为增强。
- 危险模式逐项扫描（恒真断言 / 删或反转 expect / 注释断言 / 弱化断言 / 删测试 / `.skip`·`.only` / 静默错误 / mock 误用 / 阈值增大 / 条件跳过 / 程序赋值替代交互 / 存在即通过）：本轮新增与修改用例均未命中。R1 已记录的 `test_conversion_rejects_drifted_legacy_schema_after_upgrade` 末尾 `assert verify_baseline_schema(conn)` truthy 断言本轮未改动，属 R1「未进表的提示」范围，非恒真、不阻断。

### 本轮 Findings

无新增（finding 前缀 `t077_test_f004` 起 0 条）。

### 未进表的提示

- 本轮未重跑 PG 门禁（后台全量门禁在跑，按指令不争用共享 public-schema 库）；`re_verified` 基于对累积 diff、生产校验函数、各测试断言本身与静态事实（常量 `20261107_0001`/`20261112_0002`、0002 revision DDL 与数据映射、全仓 `src/` 豁免符号零引用）的独立查证，加纯 mock 定点验证；门禁数字（定向 PG 80 passed、后端 unit 1654 passed 等）为旁证，不作判定依据。
- `tests/scripts/test_migrate_to_unified_baseline.py` 模块 docstring 未同步 0001 夹具说明（f003 只点名两个文件，其函数级 `_create_0030_schema` docstring 已同步），属范围外观察。

### 剩余覆盖缺口

- f001 护栏对「仅参数化、默认关闭、特定调用点开启」的豁免复活形态不敏感；当前架构已无该调用点（AC-003 删除 post-conversion 校验），且 f001 原始建议同型，非阻断。
- `test_conversion_rejects_drifted_legacy_schema_after_upgrade` 末尾 truthy 断言未锚定 `email` drift 列名（R1 已提示，本轮未改），可选增强。
- `check_only=True` + UPGRADE_TO_HEAD 组合（`__main__.py:83-84` 只读返回、不升级）无专门用例，属可选覆盖扩展。

### 结论

- 前轮 finding 复核：R1 三条 minor 均以真实测试 / 文档改动消除（f001 已消除、f002 已消除、f003 已消除），无「修不彻底」「换形式弱化」「仍存在」。
- 改测方向复核：无「迁就实现」的改测。
- 本轮新发现：0 条。
- 总体判断：R1 三条 minor 消除，Round 2 生产改动未破坏编排用例调用序列、未 mock 被测逻辑，逐条 AC 均有可信测试支撑，无未解决 critical / important，PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`baseline.py:407-452` `verify_baseline_schema(bind)` 签名无豁免形参、循环仅 `_is_ignored_baseline_diff`；`ignore_account_column_drift`/`_is_account_column_drift`/`_ACCOUNT_HEALTH_COLUMNS` 在累积 diff 整体删除、全仓 `src/` grep 零引用（仅 t076/t077 历史文档描述性命中）；新增 `test_verify_baseline_schema_never_exempts_health_columns`（`tests/scripts/test_migrate_to_unified_baseline.py:785`）专测四列差异不豁免，纯 mock 验证断言可达、复刻 f006 豁免反证复活必红。
- AC-002：TICK-VALID，re_verified。三夹具 `tests/scripts/test_migrate_to_unified_baseline.py:180`（护栏 `:184-194`）、`tests/mail_core/test_startup_migrations.py:117`（护栏 `:121-131`）、`tests/mail_core/test_migration_validation.py:598` 均 `command.upgrade(cfg, UNIFIED_BASELINE_REVISION)`(=`20261107_0001`，`baseline.py:45`)，构造后立即断言 `sync_status` 存在、三列不存在，并以 `current_schema()` 限定 schema；改回 `head` 会令护栏变红。
- AC-003：TICK-VALID，re_verified。`apply_narrow_legacy_conversion` 事务内删除 post-conversion `verify_baseline_schema`（`baseline.py:940-955` 仅余前置 `verify_narrow_legacy_schema` + 重建 + 迁移 + stamp 0001）；`__main__.py:85/127` 与 `run_migration` 的 `needs_upgrade` 分支（`baseline.py:1217-1226`）统一 `upgrade_head_and_verify`（`baseline.py:466-485` 先 `command.upgrade(head)` 再 `verify_upgraded_schema`，errors 则抛 `SchemaValidationError`）；startup/offline 的 LEGACY/UPGRADE_TO_HEAD 六个无 mock PG 用例真实跑校验 0 drift，drift 用例 `pytest.raises` 证失败抛错；编排用例调用序列经纯 mock 定点验证仍成立。
- AC-004：TICK-VALID，re_verified。`test_t8_real_0030_legacy_shape_upgrades_via_startup`（startup）与 `test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`（offline）从护栏保证的真实 0001 形状（含 `sync_status`、缺 `folder_patrol_status`、stamp `20261031_0030`）真跑 `run_migrations()`/`main()` 无 mock，断言 `CURRENT_HEAD_REVISION`、三列存在、`sync_status` 消失、`folder_patrol_status` 重建、`auth_failed`→`("invalid", False)`、`failed`→`("valid","degraded")`，与 `20261112_0002_account_health_states.py:26-49` DDL/映射一致。
- AC-005：TICK-VALID，re_verified。`test_conversion_rejects_drifted_legacy_schema_after_upgrade` 整体重写并写明「零写入语义变更」理由，注入 `email TYPE VARCHAR(64)`，前置 `verify_narrow_legacy_schema` 不检查该列，drift 保留到 upgrade 后被全量比较捕获（`pytest.raises(..., match="does not match the unified baseline")`）；`verify_baseline_schema` 用 `compare_metadata(compare_type=True)`，忽略项仅 `_BASELINE_ONLY_COLUMNS`/`_BASELINE_ONLY_INDEXES` raw-SQL 对象，32 表列/键/索引全量比对未削弱，6 个既有用例 + 新增四列护栏覆盖列/类型/约束/缺列/空库/全形状。
- AC-006：TICK-VALID，re_verified。累积 diff 显示 `docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` front matter 改为 `status=closed` / `resolution=resolved` / `fix_ref=t077`，`docs/specs/mail_sync_and_storage.md` front matter 登记 `t077`，`docs/blueprint/testing.md` 同步校验约定；diff 未触及 `docs/tasks/t076_*`，无新增 pending。

coverage = 6 / 6

verdict: PASS
