# 审阅结果决策

## 目录

docs/reviews/review_20261107_142548

## 报告来源

- 已读：以下 27 份根目录报告（26 份 bundle 与 1 份聚合），全部通读；未进入任何子目录。
    - `bundle_cross_validation.md`
    - `bundle_followup_q_evo_01_alembic_squash.md`
    - `bundle_followup_q_evo_02_disaster_recovery_strategy.md`
    - `bundle_followup_q_evo_03_test_dialect_and_fidelity.md`
    - `bundle_followup_q_evo_04_archive_pii_governance.md`
    - `bundle_global_architecture.md`
    - `bundle_global_evolution.md`
    - `bundle_global_strategy.md`
    - `bundle_global_system_properties.md`
    - `bundle_local_backend_core.md`
    - `bundle_local_backend_runtime_security.md`
    - `bundle_local_backend_storage_backup.md`
    - `bundle_local_backend_sync_providers.md`
    - `bundle_local_docs_archive_general.md`
    - `bundle_local_docs_archive_tasks_a.md`
    - `bundle_local_docs_archive_tasks_b.md`
    - `bundle_local_docs_current.md`
    - `bundle_local_docs_reviews_historical.md`
    - `bundle_local_frontend_desktop.md`
    - `bundle_local_frontend_ui.md`
    - `bundle_local_repo_template_core.md`
    - `bundle_local_repo_template_misc.md`
    - `bundle_local_scripts_and_ops.md`
    - `bundle_local_tests_backend.md`
    - `bundle_local_tests_scripts_e2e.md`
    - `bundle_repository_summary.md`
    - `review_intensive.md`
- 缺失：无（按本 skill 白名单及聚合列举来源核对，不推测未选模型路线）。
- 合并说明：36 条原始 finding → 26 个决策项。A1 合并三个缺失类型导入；A19 归为依赖分层设计族，分别保留两处依赖环及凭据仓储归属；A22 合并隐私治理及四条局部发现。全局测试族拆分至 A18（SQLite/dummy）、A4（SSE）和 A20（真实计数契约），不是额外三条新缺陷。下表覆盖全部原始 finding；跨 bundle 来源列全，交叉验证另附映射。同一 intensive 审阅中的多视角不作为独立多模型互证。

### 基线与判断边界

- 报告基线：`2d1752022dac0baa5f76bff3afa41e9d6a83bcfc`。本次核对 HEAD：`b2ec9c43ec5e56b2663510fe0d752a34237a8751`，分支 main；后一提交归档旧审阅并纳入本轮报告。与判断有关的源码已只读核对，未改项目实现、未运行生产操作或数据库迁移。
- 本轮为静态核对，不将审阅中的推测、Confidence、`confirmed` 或 `agree` 当作用户决策或运行验证。用户已在原 D6、D8 的“用户决策”字段均填写 A，并明确要求更新 adoption 后提交；两项已转为 A21、A22，当前无待决定项。
- 聚合 severity 计数之和为 36，bundle 的 Findings 段亦为 36；repository summary 中“28 项”是统计笔误，不采用。归档 pending 实际 73 份，缺失索引为 p060–p072 与 p074 共 14 行，p073 仍未闭环。
- 优先级保留同一问题最高来源值，和采纳结论分开。全局测试族的 HIGH 沿用至 A18/A4/A20，不将来源评级本身当作已验证高危漏洞。
- 灾备精查实质上否定了原全局建议，R1 已吸收反证；精查所称恢复耗时并非实测。交叉验证虽同意七项，也不能证明直接替换密钥文件安全、压缩迁移无需数据保护，相关修正见 A15/A17。
- 文档内不复制原始邮箱、凭据特征或开发机路径。A22 不包含 Git 历史重写，也不把修正文档等同于删除历史暴露。
- 若后续进入实施，仍须遵守仓库 task/授权写入规则、TDD 与模板资产来源规则；当前决策文档不创建 task，不授权生产迁移、部署或发布。

### 按核心架构铁律复核后的修订

- 设计判断以用户本轮重申的三条铁律为准。开发难度、改动工作量、测试迁移数量和前后兼容顾虑不作为拒绝根治、分批留下缺陷或转待决定的理由；这一用户要求优先于 skill 的低成本采纳默认。
- 已确认的纯技术问题直接给出完整采纳方案。数据备份、可恢复迁移、实施验证及生产操作授权保留，它们约束执行安全，不改变目标架构。
- 架构判断仍需证据：不把正确的单元隔离、当前产品平台适配或历史快照误认作废弃兼容层；也不因追求彻底而引入缺少当前需求的灾备设施。
- 本轮编号迁移：原 D1 → A14、D2 → A15、D3 → A16、D4 → A17、D5 → A18、D7 → A19、R2 → A20；旧编号只用于本行溯源，不再作为现行条目。A1–A12 保持；A13 改为数据库权威鉴权，消除通知缺失时的 TTL 放行窗口。
- 最终用户决策迁移：原 D6 选 A → A21（收件箱独立终态）；原 D8 选 A → A22（当前文件树脱敏及门禁）。拒绝项保留 R1、R3、R4、R5 编号，避免讨论引用错位。当前全部 26 个决策项均已归类，无待决定项。

### 原始 finding → 决策映射

|报告位置|原始 finding ID|决策|
|---|---|---|
|`bundle_global_architecture.md:L9`|`f_arch_auth_bootstrap_cycle`|A19|
|`bundle_global_architecture.md:L16`|`f_arch_provider_factory_accounts_cycle`|A19|
|`bundle_global_architecture.md:L23`|`f_arch_credentials_layer_misplacement`|A19|
|`bundle_global_evolution.md:L9`|`f_evo_alembic_linear_debt_and_lock_risk`|A17|
|`bundle_global_evolution.md:L16`|`f_evo_disaster_recovery_single_tx_rto_bottleneck`|R1|
|`bundle_global_evolution.md:L23`|`f_evo_test_suite_overmock_and_tautological_assertions`|A18、A4、A20|
|`bundle_global_evolution.md:L30`|`f_evo_archive_governance_pii_and_path_leak_recurrent`|A22|
|`bundle_global_system_properties.md:L9`|`f_sys_session_revocation_multiprocess_window`|A13|
|`bundle_local_backend_runtime_security.md:L68`|`f_backend_runtime_01`|A1|
|`bundle_local_backend_runtime_security.md:L75`|`f_backend_runtime_02`|A1|
|`bundle_local_backend_runtime_security.md:L82`|`f_arch_deprecated_v1_replay_api`|A2|
|`bundle_local_backend_runtime_security.md:L89`|`f_arch_secret_write_busy_spin`|A15|
|`bundle_local_backend_sync_providers.md:L65`|`f_backend_sync_01`|A1|
|`bundle_local_backend_sync_providers.md:L72`|`f_arch_runtime_shim_and_deprecated_aliases`|A3|
|`bundle_local_backend_sync_providers.md:L79`|`f_arch_patrol_state_in_checkpoint_cursor`|A14|
|`bundle_local_backend_sync_providers.md:L86`|`f_arch_inbox_priority_numerical_tweak`|A21|
|`bundle_local_docs_archive_general.md:L46`|`f_docs_archive_general_p060_pii_leak`|A22|
|`bundle_local_docs_archive_general.md:L53`|`f_docs_archive_general_p027_credential_characteristic_leak`|A22|
|`bundle_local_docs_archive_general.md:L60`|`f_docs_archive_general_pending_readme_index_drift`|A11|
|`bundle_local_docs_archive_tasks_a.md:L46`|`f_docs_archive_tasks_a_historical_ac_drift`|R5|
|`bundle_local_docs_archive_tasks_b.md:L46`|`f_docs_archive_tasks_b_absolute_paths_in_reviews`|A22|
|`bundle_local_docs_current.md:L57`|`f_docs_current_handoff_stale`|A9|
|`bundle_local_docs_current.md:L64`|`f_docs_current_specs_index_empty_tasks`|A10|
|`bundle_local_docs_reviews_historical.md:L46`|`f_docs_reviews_readme_missing_session`|A12|
|`bundle_local_docs_reviews_historical.md:L53`|`f_docs_reviews_execution_log_absolute_path`|A22|
|`bundle_local_frontend_desktop.md:L82`|`f_frontend_desktop_01`|R3|
|`bundle_local_frontend_desktop.md:L89`|`f_frontend_desktop_02`|R4|
|`bundle_local_frontend_desktop.md:L96`|`f_arch_desktop_startup_toctou_acknowledged_in_test`|A16|
|`bundle_local_frontend_ui.md:L83`|`f_frontend_ui_01`|A8|
|`bundle_local_tests_backend.md:L50`|`f_tb_fake_assertion_ac008`|A18|
|`bundle_local_tests_backend.md:L57`|`f_tb_overmock_delta_result_counts`|A20|
|`bundle_local_tests_backend.md:L64`|`f_tb_sqlite_production_leak`|A18|
|`bundle_local_tests_scripts_e2e.md:L45`|`f_tse_tautological_body_visible_assertion`|A4|
|`bundle_local_tests_scripts_e2e.md:L52`|`f_tse_weak_regex_clipboard_assertion`|A5|
|`bundle_local_tests_scripts_e2e.md:L59`|`f_tse_scratch_screenshot_side_effect`|A6|
|`bundle_local_tests_scripts_e2e.md:L66`|`f_tse_stale_conftest_docstring`|A7|

### 重复与精查映射

- `bundle_cross_validation.md:L5` → A14；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L7` → A2；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L9` → A15；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L11` → A16；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L13` → A22；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L15` → A17；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_cross_validation.md:L17` → A18、A4、A20；吸收其 agree 证据，具体方案仍按对应决策限制。
- `bundle_followup_q_evo_01_alembic_squash.md` → A17：直接采用统一基线；部署事实仅用于确定一次性数据迁移与恢复验证，不再影响是否保留兼容链；stamp 不能代替 schema/数据转换。
- `bundle_followup_q_evo_02_disaster_recovery_strategy.md` → R1：否定立即演进 PITR 的必要性，保留冷恢复一致性边界。
- `bundle_followup_q_evo_03_test_dialect_and_fidelity.md` → A18：支持真实 PG 数据库测试，但不要求纯函数单测访问 DB。
- `bundle_followup_q_evo_04_archive_pii_governance.md` → A22：用户已选当前文件树最小脱敏及新增文档门禁，保留 Git 历史；消费仓不直接修改模板 hook。
- `bundle_repository_summary.md` 作为索引/重复来源列入对应项，不单列新 finding；`review_intensive.md` 的 36 条均可回溯到上表 bundle，无聚合独有 finding。
- 无 finding 的局部/全局报告已通读，不从正向评价推导额外修改项。

## 本轮授权与执行状态

- 用户决策：原 D6 = A，原 D8 = A，以本轮磁盘文档为准。
- 用户要求：更新 adoption 后提交，仅归档本次 review 目录；不执行代码或其他采纳项修改。
- 本轮执行：只更新本决策文档及完成 review 目录 Git 提交；A1–A22 均为已确认的后续实施事项，本轮全部不落地，不 push。

## 统计

- 采纳：22 项（A1–A22）
- 不采纳：4 项（R1、R3–R5）
- 待决定：0 项

## 待决定项

无。

## 采纳项

### A1. 补全三个模块缺失类型导入

- 来源：`bundle_local_backend_runtime_security`、`bundle_local_backend_sync_providers`、`bundle_repository_summary`
- 位置：src/mail_core/providers/remote_writeback.py:5、40、45；src/mail_core/worker/main.py:14、42；src/mail_core/search/index.py:7、15
- 优先级：LOW
- 结论：采纳
- 详细判断理由：三个签名分别引用未导入的 Sequence/Any，future annotations 仅延迟解析，不能为 get_type_hints 提供名称。源码核对成立，补 import 不改业务行为；合并为同类类型缺陷族。
- 修复说明：remote_writeback 导入 Sequence，worker.main 导入 Any，search.index 导入 Any。验证对应函数 typing.get_type_hints 可解析；不为简单 import 修复新增镜像式测试。

### A2. 删除已废弃 Outbox v1 回放接口

- 来源：`bundle_cross_validation`、`bundle_local_backend_runtime_security`、`bundle_repository_summary`
- 位置：src/mail_core/realtime/outbox.py:83-123；src/mail_core/realtime/__init__.py:7、20；tests/mail_core/test_a380_fetch_since_deprecated.py；test_sse_outbox.py；test_sse_medium_remaining.py
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：fetch_since 明确标记仅为旧测试保留，当前 v2 使用 publication_seq。删除符合项目零兼容负担要求；范围还必须包括 realtime/__init__.py 导出及另外两个旧调用测试，不能只删除报告点名的专属测试后留下导入错误。
- 修复说明：删除 fetch_since 及包导出，整体删除专属废弃契约测试并说明旧语义失效理由。其他回放测试以真实发布批次和 after_seq 重建 v2 行为用例，保留账户过滤、全局事件及顺序断言；不能将旧 row id 机械替换成 seq。验证生产及测试均无旧调用，运行 Outbox/SSE 相关 PG 测试。

### A3. 移除连接预算与指标历史别名及签名 Shim

- 来源：`bundle_local_backend_sync_providers`、`bundle_repository_summary`
- 位置：src/mail_core/providers/connection_slots.py:60-70、432-453；src/mail_core/system_metrics.py:58-62；tests/mail_core/test_provider_connection_slots.py、test_provider_connection_budget_integration.py、test_a346_system_metrics.py
- 优先级：MEDIUM
- 结论：采纳
- 详细判断理由：源码明确保留兼容常量 __getattr__、忽略 session 的 provider_connection_permit 以及 max_sync_lag_seconds 别名。生产主路径已有 getter、permit API 和新字段，可明确迁移仓内旧测试后删除，不保留新兼容层。
- 修复说明：删除连接常量反射别名、旧 session/is_background 包装器与指标旧 property；调用方使用 get_total_slots/get_background_start_slot/get_capacity_retry_seconds、显式 TrafficClass 与现有 acquire_permit/permit_scope。旧兼容契约测试整体删除或以新语义完整替代并说明理由；保留真实独立连接释放、后台上限、前台保留和新指标语义测试。

### A4. 让双页面 SSE E2E 断言真实状态收敛

- 来源：`bundle_cross_validation`、`bundle_global_evolution`、`bundle_local_tests_scripts_e2e`、`bundle_repository_summary`
- 位置：tests/e2e/full_stack.spec.ts:160-188
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：现有用例无邮件时直接跳过核心步骤，存在邮件时仅点击第一封并断言 body 可见，既未保证初始未读也未校验另一页面同封邮件状态，确实不能保护 AC-005。全局测试族最高优先级 HIGH，限定采纳其中 SSE 子项。
- 修复说明：在真实全栈夹具中保证目标邮件初始未读，两个页面定位同一邮件并等待 SSE 就绪；page1 显式标读，page2 不点击、不刷新，自动等待该邮件未读标识和相关权威计数变化。删除 if(isVisible) 跳过及固定 sleep，缺夹具/不收敛必须失败；阻断 SSE 时应失败，正常链路应通过。

### A5. 复制验证码测试明确验证成功与失败分支

- 来源：`bundle_local_tests_scripts_e2e`
- 位置：tests/e2e/provider_account_forms.spec.ts:57-58
- 优先级：LOW
- 结论：采纳
- 详细判断理由：成功或失败二选一的正则只能证明出现反馈，无法证明复制成功。保留失败反馈覆盖仍有价值，应通过确定性测试条件分别断言，而不是只收紧文字后引入环境偶发失败。
- 修复说明：为成功场景配置浏览器写剪贴板条件或确定性 Clipboard API stub，断言写入当前验证码且出现成功反馈；失败场景显式注入拒绝并只断言失败反馈。涉及真实剪贴板集成时按现有浏览器项目验证支持情况，不向产品增加读取权限。

### A6. 移除设置 E2E 遗留截图副作用

- 来源：`bundle_local_tests_scripts_e2e`
- 位置：tests/e2e/settings_workspace.spec.ts:43、64
- 优先级：LOW
- 结论：采纳
- 详细判断理由：同文件有账户页和通用页两处固定相对 .scratch 截图，均不参与断言，依赖 cwd 并在并行运行时写同名文件。删除不会降低行为覆盖；报告只点名第一处，处置覆盖同一根因第二处。
- 修复说明：删除两处调试 page.screenshot 调用；沿用 Playwright 已有失败产物配置。运行该设置工作区用例，确认焦点、筛选和主题断言仍覆盖原行为。

### A7. 修正根 pytest 配置说明

- 来源：`bundle_local_tests_scripts_e2e`
- 位置：tests/conftest.py:1
- 优先级：INFO
- 结论：采纳
- 详细判断理由：根 docstring 声称全部测试在 tests/mail_core，实际存在 tests/scripts。只修正描述即可，不涉及 fixture 行为。
- 修复说明：将模块说明改为覆盖 tests/mail_core 与 tests/scripts 的公共 pytest 配置；核对目录与文案，不新增测试。

### A8. 为阅读器详情缓存更新补充类型约束

- 来源：`bundle_local_frontend_ui`
- 位置：src/frontend/src/components/MessageReader.tsx:169-172
- 优先级：INFO
- 结论：采纳
- 详细判断理由：setQueryData updater 使用 any，现有 MailDetail 可准确描述缓存；改为泛型并保留 undefined 分支能让 TS 检查变更字段，不改变运行行为。
- 修复说明：使用 setQueryData<MailDetail>(key, old => old ? {...old, remote_images_allowed: true} : old)，复用权威类型 import；仅处理该 updater，不扩大到其他 any。执行前端类型检查及现有远程图片阅读器测试。

### A9. 更新过时交接记录并归档旧节

- 来源：`bundle_local_docs_current`、`bundle_repository_summary`
- 位置：docs/handoff.md:5-13；docs/archive/handoff.md
- 优先级：MEDIUM
- 结论：采纳
- 详细判断理由：handoff 的日期、焦点与待验证描述明显滞后。head_commit 表示交出时快照，并不要求永远等于当前 HEAD；报告把 SHA 不同直接称违规过强，但当前正文仍需更新。不能照抄报告建议的旧 2d17520 或伪造新验证结果。
- 修复说明：将现有节完整追加到 archive/handoff，新节使用实际交出时 branch/head_commit 与带时区时间，陈述本轮决策范围、已完成检查和未执行门禁；不把历史测试通过声明当作本轮结果。核对最新仅一节，归档旧内容完整。

### A10. 补全生效 spec 的任务溯源

- 来源：`bundle_local_docs_current`、`bundle_repository_summary`
- 位置：docs/specs_index.md:8、11
- 优先级：LOW
- 结论：采纳
- 详细判断理由：auth_and_session 和 mail_account_navigation_and_read_state 两行 task 清单为空。问题成立，但报告随举的 t010/t025 等不构成真实关联证据，须从 task 收尾与 spec 变更历史核实。
- 修复说明：逐条核对历史 task 与 Git 变更，补入确实交付对应行为且完成验证的 task；若某部分来自非 task 实施，明确记录来源而不虚填编号。按项目索引维护工具规则更新，核对所有引用可解析。

### A11. 补齐归档 pending 闭环索引

- 来源：`bundle_local_docs_archive_general`、`bundle_repository_summary`
- 位置：docs/archive/pending/README.md:15-75
- 优先级：LOW
- 结论：采纳
- 详细判断理由：README 表格确实停于 p059。报告数字自相矛盾：其 files_reviewed 列出 73 个条目，且 p073 仍在 todo；不能照抄“71 项、缺 14 项”或把整个连续区间当作已闭环。
- 修复说明：按当前实际 p\*.md 文件集求差补行；闭环日期按表头规定从 git log --diff-filter=A 获取，处理指向从正文核实，提出日期无证据则保留未记录；明确排除仍未闭环的 p073。只新增缺行，不移动 pending 条目。

### A12. 补登历史审阅会话布局差异

- 来源：`bundle_local_docs_reviews_historical`、`bundle_repository_summary`
- 位置：docs/reviews/README.md 的历史会话表；docs/archive/reviews/review_20261030_103516/
- 优先级：LOW
- 结论：采纳
- 详细判断理由：历史会话表确实未列 review_20261030_103516；当前 HEAD b2ec9c43 已将其从 docs/reviews 移入 docs/archive/reviews，报告路径已过时。应登记归档后实际位置，避免新增死链。
- 修复说明：新增该会话布局差异行，说明只有 adoption.md、已归档至实际目录；登记最新会话时遵守当前索引约定，不回改历史审阅正文。验证目录链接存在。

### A13. 会话撤销校验以数据库为唯一权威，移除 TTL 放行窗口

- 来源：`bundle_global_system_properties`
- 位置：src/mail_core/realtime/listener.py:105-110；src/mail_core/security/auth.py:118-124、375-412；src/mail_core/api/app.py:57-77
- 优先级：LOW
- 结论：采纳
- 详细判断理由：仅在收到通知时更新本地 epoch 缓存仍依赖通知及时到达；监听断线或遗漏时旧会话仍可在 5 秒 TTL 内通过。这不能根治跨进程撤销一致性缺陷，原 A13 将 TTL 保留为安全判定兜底不符合本轮根因整改要求。数据库已承载权威 epoch，采用每次 Cookie Session 鉴权读取权威值；NOTIFY 继续负责主动断开 SSE，不作为 REST 拒绝旧会话的前提。
- 修复说明：在 security/auth.py 的 get_session_epoch/read_session 生产路径移除本地 5 秒缓存放行，统一读取已提交数据库 epoch 并与会话比较；删除仅服务该缓存的 TTL、generation 状态、force_refresh 签名与相关兼容调用，迁移所有调用方。配置 DB 时记录缺失或查询失败必须失败关闭，不回退进程内旧 epoch；合法初始化由启动流程完成。realtime/listener.py 保留撤销通知关闭 SSE，SSE 自身按现有约定重新校验数据库。用两个真实独立进程验证：B 预先验证过旧会话，A 提交撤销后，即使 B 未收到通知，其随后开始的鉴权也拒绝旧会话；覆盖 DB 故障、SSE 断开及通知重复/乱序。已在撤销前通过鉴权的在途请求不宣称能回溯撤销；严格区分数据库权威判断与消息传输时延。

### A14. 巡检状态与协议同步游标彻底分离

- 来源：`bundle_cross_validation`、`bundle_local_backend_sync_providers`、`bundle_repository_summary`
- 位置：src/mail_core/sync/patrol.py:8-9、33-34、126；src/mail_core/sync/checkpoints.py；docs/blueprint/architecture.md 的 STATUS 巡检段落
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：巡检基准与协议续传游标有独立职责和生命周期。既然已确认职责混用，应按核心架构铁律直接采纳拆分；所需迁移、测试及影响文件数量不构成待决定理由。本次未复现数据损坏，不夸大故障，但设计整改无需等待故障发生。
- 修复说明：在 mail/storage/models.py 建立按 folder_id 唯一关联、随文件夹删除级联清理的独立巡检状态模型；Alembic 迁移已有 last_status/last_probe_at 并从 SyncCheckpoint.cursor 删除这两个键。patrol.py 仅访问新模型，checkpoint 合并/重建仅处理协议游标，不保留旧键读取回退。明确文件夹身份或 UIDVALIDITY 改变后的基准失效规则，更新架构文档；用真实 PG 验证迁移、独立更新、重建及删除隔离。生产迁移前验证备份可恢复。

### A15. 密钥初始化统一为跨进程互斥与完整持久化发布

- 来源：`bundle_cross_validation`、`bundle_local_backend_runtime_security`、`bundle_repository_summary`
- 位置：src/mail_core/runtime/bootstrap.py:34-76、bootstrap_data_dir 的 bcrypt 写入段
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：当前 O_EXCL 后直接写最终文件，会暴露未完成内容并依赖有界轮询；创建者退出可留下空文件。根因是缺少完整初始化事务协议，采用跨进程 OS 文件锁与持久化发布直接解决。原报告无条件 os.replace 可能覆盖并发进程已使用的密钥，不能以“彻底重构”为由采纳错误方案；有效密钥属于须保护的数据，不是待删除的兼容负担。
- 修复说明：在 runtime/bootstrap.py 为整个 secrets 初始化序列建立跨进程 OS 文件锁，锁内重新读取权威文件；只对不存在目标生成新值，以 0600 同目录临时文件完整写入并 fsync，发布后按平台保证目录持久化。初始口令与 bcrypt 文件遵循同一受锁协议，移除 sleep 等待。保留有效文件；已存在空/损坏文件明确失败关闭，禁止自动重建密钥。验证并发调用得到相同密钥、创建者中断后恢复或明确报错、初始口令/hash 一致性及跨平台权限。

### A16. sidecar 持有动态监听端口并回传实际就绪地址

- 来源：`bundle_cross_validation`、`bundle_local_frontend_desktop`、`bundle_repository_summary`
- 位置：src/desktop/startup.js:190-208；src/desktop/startup.test.js:64-78；src/desktop/main.js 的 sidecar 启动路径；src/mail_core/__main__.py
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：端口使用者应从绑定成功直到退出持有监听资源；先探测、释放、再由另一进程绑定不能建立这一不变量。直接由 sidecar 绑定动态端口并报告已绑定地址，删除探测重试路径。跨 Electron/Python 协议变更与打包验证属于实施责任，不是保留竞态或继续待定的理由。
- 修复说明：修改 mail_core/__main__.py，使桌面启动模式可在 loopback 的端口 0 上创建并持有实际服务监听 socket；绑定成功并完成既有就绪条件后，经专用结构化就绪通道回传真实端口。desktop/main.js 与 startup.js 解析当前子进程的就绪消息，校验 loopback、端口、进程生命周期与超时，再进行健康检查；删除该应用服务的 freePort/tryListen 先探测再释放逻辑及其重试兼容路径。若辅助服务仍使用同名工具，按实际调用保留必要逻辑，不机械全删。整体替换披露注释断言测试，验证真实绑定、并发启动、无效/迟到消息、子进程提前退出和打包冒烟；清除相关旧协议调用。

### A17. 压缩历史迁移为单一当前基线并一次性迁移现有数据

- 来源：`bundle_cross_validation`、`bundle_followup_q_evo_01_alembic_squash`、`bundle_global_evolution`
- 位置：src/mail_core/db/alembic/versions/；20261027_0027_search_recipient_and_account_recipients.py；20261027_0028_rebuild_recipient_search_text.py；tests/mail_core/test_migration_validation.py
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：按本轮重申的零兼容负担原则，设计明确采用当前权威基线，消除探索期中间 schema 与重复修补链，不再以外部旧版本可能存在为由保留双链或延后架构选择。30 个 revision 本身不等于缺陷，Squash 也不会消除未来 DDL 风险，因此同时建立清晰迁移约束。原 A17 推荐先测量再决定是否重构，混淆了设计选择与执行验证，应撤回；备份、数据转换和恢复验证仍必须完成。
- 修复说明：将 0001–0030 的当前最终 schema 整理为单一 Alembic 基线，删除旧运行迁移链及仅断言已废弃历史 revision 的测试，以当前 schema、空库初始化和一次性数据迁移契约完整替代。对既有数据库交付一次性离线迁移：校验原 schema/数据，执行必要转换，再验证数据与新基线一致；仅当结构已严格一致时才能 stamp，不允许盲 stamp，不保留双 schema、双迁移链或运行时旧版判断。先在隔离副本验证可恢复备份、消息/附件/凭据关联和回退；性能测量作为实施验收，不再作为是否保留旧链的决策门槛。未来迁移按实际在线/停机场景选 DDL 与索引策略，大表回填有独立、幂等且可验证的执行路径；不对空库强制 CONCURRENTLY。生产库操作另行批准。

### A18. 数据库行为测试统一 PostgreSQL，删除 SQLite 生产分支

- 来源：`bundle_cross_validation`、`bundle_followup_q_evo_03_test_dialect_and_fidelity`、`bundle_global_evolution`、`bundle_local_tests_backend`、`bundle_repository_summary`
- 位置：src/mail_core/realtime/publication.py:26-43；tests/mail_core/sqlite_schema.py；tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367；依赖 SQLite 的后端数据库测试
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：PostgreSQL 是唯一生产数据库，测试行为应由同一数据库语义验证。SQLite DDL 改写与生产分支是反向适配测试设施的设计缺陷，直接全面消除，不以测试数量或运行契约改动为由保留分支。test_ac008 的 dummy 提交不覆盖声称的事件模型，不应继续补 SQLite 契约。纯函数无 DB 单测仍合理，不属于兼容层。
- 修复说明：全面盘点 SQLite 数据库行为测试并迁入现有专用隔离 PG fixture；删除 tests/mail_core/sqlite_schema.py、publication.py 的 SQLite 及其他非生产方言回退，并清除相关测试专用生产适配。整体删除已失效的非 PG 契约测试并说明原因，替换为真实 OutboxEvent/WorkerJob 提交、回滚、并发锁与通知断言；不只删分支留下跳过或空测试。保持测试实例保护、每用例隔离和清理门禁，验证数据库套件无静默跳过；纯函数单测不绑定 DB。全局测试族 SSE 由 A4 处理，真实变更计数契约由 A20 处理。

### A19. 完整解除反向依赖并下沉通用凭据仓储

- 来源：`bundle_global_architecture`
- 位置：src/mail_core/security/auth.py:564；src/mail_core/runtime/bootstrap.py:129；src/mail_core/accounts/connection.py:81；src/mail_core/providers/factory.py:209；src/mail_core/accounts/credentials.py；src/mail_core/providers/oauth.py；src/mail_core/blobs/archive.py、rotate.py
- 优先级：MEDIUM
- 结论：采纳
- 详细判断理由：已确认的两处双向依赖及 CredentialStore 基础设施归属问题应作为完整分层整改处理，不因移动调用方多而只解环、留下职责错置。用户已指定单向、纯粹、零兼容的设计取向，纯技术选型无需再次在局部修补与根治间选择。未复现导入崩溃不改变依赖方向事实。
- 修复说明：将改密成功后的初始口令清理移至应用编排层，auth 不再导入 runtime.bootstrap；共享密码字节校验放在安全层，使 bootstrap 单向依赖。将 validate_imap_host 及其所需纯主机校验下沉 providers/host_security.py，将 Microsoft IMAP 选择策略放入共享低层协议策略模块，accounts.connection 与 providers.factory 单向引用。将 CredentialStore 及加密仓储移至 security/credentials.py，迁移全部 provider/blob/accounts 调用方，删除旧位置导出和为其保留的转发层。先核对这些模块实际依赖，保证新包不重建反向依赖；保持 credential_edit 的事务、行锁及 OAuth 刷新语义，验证改密清理、账户创建/编辑、令牌轮换、归档和导入顺序。无需新增通用事件总线。

### A20. 用真实 PostgreSQL 验证 changed 计数与持久化副作用

- 来源：`bundle_cross_validation`、`bundle_global_evolution`、`bundle_local_tests_backend`、`bundle_repository_summary`
- 位置：tests/mail_core/test_delta_result_counts.py:10-65；tests/mail_core/test_sync_delta.py:25-87；tests/mail_core/test_delta_archive_integration.py
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：原 A20 用已有广义 PG 集成测试否定本项过强。计数单测把 changed=True/False 直接伪造为输入，只证明聚合分支；已核对的集成用例验证增改删或单封新建，未覆盖同页“真实变化 + 完全不变”由存储逻辑判定后仅计变化的契约。因此采纳真实行为覆盖，从测试源头补足安全网。mock 本身不是错误，不据此无差别重写全部单测。
- 修复说明：新增真实 PG 契约用例：以实际 Account/Folder/Message/Checkpoint 与租约建立基线，经生产 apply_delta_page 输入同页一条真实变化和一条完全相同的消息，精确断言仅真实变化计入 upserted，并核验消息、搜索投影、相关统计、Outbox 与 checkpoint 的持久结果；重放完全相同数据不虚报变化。不得 mock assert_fencing、upsert_messages、commit_checkpoint 等被验证内部逻辑，只在外部 provider 边界使用夹具；覆盖失效 fencing 不能提交。原狭窄 mock 单测可作为聚合单元保留，但不再声称覆盖存储、锁或完整同步契约。

### A21. 收件箱同步独立终态，完整同步后台独立反馈

- 来源：`bundle_local_backend_sync_providers`、`bundle_repository_summary`
- 位置：src/mail_core/sync/engine.py:386-425；docs/pending/todo/p073_manual_refresh_inbox_latency.md；src/frontend/src/api/sync.ts；docs/blueprint/architecture.md 的 t074 段落
- 优先级：MEDIUM
- 结论：采纳
- 详细判断理由：原 D6，用户已在文档明确选择 A。收件箱同步与目录发现解耦，已有收件箱不先等目录发现；主刷新以收件箱完成进入终态，目录发现与其余文件夹后台独立运行，完整同步状态单独呈现。该选择既明确主要阅读路径反馈，又保留完整同步的可观察结果，不能将后台失败伪报为完整同步成功。
- 修复说明：调整 sync/engine.py、同步请求/目标状态模型及前端 api/sync.ts 与刷新反馈组件，使收件箱请求和完整后台任务独立调度、结算。主刷新在目标收件箱任务完成后结束，目录发现及其他文件夹继续后台运行并独立展示进度与失败；新账号或收件箱身份失效时走必要发现流程，明确排队、失败及部分完成状态。priority 仅用于调度，不代替拓扑拆分。用真实 PG 请求结算测试及前端交互/E2E 验证收件箱不受慢目录发现阻塞、主刷新正确终态、后台状态持续可见与错误隔离；更新 p073 对应契约记录。

### A22. 当前文件树最小脱敏并建立新增文档门禁

- 来源：`bundle_cross_validation`、`bundle_followup_q_evo_04_archive_pii_governance`、`bundle_global_evolution`、`bundle_local_docs_archive_general`、`bundle_local_docs_archive_tasks_b`、`bundle_local_docs_reviews_historical`、`bundle_repository_summary`
- 位置：docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3、p027_account_folder_sync_failure_and_unknown_unread_badge.md:11；docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/、t075_backup_export_permission_boundary/ 的 review_code.md/review_test.md:6；docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5；当前审阅报告中的对应复述
- 优先级：HIGH
- 结论：采纳
- 详细判断理由：原 D8，用户已在文档明确选择 A。批准当前文件树中已确认历史文档与审阅副本原位最小脱敏并加勘误，同时建立项目新增文档门禁；保留 Git 历史与其余审计内容。范围限已确认个人标识、凭据特征和本机路径，不把所有非保留域邮箱或绝对路径一律判为敏感信息。该决策记录未来实施范围，本轮仅更新并提交 adoption，不执行脱敏或门禁实现。
- 修复说明：在原位置列举的 p060/p027、t061/t075 审阅文件、历史 execution_log 及当前审阅报告的对应复述中，对已确认敏感值原位最小替换并附勘误；保持问题描述、验证事实和溯源关系。建立项目侧新增/修改文档内容检查器，定义明确检测范围、规则与有依据的豁免，接入项目现有本地门禁，验证真实泄露可被拦截且协议测试域名、官方地址及容器路径不被误伤。模板通用 hook 演进须按模板仓流程处理，不直接修改消费仓 .repo_template。当前 review 目录正文修订属于后续脱敏实施，应独立安排在无提交子代理并行修改的阶段；不得在本轮归档提交中顺带执行。不改写 Git 历史，不迁出历史证据，不发布或轮换凭据。

## 不采纳项

### R1. 不引入当前无需求的 PITR/持续物理备份

- 来源：`bundle_followup_q_evo_02_disaster_recovery_strategy`、`bundle_global_evolution`
- 位置：src/mail_core/backup/package.py 的 restore_backup_package/\_run_pg_restore；灾备指南
- 优先级：MEDIUM
- 结论：不采纳
- 详细判断理由：定向精查已反证原宏观结论：当前冷恢复的空目标、先 Blob 后单事务 DB 提交用于保证一致性；没有真实 RTO 超标或容量上限测量，不能仅凭单事务推断灾备缺陷。精查所称数十秒也只是估计，不作为实测。本轮保持现状，不引入 WAL/PITR、对象存储或增量备份。原 finding 保留来源最高 MEDIUM，处置为不采纳。

### R3. 不因假定的 120 秒 CI 阈值拆桌面测试

- 来源：`bundle_local_frontend_desktop`
- 位置：src/desktop/package.json:15；docs/blueprint/decisions.md 的本地门禁注记
- 优先级：LOW
- 结论：不采纳
- 详细判断理由：报告标注 reproduced，但未提供实际耗时、失败命令或受约束 timeout；项目 decisions/testing 已明确无远程 CI。串行还避免真实进程、端口与 PostgreSQL 资源互扰。没有验证到项目门禁超时，不能为外部假设改测试入口。

### R4. 保留 HTTP 自托管剪贴板降级

- 来源：`bundle_local_frontend_desktop`
- 位置：src/frontend/src/lib/clipboard.ts:48；docs/blueprint/conventions.md 第八节
- 优先级：INFO
- 结论：不采纳
- 详细判断理由：conventions.md 明确要求非安全上下文使用 execCommand 降级并诚实反馈失败。接口废弃状态不证明当前功能错误；HTTPS 已在部署/安全指南涉及，报告也主张保留逻辑。本轮不删除降级、不重复新增同义部署建议，待出现可复现不兼容时按实际行为处理。

### R5. 历史 task 行为漂移保留快照免责声明

- 来源：`bundle_local_docs_archive_tasks_a`
- 位置：docs/archive/tasks/README.md:1-11；早期 t001-t012 task
- 优先级：INFO
- 结论：不采纳
- 详细判断理由：归档 task 记录当时需求与验证结果，随系统演进与现行 spec 不同是预期。README 已声明历史快照、现行以 specs 为准；回写早期 AC 会损害审计证据。无须修复。
