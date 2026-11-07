# bundle_local_tests_backend

## responsibilities

- 验证 mail_core 后端服务的业务逻辑、协议解析、数据存储与运行时健壮性
- 通过 runtime_isolation 机制确保各测试用例间数据库提交、连接池、后台线程与单例状态的完全隔离
- 提供 Dovecot 与 Maildir 测试夹具与合成测试数据支撑 L2 集成测试

## interfaces

- pytest fixtures: api_client, auth_headers, \_isolated_backend_runtime
- tests.mail_core.runtime_isolation: isolated_runtime(monkeypatch, tmp_path, session)
- tests.mail_core.sqlite_schema: sqlite_table_ddl(table: Table) -> str
- tests.mail_core.mailbox_factory: build_mailbox(session, blob_root, seed)

## dependencies

- pytest, fastapi.testclient.TestClient, sqlalchemy, psycopg, alembic
- mail_core production modules (api, sync, db, worker, realtime, providers, blobs, security)

## flows

- pytest 启动 -> pytest_configure 校验专用测试数据库安全哨兵 -> 每个用例执行前 isolated_runtime 清理数据库 (TRUNCATE) 并重置全局单例 -> 执行测试逻辑 -> 夹具清理连接池与未关闭线程
- L2 IMAP 集成测试 -> 启动本地 Dovecot 容器/Pymap -> 连接 1143 端口 -> 执行登录、拉取、同步与 UIDVALIDITY 校验

## constraints

- 严禁在非测试数据库上运行测试（guard_database 强制拦截）
- CI 模式下 MAIL_CORE_REQUIRE_DB=1 时禁止静默跳过 PG 测试
- 禁止就地修改旧测试预期迎合实现输出（TDD 铁律）

## decisions

- 采用集中式 isolated_runtime 针对每个测试进行物理表 TRUNCATE 与进程内单例重置，避免测试污染
- 对快速单测使用 SQLite 内存库，对集成测试使用专属 PostgreSQL 实例

## evidence

- tests/mail_core/conftest.py:50-95
- tests/mail_core/runtime_isolation.py:13-32
- tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367
- tests/mail_core/test_delta_result_counts.py:10-65
- tests/mail_core/sqlite_schema.py:1-20
- src/mail_core/realtime/publication.py:38-42

## uncertainties

## Findings

- [Medium][95] tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367 — test_ac008 缺少对 OutboxEvent 或 WorkerJob 的提交操作致断言脱靶

    - ID: f_tb_fake_assertion_ac008; verification: static
    - Evidence: 测试 docstring 声明：AC-008: Non-PostgreSQL dialect sessions commit OutboxEvent / WorkerJob without error.; 实际代码仅创建 dummy 表并插入单行：session.execute(text("CREATE TABLE dummy (id INT)"))，未向 session 添加或修改任何 OutboxEvent / WorkerJob 实例; src/mail_core/db/events.py:101-118 中的 \_on_before_flush 仅在检测到 session.new 或 session.dirty 中包含对应实例时才触发唤醒标记，当前测试无法检验该逻辑在 SQLite 下的行为
    - Impact: 测试沦为无意义空操作，未能实际验证非 PG 方言下提交 OutboxEvent 与 WorkerJob 时事件拦截器与唤醒标记的容错与兼容性
    - Fix: 在测试用例中向 SQLite 会话中添加并提交真实的 OutboxEvent 与 WorkerJob 实例，验证 session.commit() 成功且不触发 notify 错误

- [Medium][90] tests/mail_core/test_delta_result_counts.py:10-65 — apply_delta_page 单测过度 mock 内部实现掏空被测逻辑

    - ID: f_tb_overmock_delta_result_counts; verification: static
    - Evidence: 测试对同模块内部的 assert_fencing, upsert_messages, upsert_message_search, \_apply_flag_patches, messages_upserted_event, recompute_folder_stats, commit_checkpoint 全部 monkeypatch 打桩为 lambda 空操作; 数据库 Session 被替换为手写的虚拟类 Session，内部 scalars 返回空列表、scalar 返回 None
    - Impact: 被测函数 apply_delta_page 内部与数据库事务、锁状态检验及核心存储逻辑完全隔离，测试仅对外层计数三元表达式生效，无法捕获真实的集成契约违约
    - Fix: 减少对内部被测业务函数的 mock，改用基于内存数据库或专用测试 DB 的真实 apply_delta_page 契约测试

- [Low][90] tests/mail_core/sqlite_schema.py:1-20 — 为适配单测引入 SQLite 导致生产代码混入非生产方言分支

    - ID: f_tb_sqlite_production_leak; verification: static
    - Evidence: sqlite_schema.py 通过正则替换将 JSONB 与 ::jsonb 转换为 SQLite 格式以供内存单测运行; src/mail_core/realtime/publication.py:38-42 中存在专为 SQLite 单测妥协的生产代码：elif dialect == "sqlite": ... on_conflict_do_nothing()，并标注 # pragma: no cover - production is PostgreSQL, tests SQLite
    - Impact: 生产代码被测试基础设施反向污染，且 SQLite 缺乏 PostgreSQL 的行级排他锁 (with_for_update) 与 LISTEN/NOTIFY 真实语义，易产生测试通过但生产并发失效的隐患
    - Fix: 逐步将依赖 SQLite DDL 垫片的单测迁移至基于真实 PostgreSQL 测试实例的容器/本地测试环境，清理生产代码中的 sqlite 特判

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_tests"
  }
}
```

## files_reviewed

```json
[
  "tests/mail_core/conftest.py",
  "tests/mail_core/fixtures/README.md",
  "tests/mail_core/fixtures/dovecot/10-auth.conf",
  "tests/mail_core/fixtures/dovecot/10-mail.conf",
  "tests/mail_core/fixtures/dovecot/10-master.conf",
  "tests/mail_core/fixtures/dovecot/Dockerfile",
  "tests/mail_core/fixtures/dovecot/seed.eml",
  "tests/mail_core/fixtures/dovecot/users",
  "tests/mail_core/fixtures/maildir/alice/Maildir/new/1792515417.kkmail.local",
  "tests/mail_core/mailbox_factory.py",
  "tests/mail_core/runtime_isolation.py",
  "tests/mail_core/sqlite_schema.py",
  "tests/mail_core/test_a104_pool_kwargs.py",
  "tests/mail_core/test_a11_trash_provider_default.py",
  "tests/mail_core/test_a248_imap_dict_password.py",
  "tests/mail_core/test_a252_bcrypt_hash_whitespace.py",
  "tests/mail_core/test_a273_imap_host_port_validation.py",
  "tests/mail_core/test_a274_timeout_cache_graph.py",
  "tests/mail_core/test_a275_worker_stop_event.py",
  "tests/mail_core/test_a286_unknown_archive_state.py",
  "tests/mail_core/test_a288_rewrap_remaining_count.py",
  "tests/mail_core/test_a294_healthcheck_env.py",
  "tests/mail_core/test_a295_heartbeat_bad_rows.py",
  "tests/mail_core/test_a296_heartbeat_loop_idempotent.py",
  "tests/mail_core/test_a297_heartbeat_lock_scope.py",
  "tests/mail_core/test_a318_rewrap_file_hardening.py",
  "tests/mail_core/test_a319_metadata_completion_dedupe.py",
  "tests/mail_core/test_a320_folder_pause_revival.py",
  "tests/mail_core/test_a321_gmail_virtual_exact.py",
  "tests/mail_core/test_a322_live_generations_payload.py",
  "tests/mail_core/test_a327_listener_join_timeout.py",
  "tests/mail_core/test_a346_system_metrics.py",
  "tests/mail_core/test_a349_heartbeat_expiry.py",
  "tests/mail_core/test_a350_toctou_disclosure.py",
  "tests/mail_core/test_a351_prune_null_published_at.py",
  "tests/mail_core/test_a352_publication_state_race.py",
  "tests/mail_core/test_a380_fetch_since_deprecated.py",
  "tests/mail_core/test_a45_sse_events_coverage.py",
  "tests/mail_core/test_a68_reclaim_isolation.py",
  "tests/mail_core/test_a82_rewrap_result_semantics.py",
  "tests/mail_core/test_a83_backup_keyring_conflict.py",
  "tests/mail_core/test_a85_apply_lease_release.py",
  "tests/mail_core/test_account_credentials_unit.py",
  "tests/mail_core/test_account_email_normalization.py",
  "tests/mail_core/test_account_folder_navigation.py",
  "tests/mail_core/test_account_update_lock_order.py",
  "tests/mail_core/test_accounts_api_pg.py",
  "tests/mail_core/test_accounts_api_unit.py",
  "tests/mail_core/test_accounts_app_groups.py",
  "tests/mail_core/test_accounts_create_group_check.py",
  "tests/mail_core/test_accounts_list_count_once.py",
  "tests/mail_core/test_accounts_remote_ops.py",
  "tests/mail_core/test_accounts_run_in_session_a247.py",
  "tests/mail_core/test_accounts_sidebar_layout_queries.py",
  "tests/mail_core/test_accounts_sync_status_deadcode.py",
  "tests/mail_core/test_adoptions_patch.py",
  "tests/mail_core/test_api_a284_security_headers.py",
  "tests/mail_core/test_api_a313_cors.py",
  "tests/mail_core/test_api_health.py",
  "tests/mail_core/test_api_request_bounds.py",
  "tests/mail_core/test_api_search_validation.py",
  "tests/mail_core/test_application_exports.py",
  "tests/mail_core/test_archive_adoption_p15.py",
  "tests/mail_core/test_archive_claim_ownership.py",
  "tests/mail_core/test_archive_decode_failure.py",
  "tests/mail_core/test_archive_mime_parser.py",
  "tests/mail_core/test_archive_scheduler.py",
  "tests/mail_core/test_archive_state_machine.py",
  "tests/mail_core/test_assert_fencing_lock.py",
  "tests/mail_core/test_attachment_access.py",
  "tests/mail_core/test_attachment_content_type_api.py",
  "tests/mail_core/test_auth.py",
  "tests/mail_core/test_auth_change_password_a105.py",
  "tests/mail_core/test_auth_epoch_concurrency.py",
  "tests/mail_core/test_auth_migration_0013.py",
  "tests/mail_core/test_auth_password_limits.py",
  "tests/mail_core/test_auth_plan_a_db.py",
  "tests/mail_core/test_auth_r4adopt_p16.py",
  "tests/mail_core/test_backend_isolation.py",
  "tests/mail_core/test_backup_container_permissions.py",
  "tests/mail_core/test_backup_crypto.py",
  "tests/mail_core/test_backup_export.py",
  "tests/mail_core/test_backup_manifest_redaction_a272.py",
  "tests/mail_core/test_backup_package.py",
  "tests/mail_core/test_backup_pg_timeout_a316.py",
  "tests/mail_core/test_backup_r4adopt_p10.py",
  "tests/mail_core/test_backup_restore_cross_volume.py",
  "tests/mail_core/test_backup_restore_drill_live.py",
  "tests/mail_core/test_backup_verify_drill.py",
  "tests/mail_core/test_benchmark_mailbox.py",
  "tests/mail_core/test_blob_archive_fixes.py",
  "tests/mail_core/test_blob_crypto_gc.py",
  "tests/mail_core/test_blob_crypto_streaming_a110.py",
  "tests/mail_core/test_blob_keyring_required.py",
  "tests/mail_core/test_blob_permissions.py",
  "tests/mail_core/test_blob_put_hardening_a138.py",
  "tests/mail_core/test_blob_rewrap.py",
  "tests/mail_core/test_blob_store.py",
  "tests/mail_core/test_blob_verified_stream_a81.py",
  "tests/mail_core/test_body_preview_query.py",
  "tests/mail_core/test_chaos_lease_recovery.py",
  "tests/mail_core/test_check_constraints_a168.py",
  "tests/mail_core/test_checkpoint_generation_query_r4adopt_p29.py",
  "tests/mail_core/test_config.py",
  "tests/mail_core/test_connection_whitelist_a165.py",
  "tests/mail_core/test_credential_store_db.py",
  "tests/mail_core/test_credentials_corrupt_r4adopt_p29.py",
  "tests/mail_core/test_credentials_r4adopt_p29.py",
  "tests/mail_core/test_csrf_safe_methods.py",
  "tests/mail_core/test_delta_archive_integration.py",
  "tests/mail_core/test_delta_change_kind_a366.py",
  "tests/mail_core/test_delta_cursor_invalid_request_feedback.py",
  "tests/mail_core/test_delta_fencing_followup_a147.py",
  "tests/mail_core/test_delta_flag_fallback.py",
  "tests/mail_core/test_delta_flag_patch.py",
  "tests/mail_core/test_delta_merge_unknown_a172.py",
  "tests/mail_core/test_delta_result_counts.py",
  "tests/mail_core/test_device_oauth_poll_locking.py",
  "tests/mail_core/test_dispatcher_cross_loop_ack.py",
  "tests/mail_core/test_dispatcher_dispatch_drain.py",
  "tests/mail_core/test_dispatcher_nonblocking.py",
  "tests/mail_core/test_dispatcher_singleton.py",
  "tests/mail_core/test_dispatcher_subs_cleanup.py",
  "tests/mail_core/test_domain_models_a202.py",
  "tests/mail_core/test_domain_sync_statuses.py",
  "tests/mail_core/test_flag_convergence.py",
  "tests/mail_core/test_folder_role_inbox_api.py",
  "tests/mail_core/test_folder_stats_race.py",
  "tests/mail_core/test_folder_stats_retry_a167.py",
  "tests/mail_core/test_fts_inbox_api.py",
  "tests/mail_core/test_global_stats.py",
  "tests/mail_core/test_gmail_graph_contracts.py",
  "tests/mail_core/test_gmail_sync_strategy_and_timeout.py",
  "tests/mail_core/test_graph_a289_well_known_errors.py",
  "tests/mail_core/test_graph_a290_page_item_limit.py",
  "tests/mail_core/test_graph_a367_cursor_mapping.py",
  "tests/mail_core/test_graph_a369_remote_operation_nondict.py",
  "tests/mail_core/test_graph_folder_roles.py",
  "tests/mail_core/test_high_blobs_providers_metadata.py",
  "tests/mail_core/test_host_security_a171.py",
  "tests/mail_core/test_http_headers.py",
  "tests/mail_core/test_http_retry_after_r4adopt_p29.py",
  "tests/mail_core/test_http_transport_r4adopt_p29.py",
  "tests/mail_core/test_imap_connect_socket_cleanup.py",
  "tests/mail_core/test_imap_delta_flag_sweep.py",
  "tests/mail_core/test_imap_flag_sweep_fetch_failure.py",
  "tests/mail_core/test_imap_folder_mismatch_rejection.py",
  "tests/mail_core/test_imap_header_decode.py",
  "tests/mail_core/test_imap_id_handshake.py",
  "tests/mail_core/test_imap_list_escaped_names.py",
  "tests/mail_core/test_imap_metadata_page_size_bounds.py",
  "tests/mail_core/test_imap_metadata_scan_cache_start.py",
  "tests/mail_core/test_imap_noselect_and_transient_retry.py",
  "tests/mail_core/test_imap_plaintext_policy.py",
  "tests/mail_core/test_imap_protocol_suite.py",
  "tests/mail_core/test_imap_provider_live.py",
  "tests/mail_core/test_imap_reconcile_uidvalidity.py",
  "tests/mail_core/test_imap_remote_id.py",
  "tests/mail_core/test_imap_search_uids_multichunk.py",
  "tests/mail_core/test_imap_store_move_missing_uid.py",
  "tests/mail_core/test_imap_sync_loop.py",
  "tests/mail_core/test_imap_uidvalidity_metadata_abort.py",
  "tests/mail_core/test_imap_unknown_flags.py",
  "tests/mail_core/test_inbox_stats_dead_branch_a218.py",
  "tests/mail_core/test_inline_preview_signed_url.py",
  "tests/mail_core/test_job_successor_atomicity.py",
  "tests/mail_core/test_jobs_backoff.py",
  "tests/mail_core/test_keyset_pagination.py",
  "tests/mail_core/test_legacy_migration.py",
  "tests/mail_core/test_listener_dsn.py",
  "tests/mail_core/test_logging_configure_handlers_a164.py",
  "tests/mail_core/test_logging_trace_and_redact.py",
  "tests/mail_core/test_mailbox_performance_baseline.py",
  "tests/mail_core/test_main_module_r4adopt_p29.py",
  "tests/mail_core/test_main_port_r4adopt_p29.py",
  "tests/mail_core/test_main_proxy_headers.py",
  "tests/mail_core/test_mark_all_read_limits_a180.py",
  "tests/mail_core/test_mark_all_read_scope.py",
  "tests/mail_core/test_mark_read_convergence_suite.py",
  "tests/mail_core/test_medium_hardening.py",
  "tests/mail_core/test_medium_providers_sync_blobs.py",
  "tests/mail_core/test_message_detail_api.py",
  "tests/mail_core/test_message_detail_attachment_order_a317.py",
  "tests/mail_core/test_message_detail_readonly.py",
  "tests/mail_core/test_message_mutations_api.py",
  "tests/mail_core/test_messages_by_ids_folder_a287.py",
  "tests/mail_core/test_metadata_apply.py",
  "tests/mail_core/test_metadata_duplicate_remote_id_a146.py",
  "tests/mail_core/test_microsoft_oauth.py",
  "tests/mail_core/test_microsoft_redirect_exchange.py",
  "tests/mail_core/test_migration_0027_backfill_a315.py",
  "tests/mail_core/test_migration_0027_guard_batch_a25.py",
  "tests/mail_core/test_migration_0028_guard.py",
  "tests/mail_core/test_migration_script_safety.py",
  "tests/mail_core/test_migration_validation.py",
  "tests/mail_core/test_notify_warning.py",
  "tests/mail_core/test_oauth_allowlist.py",
  "tests/mail_core/test_oauth_callback_csp.py",
  "tests/mail_core/test_oauth_flow_locking.py",
  "tests/mail_core/test_oauth_origin_validation.py",
  "tests/mail_core/test_oauth_r4adopt.py",
  "tests/mail_core/test_oauth_transport.py",
  "tests/mail_core/test_on_demand_body_sync.py",
  "tests/mail_core/test_openapi_contract.py",
  "tests/mail_core/test_outbox_listen.py",
  "tests/mail_core/test_outbox_publication_order.py",
  "tests/mail_core/test_outbox_retention.py",
  "tests/mail_core/test_outbox_retention_unit.py",
  "tests/mail_core/test_outbox_wake_notify_only.py",
  "tests/mail_core/test_partial_metadata_fidelity.py",
  "tests/mail_core/test_primary_location.py",
  "tests/mail_core/test_provider_account_forms.py",
  "tests/mail_core/test_provider_accounts_pg.py",
  "tests/mail_core/test_provider_connection_budget_integration.py",
  "tests/mail_core/test_provider_connection_slots.py",
  "tests/mail_core/test_provider_stub.py",
  "tests/mail_core/test_quota_reserve_a108.py",
  "tests/mail_core/test_r4adopt_p23_api.py",
  "tests/mail_core/test_r4adopt_p23_gc.py",
  "tests/mail_core/test_r4adopt_p28_a112.py",
  "tests/mail_core/test_r4adopt_p28_a113.py",
  "tests/mail_core/test_r4adopt_p28_a143.py",
  "tests/mail_core/test_r4adopt_p28_a148.py",
  "tests/mail_core/test_r4adopt_p28_a162.py",
  "tests/mail_core/test_r4adopt_p28_a179.py",
  "tests/mail_core/test_r4adopt_p28_a347.py",
  "tests/mail_core/test_r4adopt_p28_a84.py",
  "tests/mail_core/test_ratelimit_capacity.py",
  "tests/mail_core/test_ratelimit_config_a7.py",
  "tests/mail_core/test_ratelimit_eviction_a89.py",
  "tests/mail_core/test_readme_layout_a233.py",
  "tests/mail_core/test_reconcile_delete_batch.py",
  "tests/mail_core/test_redact_and_poll.py",
  "tests/mail_core/test_redact_auth_headers_a120.py",
  "tests/mail_core/test_redacting_filter_exc_a326.py",
  "tests/mail_core/test_remote_image_proxy.py",
  "tests/mail_core/test_remote_images_allowlists.py",
  "tests/mail_core/test_remote_images_api.py",
  "tests/mail_core/test_remote_ops_coalesce_entity.py",
  "tests/mail_core/test_remote_ops_coalesce_scoping.py",
  "tests/mail_core/test_remote_ops_reconcile.py",
  "tests/mail_core/test_remote_ops_redact.py",
  "tests/mail_core/test_remote_push_capacity_attempts_a30.py",
  "tests/mail_core/test_remote_push_capacity_coalesced.py",
  "tests/mail_core/test_remote_push_imap_trash_a17.py",
  "tests/mail_core/test_remote_push_robustness.py",
  "tests/mail_core/test_remote_state_writeback.py",
  "tests/mail_core/test_remote_writeback.py",
  "tests/mail_core/test_rotate_credential_locking.py",
  "tests/mail_core/test_runtime_bootstrap.py",
  "tests/mail_core/test_safe_error_converge_a325.py",
  "tests/mail_core/test_schema_pg.py",
  "tests/mail_core/test_search_cc_recipients.py",
  "tests/mail_core/test_search_docstring.py",
  "tests/mail_core/test_search_like_escape.py",
  "tests/mail_core/test_search_migration_recipient_text.py",
  "tests/mail_core/test_search_pagination.py",
  "tests/mail_core/test_search_pagination_validation_a115.py",
  "tests/mail_core/test_search_query_limit.py",
  "tests/mail_core/test_search_recipients.py",
  "tests/mail_core/test_select_display_body.py",
  "tests/mail_core/test_session_engine_thread_safety.py",
  "tests/mail_core/test_settings_store.py",
  "tests/mail_core/test_sidebar_group_scope.py",
  "tests/mail_core/test_spa_fallback.py",
  "tests/mail_core/test_sse_epoch_precheck_a271.py",
  "tests/mail_core/test_sse_keepalive_floor_a379.py",
  "tests/mail_core/test_sse_max_connections_a244.py",
  "tests/mail_core/test_sse_medium_remaining.py",
  "tests/mail_core/test_sse_outbox.py",
  "tests/mail_core/test_sse_session_revocation.py",
  "tests/mail_core/test_storage_exports.py",
  "tests/mail_core/test_stub_memory_provider.py",
  "tests/mail_core/test_sync_checkpoint_generation_order.py",
  "tests/mail_core/test_sync_delta.py",
  "tests/mail_core/test_sync_engine_failure_unit.py",
  "tests/mail_core/test_sync_execution_lock_order.py",
  "tests/mail_core/test_sync_execution_migration.py",
  "tests/mail_core/test_sync_execution_tracking.py",
  "tests/mail_core/test_sync_execution_unit.py",
  "tests/mail_core/test_sync_full_scan_metadata_reuse.py",
  "tests/mail_core/test_sync_hardening_a27_a28_a29.py",
  "tests/mail_core/test_sync_high_hardening.py",
  "tests/mail_core/test_sync_inbox_first.py",
  "tests/mail_core/test_sync_lease_datetime.py",
  "tests/mail_core/test_sync_leases_jobs.py",
  "tests/mail_core/test_sync_lock_order_unified.py",
  "tests/mail_core/test_sync_mode_policy.py",
  "tests/mail_core/test_sync_orphan_patrol_live_generations.py",
  "tests/mail_core/test_sync_orphan_patrol_stale_snapshot.py",
  "tests/mail_core/test_sync_requests.py",
  "tests/mail_core/test_sync_requests_paused_folder.py",
  "tests/mail_core/test_sync_requests_scope_exact.py",
  "tests/mail_core/test_sync_requests_unit.py",
  "tests/mail_core/test_sync_retry_queue.py",
  "tests/mail_core/test_sync_settlement_target_prelock.py",
  "tests/mail_core/test_sync_shared_full_scan.py",
  "tests/mail_core/test_sync_successor_binding_backfill.py",
  "tests/mail_core/test_system_health.py",
  "tests/mail_core/test_t061_config.py",
  "tests/mail_core/test_t061_graph_probe.py",
  "tests/mail_core/test_t061_idle_watcher.py",
  "tests/mail_core/test_t061_imap_idle_probe.py",
  "tests/mail_core/test_t061_memory_probe.py",
  "tests/mail_core/test_t061_status_patrol.py",
  "tests/mail_core/test_t062_outbox_and_job_notify_wake.py",
  "tests/mail_core/test_t063_worker_concurrent_executor.py",
  "tests/mail_core/test_t064_batched_remote_writeback.py",
  "tests/mail_core/test_threading.py",
  "tests/mail_core/test_threading_extract_ids_mixed.py",
  "tests/mail_core/test_threading_provider_key_backfill.py",
  "tests/mail_core/test_threading_subject_norm_truncation.py",
  "tests/mail_core/test_threading_subject_prefix_variants.py",
  "tests/mail_core/test_uidvalidity_rebuild.py",
  "tests/mail_core/test_unknown_mail_status.py",
  "tests/mail_core/test_worker_capacity_retry_after_a18.py",
  "tests/mail_core/test_worker_invalid_payload.py",
  "tests/mail_core/test_worker_loop.py",
  "tests/mail_core/test_worker_payload_gc_backup_a253.py",
  "tests/mail_core/test_worker_process_recovery.py",
  "tests/mail_core/test_worker_scheduler.py"
]
```
