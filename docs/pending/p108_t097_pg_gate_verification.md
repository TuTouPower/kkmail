---
pid: "p108"
slug: "t097_pg_gate_verification"
status: "todo"
---
# p108 t097 在 Docker 门禁环境补跑真实 PostgreSQL 全量验证

- 来源：t097 云端实施（2026-11-29）。云端 VM 无 Docker，仓库正式 PG 门禁 `scripts/run-mail-core-tests.sh run` 依赖 Docker 托管的专用测试实例（`scripts/test_pg_runtime.py` 的 `guard_database` 校验容器身份），云端无法以仓库原生路径执行。
- 内容：在具备 Docker 的环境（本地 Mac）补跑正式门禁并据结果处置 t097 的 AC 打勾：`scripts/run-mail-core-tests.sh run -k "test_t097 or test_t095_patrol or test_t096_migration_and_patrol or test_migration_validation"` 及后端全量 PG 套件。云端已完成的等效验证（不替代正式门禁）：用仓库 pin 定 SHA-256 的 theseus-rs PostgreSQL 16.6.0 linux-x64 便携二进制自建一次性集群（127.0.0.1:54399），将 t097 新增 9 个 PG 测试与受影响的 t095/t096 巡检、迁移测试以相同断言实跑通过（t097 9/9、t095 patrol 15/15、t095 readiness + t096 5/6，余 1 例为缺仓库隔离夹具的环境产物且旧代码同环境同样失败；test_migration_validation 新代码 11/13、旧代码同环境 6/13，失败项均为环境产物）；旧实现对同一批 t097 行为测试 7/8 失败（红灯对照成立）。正式门禁通过后关闭本条目，并由 t097 收尾流程据实打勾 AC-001..AC-005。
- 处理：未开
