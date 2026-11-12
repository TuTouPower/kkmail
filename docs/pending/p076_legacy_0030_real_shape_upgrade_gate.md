---
pid: "p076"
slug: "legacy_0030_real_shape_upgrade_gate"
status: "closed"
resolution: "resolved"
reason: "已验证闭环：t077 从根因修正 LEGACY 夹具忠实重放 0001 历史 DDL、删除 f006 豁免补丁并把全量校验归位到升级后"
fix_ref: "t077"
---
# p076 补齐 LEGACY 真实 0030 形状（accounts.sync_status）经 narrow conversion 升级到 head 的正向 PG 用例

- 来源：t076 Round 3 测试 reviewer finding `t076_test_f008`（minor，非阻断遗留）
- 内容：现有 LEGACY 夹具（`_create_0030_schema` / `_make_0030_db` / `_pg_build_0030_shape`）均由 head DDL 改 stamp 而成，`accounts` 不含历史 `sync_status` 列；`test_conversion_rejects_drifted_legacy_schema_and_rolls_back` 仅作负向证明。需补一条真实 PG 正向用例：用 `alembic upgrade 20261107_0001` 构造含 `accounts.sync_status`、缺 `folder_patrol_status` 的 0030 形状，stamp `20261031_0030`，经 `python -m mail_core` 的 narrow conversion + `upgrade head` 后断言三列存在、`sync_status` 消失、`folder_patrol_status` 重建、revision 到 `20261112_0002`，并覆盖历史 `sync_status` 值映射。t076 已用 Alembic 结构探针 + 真实 `test_t7`（0001 基线库升级）覆盖主链路，本项补齐 LEGACY 入口的端到端证据。
- 处理：t077；resolution=resolved；reason=已验证闭环：t077 从根因修正 LEGACY 夹具忠实重放 0001 历史 DDL、删除 f006 豁免补丁并把全量校验归位到升级后
