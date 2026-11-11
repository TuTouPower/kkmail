# Task review t072（reviewer_focus: 通用）

- task：`t072_t061_idle_watcher_red_test_repair`
- spec：`docs/tasks/t072_t061_idle_watcher_red_test_repair/spec.md`
- diff_anchor：`20e90ce6154e472239ad71d805f90aea759359a2`
- target：`git -C '<repo_root>' diff 20e90ce6154e472239ad71d805f90aea759359a2`
- round：1
- reviewed_at：2026-10-31T23:00:57+08:00

reviewed_scope: bd77230c16047d8c

## Findings

无。diff 仅改动 `tests/mail_core/test_t061_idle_watcher.py` 与 `task.md` 实施笔记，未触及生产代码；三处修复均保持原有行为断言不变。

## 结论

- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：`_manager()` 改用构造参数创建 frozen `IdleWatcherConfig`，`test_load_candidates_ranks_by_arrival_not_checkpoint` 在 commit 前固化账号 ID，`test_ac006_disabled_account_session_closed`（及同形 paused 用例）改为等待 `fake.closed` 后再断言注册表为空；三条目标失败/竞态均已消除，t061 文件 fresh PostgreSQL 全量 34 passed，无未解决 critical / important。

### AC 复验方式

- AC-001：`re_verified`。以 `scripts/run-mail-core-tests.sh run -k test_t061_idle_watcher`（每次新建 fresh PostgreSQL database 并迁移到 head）运行通过；`test_ac005_quota_limits_sessions` 仍 seed 3 个账号、`quota=2`，断言 held 恰为 inbox 到达时间最新的两个账号（`tests/mail_core/test_t061_idle_watcher.py:443-448`）。
- AC-002：`re_verified`。同一 fresh PG 运行通过；断言仍比较两账号 `inbox_latest_arrival_at` 大小，并用 `select_idle_holders(quota=1)` 断言最新到达账号拿到席位（`tests/mail_core/test_t061_idle_watcher.py:483-494`），未被弱化。
- AC-003：`re_verified`。对 `test_ac006_disabled_account_session_closed` 连续 10 次独立执行 `scripts/run-mail-core-tests.sh run -k test_ac006_disabled_account_session_closed`，每次 fresh PG database，10/10 均为 `1 passed`；断言仍验证禁用后会话 `close()` 已发生（`tests/mail_core/test_t061_idle_watcher.py:516`）。
- AC-004：`re_verified`。同一文件级运行 `34 passed, 1896 deselected`，0 failed（fresh PostgreSQL，alembic upgrade head）。
- coverage = 4/4

verdict: PASS
