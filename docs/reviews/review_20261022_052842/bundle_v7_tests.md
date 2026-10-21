# Intensive Review — 视角7 测试可信与规格对齐 (Testing & Specs)

## 视角摘要

测试断言可信度、假行为判定、环境与时区确定性、门禁覆盖率、Task 规格契约对齐。

## Findings

- [High][96] tests/mail_core/conftest.py:83 — MAIL_CORE_REQUIRE_DB 门禁匹配漏洞导致 DB 测试静默跳过 — `pytest_collection_modifyitems` 仅根据 `if "MAIL_CORE_DATABASE_URL" in reason` 报错；但 `test_auth.py:36`、`test_attachment_access.py:95` 的 skip 原因写为 `reason="database required"`，`test_blob_crypto_gc.py:59` 写为 `reason="PG required"`，均未包含 `MAIL_CORE_DATABASE_URL` 子串。导致即便在强制 DB 的 CI 门禁环境下，上述测试跳过时依然不会触发报错，门禁失效 — 放宽正则或子串匹配检查，凡是检测缺少数据库的跳过一律统一拦截。
- [Medium][98] docs/blueprint/testing.md:18 — 长期真相文档机械锚点 test_cmd 遗漏核心后端测试命令 — `## test_cmd` 章节仅列出了模板契约、前端测试和桌面端测试，完全未包含 `tests/mail_core` 后端测试命令，自动化流水线和开发人员执行日常全量门禁时会直接漏跑全部核心后端测试 — 在 `## test_cmd` 中补充 `pytest tests/mail_core -q`。
- [Low][90] tests/mail_core/test_remote_writeback.py:8 — 测试用例中散落的未使用 import 堆叠 — `test_remote_writeback.py:8` 导入 `pytest`、`test_flag_convergence.py:23` 导入 `reclaim_stale_in_progress`、`test_auth_plan_a_db.py:7,11` 导入 `MagicMock, get_session_epoch`、`test_sync_high_hardening.py:18,25` 导入 `MetadataPage, RemoteOperationResult` 等，均为死 import — 统一清理。
- [Info][100] docs/archive/tasks/t001_mail_core_sent_query/spec.md:29 — t001（mail_core_sent_query）规格契约完全达成 — 经核验：`imap.py` 正确识别 `\Sent` 与中文已发送；`queries.py` 支持 `folder_role="sent"`；`/api/mail/inbox` 参数向后兼容；`schemas/openapi.json` 同步更新；测试覆盖完整无遗漏。
- [Info][100] docs/archive/tasks/t002_frontend_favorites_views/spec.md:29 — t002（frontend_favorites_views）规格契约完全达成 — 经核验：个人收藏已重构为收件箱、未读、已发三折叠树；仅收件箱展示未读角标；支持多路分类视图切换；组件测试与 store 测试覆盖完整无遗漏。
- [Info][100] docs/archive/tasks/t003_reader_toolbar_and_context_menu/spec.md:31 — t003（reader_toolbar_and_context_menu）规格契约完全达成 — 经核验：邮件详情顶部工具栏居中；已读未读双向切换响应；发信按钮置灰禁用；列表右键菜单包含所有动作且删除弹出确认；ESC/外部点击关闭测试通过无遗漏。
