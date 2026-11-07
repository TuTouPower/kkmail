# Cross validation

Reviewer: subagent_independent_validator

- f_arch_patrol_state_in_checkpoint_cursor: agree — 代码明确以注释坦承为避免迁移将巡检状态写入 Checkpoint cursor 字段，证实违背架构至上铁律。
    - Evidence: src/mail_core/sync/patrol.py:8-9; docs/blueprint/architecture.md:113
- f_arch_deprecated_v1_replay_api: agree — 废弃接口 fetch_since 仍存留并专设测试套件保障废弃行为，证实违背零兼容负担铁律。
    - Evidence: src/mail_core/realtime/outbox.py:83-123; tests/mail_core/test_a380_fetch_since_deprecated.py:1-40
- f_arch_secret_write_busy_spin: agree — 并发写密钥文件在捕获 FileExistsError 后执行 while time.monotonic() 忙轮询死等，证实违背拒绝妥协铁律。
    - Evidence: src/mail_core/runtime/bootstrap.py:41-55, 61-76
- f_arch_desktop_startup_toctou_acknowledged_in_test: agree — 端口探测 TOCTOU 竞态未改后端绑定协议，以单测断言注释承认缺陷妥协保留，事实确凿。
    - Evidence: src/desktop/startup.js:190-208; src/desktop/startup.test.js:64-78
- f_docs_archive_general_p060_pii_leak: agree — 确凿泄露真实个人邮箱（现已脱敏为 user@example.com）。
    - Evidence: docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3
- f_evo_alembic_linear_debt_and_lock_risk: agree — 11 天堆叠 30 个迁移，大表同步 DDL 持有 ACCESS EXCLUSIVE 锁且存在回滚不可逆事实。
    - Evidence: src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py:6-15,126-139
- f_evo_test_suite_overmock_and_tautological_assertions: agree — 单测 monkeypatch 底层存储、E2E 双页同步恒真断言 body.toBeVisible()、生产代码混入 SQLite 特判事实确凿。
    - Evidence: tests/mail_core/test_delta_result_counts.py:10-22; tests/e2e/full_stack.spec.ts:177-184; src/mail_core/realtime/publication.py:38-42
