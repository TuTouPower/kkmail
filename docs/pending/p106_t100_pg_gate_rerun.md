---
pid: "p106"
slug: "t100_pg_gate_rerun"
status: "todo"
---
# p106 t100 真实 PG 门禁复跑（云端无 Docker 未执行）

- 来源：t100 云端执行环境限制（2026-11-29）。执行机无 Docker（daemon 因缺 NET_ADMIN 无法启动），仓库的 PG 测试运行时（`scripts/test_pg_runtime.py` 的 ownership guard）强制要求 Docker 托管的专用测试实例，便携 PG 二进制无法通过该 guard，故下列真实 PG 验证未在云端执行。
- 内容：在具备 Docker 的环境（Mac 本地）对 t100 分支复跑：（1）全量后端 PG 门禁 `scripts/run-mail-core-tests.sh run`（含 Alembic 升级与覆盖率），确认无回归；（2）`tests/mail_core/test_t061_idle_watcher.py` 全部 db_only 用例——候选加载 SQL 排序、首连/重连补偿入队、与 pending/claimed delta 的去重合并、凭据轮换与收件箱失去资格关闭会话、轮询跳过与恢复；（3）`tests/mail_core/test_t090_execution_origin.py` 与 `test_t090_coalescing_and_fencing.py` 的 PG 用例（IDLE 补偿入队 execution_origin=BACKGROUND 断言已按 t100 会话所有权改写驱动）。云端已以 unit 模式跑通全部非 PG 用例（纯策略、真实线程+fake 会话、本地 stub IMAP 协议用例），结果记于 t100 progress.md。
- 处理：未开
