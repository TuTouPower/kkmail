# Task review t077（reviewer_focus: 代码）

- task：`t077_legacy_fixture_truth_and_conversion_verify`
- spec：`docs/tasks/t077_legacy_fixture_truth_and_conversion_verify/task.md`
- diff_anchor：`bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`
- target：`git diff bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`
- round：1
- reviewed_at：2026-11-12T12:10:19+08:00

reviewed_scope: aede7f7baa26f098

## Findings

### t077_code_f001 - 生产模块/函数 docstring 仍描述 t076 旧校验时序（离线不升级、转换事务内全量校验）

- 严重度：minor
- 锚点：文档与实现不一致（未违反行为 AC；误导后续维护者对失败边界的理解）
- 位置：`src/mail_core/db/baseline.py:8-13`、`:529-532`、`:1014-1017`
- 问题：模块 docstring 仍称「the offline tool only verifies schema, performs supported narrow legacy conversions and stamps」；`verify_narrow_legacy_schema` docstring 仍称「full-baseline equivalence is enforced by `verify_baseline_schema` after the conversion, **inside the same transaction** (see `apply_narrow_legacy_conversion`)」；`plan_migration` docstring 仍称「the offline tool verifies schema and converts supported legacy databases」。t077 后离线入口经 `run_migration:1225` → `upgrade_head_and_verify:466-485` 重放增量 0002，`apply_narrow_legacy_conversion:947-955` 已删除事务内 post-conversion 全量校验，全量比对改由升级后 `verify_upgraded_schema` 执行。三处陈述与实现矛盾，尤其 `verify_narrow_legacy_schema` 指向的 `apply_narrow_legacy_conversion` 已无该校验，读者会沿用「drift 在转换事务内回滚、零写入」的旧模型（恰是本 task 重写的语义）。
- 建议：三处统一改为「离线/启动两入口在 `upgrade head` 之后由 `upgrade_head_and_verify` / `_raise_if_schema_drift` 对升级后库做全量 ORM 比对；转换事务只做前置 precondition 校验」。

### t077_code_f002 - `docs/blueprint/testing.md` 未随实现更新，Finalization 要求的 blueprint 同步未落地

- 严重度：minor
- 锚点：文档与实现不一致（长期真相文档与 t077 核心语义变更冲突）
- 位置：`docs/blueprint/testing.md:204`；对照 `docs/tasks/t077_legacy_fixture_truth_and_conversion_verify/task.md:92-95`
- 问题：该行仍描述「已在统一基线的库、以及**窄转换完成之后（同一写事务内、校准 `alembic_version` 之前）**，都走 `verify_baseline_schema`」，此机制 t077 已删除。`task.md` Finalization 明确要求把迁移校验约定改为「升级到 head 后全量比对」并删除豁免约定，但指向 `docs/blueprint/conventions.md`——该文件无迁移校验段落（grep 零匹配），实际约定在 `testing.md:204`；本次 diff 的 9 个文件不含任何 blueprint 文件。blueprint 是项目长期真相，将持续与新实现冲突。
- 建议：改 `testing.md:204` 为「升级到 head 后全量比对」，删除「转换事务内 / 校准 `alembic_version` 之前」表述；同步修正 `task.md` Finalization 的路径指向，避免下次收尾再次漏改。

### t077_code_f003 - `upgrade_head_and_verify` 自称「两入口单一收敛点」，启动入口未复用，post-upgrade 校验分裂

- 严重度：minor
- 锚点：DRY / separation of concerns（未违反行为 AC，两路径当前功能等价）
- 位置：`src/mail_core/db/baseline.py:466-485`（docstring `:469`）、`:1225`；`src/mail_core/__main__.py:40-56`、`:104-105`、`:147-148`
- 问题：`upgrade_head_and_verify` docstring 写「Single convergence point for both migration entries」，但全仓 grep 显示仅 `run_migration:1225` 调用；`__main__.run_migrations` 的 UPGRADE_TO_HEAD（`:104-105`）与 LEGACY（`:147-148`）各自 `command.upgrade(cfg, "head")` + `_raise_if_schema_drift`，后者（`:40-56`）与 `upgrade_head_and_verify:479-485` 的「upgrade → `verify_upgraded_schema` → 抛错」是同形逻辑的两次实现，错误类型还不一致（`RuntimeError` vs `SchemaValidationError`）。当前两路径都执行升级后全量校验、都拒绝 drift，无坏结果；但未来修改校验规则（加只读/超时保护、改错误信息/类型）需同步两处，易遗漏一侧。progress 笔记声称「单一收敛点」与代码不符（不采信自述，仅以代码为据）。
- 建议：`__main__` 两分支改调 `baseline.upgrade_head_and_verify(db_url)`（或抽公共 helper 统一升级+校验+错误类型），使 docstring 与事实一致、消除重复。

### t077_code_f004 - `verify_upgraded_schema` 新建 engine 缺只读事务与 statement_timeout 保护

- 严重度：minor
- 锚点：健壮性 / 与既有校验路径不一致（无当前可观测坏结果）
- 位置：`src/mail_core/db/baseline.py:452-463`；对照 `:293-311`（`read_only_connection`）、`:692-695`（`verify_for_plan`）
- 问题：`verify_upgraded_schema` 用 `create_engine(check_connect_url(database_url))` 直连后调 `verify_baseline_schema(engine)`，仅带 `connect_timeout=10`；而其它全量比对入口（`verify_for_plan` → `read_only_connection`）额外施加 `SET TRANSACTION READ ONLY` 与 `statement_timeout=10s`。t077 把全量 `compare_metadata` 从「转换事务内 / read-only 连接」移到升级后的这条新路径，丢了这两层保护。`compare_metadata` 本身只读、32 表规模下无当前坏结果，但与项目既有校验契约不一致，异常 catalog 上无语句级超时兜底。
- 建议：`verify_upgraded_schema` 改用 `read_only_connection(database_url)`（或在该连接上 `configure_read_only` + `statement_timeout`），与 `verify_for_plan` 对齐。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 本轮新发现：4 条（t077_code_f001~f004，均 minor，非阻断）。
- 未进表的提示：
    - 文件过大（命中阈值但按降级规则不进表）：`src/mail_core/db/baseline.py` 1233 行（实现源码 ≥800），本 task 净增仅 +1（`+71/-70`，删豁免补丁与新增 `verify_upgraded_schema`/`upgrade_head_and_verify` 等量替换，非堆大）；测试源码 `tests/mail_core/test_startup_migrations.py` 727 行（净增 +96）、`tests/mail_core/test_migration_validation.py` 771 行（净增 +12）、`tests/scripts/test_migrate_to_unified_baseline.py` 782 行（净增 +65），均 ≥600 minor 阈值。
    - 圈复杂度：`__main__.run_migrations` 手算 CC≈11（≥10，结论段提示），本 task 未新增分支（仅两处 `_raise_if_schema_drift` 调用），按「≥15 且本 task 仍增分支」不命中；`baseline.run_migration` 手算 ≈7，未达阈值。
    - 范围外观察：EMPTY_DATABASE / AT_BASELINE 分支在 `command.upgrade(cfg,"head")` 后未补 post-upgrade 校验（既存设计，分别因空库由 Alembic 建表、升级前 `verify_for_plan` 已全量校验而自洽；AC-003 只要求 LEGACY / UPGRADE_TO_HEAD，非本 task 范围，不出 finding）；测试文件模块 docstring 过期已由 test 轴 `t077_test_f003` 覆盖，code 轴不重复；`docs/tasks/t076_*` 历史 review 文档仍描述 f006 豁免，属历史记录、非范围且不应改。
    - 7 视角均已扫描：安全（cfg URL `%%` 转义经 `alembic/env.py:28-31` 确认生效、日志用 `hide_password=True` 脱敏、advisory lock key 为常量、无外部输入拼接 SQL）、实现正确性、契约·Breaking（`verify_baseline_schema` 删参为 spec 明列的破坏性变更、无迁移说明缺口）、性能·资源（新 engine 均 `finally dispose`、无循环内查库泄漏）、架构·可维护性（f003）、健壮性·可观测（f004）、测试·文档·规格（f001/f002）。
- 总体判断：6 条 AC 实现层全部真实支撑（全 TICK-VALID）；豁免补丁三符号在生产 `src/` 零引用、删除彻底；LEGACY / UPGRADE_TO_HEAD / AT_BASELINE / EMPTY_DATABASE 四路径 `verify_for_plan` → conversion → `upgrade_head_and_verify` / `_raise_if_schema_drift` 时序自洽，`dry_run` 与 `check_only` 全零写入，`upgrade_head_and_verify` 的 cfg URL 转义与 `check_connect_url` 用法正确；`docs/tasks/t076_*` 零改动、t076 交付未被触碰（仅 p076 pending 状态与 spec 索引）。4 条 minor 均为文档同步 / DRY / 健壮性，无未解决 critical / important，PASS。复验方式为静态查证 diff 与代码/测试断言本身、全仓 grep、`git diff --numstat` 与 `review-status` 只读核对；未重跑 PG 门禁，依派审方门禁证据与 test 轴 `review_test.md`（PASS）佐证。
- 系统性 follow-up：无（f001/f002 归入 `task.md` 已列的 Finalization blueprint 同步，不另立 task；f003/f004 由 implementer 在 adoption 阶段处置）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/db/baseline.py:404-449` `verify_baseline_schema` 签名恢复为 `(bind)`，循环内仅 `_is_ignored_baseline_diff`（全表通用 raw-SQL 对象）跳过；`_ACCOUNT_HEALTH_COLUMNS`/`_is_account_column_drift`/`ignore_account_column_drift` 在本 diff 整体删除，全仓 grep 生产 `src/` 零引用（仅 t077 文档与 t076 历史 review 有描述性提及），对 accounts 任意列差异均返回 `_describe_diff`。
- AC-002：TICK-VALID，re_verified。三夹具 `_make_0030_db`（`tests/mail_core/test_startup_migrations.py:117`）、`_pg_build_0030_shape`（`tests/mail_core/test_migration_validation.py:597`）、`_create_0030_schema`（`tests/scripts/test_migrate_to_unified_baseline.py:180`）均改 `command.upgrade(cfg, UNIFIED_BASELINE_REVISION)` 并各自立即 `assert "sync_status" in`、三列 not in（`:130-131`/`:618-619`/`:193-194`）；`20261107_0001_unified_baseline.py:85,326-327` 确含 `accounts.sync_status` 且创建 `folder_patrol_status` 供 DROP。
- AC-003：TICK-VALID，re_verified。`apply_narrow_legacy_conversion`（`baseline.py:909-957`）事务内只留 `verify_narrow_legacy_schema` + 重建 patrol + 数据迁移 + stamp 0001，无 `verify_baseline_schema`；`__main__.run_migrations` UPGRADE_TO_HEAD（`:104-105`）/LEGACY（`:147-148`）在 `command.upgrade` 后调 `_raise_if_schema_drift`→`verify_upgraded_schema`→`verify_baseline_schema`，`run_migration`（`:1217-1226`）两路径收敛 `upgrade_head_and_verify`（`:466-485`），失败分别抛 RuntimeError / SchemaValidationError 且库不被接受（负向用例事后 `assert verify_baseline_schema(conn)` 证明持续不被接受）。
- AC-004：TICK-VALID，re_verified。`test_t8_real_0030_legacy_shape_upgrades_via_startup`（`test_startup_migrations.py:655-727`）无 mock 走启动入口，断言 rev=head、三列存在、`sync_status` 消失、`folder_patrol_status` 重建、`auth_failed`→`("invalid", False)`、`failed`→`("valid","degraded")`；离线侧 `test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`（`test_migrate_to_unified_baseline.py:477-562`）对称覆盖；`20261112_0002_account_health_states.py:26-49` 的 DDL/映射与断言一致，且 `ret==0` / `run_migrations()` 不抛即隐式证明升级后 `verify_baseline_schema` 0 drift。
- AC-005：TICK-VALID，re_verified。`test_conversion_rejects_drifted_legacy_schema_after_upgrade`（`test_migrate_to_unified_baseline.py:354-378`）整体重写并写明「零写入」语义变更理由（未就地改预期），仍 `pytest.raises(SchemaValidationError, match="does not match the unified baseline")` 拒绝 `accounts.email VARCHAR(64)` drift；`verify_baseline_schema`（`baseline.py:441-449`）仍 `compare_metadata(ctx, _baseline_metadata())` 全 32 表，`_is_ignored_baseline_diff` 未放宽。
- AC-006：TICK-VALID，re_verified。`docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` front matter 改 `status: closed` / `resolution: resolved` / `fix_ref: t077`；`docs/specs/mail_sync_and_storage.md` front matter `tasks` 增 `t077`；本 diff 的 9 个文件无新增 pending / finding 遗留项。

coverage = 6 / 6

verdict: PASS

______________________________________________________________________

## Round 2 (2026-11-12T14:35:00+08:00)

- round：2
- reviewed_at：2026-11-12T14:35:00+08:00
- diff_anchor：`bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`（与 HEAD 一致，累积 R1 实现 + R2 修复的全部工作区改动）
- target：`git diff bc61fd8bcf40e82819f9769f0ef7467e562c7c5f`

reviewed_scope: d53ff8ef015acd4a

落点仓库校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于 worktree 根，通过。指纹用 `monitoring.review_scope_fingerprint(anchor, task_dir)` 只读重算，结果 `d53ff8ef015acd4a`，与派审方重新渲染的 prompt 注入值一致；`review-status` 当前 `review_scope=stale / round=1` 系 R1 指纹 `aede7f7baa26f098` 过期所致，本轮写入当前指纹后由脚本取全文最后一条比对。

## Findings

本轮 0 条新 finding（`t077_code_f005` 起未启用）。前轮 4 条 minor 逐条以 diff / 代码核实为已消除，修复过程未引入 regression；7 视角复扫无新增可观测缺陷。

### 前轮 finding 复核（以 diff 与代码为准，不采信 progress.md 处置表自称「已修」）

- **t077_code_f001（docstring 漂移）— 已消除**。`src/mail_core/db/baseline.py` 模块 docstring（:5-22）改为「Execution is unified … replay the incremental Alembic chain to head through `upgrade_head_and_verify` and only then run the full `verify_baseline_schema`」；`verify_narrow_legacy_schema`（:527-535）改为「equivalence is enforced by `upgrade_head_and_verify` after the conversion has been upgraded to head」；`plan_migration`（:1008-1017）改为「Both entries then execute the same upgrade path: `upgrade_head_and_verify` …」。另 `verify_baseline_schema`（:430-436）、`verify_upgraded_schema`（:455-460）、`verify_for_plan`（:678-691）、`apply_narrow_legacy_conversion`（:909-920）、`run_migration`（:1152-1157）docstring 同步为「升级后全量比对」时序。全仓 grep 旧时序陈述（「offline tool only verifies schema」「inside the same transaction」「converts supported legacy databases」）零残留，三处旧失败边界误导已根除。`verify_for_plan` docstring 新增 UPGRADE_TO_HEAD 条目与函数体（:692-696 返回 `[]`）一致，无新漂移。
- **t077_code_f002（blueprint 漂移）— 已消除**。`docs/blueprint/testing.md:203` 改为「迁移链为单一线性链（统一基线 `20261107_0001` + 增量 revision `20261112_0002`），严格确保迁移链单 head 无分叉、无孤立 revision」；`:204` 改为「启动入口与离线工具统一走 `upgrade_head_and_verify` … `verify_baseline_schema` 只在升级到 head 后执行，绝不拿 head 的 ORM 去比对更早 revision 的 catalog，也不对任何列差异做豁免」。`task.md:92-95` Finalization 指向由 `conventions.md` 修正为 `docs/blueprint/testing.md`（标注「已落地」）。`tests/mail_core/test_baseline_unit.py:254-271` 的文档门禁断言（含 `verify_baseline_schema`/`compare_metadata`、不含三处禁用旧表述）与新文本相容，定点 unit 实测通过。
- **t077_code_f003（DRY 分裂）— 已消除**。`__main__.py` 全文（:40-130）已无 `_raise_if_schema_drift`（全仓 grep 零引用），UPGRADE_TO_HEAD（:85）与 LEGACY（:127）统一调 `baseline.upgrade_head_and_verify(db_url)`；`baseline.run_migration:1225` 亦调同一函数，三处调用使「Single convergence point」docstring 与事实一致。`command.upgrade` 在 `__main__.py` 仅剩 :75（EMPTY_DATABASE）、:103（AT_BASELINE）使用，与核实重点吻合。收敛点内部链路（:466-485）正确：局部 `from alembic import command` → `alembic_config()` → `cfg.set_main_option("sqlalchemy.url", database_url.replace("%","%%"))`（ConfigParser 插值所需，与夹具一致）→ `command.upgrade(cfg, "head")` → `verify_upgraded_schema(database_url)` → 有 drift 抛 `SchemaValidationError`（:261，确认继承 `RuntimeError`）。错误类型对启动入口调用者一致：`main()` 的 gate 路径（:186-194）只 catch `DatabaseConfigError`，`RuntimeError`/`SchemaValidationError` 均 propagate 为非零退出；LEGACY 分支 `apply_narrow_legacy_conversion` 失败仍由 :121-125 包装为「rolled back / was not modified」`RuntimeError`，而 :127 的 `upgrade_head_and_verify` 失败（conversion 已提交）抛 `SchemaValidationError` 表示「库不被接受为健康」，正是 AC-003/AC-005 的新语义。`check_only`（:83-84、:117-118）与 `dry_run`（:1213-1215，位于 `if needs_upgrade` 之前）均零写入。
- **t077_code_f004（超时保护）— 已消除**。`verify_upgraded_schema`（:455-463）改用 `with read_only_connection(database_url) as conn: return verify_baseline_schema(conn)`，不再裸 `create_engine`。`read_only_connection`（:296-314）施 `SET TRANSACTION READ ONLY` + `SET LOCAL statement_timeout='10s'`（`configure_read_only`:280-293）+ `conn.rollback()` + `engine.dispose()`，与 `verify_for_plan` / `run_migration:1170` 既有校验路径一致；该连接独立于 `command.upgrade` 事务，SET 为事务首句，保护生效且零写入。

### 新增测试复核（code 轴视角，test 轴详审）

- `test_verify_baseline_schema_never_exempts_health_columns`（`tests/scripts/test_migrate_to_unified_baseline.py:785-806`）：真实 PG `command.upgrade(cfg, UNIFIED_BASELINE_REVISION)` 造 0001 形状 catalog，直接 `verify_baseline_schema(conn)`，断言 errors 文本含 `sync_status`/`credential_state`/`connectivity_state`/`sync_activity` 四列。`_is_ignored_baseline_diff`（:357-364）仅过滤 raw-SQL 对象、不涉 accounts 列，0001 形状的 1 个 remove_column + 3 个 add_column 必现，是豁免逻辑复活的有效红灯护栏；无 mock、无恒真断言。
- `test_offline_upgrade_to_head_from_0001_baseline`（同文件 :809-844）：造 0001 形状 → 断言 stamp=`UNIFIED_BASELINE_REVISION` → 真实 `main([...])==0` → 断言 `CURRENT_HEAD_REVISION`、`verify_baseline_schema(conn)==[]`、三列存在/`sync_status` 消失。覆盖 AC-003「离线入口不再拒绝落后 revision」正向路径（`plan_migration:1061-1072` 将 0001 分类为 UPGRADE_TO_HEAD → `needs_upgrade` → `upgrade_head_and_verify`），无 mock。

## 结论

- 前轮 finding 复核：4 条（f001~f004）全部已消除，均为从根因修复；无「修不彻底」「仍存在」「同意撤回」项。修复集中在 docstring / blueprint / `__main__.py` 收敛 / `verify_upgraded_schema` 连接，未改动 AC-001~AC-006 的实现语义，未引入 regression。
- 本轮新发现：0 条。
- 未进表的提示：文件过大（按降级规则不进表）——`src/mail_core/db/baseline.py` 1233 行（实现源码 ≥800），本 task 累积净增 +1（`+87/-86`，删豁免补丁与新增两函数等量替换，R2 仅 docstring 与连接改写等量替换，非堆大）；测试源码 `tests/scripts/test_migrate_to_unified_baseline.py` 844 行（≥600），另 `test_startup_migrations.py` / `test_migration_validation.py` 同达 600 minor 阈值。圈复杂度：`__main__.run_migrations` 手算 ≈11（≥10 结论段提示），R2 删除 `_raise_if_schema_drift` 定义并替换为两处单行调用，分支数不增，未达「≥15 且仍增分支」；`upgrade_head_and_verify` ≈2、`run_migration` ≈7。范围外观察：EMPTY_DATABASE（:75）/AT_BASELINE（:103）仍用裸 `command.upgrade` 且不做 post-upgrade 校验，属 R1 已记录的既存设计（AC-003 只要求 LEGACY / UPGRADE_TO_HEAD），本轮复核未变、不出 finding；`docs/tasks/t076_*` 零改动（`git diff --name-only bc61… | grep t076` 无匹配），t076 已 done 交付未触碰。7 视角复扫：安全（cfg URL `%%` 转义经 `alembic/env.py` 生效、日志 `hide_password=True` 脱敏、无外部输入拼接 SQL）、实现正确性、契约·Breaking（`verify_baseline_schema` 删参为 spec 明列破坏性变更）、性能·资源（`read_only_connection` 与 `create_engine` 均 `finally dispose`、无循环内查库）、架构·可维护性（f003 已收敛）、健壮性·可观测（f004 已补只读+超时）、测试·文档·规格（f001/f002 已同步）均已扫过，无新命中。
- 总体判断：6 条 AC 实现层全部 TICK-VALID；R1 四条 minor 从根因消除且无 regression；`upgrade_head_and_verify` 成为两入口三调用点真正收敛点，`command.upgrade` 在 `__main__.py` 仅剩 EMPTY_DATABASE / AT_BASELINE；`check_only`/`dry_run` 零写入、`SchemaValidationError(RuntimeError)` 对启动入口行为一致；新增两测试无 mock 假绿、断言真实；`docs/tasks/t076_*` 零改动。独立动态复验：`KKMAIL_TEST_MODE=unit` 定点跑 `tests/mail_core/test_baseline_unit.py` 20 passed，佐证 `plan_migration`/`verify_for_plan`/`_stamp_targets`/testing.md 文档门禁断言未受修复影响；未重跑 PG 门禁（后台全量门禁进行中，避免并发冲突），依派审方门禁证据（定向 PG 80 passed、后端 unit 1654 passed、黑盒 E2E 21 passed、全栈 E2E 8 passed）与 test 轴佐证。无未解决 critical / important，PASS。
- 系统性 follow-up：无。
- 剩余风险：全量 PG 门禁后台重跑中（首次因测试 PG 瞬时 recovery mode 中断，非代码失败）；2 个采纳前基线既存 unit 失败（`test_check_dep_locks` / `test_check_doc_sensitive`）主仓与 t076 HEAD 复现、非本 task 引入，progress.md 已按配置缺陷报告约定披露；`review-status` 当前 overall=INCOMPLETE 仅因 R1 指纹 stale，本轴 R2 报告已写入当前指纹，整体 overall 仍待 test 轴 R2 报告同步更新（test reviewer 职责，本轴不代写）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。diff 整体删除 `ignore_account_column_drift`/`_is_account_column_drift`/`_ACCOUNT_HEALTH_COLUMNS`，全仓 `src/` grep 零引用；`verify_baseline_schema(bind)`（:404-452）循环内仅 `_is_ignored_baseline_diff`（全表通用 raw-SQL 对象，:357-364）跳过，对 accounts 任意列差异返回 `_describe_diff`；新增 0001 形状护栏 `:785-806` 断言四列差异均上报。
- AC-002：TICK-VALID，re_verified。三夹具 `_make_0030_db` / `_pg_build_0030_shape` / `_create_0030_schema` 均改 `command.upgrade(cfg, UNIFIED_BASELINE_REVISION)` 派生 0001 形状，各自构造后立即 `assert "sync_status" in` 且三列不与列集合相交（diff 三处 guard），防止回退为 head 伪造。
- AC-003：TICK-VALID，re_verified。`apply_narrow_legacy_conversion`（:909-957）事务内仅 precondition + patrol 重建 + 数据迁移 + stamp 0001，无 `verify_baseline_schema`；`__main__.run_migrations` UPGRADE_TO_HEAD（:85）/LEGACY（:127）与 `run_migration`（:1225）收敛 `upgrade_head_and_verify`（:466-485），先 `command.upgrade(head)` 再 `verify_upgraded_schema`→`verify_baseline_schema`，drift 抛 `SchemaValidationError` 且库不被接受；`check_only`/`dry_run` 零写入。
- AC-004：TICK-VALID，re_verified。`test_t8_real_0030_legacy_shape_upgrades_via_startup`（`test_startup_migrations.py:655-727`）与 `test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`（`test_migrate_to_unified_baseline.py:477-562`）无 mock 走启动/离线入口，断言 rev=head、三列存在、`sync_status` 消失、`folder_patrol_status` 重建、`auth_failed`→`("invalid", False)`、`failed`→`("valid","degraded")`；实现链路 `run_migrations`/`run_migration` + `20261112_0002` DDL/映射完整支撑（未重跑 PG，依门禁证据与静态查证断言本身）。
- AC-005：TICK-VALID，re_verified。`test_conversion_rejects_drifted_legacy_schema_after_upgrade`（`test_migrate_to_unified_baseline.py:354-378`）整体重写并写明「零写入」语义变更理由，仍 `pytest.raises(SchemaValidationError, match="does not match the unified baseline")` 拒绝 `accounts.email VARCHAR(64)` drift，事后 `assert verify_baseline_schema(conn)` 证明持续不被接受；`verify_baseline_schema`（:441-452）全 32 表 `compare_metadata`、`_is_ignored_baseline_diff` 未放宽。
- AC-006：TICK-VALID，re_verified。`docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` front matter 改 `status: closed`/`resolution: resolved`/`fix_ref: t077`；`docs/specs/mail_sync_and_storage.md` front matter `tasks` 增 `t077`；10 个改动文件（`git diff --name-status`）无新增 pending / finding 遗留项。

coverage = 6 / 6

verdict: PASS
