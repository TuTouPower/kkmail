# Task spec

## 背景

t076 新增 Alembic revision `20261112_0002` 把 `accounts.sync_status` 拆为三维健康列后，遗留 `p076`：LEGACY 真实 0030 形状（含 `sync_status`、缺 `folder_patrol_status`）的 narrow conversion 正向 PostgreSQL 用例缺失。

根因不是「少一条测试」，而是两层设计妥协：

1. **夹具与被测对象同源（假绿）**：`_make_0030_db`、`_pg_build_0030_shape`、`_create_0030_schema` 全部用 `upgrade head` / `Base.metadata.create_all()` 造出**当前 0002 三列 schema**，再 `DROP folder_patrol_status` + 篡改 `alembic_version` 伪装成 0030。真实 0030 库应由 `20261107_0001` 基线 DDL 派生，`accounts` 含 `sync_status`。夹具用新真相反推旧真相，导致整类 LEGACY 测试跑在失真输入上。
2. **校验对象错位 + 临时豁免补丁**：`apply_narrow_legacy_conversion` 在转换后用**当前 head ORM（0002）**比对**升级输入（0001 形状）**，职责错位；t076 的 f006 修复加了 `ignore_account_column_drift` / `_is_account_column_drift` 豁免四列来绕过，属开发铁律禁止的临时补丁。因夹具本就是三列，豁免前后都不报红，测试永远验证不到该分支。

依据开发铁律（架构至上、拒绝妥协、零兼容性负担），从根因修正：夹具忠实重放历史 DDL；删除豁免兼容层；把全量 schema 校验归位到「升级到 head 之后」，使校验对象与 ORM 唯一真相一致。t076 已 done 且未合入主干，本 task 以该分支为 `--base`。

## 契约区

### 范围

- 删除 `src/mail_core/db/baseline.py` 的 `ignore_account_column_drift` 参数、`_is_account_column_drift`、`_ACCOUNT_HEALTH_COLUMNS`；`verify_baseline_schema` 恢复为对任意 accounts 列差异均不豁免。
- `apply_narrow_legacy_conversion` 事务内删除用当前 ORM 比对升级输入的 post-conversion `verify_baseline_schema`，保留 `verify_narrow_legacy_schema` 前置校验 + `folder_patrol_status` 重建 + patrol 数据迁移 + stamp `20261107_0001`。
- 两个迁移入口（`mail_core.__main__.run_migrations` 与 `baseline.run_migration`）的 LEGACY / UPGRADE_TO_HEAD 路径在 `command.upgrade(cfg, "head")` 之后对**升级后的库**执行 `verify_baseline_schema`，失败即拒绝、库不被接受为健康；离线入口不再以「不重放增量 revision」为由拒绝落后 revision。
- 三个 LEGACY 夹具改由 `command.upgrade(cfg, "20261107_0001")` 派生真实历史形状，构造后立即断言 `accounts` 含 `sync_status`、不含三列，作为防退化护栏。
- 新增真实 PostgreSQL 正向用例：真实 0030 形状经启动/离线升级到 `20261112_0002`，断言三列存在、`sync_status` 消失、`folder_patrol_status` 重建、历史 `auth_failed`/`failed` 值映射为 `invalid`/`degraded`。
- 既有负向 drift 用例按 TDD 规则整体重写（写明「零写入」语义变更理由），仍拒绝 `accounts.email` 类型 drift。
- 闭环来源 pending `p076`（`resolution=resolved`、`fix_ref=t077`）。

### 非范围

- 不改动 `20261112_0002` revision 的 DDL 与数据映射内容、不改动 ORM 三维状态模型、不改动前端与 API 契约。
- 不改动 `docs/tasks/t076_*` 的任何文件（t076 已 done，其交付指纹与 `review_scope` 绑定，禁止改已 done 交付内容）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：`baseline.py` 中 `ignore_account_column_drift`、`_is_account_column_drift`、`_ACCOUNT_HEALTH_COLUMNS` 全部移除，全仓零引用；`verify_baseline_schema` 对 `accounts` 任意列差异（含 `sync_status` / 三维列）均不豁免，返回对应差异。
- [ ] AC-002：三个 LEGACY 夹具由 `command.upgrade(cfg, "20261107_0001")` 派生；构造出的 `accounts` 表含 `sync_status`、不含 `credential_state` / `connectivity_state` / `sync_activity`；每个夹具在构造后立即断言该形状，防止再次退化为「由 head 伪造」。
- [ ] AC-003：`apply_narrow_legacy_conversion` 转换事务内不再执行 `verify_baseline_schema`；`__main__.run_migrations` 与 `run_migration` 的 LEGACY / UPGRADE_TO_HEAD 分支在 `upgrade head` 后对升级后库执行 `verify_baseline_schema`，0 drift，失败时抛错且库不被接受。
- [ ] AC-004：新增真实 PG 正向用例，从真实 0030 形状（`accounts.sync_status` 存在、`folder_patrol_status` 缺失、stamp `20261031_0030`）经启动升级，断言 `alembic_version` 为 `20261112_0002`、三列存在、`sync_status` 消失、`folder_patrol_status` 重建、历史 `auth_failed`→`credential_state=invalid` 且 `sync_enabled=false`、`failed`→`connectivity_state=degraded`。
- [ ] AC-005：负向 drift 用例经整体重写并写明理由后，仍拒绝 `accounts.email` 改为 `VARCHAR(64)` 的 drift；`verify_baseline_schema` 对其余 32 张表的列、键、索引全量比对不削弱。
- [ ] AC-006：`docs/pending/p076_legacy_0030_real_shape_upgrade_gate.md` 闭环为 `status=closed` / `resolution=resolved` / `fix_ref=t077`；本 task 不新增遗留项。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试（AC-004 的真实 PG 用例由 `scripts/run-mail-core-tests.sh run` 提供专用测试 PostgreSQL）。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p076（2026-11-12 核实：t076 Round 3/4 测试 reviewer minor finding `t076_test_f008`；根因为 LEGACY 夹具由当前 head 反推伪造旧库 + f006 豁免补丁）

### 有意不测

- 无：所有迁移入口分支与夹具形状均有真实 PG 或单元覆盖

### 测试策略

- 后端 PostgreSQL 集成：真实 0030 形状正向升级 + 数据映射、负向 drift 拒绝、离线 CLI 退出码、两个迁移入口的一致性、夹具形状自检。
- 后端单元：`plan_migration` 分类、`_stamp_targets`、既有 baseline/migration 单测回归。
- 门禁：`scripts/run-mail-core-tests.sh run`（含迁移质量门禁 `test_migration_validation` / `test_migrate_to_unified_baseline`）、后端 unit、前端不改动无需重跑前端门禁（仅回归确认）。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：改动 narrow conversion 与离线入口的升级职责，可能影响既有 LEGACY 迁移测试语义；`upgrade head` 在离线入口执行会改变其对落后 revision 的返回码与 alembic_version 结果。
- 回退：本 task 独立分支，以 t076 分支为 base；失败时整体丢弃该分支，t076 交付不受影响。

### 依赖与约束

- 前置依赖：t076（done，未合入主干）；`run-begin` 以 `t076_account_sync_state_and_retry_architecture_refactor` 为 `--base`。
- 遵循开发铁律：零兼容性负担，直接删除豁免补丁与错位的 post-conversion 校验，不保留兼容层。
- 按 TDD 规则：实现让旧测试语义失效时，整体删除/重写旧测试并写明理由，新增覆盖新语义的测试，禁止就地改预期。

### Finalization 时更新的 blueprint

- `docs/specs/mail_sync_and_storage.md`：front matter `tasks` 登记 `t077`。
- `docs/blueprint/conventions.md`：迁移校验约定改为「升级到 head 后全量比对」，删除豁免约定（若 t076 分支文档仍描述旧行为）。
