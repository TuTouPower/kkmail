# bundle_global_evolution

## Summary

系统当前具备清晰的架构边界与零兼容负担演进意图，但面临四项显著长期演进与维护成本瓶颈：1) Alembic 迁移链 11 天内线性堆叠 30 个版本，大表存在排他锁与 STORED 计算列全表重写风险，downgrade 名存实亡；2) 灾备机制仅支持全停机单事务冷还原，大数据量下 RTO 膨胀且对宿主机资源要求苛刻；3) 单测过度 mock 核心逻辑、E2E 存在恒真断言、生产代码混入 SQLite 适配特判，严重侵蚀重构安全感；4) 归档目录超 600 文件且持续复发 PII 真实邮箱与本地绝对路径泄漏，缺乏前置自动化拦截门禁导致治理成本发散。

## Findings

- [High][95] src/mail_core/db/alembic/versions/ — Alembic 迁移链线性膨胀（0001~0030）与大表同步 DDL 锁升级阻断演进

    - ID: f_evo_alembic_linear_debt_and_lock_risk; verification: static
    - Evidence: 11 天内生成 30 个连续迁移脚本，保留大量早期探索期中间态与补丁逻辑（如 0027 回填数据提取格式错误，0028 立即再跑一次全表扫描修复）；; 20261027_0027 在 messages / message_search 潜在百万级大表上执行同步 ADD COLUMN document tsvector GENERATED ALWAYS AS (...) STORED，触发全表重写并持有 ACCESS EXCLUSIVE 排他锁；; 20261027_0027 执行非 CONCURRENTLY 的 GIN 索引构建（CREATE INDEX ix_message_search_document），在事务内长时间阻塞业务写入；; 20261027_0028 upgrade 直接全表 UPDATE message_search，downgrade 直接声明为 pass；多个版本降级逻辑无法恢复数据，回滚路径事实不可逆。
    - Impact: 生产环境热升级时面临长时间锁阻塞、死锁与事务超时风险；新部署与 CI 测试环境必须完整重放 30 个版本，拉长自举与测试耗时；迁移链膨胀违背零兼容性铁律，增加长期维护与架构演进心智负担。
    - Fix: 执行 Alembic 迁移链 Squash，将 0001~0030 合并为当前权威单一基线 0001_unified_baseline；确立大表 DDL 规范，索引创建强制使用 CONCURRENTLY，CHECK 约束使用 NOT VALID 分步验证；大表数据回填必须从 Alembic 事务中剥离为幂等后台运维任务。

- [Medium][90] src/mail_core/backup/package.py:1868-2007 — 全量冷备与单一事务还原（--single-transaction）随数据膨胀导致 RTO 发散

    - ID: f_evo_disaster_recovery_single_tx_rto_bottleneck; verification: static
    - Evidence: restore_backup_package 强约束服务全停机冷还原，要求目标数据库与目标 Blob 目录绝对为空；; \_run_pg_restore 强制携带 --single-transaction --exit-on-error，将数十万至百万邮件全量数据放入单一 PostgreSQL 事务；; 恢复阶段需完整解密 Blob、校验全量 SHA-256 并双重占用磁盘（tar 包 + staging 目录 + 最终目标目录 + 数据库 dump + WAL 日志）；; 系统未提供 WAL 增量归档（PITR）或差异化备份演进路径。
    - Impact: 随着归档邮件体量增长至数十 GB，恢复时间目标（RTO）将以线性至超线性膨胀，单次还原停机时间过长；单一事务还原对系统资源（WAL、连接超时、内存）要求极高，任一语句异常即导致全量回滚，大库恢复容错脆弱。
    - Fix: 确立分级演进策略：邮件 Blob 原生具备内容寻址与不可变特性，后续演进应支持增量 Blob 同步与外部对象存储挂载；数据库层演进支持物理备份与 WAL 持续归档（PITR），解除对单体单事务快照的单一依赖。

- [High][95] tests/mail_core/test_delta_result_counts.py, tests/e2e/full_stack.spec.ts:182-184 — 单测过度 Mock 与 E2E 恒真断言腐蚀重构信心形成虚假安全网

    - ID: f_evo_test_suite_overmock_and_tautological_assertions; verification: static
    - Evidence: tests/mail_core/test_delta_result_counts.py:10-65 将 assert_fencing, upsert_messages, commit_checkpoint 等底层核心存储与锁逻辑全部 monkeypatch 为 lambda，仅测外层三元表达式；; tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367 (f_tb_fake_assertion_ac008) 声明验证非 PG 方言提交，实际未写入或提交任何 OutboxEvent 实例导致断言完全脱靶；; tests/e2e/full_stack.spec.ts:182-184 (f_tse_tautological_body_visible_assertion) 双页面并发 SSE 同步测试退化为 await expect(page2.locator('body')).toBeVisible() 恒真断言；; src/mail_core/realtime/publication.py:38-42 为适配单测 SQLite 嵌入特判分支（elif dialect == 'sqlite': ... on_conflict_do_nothing()）。
    - Impact: 测试套件（4.8 万行）虽呈现高覆盖率和绿灯状态，但关键并发锁、增量对账及实时推送断言退化，无法拦截真实的集成破坏；生产代码反向受测试方言妥协；团队实施破坏性架构升级时缺乏可靠的安全网，大幅推高重构与维护成本。
    - Fix: 彻底清理生产代码中的 sqlite 特判，单测与集成测试全面对齐真实轻量 PostgreSQL 实例；清理同模块内部关键业务逻辑 monkeypatch，建立真实事务与锁契约测试；修正 E2E 断言，精确定位邮件行已读状态与未读徽标变化，剔除恒真断言与弱化正则。

- [Medium][95] docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3, docs/archive/tasks/t075/review_code.md:6 — 敏感信息（PII 真实邮箱/宿主机路径/口令特征）反复渗入历史归档且缺乏自动化门禁

    - ID: f_evo_archive_governance_pii_and_path_leak_recurrent; verification: static
    - Evidence: docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 曾泄露真实用户个人邮箱（已脱敏为 user@example.com 并勘误） (f_docs_archive_general_p060_pii_leak)；; docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 原残留口令长度特征（已脱敏并勘误）；; docs/archive/tasks/t075/review_code.md:6 及 t061/review_code.md:6 原包含开发者宿主机绝对路径（已脱敏为占位符并勘误）；; 上述问题在第三轮及第四轮 review 中已多次作为 Medium/Critical 指出并局部修复，但在后续新 task 归档中再次反复出现，缺乏自动化 pre-commit 门禁。
    - Impact: 开源公开仓库中持续暴露特定开发者隐私与环境结构，产生合规与钓鱼风险；“归档只追加”原则与脱敏要求频繁冲突，反复消耗工程人力进行全仓正则扫描与人工勘误，长期资产治理成本发散。
    - Fix: 在 .repo_template/hooks/pre-commit 与 CI 检查中植入自动化脱敏门禁，通过正则表达式强制阻断非 RFC 2606 邮箱、密码长度数值描述及本地绝对路径；对历史已泄露文件执行一次性就地脱敏并附加勘误修订声明。

## questions

```json
[
  {
    "id": "q_evo_01_alembic_squash",
    "question": "Alembic 迁移链已达 30 个版本并包含多处修补型与高风险 DDL，是否应基于零兼容性铁律将其压缩（Squash）为单一当前基准（0001_unified_baseline）？",
    "units": [
      "backend_core"
    ],
    "evidence_needed": "确认是否有外部多版本分发或生产兼容约束",
    "counterevidence": "存在生产版本不能直接重置迁移链的不可逆依赖"
  },
  {
    "id": "q_evo_02_disaster_recovery_strategy",
    "question": "面对大数据量下全停机单事务还原（--single-transaction）的 RTO 瓶颈，灾备体系应如何演进？",
    "units": [
      "backend_storage_backup"
    ],
    "evidence_needed": "自托管单机规模下实际 RTO 测试与数据量上限事实",
    "counterevidence": "单机数万封邮件规模下冷备还原耗时小于 30 秒且无运维痛点"
  },
  {
    "id": "q_evo_03_test_dialect_and_fidelity",
    "question": "是否应彻底移除生产代码中的 SQLite 适配分支，将所有后端测试统一至真实 PostgreSQL 环境？",
    "units": [
      "tests_backend",
      "backend_runtime_security"
    ],
    "evidence_needed": "测试代码对 SQLite 转换的依赖程度与生产特判代码位置",
    "counterevidence": "本地开发必须脱离 Docker 运行轻量测试且无法部署单机 PG"
  },
  {
    "id": "q_evo_04_archive_pii_governance",
    "question": "针对已归档文件（docs/archive/）中的真实 PII 邮箱与绝对路径泄露，应如何处理与“只追加不修改”规范的冲突？",
    "units": [
      "docs_archive_general",
      "docs_archive_tasks_b"
    ],
    "evidence_needed": "历史审阅对隐私优先与归档只追加的裁决依据与处理先例",
    "counterevidence": "公开仓库允许长期保留真实个人邮箱与口令特征"
  }
]
```

## question_decisions

```json
{
  "q_evo_01_alembic_squash": {
    "result": "confirmed",
    "reason": "采用 AGENTS.md 零兼容性铁律与 decisions.md 证据，确认系统无外部商业分发与多版本升级包袱。支持选项 A：直接将 0001~0030 Squash 为统一基线 0001_unified_baseline，同步重构测试门禁，根除早期补丁 DDL 的锁升级隐患与测试损耗。",
    "followup_sha256": "efbfbdf56aaf57b0daaed7699a9d067b1b94cd1338293b82b473a9e2fe5bb074"
  },
  "q_evo_02_disaster_recovery_strategy": {
    "result": "confirmed",
    "reason": "采用 decisions.md 单用户/单 Worker 约束及 package.py 状态机证据，确证系统定位于单机单租户（数万封邮件）。单事务冷还原在当前业务规模下完全可接受且具有绝对原子性。采纳选项 A：维持离线全量快照为核心机制，修正原宏观判断对 RTO 瓶颈的过度悲观估计，避免过早引入 PITR/WAL-G 过度设计。",
    "followup_sha256": "2fc0c80a8e8107a9c4f9d4b9e8b1bb00c90958d7655bdceea70961da246beac3"
  },
  "q_evo_03_test_dialect_and_fidelity": {
    "result": "confirmed",
    "reason": "采用 publication.py:38-42 与 sqlite_schema.py 证据，核实生产代码中混入 sqlite 特判分支且测试存在假断言。采纳选项 A：彻底移除 SQLite 兼容分支与测试垫片，测试统一对齐隔离轻量 PostgreSQL 实例，彻底消除测试脱靶与并发锁盲区。",
    "followup_sha256": "20ae44ff5c9378b25f8d5118933fee61dfcced04d510ff1269384bca0b479514"
  },
  "q_evo_04_archive_pii_governance": {
    "result": "confirmed",
    "reason": "采用既往 review_20261027 裁决与 DOCUMENTATION_STANDARD.md 证据，确立隐私脱敏位阶高于 archive 只追加约定。采纳选项 A：对已归档的真实邮箱与绝对路径执行就地最小替换脱敏并追加勘误说明，同时在 pre-commit 中植入正则阻断门禁，彻底解决治理成本发散。",
    "followup_sha256": "0af957c175141e7af7eb91266cac87495906376fa8d2ddddc2c348eccb5537ef"
  }
}
```
