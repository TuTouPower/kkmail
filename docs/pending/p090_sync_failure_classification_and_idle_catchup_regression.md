---
pid: "p090"
slug: "sync_failure_classification_and_idle_catchup_regression"
status: "closed"
resolution: "resolved"
reason: "已在 t088 修复 2 条失败分类回归；idle watcher 2 条转 p091 继续跟踪"
fix_ref: "t088"
---
# p090 t087 合入后 4 条 PG 用例失败：失败分类与 idle 补偿退避

- 现象：t087 合入 main 后，完整 PostgreSQL 套件稳定失败 4 条（`scripts/run-mail-core-tests.sh run --no-cov`）：
    - `test_sync_backend_handler_isolation.py::test_account_failure_kind_is_orthogonal`：`account_failure_kind(result={'status': 'provider_error', 'error': 'OSError code=101'}, is_background=False)` 返回 `NONE`，期望 `TRANSPORT`。
    - `test_sync_background_lineage.py::test_failure_status_classification_is_centralized`：`account_failure_kind(result={'status': 'auth_failed'}, ...)` 返回 `NONE`，期望 `AUTH`。
    - `test_t061_idle_watcher.py::test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling` 与 `ac003`：持续补偿入队失败未进入退避，`idle catch-up delta enqueue failed ... retrying in 0.20s (1/3)` 重复出现。
- 影响：失败分类集中化与空闲监听补偿失败退避的契约未被当前实现满足；完整 PG 门禁无法全绿。与 t088 的 Gmail 标签回填无关，已在 t088 分支与 main 基线分别复现同样 4 条。
- 根因：待查。现象指向 t087 引入的 `account_failure_kind` 分类入口与 idle watcher 重试计数的语义变化；本条仅记录已验证现象与复现方式，不在 t088 越界修生产代码。
- 测试缺口：现有 4 条用例即为契约测试，当前为真实红；需要在修复后重跑并确认分类与退避行为同时成立。
- 线索：`.scratch/t088_full_pg.log`（t088 分支全量 PG 失败明细）；main 基线同命令复现结果；t088 定向 PG 套件 `test_gmail_label_backfill` + `test_migration_validation` 17 passed。
- 处理：t088；resolution=resolved；reason=已在 t088 修复 2 条失败分类回归；其余 2 条 idle watcher 回归转 p091
- 更正（t088）：实际修复的是两条失败分类用例（`auth_failed` 结构化映射、旧自由文本断言按 t087 契约重写）；idle watcher 两条因状态机改动会引发其它用例回归，已撤回并转移到 p091。
