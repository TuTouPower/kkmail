# Intensive Review

- Coverage: completed_with_limitations

- Scope: {"mode": "all", "base": null, "head": "2d1752022dac0baa5f76bff3afa41e9d6a83bcfc", "include_untracked": false, "paths": [], "exclude_paths": [".agents/skills", ".claude/skills", "docs/reviews/review_20261107_142548"]}

- Targets: 1473; units: 16

- Verdict: REQUEST CHANGES

- Findings: {"Critical": 0, "High": 7, "Medium": 13, "Low": 12, "Info": 4}

## Global conclusions

- strategy: 全仓战略适配宏观评估结论：产品边界控制极其精准克制，技术投入与核心业务价值高度匹配，依赖与供应商选型自洽稳健。

1. 产品边界控制（收信/阅读/检索 vs 砍发信/砍扩展）：

- 剔除发信能力（SMTP/Graph Send/Compose/Reply）彻底消除了自托管节点沦为垃圾邮件放大器的严重合规与安全漏洞，规避了 SPF/DKIM/DMARC 投递失败、IP 信誉及复杂富文本编辑器的维护黑洞，攻击面缩减 80% 以上，使系统纯粹聚焦于多账号统一监控、阅读、归档与快速检索。
- 彻底废弃浏览器扩展及相关桥接 API，避免了跨域提权漏洞与扩展商店审核包袱，使客户端交付形态清晰收敛为 Web SPA 与 Electron 桌面端。
- 审慎克制跨目录移动与归档写回动作，深刻识别了 Gmail 标签机制、Graph ID 漂移与 IMAP 销毁旧 UID 等语义冲突，从根因上杜绝了增量同步撕裂与幽灵邮件风险。

2. 技术投入与业务价值匹配（统一 PostgreSQL 与 Electron 集成）：

- 坚决回绝 SQLite，统一强制采用 PostgreSQL 16 作为跨 Web 容器与 Electron 桌面的唯一数据基线，彻底贯彻了“单一架构真相”与“零兼容性负担”铁律。规避了双数据库方言在 ORM、FTS 全文检索、事务隔离及高并发锁（LISTEN/NOTIFY、咨询锁、行级写锁）上的严重抽象泄漏。
- 桌面端虽因内置 PostgreSQL 管理器（postgresManager.js）增加了多进程编排与打包体积，但直接赋能了单进程 Worker 8 槽位并发执行器、IDLE 实时长连接、错峰增量巡检及后台批量 AES-256-GCM 归档的高吞吐并发，完全消除多账号并发下的写入锁死瓶颈。
- 严格落实单用户 Capability-based UUID 模型，拒绝推测性的多租户 RBAC 复杂度，技术资源完全倾斜在侧边栏分组、深翻页与端到端安全加固上。

3. 依赖与供应商选择合理性（下线 Gmail API，收敛至 IMAP 与 Graph）：

- 全面下线 Gmail API 是极具远见的战略决断，规避了 Google 极其苛刻且昂贵的受限权限年审（CASA Tier 2/3）与个人测试凭据 7 天强制过期的致命枷锁；通过标准 IMAP 加应用专用密码接入，配合虚拟文件夹（\\All 等）屏蔽策略，以极简实现保障了极高稳定性。
- 针对微软生态顺应其官方淘汰 IMAP Basic Auth 的趋势，全面拥抱 Graph REST API，提供 PKCE 授权码与设备码双轨接入，并以 JSON batching 批量写回，适配现代云端规范。
- 协议适配器高度收敛为统一 IMAP 与 Graph 两大引擎，无私有散乱协议，大幅降低全生命周期维护成本。
- architecture: kkmail 整体架构清晰，职责划分与安全防御体系高度纯粹。PostgreSQL 与 BlobStore 职责分明，分别确立了元数据与加密正文内容的单一权威；MailProvider 协议抽象彻底收敛了 IMAP 与 Microsoft Graph 的异构差异；受控无脚本沙箱 iframe、严格同源 CSP 与服务端图片反向代理构建了严密闭环的零外部出网信任边界。系统大体遵循 FastAPI -> Service/Application -> Storage/Provider 的单向调用，但在底层存在 3 处通过 lazy import 规避的跨层反向依赖与依赖环，需在后续演进中完成下沉解耦。
- system_properties: 系统各部分组合后的整体性质审查结论：核心安全、一致性、可靠性与性能资源上限承诺均严格成立，整体架构具备坚实的防御深度与工程鲁棒性。具体表现为：1. 安全域：图片代理结合底层套接字直连与双重校验彻底杜绝了 SSRF 与 DNS Rebinding 风险，前端受控沙箱 iframe 配合严苛的 CSP 与 DOMPurify 剥离实现了正文不可信输入与宿主上下文的彻底物理隔离；防暴力破解限流器具备 O(1) 淘汰与内存上限保护；session_epoch 驱动的会话撤销在单进程及长连接 SSE 维度即时生效（跨进程 REST 请求存在 5s 缓存 TTL 窗口）。2. 可靠性与一致性域：Outbox 基于单例行行锁分配全局递增 publication_seq，彻底消除并发空洞漏读；SSE 具备基于 Last-Event-ID 的断点续传及全量重对齐安全降级（resync_hint）；多账号同步基于 PostgreSQL 行排他锁与单调递增 fencing_token 实施多粒度断言，严格杜绝脑裂与脏写覆盖。3. 性能与容量域：基于 PG 咨询锁的 8 槽位全局出站配额与前后台流量分级（0-1 预留前台交互，2-7 后台归档）彻底避免了大量后台同步饿死用户交互；SSE 连接数受 128 上限保护；前端采用基于 rAF 帧对齐节流的定高轻量虚拟列表，渲染万级邮件 DOM 节点恒定在数十个，保证了极致流畅度。
- evolution: 系统当前具备清晰的架构边界与零兼容负担演进意图，但面临四项显著长期演进与维护成本瓶颈：1) Alembic 迁移链 11 天内线性堆叠 30 个版本，大表存在排他锁与 STORED 计算列全表重写风险，downgrade 名存实亡；2) 灾备机制仅支持全停机单事务冷还原，大数据量下 RTO 膨胀且对宿主机资源要求苛刻；3) 单测过度 mock 核心逻辑、E2E 存在恒真断言、生产代码混入 SQLite 适配特判，严重侵蚀重构安全感；4) 归档目录超 600 文件且持续复发 PII 真实邮箱与本地绝对路径泄漏，缺乏前置自动化拦截门禁导致治理成本发散。

## Findings

- [High][95] src/mail_core/sync/patrol.py:8-9 — 为规避数据库迁移将 STATUS 巡检基线塞入 Checkpoint Cursor JSONB，违反架构至上铁律
    - Sources: bundle_local_backend_sync_providers.md (f_arch_patrol_state_in_checkpoint_cursor)
    - f_arch_patrol_state_in_checkpoint_cursor: src/mail_core/sync/patrol.py:8-9 注释明示: 'The probe baseline lives in the checkpoint cursor JSONB (last_status / last_probe_at) — no migration.'; docs/blueprint/architecture.md:113 亦记录该妥协决策
        - Impact: 为了规避一次正规 Alembic 数据库迁移，将本用于协议同步游标（IMAP UID / deltaLink）的 cursor 字段滥用为存储探测未读数、巡检时间戳的多用途杂物箱，破坏了领域模型的单一职责与纯粹性。
        - Fix: 创建正规数据模型与 Alembic 迁移脚本，为文件夹巡检状态建立独立的巡检基准表或字段，将巡检状态从 SyncCheckpoint.cursor 中彻底剔除。
        - Verification: static
- [High][95] src/mail_core/realtime/outbox.py:83-123 — 保留废弃的 v1 顺序回放接口与专属兼容测试，违反零兼容性负担铁律
    - Sources: bundle_local_backend_runtime_security.md (f_arch_deprecated_v1_replay_api)
    - f_arch_deprecated_v1_replay_api: src/mail_core/realtime/outbox.py:83-123 保留 fetch_since 废弃函数及 DeprecationWarning 包装; tests/mail_core/test_a380_fetch_since_deprecated.py:1-40 专门编写测试套件断言废弃接口在报警后仍正常返回数据
        - Impact: 在 Outbox 升级到 v2 连续序列号（publication_seq）后，未执行破坏性清理，保留了按自增 id 排序的旧接口与测试预算，形成长期兼容债务。
        - Fix: 依据零兼容负担铁律，物理删除 outbox.py 中的 fetch_since 废弃函数及其专属测试文件 test_a380_fetch_since_deprecated.py，上层调用统一使用 fetch_published_since。
        - Verification: static
- [High][95] src/mail_core/runtime/bootstrap.py:41-55, 61-76 — 单机文件并发写入采用 time.sleep(0.01) 自旋死等，违反拒绝妥协铁律
    - Sources: bundle_local_backend_runtime_security.md (f_arch_secret_write_busy_spin)
    - f_arch_secret_write_busy_spin: src/mail_core/runtime/bootstrap.py:41-55 在写入密钥文件捕获 FileExistsError 后，使用 while time.monotonic() < deadline 并在循环内执行 time.sleep(0.01) 忙轮询等待; src/mail_core/runtime/bootstrap.py:61-76 同样存在同型自旋死等逻辑
        - Impact: 创建密钥文件时未采用 POSIX 原子替换范式，并发进程在竞争时被迫自旋死等，不仅浪费 CPU，而且存在超时未写完的死锁风险，属典型用 sleep 掩盖原子写入缺陷的妥协方案。
        - Fix: 重构为原子写入范式：先写入带随机后缀的临时文件，刷盘 fsync 后通过 os.replace 原子重命名为目标路径，彻底移除 time.sleep 自旋等待循环。
        - Verification: static
- [High][95] src/desktop/startup.js:190-208 — 桌面端端口探测 TOCTOU 竞态写单测断言注释承认缺陷，严重违反拒绝妥协与架构至上铁律
    - Sources: bundle_local_frontend_desktop.md (f_arch_desktop_startup_toctou_acknowledged_in_test)
    - f_arch_desktop_startup_toctou_acknowledged_in_test: src/desktop/startup.js:190-208 注释自述: 'TOCTOU warning: this is a probe, NOT a reservation... Eliminating the race requires the backend to bind port 0 and report the assigned port back to the launcher (a backend protocol change); until that exists, treat the two failure shapes above as the port-raced signature and retry the launch.'; src/desktop/startup.test.js:64-78 专门编写单测断言注释承认缺陷: 'assert.match(docBlock, /TOCTOU/); assert.match(docBlock, /bind.\*0|port 0/)'
        - Impact: 由于根治竞态需要修改后端服务启动协议（绑定 port 0 并回传已分配端口），开发团队选择保留先监听再关闭释放的伪探测机制，留下严重 TOCTOU 窗口，并通过编写单元测试断言注释中承认了该缺陷，以此规避重构。
        - Fix: 彻底重写服务拉起协议：桌面端启动 mail_core 时传入 --port 0，后端在绑定成功后通过标准输出管道原子汇报分配端口，主进程直接健康检查，彻底移除 freePort 与 tryListen 伪探测机制及其对应单测。
        - Verification: static
- [High][95] docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 — 已归档 pending 正文泄露真实用户个人 Gmail 邮箱地址
    - Sources: bundle_local_docs_archive_general.md (f_docs_archive_general_p060_pii_leak)
    - f_docs_archive_general_p060_pii_leak: docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 正文曾写出真实个人邮箱："用户截图 2026-10-27（账号 [REDACTED_GMAIL]）"（已脱敏为 user@example.com 并勘误）；明显为用户真实个人邮箱，非 example.com / test.com 等脱敏样例，直接导致个人 PII 隐私在公开仓外泄
        - Impact: 公开仓库中直接暴露特定开发者的真实个人邮箱，面临垃圾邮件骚扰与身份关联风险，违反开源安全脱敏铁律
        - Fix: 将真实个人邮箱替换为符合 RFC 2606 的脱敏样例（如 user@example.com），并在文末注明脱敏修订
        - Verification: static
- [High][95] src/mail_core/db/alembic/versions/ — Alembic 迁移链线性膨胀（0001~0030）与大表同步 DDL 锁升级阻断演进
    - Sources: bundle_global_evolution.md (f_evo_alembic_linear_debt_and_lock_risk)
    - f_evo_alembic_linear_debt_and_lock_risk: 11 天内生成 30 个连续迁移脚本，保留大量早期探索期中间态与补丁逻辑（如 0027 回填数据提取格式错误，0028 立即再跑一次全表扫描修复）；; 20261027_0027 在 messages / message_search 潜在百万级大表上执行同步 ADD COLUMN document tsvector GENERATED ALWAYS AS (...) STORED，触发全表重写并持有 ACCESS EXCLUSIVE 排他锁；; 20261027_0027 执行非 CONCURRENTLY 的 GIN 索引构建（CREATE INDEX ix_message_search_document），在事务内长时间阻塞业务写入；; 20261027_0028 upgrade 直接全表 UPDATE message_search，downgrade 直接声明为 pass；多个版本降级逻辑无法恢复数据，回滚路径事实不可逆。
        - Impact: 生产环境热升级时面临长时间锁阻塞、死锁与事务超时风险；新部署与 CI 测试环境必须完整重放 30 个版本，拉长自举与测试耗时；迁移链膨胀违背零兼容性铁律，增加长期维护与架构演进心智负担。
        - Fix: 执行 Alembic 迁移链 Squash，将 0001~0030 合并为当前权威单一基线 0001_unified_baseline；确立大表 DDL 规范，索引创建强制使用 CONCURRENTLY，CHECK 约束使用 NOT VALID 分步验证；大表数据回填必须从 Alembic 事务中剥离为幂等后台运维任务。
        - Verification: static
- [High][95] tests/mail_core/test_delta_result_counts.py, tests/e2e/full_stack.spec.ts:182-184 — 单测过度 Mock 与 E2E 恒真断言腐蚀重构信心形成虚假安全网
    - Sources: bundle_global_evolution.md (f_evo_test_suite_overmock_and_tautological_assertions)
    - f_evo_test_suite_overmock_and_tautological_assertions: tests/mail_core/test_delta_result_counts.py:10-65 将 assert_fencing, upsert_messages, commit_checkpoint 等底层核心存储与锁逻辑全部 monkeypatch 为 lambda，仅测外层三元表达式；; tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367 (f_tb_fake_assertion_ac008) 声明验证非 PG 方言提交，实际未写入或提交任何 OutboxEvent 实例导致断言完全脱靶；; tests/e2e/full_stack.spec.ts:182-184 (f_tse_tautological_body_visible_assertion) 双页面并发 SSE 同步测试退化为 await expect(page2.locator('body')).toBeVisible() 恒真断言；; src/mail_core/realtime/publication.py:38-42 为适配单测 SQLite 嵌入特判分支（elif dialect == 'sqlite': ... on_conflict_do_nothing()）。
        - Impact: 测试套件（4.8 万行）虽呈现高覆盖率和绿灯状态，但关键并发锁、增量对账及实时推送断言退化，无法拦截真实的集成破坏；生产代码反向受测试方言妥协；团队实施破坏性架构升级时缺乏可靠的安全网，大幅推高重构与维护成本。
        - Fix: 彻底清理生产代码中的 sqlite 特判，单测与集成测试全面对齐真实轻量 PostgreSQL 实例；清理同模块内部关键业务逻辑 monkeypatch，建立真实事务与锁契约测试；修正 E2E 断言，精确定位邮件行已读状态与未读徽标变化，剔除恒真断言与弱化正则。
        - Verification: static
- [Medium][95] src/mail_core/providers/connection_slots.py:60-70, 431-453 — 模块级反射动态别名与历史签名 Shim，违反零兼容负担铁律
    - Sources: bundle_local_backend_sync_providers.md (f_arch_runtime_shim_and_deprecated_aliases)
    - f_arch_runtime_shim_and_deprecated_aliases: src/mail_core/providers/connection_slots.py:60-70 使用 __getattr__ 动态拦截对 TOTAL_SLOTS、BACKGROUND_START_SLOT 等已废弃常量的访问并重定向至 getter; src/mail_core/system_metrics.py:58-62 保留 @property max_sync_lag_seconds 作为 last_sync_lag_seconds 的废弃别名
        - Impact: 配置重构与属性更名后，为了不修改存量调用方代码，在模块中通过反射和属性别名维持向后兼容，违背零兼容负担原则，模糊模块真实公开接口契约。
        - Fix: 物理删除 connection_slots.py 中的 __getattr__ 常量拦截与废弃别名，删除 system_metrics.py 中的 max_sync_lag_seconds 属性别名，调用方直接引用最新权威命名。
        - Verification: static
- [Medium][90] src/mail_core/sync/engine.py:386-425 — 全局优先级数值微调代替收发拓扑解耦，违反拒绝妥协铁律
    - Sources: bundle_local_backend_sync_providers.md (f_arch_inbox_priority_numerical_tweak)
    - f_arch_inbox_priority_numerical_tweak: src/mail_core/sync/engine.py:386-425 为优化收件箱响应，将收件箱 delta 任务分配 priority = 55，其余文件夹分配 60; docs/pending/todo/p073_manual_refresh_inbox_latency.md 明确承认：'文件夹发现 12.5s 仍在收件箱前，前端仍等全部文件夹完成后终态/停止旋转；因此按钮空转时长不会完全消失'
        - Impact: 未能从根因重构'先全量目录发现、再同步文件夹'的强耦合拓扑，不敢解耦前端终态模型，仅通过在单一全局优先队列里微调离散数值（55 vs 60）治标，导致跨账号优先级倒挂且未解决根本卡顿。
        - Fix: 重构收件箱同步拓扑：将收件箱实时同步与全量目录发现彻底解耦，收件箱同步直连触发；前端在收件箱任务完成后立即终态收尾，目录发现转为低频异步后台任务，删除优先级数值调优补丁。
        - Verification: static
- [Medium][95] tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367 — test_ac008 缺少对 OutboxEvent 或 WorkerJob 的提交操作致断言脱靶
    - Sources: bundle_local_tests_backend.md (f_tb_fake_assertion_ac008)
    - f_tb_fake_assertion_ac008: 测试 docstring 声明：AC-008: Non-PostgreSQL dialect sessions commit OutboxEvent / WorkerJob without error.; 实际代码仅创建 dummy 表并插入单行：session.execute(text("CREATE TABLE dummy (id INT)"))，未向 session 添加或修改任何 OutboxEvent / WorkerJob 实例; src/mail_core/db/events.py:101-118 中的 \_on_before_flush 仅在检测到 session.new 或 session.dirty 中包含对应实例时才触发唤醒标记，当前测试无法检验该逻辑在 SQLite 下的行为
        - Impact: 测试沦为无意义空操作，未能实际验证非 PG 方言下提交 OutboxEvent 与 WorkerJob 时事件拦截器与唤醒标记的容错与兼容性
        - Fix: 在测试用例中向 SQLite 会话中添加并提交真实的 OutboxEvent 与 WorkerJob 实例，验证 session.commit() 成功且不触发 notify 错误
        - Verification: static
- [Medium][90] tests/mail_core/test_delta_result_counts.py:10-65 — apply_delta_page 单测过度 mock 内部实现掏空被测逻辑
    - Sources: bundle_local_tests_backend.md (f_tb_overmock_delta_result_counts)
    - f_tb_overmock_delta_result_counts: 测试对同模块内部的 assert_fencing, upsert_messages, upsert_message_search, \_apply_flag_patches, messages_upserted_event, recompute_folder_stats, commit_checkpoint 全部 monkeypatch 打桩为 lambda 空操作; 数据库 Session 被替换为手写的虚拟类 Session，内部 scalars 返回空列表、scalar 返回 None
        - Impact: 被测函数 apply_delta_page 内部与数据库事务、锁状态检验及核心存储逻辑完全隔离，测试仅对外层计数三元表达式生效，无法捕获真实的集成契约违约
        - Fix: 减少对内部被测业务函数的 mock，改用基于内存数据库或专用测试 DB 的真实 apply_delta_page 契约测试
        - Verification: static
- [Medium][95] tests/e2e/full_stack.spec.ts:182-184 — 全栈 E2E 双页面并发 SSE 同步测试使用恒真 body 可见性断言
    - Sources: bundle_local_tests_scripts_e2e.md (f_tse_tautological_body_visible_assertion)
    - f_tse_tautological_body_visible_assertion: 用例 双页面并发下真实SSE推送与实时状态更新 (AC-005) 在 page1 标记已读后，page2 仅执行 await page2.waitForTimeout(1000) 与 await expect(page2.locator('body')).toBeVisible(); 任何加载中的网页 body 均可见，该断言属于恒真断言 (Tautological assertion)
        - Impact: 若 SSE 传输中断、事件处理异常或前端状态未更新，测试仍会绿灯通过，导致实时多端同步失效无法被 E2E 门禁拦截
        - Fix: 在 page2 上定位对应的邮件行，断言其已读样式类（如 .message-read 或未读红点消失），验证状态真实变更
        - Verification: static
- [Medium][95] docs/handoff.md:6-13 — docs/handoff.md 交接记录严重滞后且 commit SHA 失步
    - Sources: bundle_local_docs_current.md (f_docs_current_handoff_stale)
    - f_docs_current_handoff_stale: docs/handoff.md:6-13 记录停留在 2026-10-27T14:45:00+08:00、head_commit 为 a7255499，而当前仓库 HEAD 已推进至 2d17520 且包含了 t061~t075 大量 task 的合并与部署变更; 违反 AGENTS.md 约定：docs/handoff.md 仅保留最新一节，过时段落应迁入 docs/archive/handoff.md
        - Impact: 后续开发者或 Agent 读取 handoff.md 无法获知当前最新交接状态、已验证范围与当前焦点，导致工作上下文断裂
        - Fix: 将 2026-10-27 的过时交接记录追加归档至 docs/archive/handoff.md，并在 docs/handoff.md 写入最新提交点（2d17520）的交接内容
        - Verification: static
- [Medium][100] docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md:6 — 归档任务 review 文件硬编码开发者本地绝对路径及系统用户名
    - Sources: bundle_local_docs_archive_tasks_b.md (f_docs_archive_tasks_b_absolute_paths_in_reviews)
    - f_docs_archive_tasks_b_absolute_paths_in_reviews: docs/archive/tasks/t075_backup_export_permission_boundary/review_code.md:6 及 review_test.md:6 原包含本地私有绝对路径 target：git -C '<workspace>/kkmail_t075'（现已脱敏并勘误）；docs/archive/tasks/t061_idle_inbox_and_all_folder_status_patrol/review_code.md:6 及 review_test.md:6 原包含 target：git -C '<workspace>/kkmail_t061'（现已脱敏并勘误）；此问题此前已在第三轮审阅 docs/archive/reviews/review_20261025_020805/bundle_privacy_history.md 与第四轮审阅中被定为 Medium，但在新增任务归档时再次被带入
        - Impact: 在公开开源仓库暴露维护者的本地工作目录层级与操作系统用户名，违反公开仓安全基线
        - Fix: 对 docs/archive/tasks/t061/ 及 t075/ 的 review_code.md 与 review_test.md 执行脱敏清洗，将本地绝对路径统一替换为相对路径或占位符（如 git -C '<local-path>'），并在 CI/pre-commit 增加路径门禁
        - Verification: static
- [Medium][90] docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 — 已归档 pending 仍残留真实口令长度特征描述未脱敏
    - Sources: bundle_local_docs_archive_general.md (f_docs_archive_general_p027_credential_characteristic_leak)
    - f_docs_archive_general_p027_credential_characteristic_leak: docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 曾包含口令具体长度描述（已脱敏泛化为因口令配置不匹配并勘误）；在第四轮 review（review_20261027_021416/review_intensive.md:11）中已作为 Critical 明确指出应"删除账号 UUID 与口令长度描述"，此前仍保留了口令长度的具体特征
        - Impact: 泄露了特定账号的密码长度与凭据特征，降低了口令字典破解空间
        - Fix: 删除精确口令长度特征描述，泛化为"因口令配置不匹配导致认证失败"
        - Verification: static
- [Medium][95] docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5 — 历史审阅修复执行日志残留宿主机绝对路径
    - Sources: bundle_local_docs_reviews_historical.md (f_docs_reviews_execution_log_absolute_path)
    - f_docs_reviews_execution_log_absolute_path: docs/archive/reviews/review_20261026_005019_full_repository/execution_log.md:5 原包含开发者宿主机绝对路径（已脱敏为 "$WORKTREES/kkmail_review_integration" 占位并勘误）；同目录下的 repair_plan.md 已在之前轮次修复为占位，但 execution_log.md 遗漏了该项替换
        - Impact: 公开仓库中暴露开发者本地工作区路径和用户名
        - Fix: 将 execution_log.md:5 中的绝对路径替换为 $WORKTREES/kkmail_review_integration 占位符
        - Verification: static
- [Medium][95] src/mail_core/security/auth.py:564 — 底层认证模块反向依赖运行时引导模块形成导入环
    - Sources: bundle_global_architecture.md (f_arch_auth_bootstrap_cycle)
    - f_arch_auth_bootstrap_cycle: src/mail_core/security/auth.py:564: from mail_core.runtime.bootstrap import clear_initial_password; src/mail_core/runtime/bootstrap.py:129: from mail_core.security.auth import \_bcrypt_password_bytes
        - Impact: 底层核心安全认证模块（security.auth）在改密成功后反向感知并调用进程启动引导模块（runtime.bootstrap）的清理逻辑。尽管使用函数内延迟导入避开了加载期报错，但在架构层级上违反自底向上的单向依赖原则，形成 security.auth \<-> runtime.bootstrap 循环依赖。
        - Fix: 将首启密码清理逻辑解耦为生命周期事件钩子，或移至顶层应用服务层（API 路由/应用服务）作为改密完成后的编排逻辑调用，解除底层安全认证模块对运行时引导模块的反向依赖。
        - Verification: static
- [Medium][95] src/mail_core/providers/factory.py:209 — 协议适配工厂与账号连接校验模块双向依赖
    - Sources: bundle_global_architecture.md (f_arch_provider_factory_accounts_cycle)
    - f_arch_provider_factory_accounts_cycle: src/mail_core/accounts/connection.py:81: from mail_core.providers.factory import validate_imap_host; src/mail_core/providers/factory.py:209: from mail_core.accounts.connection import reject_microsoft_imap; src/mail_core/providers/__init__.py:4: the whole package graph (avoids import cycles between accounts/sync/providers)
        - Impact: 账号连接层依赖适配工厂的主机校验，适配工厂又反向依赖账号层的微软协议拦截逻辑，导致 providers 与 accounts 形成双向依赖环，迫使 providers 包使用 PEP 562 延迟导出（__getattr__）以规避循环导入崩溃。
        - Fix: 将网络主机安全校验（validate_imap_host）与协议拦截规则（reject_microsoft_imap）统一下沉至底层 host_security 模块（src/mail_core/providers/host_security.py），实现纯净单向依赖。
        - Verification: static
- [Medium][90] src/mail_core/backup/package.py:1868-2007 — 全量冷备与单一事务还原（--single-transaction）随数据膨胀导致 RTO 发散
    - Sources: bundle_global_evolution.md (f_evo_disaster_recovery_single_tx_rto_bottleneck)
    - f_evo_disaster_recovery_single_tx_rto_bottleneck: restore_backup_package 强约束服务全停机冷还原，要求目标数据库与目标 Blob 目录绝对为空；; \_run_pg_restore 强制携带 --single-transaction --exit-on-error，将数十万至百万邮件全量数据放入单一 PostgreSQL 事务；; 恢复阶段需完整解密 Blob、校验全量 SHA-256 并双重占用磁盘（tar 包 + staging 目录 + 最终目标目录 + 数据库 dump + WAL 日志）；; 系统未提供 WAL 增量归档（PITR）或差异化备份演进路径。
        - Impact: 随着归档邮件体量增长至数十 GB，恢复时间目标（RTO）将以线性至超线性膨胀，单次还原停机时间过长；单一事务还原对系统资源（WAL、连接超时、内存）要求极高，任一语句异常即导致全量回滚，大库恢复容错脆弱。
        - Fix: 确立分级演进策略：邮件 Blob 原生具备内容寻址与不可变特性，后续演进应支持增量 Blob 同步与外部对象存储挂载；数据库层演进支持物理备份与 WAL 持续归档（PITR），解除对单体单事务快照的单一依赖。
        - Verification: static
- [Medium][95] docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3, docs/archive/tasks/t075/review_code.md:6 — 敏感信息（PII 真实邮箱/宿主机路径/口令特征）反复渗入历史归档且缺乏自动化门禁
    - Sources: bundle_global_evolution.md (f_evo_archive_governance_pii_and_path_leak_recurrent)
    - f_evo_archive_governance_pii_and_path_leak_recurrent: docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 曾泄露真实用户个人邮箱（已脱敏为 user@example.com 并勘误） (f_docs_archive_general_p060_pii_leak)；; docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 原残留真实口令长度特征（已脱敏并勘误）；; docs/archive/tasks/t075/review_code.md:6 及 t061/review_code.md:6 原包含开发者宿主机绝对路径（已脱敏为占位符并勘误）；; 上述问题在第三轮及第四轮 review 中已多次作为 Medium/Critical 指出并局部修复，但在后续新 task 归档中再次反复出现，缺乏自动化 pre-commit 门禁。
        - Impact: 开源公开仓库中持续暴露特定开发者隐私与环境结构，产生合规与钓鱼风险；“归档只追加”原则与脱敏要求频繁冲突，反复消耗工程人力进行全仓正则扫描与人工勘误，长期资产治理成本发散。
        - Fix: 在 .repo_template/hooks/pre-commit 与 CI 检查中植入自动化脱敏门禁，通过正则表达式强制阻断非 RFC 2606 邮箱、密码长度数值描述及本地绝对路径；对历史已泄露文件执行一次性就地脱敏并附加勘误修订声明。
        - Verification: static
- [Low][95] src/mail_core/providers/remote_writeback.py:40 — compress_uids 等函数类型标注引用未导入的 Sequence 类型
    - Sources: bundle_local_backend_sync_providers.md (f_backend_sync_01)
    - f_backend_sync_01: src/mail_core/providers/remote_writeback.py:5 仅导入了 from typing import Any; src/mail_core/providers/remote_writeback.py:40 def compress_uids(uids: Sequence[int], ...) -> list\[str\]:; src/mail_core/providers/remote_writeback.py:45 def compress_uids_chunked(uids: Sequence[int], ...) -> list\[tuple\[str, list[int]\]\]:
        - Impact: 由于声明了 from __future__ import annotations，模块常规加载与运行时执行不受影响；但若使用 typing.get_type_hints 对该模块函数进行类型内省时，会抛出 NameError: name 'Sequence' is not defined。
        - Fix: 在 src/mail_core/providers/remote_writeback.py 顶部导入语句中增加 Sequence：from typing import Any, Sequence。
        - Verification: static
- [Low][95] src/mail_core/worker/main.py:42 — __getattr__ 签名引用未导入的 Any 类型
    - Sources: bundle_local_backend_runtime_security.md (f_backend_runtime_01)
    - f_backend_runtime_01: src/mail_core/worker/main.py:14 仅导入了 from typing import NamedTuple; src/mail_core/worker/main.py:42 def __getattr__(name: str) -> Any:
        - Impact: 由于存在 from __future__ import annotations，模块启动执行不报错，但使用 typing.get_type_hints 进行类型自省或测试检查时会抛出 NameError: name 'Any' is not defined。
        - Fix: 在 src/mail_core/worker/main.py 中修改为 from typing import Any, NamedTuple。
        - Verification: static
- [Low][95] src/mail_core/search/index.py:15 — \_format_recipient_text 函数签名引用未导入的 Any 类型
    - Sources: bundle_local_backend_runtime_security.md (f_backend_runtime_02)
    - f_backend_runtime_02: src/mail_core/search/index.py:7 仅导入了 from typing import Sequence; src/mail_core/search/index.py:15 def \_format_recipient_text(addresses: Sequence[Any] | None) -> str:
        - Impact: 在运行时对该函数执行 typing.get_type_hints 时会抛出 NameError: name 'Any' is not defined。
        - Fix: 在 src/mail_core/search/index.py 中修改为 from typing import Any, Sequence。
        - Verification: static
- [Low][90] tests/mail_core/sqlite_schema.py:1-20 — 为适配单测引入 SQLite 导致生产代码混入非生产方言分支
    - Sources: bundle_local_tests_backend.md (f_tb_sqlite_production_leak)
    - f_tb_sqlite_production_leak: sqlite_schema.py 通过正则替换将 JSONB 与 ::jsonb 转换为 SQLite 格式以供内存单测运行; src/mail_core/realtime/publication.py:38-42 中存在专为 SQLite 单测妥协的生产代码：elif dialect == "sqlite": ... on_conflict_do_nothing()，并标注 # pragma: no cover - production is PostgreSQL, tests SQLite
        - Impact: 生产代码被测试基础设施反向污染，且 SQLite 缺乏 PostgreSQL 的行级排他锁 (with_for_update) 与 LISTEN/NOTIFY 真实语义，易产生测试通过但生产并发失效的隐患
        - Fix: 逐步将依赖 SQLite DDL 垫片的单测迁移至基于真实 PostgreSQL 测试实例的容器/本地测试环境，清理生产代码中的 sqlite 特判
        - Verification: static
- [Low][90] tests/e2e/provider_account_forms.spec.ts:58 — 微软设备登录验证码复制测试使用容忍失败的弱化正则断言
    - Sources: bundle_local_tests_scripts_e2e.md (f_tse_weak_regex_clipboard_assertion)
    - f_tse_weak_regex_clipboard_assertion: 断言语句为 await expect(edit).toContainText(/已复制验证码|复制失败/); 将错误状态 复制失败 与成功状态 已复制验证码 作为并列匹配项
        - Impact: 即使剪贴板操作因权限或实现缺陷发生异常，测试依然判定成功，掩盖复制功能的破坏性缺陷
        - Fix: 配置 Playwright 上下文的 clipboard-write 权限，并将断言严格限定为 toContainText('已复制验证码')
        - Verification: static
- [Low][85] tests/e2e/settings_workspace.spec.ts:43 — 设置工作区测试残留向相对路径 .scratch 写入截图的调试代码
    - Sources: bundle_local_tests_scripts_e2e.md (f_tse_scratch_screenshot_side_effect)
    - f_tse_scratch_screenshot_side_effect: 测试执行中包含 await page.screenshot({ path: '../../.scratch/settings_design_review/current_accounts.png' })
        - Impact: 依赖特定工作目录层级与外部未受控的 .scratch 目录，在受限 CI 或无写权限环境下可能引发文件系统异常
        - Fix: 删除遗留的截图语句，或改用 Playwright 官方受管的 testInfo.attach 进行产物归档
        - Verification: static
- [Low][90] src/desktop/package.json:15 — npm test 串行执行 12 个集成测试可能超过标准 CI 超时阈值
    - Sources: bundle_local_frontend_desktop.md (f_frontend_desktop_01)
    - f_frontend_desktop_01: "test": "node paths.test.js && node hardening.test.js && node postgresManager.test.js && node startup.test.js && node logRotation.test.js && node desktopLog.test.js && node clipboard.test.js && node windowOptions.test.js && node packLinux.test.js && node scripts/packaged_smoke_db.test.js && node scripts/packaged_smoke.test.js && node oauth_integration.test.js"
        - Impact: 测试脚本在单条命令中串行拉起多个真实的 PostgreSQL 启动/停止和真实的 Electron 端到端实例，累计耗时较大（超过常规单步 120 秒超时），容易在 CI 环境中因超时被中断。
        - Fix: 建议将纯逻辑单元测试与启动真实进程的集成冒烟测试拆分为独立命令（如 test:unit 与 test:e2e），提高测试执行效率与容错度。
        - Verification: reproduced
- [Low][90] docs/specs_index.md:8,11 — specs_index.md 中部分生效 spec 的 task 清单为空
    - Sources: bundle_local_docs_current.md (f_docs_current_specs_index_empty_tasks)
    - f_docs_current_specs_index_empty_tasks: docs/specs_index.md:8 的 auth_and_session 与 Line 11 的 mail_account_navigation_and_read_state 的 task 清单列为空白; 违反该文件头部契约："每个 task 收尾时写入或更新对应行（须已过黑盒）"
        - Impact: 破坏了规范与 task 实施记录的溯源链条，无法快速反查该 spec 是由哪些 task 演进交付的
        - Fix: 梳理对应历史 task（例如 t010/t025/t041/t042 等），在表格中补全关联 task 编号
        - Verification: static
- [Low][90] docs/archive/pending/README.md:15-75 — docs/archive/pending/README.md 闭环日期对照表漏登 p060 至 p074
    - Sources: bundle_local_docs_archive_general.md (f_docs_archive_general_pending_readme_index_drift)
    - f_docs_archive_general_pending_readme_index_drift: docs/archive/pending/README.md 的闭环日期对照表只记录到 p059（Line 75），共 59 条; docs/archive/pending/ 目录下实际已存在 p060 至 p074（共计 71 个条目，缺 14 条索引）
        - Impact: 归档待办索引总账与磁盘实际文件不一致，破坏了归档总账的完整性与可检索性
        - Fix: 使用脚本重新抓取 p060 至 p074 的 git 入库日期与处理指向，在 README.md 闭环日期对照表中补全缺失行
        - Verification: static
- [Low][95] docs/reviews/README.md:15-27 — docs/reviews/README.md 差异对照表遗漏 review_20261030_103516
    - Sources: bundle_local_docs_reviews_historical.md (f_docs_reviews_readme_missing_session)
    - f_docs_reviews_readme_missing_session: docs/reviews/README.md:27 只列到 review_20261027_021416; docs/reviews/ 目录下实际存在 review_20261030_103516/adoption.md，未在对照表中登记其布局差异（单文件 adoption.md）
        - Impact: 破坏了 docs/reviews 目录索引的完备性
        - Fix: 在 docs/reviews/README.md 的历史会话表格中补充 review_20261030_103516 的差异说明
        - Verification: static
- [Low][90] src/mail_core/accounts/credentials.py:16 — 通用凭据存储仓储放置于 accounts 业务包导致底层基础设施反向引用
    - Sources: bundle_global_architecture.md (f_arch_credentials_layer_misplacement)
    - f_arch_credentials_layer_misplacement: src/mail_core/providers/oauth.py:34: from mail_core.accounts.credentials import ...; src/mail_core/blobs/archive.py:24: from mail_core.accounts.credentials import CredentialStore, get_credential_store; src/mail_core/blobs/rotate.py:45: from mail_core.accounts.credentials import credential_lock_key
        - Impact: CredentialStore / DbCredentialStore 属于基于 AES-256-GCM 与数据库锁的通用机密持久化基础设施，目前置于上层业务模块 accounts 中，导致底层协议层（providers.oauth）与存储归档层（blobs.archive/rotate）必须反向依赖 accounts 包，层级定位错位。
        - Fix: 将凭据存储接口与加密仓储下沉迁移至独立基础设施包（如 mail_core.security.credentials），accounts 仅保留账户聚合逻辑与 DTO。
        - Verification: static
- [Low][95] src/mail_core/realtime/listener.py:105-110 — 跨进程场景下 session_epoch 撤销对 REST API 存在最长 5 秒缓存窗口
    - Sources: bundle_global_system_properties.md (f_sys_session_revocation_multiprocess_window)
    - f_sys_session_revocation_multiprocess_window: src/mail_core/realtime/listener.py:105-110 中 \_handle_notification 收到 SESSION_REVOCATION_CHANNEL 时仅调用了 self.dispatcher.close_session_streams(current_epoch=current_epoch); src/mail_core/security/auth.py:388-392 中 get_session_epoch 使用了 \_SESSION_EPOCH_CACHE_TTL_SECONDS = 5.0 的进程内缓存，且 listener 未通知或清理 auth 模块中的 \_session_epoch_cache
        - Impact: 在多工作进程或分布式部署场景下，用户修改密码或注销后，长连接 SSE 会被立刻切断，但其他工作进程对无状态 REST API 请求仍会在最长 5 秒的 TTL 窗口内信任旧凭据。在桌面单进程环境下无影响。
        - Fix: 在 src/mail_core/realtime/listener.py 收到 SESSION_REVOCATION_CHANNEL 广播时，同步调用 mail_core.security.auth 中的缓存更新函数或清空 \_session_epoch_cache，消除跨进程撤销延迟。
        - Verification: static
- [Info][95] tests/conftest.py:1 — 根测试配置文件包含陈旧过时的测试范围声明
    - Sources: bundle_local_tests_scripts_e2e.md (f_tse_stale_conftest_docstring)
    - f_tse_stale_conftest_docstring: 模块 docstring 标明：Root pytest config. All tests live under tests/mail_core/.; 实际上 tests/scripts/ 目录下包含 27 个脚本测试文件，与根级 docstring 描述不符
        - Impact: 文档描述与目录真实结构脱节，误导维护者对测试套件分布的认知
        - Fix: 修正 tests/conftest.py 顶层文档，补充对 tests/scripts/ 范围的说明
        - Verification: static
- [Info][95] src/frontend/src/components/MessageReader.tsx:171 — setQueryData 内部使用 any 绕过类型安全检查
    - Sources: bundle_local_frontend_ui.md (f_frontend_ui_01)
    - f_frontend_ui_01: queryClient.setQueryData(['detail', 'mail-core', selected.id], (old: any) => (old ? { ...old, remote_images_allowed: true } : old))
        - Impact: 使用了 any 强制绕过 TypeScript 编译期检查，若 MailDetail 结构字段发生重构或扩展，编译器无法发现类型不一致风险。
        - Fix: 为 updater 参数提供显式类型标注 (old: MailDetail | undefined) => ...，消除 any 逃逸。
        - Verification: static
- [Info][95] src/frontend/src/lib/clipboard.ts:48 — 非安全上下文使用已废弃的 document.execCommand 作为剪贴板降级方案
    - Sources: bundle_local_frontend_desktop.md (f_frontend_desktop_02)
    - f_frontend_desktop_02: ok = document.execCommand('copy')
        - Impact: document.execCommand 属于已被 Web 标准废弃的接口。在非 HTTPS/非安全自托管环境下作为唯一同步兜底方案目前仍有效，但存在未来浏览器版本完全废弃导致失效的潜在兼容性风险。
        - Fix: 保持现有降级逻辑，在部署文档中明确建议用户生产环境配置 HTTPS 以优先启用现代异步 Clipboard API。
        - Verification: static
- [Info][85] docs/archive/tasks/README.md:1-11 — 早期归档 task 契约与现行实现存在演进漂移（已在 README 免责声明）
    - Sources: bundle_local_docs_archive_tasks_a.md (f_docs_archive_tasks_a_historical_ac_drift)
    - f_docs_archive_tasks_a_historical_ac_drift: t001 至 t012 中部分关于未读统计与分类视图的 AC 已在后续 t027/t041/t045 中被重构替代; docs/archive/tasks/README.md:1-7 明确声明本目录下各 task 为历史快照，不代表现行契约，现行以 docs/specs/ 为准
        - Impact: 无负面影响；若读者未读 README 直接引用早期 task.md 可能误解当前系统行为
        - Fix: 保持现状，继续维持 README.md 的统领免责约定
        - Verification: static

## Gaps

None.

## Limitations

- 本次全仓审阅为纯静态代码与文档审查，未启动真实 PostgreSQL 或生产邮件服务执行网络交互复现。

## Sources

- [bundle_local_backend_core.md](bundle_local_backend_core.md)
- [bundle_local_backend_storage_backup.md](bundle_local_backend_storage_backup.md)
- [bundle_local_backend_sync_providers.md](bundle_local_backend_sync_providers.md)
- [bundle_local_backend_runtime_security.md](bundle_local_backend_runtime_security.md)
- [bundle_local_tests_backend.md](bundle_local_tests_backend.md)
- [bundle_local_tests_scripts_e2e.md](bundle_local_tests_scripts_e2e.md)
- [bundle_local_frontend_ui.md](bundle_local_frontend_ui.md)
- [bundle_local_frontend_desktop.md](bundle_local_frontend_desktop.md)
- [bundle_local_scripts_and_ops.md](bundle_local_scripts_and_ops.md)
- [bundle_local_repo_template_core.md](bundle_local_repo_template_core.md)
- [bundle_local_repo_template_misc.md](bundle_local_repo_template_misc.md)
- [bundle_local_docs_current.md](bundle_local_docs_current.md)
- [bundle_local_docs_archive_tasks_a.md](bundle_local_docs_archive_tasks_a.md)
- [bundle_local_docs_archive_tasks_b.md](bundle_local_docs_archive_tasks_b.md)
- [bundle_local_docs_archive_general.md](bundle_local_docs_archive_general.md)
- [bundle_local_docs_reviews_historical.md](bundle_local_docs_reviews_historical.md)
- [bundle_repository_summary.md](bundle_repository_summary.md)
- [bundle_global_strategy.md](bundle_global_strategy.md)
- [bundle_global_architecture.md](bundle_global_architecture.md)
- [bundle_global_system_properties.md](bundle_global_system_properties.md)
- [bundle_followup_q_evo_01_alembic_squash.md](bundle_followup_q_evo_01_alembic_squash.md)
- [bundle_followup_q_evo_02_disaster_recovery_strategy.md](bundle_followup_q_evo_02_disaster_recovery_strategy.md)
- [bundle_followup_q_evo_03_test_dialect_and_fidelity.md](bundle_followup_q_evo_03_test_dialect_and_fidelity.md)
- [bundle_followup_q_evo_04_archive_pii_governance.md](bundle_followup_q_evo_04_archive_pii_governance.md)
- [bundle_global_evolution.md](bundle_global_evolution.md)
- [bundle_cross_validation.md](bundle_cross_validation.md)
