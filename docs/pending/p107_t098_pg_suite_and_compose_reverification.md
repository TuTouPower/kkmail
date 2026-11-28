---
pid: "p107"
slug: "t098_pg_suite_and_compose_reverification"
status: "todo"
---
# p107 t098 PG 全量套件与双 Compose 配置复验（需 Docker 主机）

- 来源：t098 云端执行遗留（2026-11-29）。t098 的 AC 已由进程入口、模拟 DB 心跳、实际文件操作与 `/ready` 请求在云端 unit 模式全量验证（`tests/mail_core/test_t098_worker_launch_readiness.py` 13 项全过，后端 unit 全量 1775 passed）；但 task 测试策略中的 PG 侧复跑与 Compose 配置检查依赖 Docker，云端 VM 无 Docker 且测试 PG guard（`scripts/test_pg_runtime.py`）强制校验 owned Docker 容器身份，便携 PG 二进制无法合规替代，故未执行。
- 内容：在具备 Docker 的主机上复验：(1) `scripts/run-mail-core-tests.sh run` 全量 PG 套件，重点含 `-k "test_t095 or test_t096 or test_t061_idle_watcher"` 的缓存、监听失效、Watcher/Worker 组合回归与 `test_t095_combined_regression.py` 嵌入式 `/ready` 恢复全链；(2) `docker compose -f docker-compose.embedded.yml config --quiet` 与 `docker compose -f docker-compose.mail-core.yml --profile distributed config --quiet` 双 Compose 配置检查。复验通过后关闭本条目。
- 处理：未开
