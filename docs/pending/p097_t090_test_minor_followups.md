---
pid: "p097"
slug: "t090_test_minor_followups"
status: "todo"
---
# p097 t090 测试次要收口：engine/remote_push 后台覆盖与入口枚举值断言

- 来源：t090 遗留（Round 1 `review_test.md` 2 条非阻断 `minor`：`t090_test_f001`、`t090_test_f002`）
- 内容：
    1. `t090_test_f001`：在 `tests/mail_core/test_t090_execution_origin.py` 补充 `execution_origin="background"` 下 `sync_folder_metadata`（`LeaseBusy` / `RateLimitedError` / `CAPACITY_ERRORS` / `CursorInvalidError` 重建 / `exhausted=False` / `full and request_id`）、`sync_account_folders`（`CAPACITY_ERRORS` / `RateLimitedError`）以及 `push_remote_operations` 重试/分批续跑的血缘继承覆盖。
    2. `t090_test_f002`：改用公开 `push_remote_operations` 移动回写场景驱动未知目标目录发现兜底（替代直接调用 `_persist_move_remote_state`），并在 `create_account_app` / `sync_account_app` / `oauth_routes._enqueue_sync_best_effort` / `archive.resume_quota_paused_archives` 测试补充显式 `execution_origin` 枚举值断言。
        以上均不阻断 `t090` 核心行为 AC，已在 Round 1 PASS 后转入待办统一收口。
- 处理：未开
