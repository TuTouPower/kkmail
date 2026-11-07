# bundle_local_docs_reviews_historical

## responsibilities

- 维护并留存 kkmail 项目历史多轮集中审阅（intensive-review）的全部过程产物、分析 bundle、机器 finding 及决策报告
- 在 docs/reviews/README.md 中规范会话目录结构、必备文件与历史各轮审阅的布局差异对照
- 为系统缺陷修复、演进历史与回归对比提供权威历史证据

## interfaces

- docs/reviews/README.md：历史审阅会话差异索引与最小布局约定
- review_intensive.md：聚合审阅报告与 finding 全文单一权威
- adoption_decision.md / adoption.md：审阅问题采纳与处置决策书

## dependencies

- 被审代码库的历史 commit 与当时代码快照
- 集中审阅工具链（bundle.py, aggregate.py 等）

## flows

- 审阅阶段产出报告经用户与开发团队裁决后，由 repo-hygiene 从 docs/reviews/ 迁入 docs/archive/reviews/ 永久留存

## constraints

- 历史审阅记录原样封存，原则上不回改历史 finding 内容
- 杜绝新的隐私信息在审阅报告中二次扩散

## decisions

- 承认各轮历史审阅在工具链演进过程中的不同格式形态，统一在 docs/reviews/README.md 表格记录差异，不强制回写历史
- 历史审阅中引用的真实泄漏在报告中全部打码处理（如 [REDACTED_HISTORICAL_LOCATOR]）

## evidence

- docs/reviews/README.md:1-27
- docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5
- docs/reviews/review_20261030_103516/adoption.md:1-36

## uncertainties

- 历史审阅产物中部分未采纳（rejected）的疑点，是否会在后续重构中以不同形式重新出现

## Findings

- [Low][95] docs/reviews/README.md:15-27 — docs/reviews/README.md 差异对照表遗漏 review_20261030_103516

    - ID: f_docs_reviews_readme_missing_session; verification: static
    - Evidence: docs/reviews/README.md:27 只列到 review_20261027_021416; docs/reviews/ 目录下实际存在 review_20261030_103516/adoption.md，未在对照表中登记其布局差异（单文件 adoption.md）
    - Impact: 破坏了 docs/reviews 目录索引的完备性
    - Fix: 在 docs/reviews/README.md 的历史会话表格中补充 review_20261030_103516 的差异说明

- [Medium][95] docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5 — 历史审阅修复执行日志残留宿主机绝对路径

    - ID: f_docs_reviews_execution_log_absolute_path; verification: static
    - Evidence: docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5 原包含开发者宿主机绝对路径（已脱敏为 "$WORKTREES/kkmail_review_integration" 占位并勘误）；同目录下的 repair_plan.md 已在之前轮次修复为占位，但 execution_log.md 遗漏了该项替换
    - Impact: 公开仓库中暴露开发者本地工作区路径和用户名
    - Fix: 将 execution_log.md:5 中的绝对路径替换为 $WORKTREES/kkmail_review_integration 占位符

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_docs"
  }
}
```

## files_reviewed

```json
[
  "docs/archive/reviews/review_20261021_011116/_meta.json",
  "docs/archive/reviews/review_20261021_011116/bundle.json",
  "docs/archive/reviews/review_20261021_011116/bundle_cross_validation.md",
  "docs/archive/reviews/review_20261021_011116/bundle_v1_security_v2_correctness.md",
  "docs/archive/reviews/review_20261021_011116/bundle_v3_contracts_v4_perf.md",
  "docs/archive/reviews/review_20261021_011116/bundle_v5_arch_v6_robust.md",
  "docs/archive/reviews/review_20261021_011116/bundle_v7_tests_v8_docs.md",
  "docs/archive/reviews/review_20261021_011116/bundle_zz_findings_machine.md",
  "docs/archive/reviews/review_20261021_011116/review_intensive.md",
  "docs/archive/reviews/review_20261021_034329/_meta/_meta.json",
  "docs/archive/reviews/review_20261021_034329/_meta/rubric.md",
  "docs/archive/reviews/review_20261021_034329/bundle.json",
  "docs/archive/reviews/review_20261021_034329/bundle_pkg_root.md",
  "docs/archive/reviews/review_20261021_040521/_meta/_meta.json",
  "docs/archive/reviews/review_20261021_040521/bundle.json",
  "docs/archive/reviews/review_20261021_040521/bundle_cross_validation.md",
  "docs/archive/reviews/review_20261021_040521/bundle_parent_followups.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v1_security.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v2_correctness.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v3_contracts.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v4_performance.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v5_architecture.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v6_robustness.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v7_tests.md",
  "docs/archive/reviews/review_20261021_040521/bundle_v8_docs.md",
  "docs/archive/reviews/review_20261021_040521/scope.json",
  "docs/archive/reviews/review_20261021_040521/summary_verification_report.md",
  "docs/archive/reviews/review_20261021_040521/validation_read_only.md",
  "docs/archive/reviews/review_20261021_064335/review_da57df7_findings_and_decisions.md",
  "docs/archive/reviews/review_20261022_052842/adoption_decision.md",
  "docs/archive/reviews/review_20261022_052842/bundle.json",
  "docs/archive/reviews/review_20261022_052842/bundle_cross_validation.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v1_security.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v2_correctness.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v3_contracts.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v4_performance.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v5_architecture.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v6_robustness.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v7_tests.md",
  "docs/archive/reviews/review_20261022_052842/bundle_v8_docs.md",
  "docs/archive/reviews/review_20261022_052842/review_intensive.md",
  "docs/archive/reviews/review_20261022_071448/adoption_decision.md",
  "docs/archive/reviews/review_20261022_071448/bundle.json",
  "docs/archive/reviews/review_20261022_071448/bundle_cross_validation.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_._a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_._b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.claude.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.opencode_commands_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.opencode_commands_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_docs.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_docs_review_prompts.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_docs_task_template.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_hooks.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_repo_task_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_repo_task_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_repo_task_c.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_scripts_repo_task_view_static.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_bug-to-pending.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_pending-record.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_repo-cleanup.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_repo-hygiene.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_repo-template-sync-core.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_repo-template-sync.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-create.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-from-pending.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-integrate.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-merge.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-preflight.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-run.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-schedule.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_task-work.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_skills_template-issue-report.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_tests_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_tests_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_tests_c.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_tests_d.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_.repo_template_tests_fixtures.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_assets.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_config.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive_legacy_architecture.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive_pending.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive_tasks_t001_mail_core_sent_query.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive_tasks_t002_frontend_favorites_views.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_archive_tasks_t003_reader_toolbar_and_context_menu.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_blueprint.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_guides.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_pending_todo.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_011116_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_011116_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_034329.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_034329__meta.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_040521__meta.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_040521_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_040521_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261021_064335.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261022_052842_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_reviews_review_20261022_052842_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_skills_kkmail.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_skills_kkmail_scripts.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_specs.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_docs_tasks_t004_fix_accounts_dto_and_sidebar_error.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_schemas.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_scripts_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_scripts_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_desktop_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_desktop_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_desktop_scripts.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_public.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_scripts.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_api_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_api_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_api_generated.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_components_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_components_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_design-system.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_hooks.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_lib_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_lib_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_lib_c.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_lib_d.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_store.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_test.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_frontend_src_types.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_accounts.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_api.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_backup.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_blobs.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_db.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_db_alembic.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_db_alembic_versions_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_db_alembic_versions_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_mail.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_mail_application.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_mail_domain.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_mail_storage.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_providers_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_providers_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_providers_parsing.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_realtime.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_runtime.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_search.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_security.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_sync_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_sync_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_threading.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_src_mail_core_worker.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_e2e.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_a.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_b.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_c.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_d.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_e.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_f.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_fixtures.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_fixtures_dovecot.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_fixtures_maildir_alice_Maildir_new.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_g.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_h.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_mail_core_i.md",
  "docs/archive/reviews/review_20261022_071448/bundle_dir_tests_scripts.md",
  "docs/archive/reviews/review_20261022_071448/review_intensive.md",
  "docs/archive/reviews/review_20261025_020805/adoption_decision.md",
  "docs/archive/reviews/review_20261025_020805/bundle_cross_validation.md",
  "docs/archive/reviews/review_20261025_020805/bundle_desktop_scripts.md",
  "docs/archive/reviews/review_20261025_020805/bundle_docs_archive.md",
  "docs/archive/reviews/review_20261025_020805/bundle_docs_live.md",
  "docs/archive/reviews/review_20261025_020805/bundle_docs_reviews.md",
  "docs/archive/reviews/review_20261025_020805/bundle_frontend_state.md",
  "docs/archive/reviews/review_20261025_020805/bundle_frontend_ui.md",
  "docs/archive/reviews/review_20261025_020805/bundle_mc_api_app.md",
  "docs/archive/reviews/review_20261025_020805/bundle_mc_data_crypto.md",
  "docs/archive/reviews/review_20261025_020805/bundle_mc_providers_sync.md",
  "docs/archive/reviews/review_20261025_020805/bundle_privacy_history.md",
  "docs/archive/reviews/review_20261025_020805/bundle_regression.md",
  "docs/archive/reviews/review_20261025_020805/bundle_regression_addendum.md",
  "docs/archive/reviews/review_20261025_020805/bundle_repo_tooling.md",
  "docs/archive/reviews/review_20261025_020805/bundle_root_ci.md",
  "docs/archive/reviews/review_20261025_020805/review_intensive.md",
  "docs/archive/reviews/review_20261025_020805/review_summary.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/repair_plan.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/repair_results.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/review_evidence.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/review_report.md",
  "docs/archive/reviews/review_20261026_005019_full_repository/technical_design.md",
  "docs/archive/reviews/review_20261026_180800_current_repository/review_report.md",
  "docs/archive/reviews/review_20261026_commits/repair_design.md",
  "docs/archive/reviews/review_20261026_commits/review_report.md",
  "docs/reviews/README.md",
  "docs/reviews/review_20261027_021416/adoption_decision.md",
  "docs/reviews/review_20261027_021416/bundle_cross_validation.md",
  "docs/reviews/review_20261027_021416/bundle_cross_validation_regression.md",
  "docs/reviews/review_20261027_021416/bundle_unit01.md",
  "docs/reviews/review_20261027_021416/bundle_unit02.md",
  "docs/reviews/review_20261027_021416/bundle_unit03.md",
  "docs/reviews/review_20261027_021416/bundle_unit04.md",
  "docs/reviews/review_20261027_021416/bundle_unit05.md",
  "docs/reviews/review_20261027_021416/bundle_unit06.md",
  "docs/reviews/review_20261027_021416/bundle_unit07.md",
  "docs/reviews/review_20261027_021416/bundle_unit08.md",
  "docs/reviews/review_20261027_021416/bundle_unit09.md",
  "docs/reviews/review_20261027_021416/bundle_unit10.md",
  "docs/reviews/review_20261027_021416/bundle_unit11.md",
  "docs/reviews/review_20261027_021416/bundle_unit12.md",
  "docs/reviews/review_20261027_021416/bundle_unit13.md",
  "docs/reviews/review_20261027_021416/regression.md",
  "docs/reviews/review_20261027_021416/review_intensive.md",
  "docs/reviews/review_20261027_021416/review_summary.md",
  "docs/reviews/review_20261027_021416/validation.md",
  "docs/reviews/review_20261030_103516/adoption.md"
]
```
