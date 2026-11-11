---
pid: "p071"
slug: "t061_idle_watcher_preexisting_red_tests"
status: "closed"
resolution: "resolved"
reason: "已在 t072 修复并验证"
fix_ref: "t072"
---
# p071 t061 IDLE 测试套件既有红测试与同步竞态

- 现象：在当前 anchor `e4752c24`（t071 开始前）运行 `tests/mail_core/test_t061_idle_watcher.py`，稳定出现 2 个失败：`test_ac005_quota_limits_sessions` 在 `_manager()` 中对 frozen dataclass `IdleWatcherConfig` 执行 `setattr`，抛 `FrozenInstanceError`；`test_load_candidates_ranks_by_arrival_not_checkpoint` 在 commit 后访问已 detach 的 `Account.id`，抛 `DetachedInstanceError`。另有 `test_ac006_disabled_account_session_closed` 在含 t071 改动的全文件重复运行中约 1/8 概率失败：测试等待 `held_account_ids() == set()`，但 `_close_watch` 先 pop `_watches` 再 `join`，空集可在旧会话 `close()` 前被观察到。上述失败在 anchor 与 t071 工作树均存在；t071 的建连补偿入队会放大第三个竞态窗口。
- 影响：t061 IDLE watcher 回归门禁无法全绿，t071 spec 中“既有 t061 配额等回归保持通过”无法完整验证；失败测试与生产 watcher 行为无关，但会掩盖后续真实回归。
- 根因：测试辅助代码与冻结/过期对象语义不匹配（`setattr` 到 frozen dataclass、commit 后使用 detached ORM 实例）；`test_ac006_disabled_account_session_closed` 同步点选在 watch 注册表变化而非会话关闭完成，`_close_watch` 的 pop-then-join 顺序使该窗口可观察。
- 测试缺口：现有断言本身暴露了测试基础设施缺陷，但没有独立 task 覆盖修复；应修 `_manager()` 改用构造参数、避免 commit 后访问 ORM 实例、把禁用账号用例同步点改为等待 `fake.closed` 或线程退出，并在修复后重跑该文件全量。
- 线索：`tests/mail_core/test_t061_idle_watcher.py:345`（`_manager` setattr）、`:478`（detached `Account.id`）、`:515`（`assert fake.closed is True`）；t071 Round 1/2 代码与测试 review 均已记录。
- 处理：t072；resolution=resolved；reason=已在 t072 修复并验证
