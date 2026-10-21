# 审阅结果决策

## 目录

docs/reviews/review_20261022_052842

## 报告来源

- 已读：bundle_cross_validation.md, bundle_v1_security.md, bundle_v2_correctness.md, bundle_v3_contracts.md, bundle_v4_performance.md, bundle_v5_architecture.md, bundle_v6_robustness.md, bundle_v7_tests.md, bundle_v8_docs.md, review_intensive.md
- 缺失：无
- 合并说明：原始 86 项 finding（Critical=6, High=22, Medium=28, Low=27, Info=3）经交叉核验、去重与聚类合并为 67 项决策条目。原 4 项待决定项（D1-D4）经用户决策已全部转为采纳项（A53-A56），最终形成采纳 56 项、不采纳 11 项、待决定 0 项。其中死代码与死 import 统一收拢为 A46；文档断链与旧路径统一收拢为 A47；跨 bundle 交叉确认项（如单实例锁、会话无缓存查库、日志脱敏等）来源均已列全并吸收 bundle_cross_validation 验证结论。

## 统计

- 采纳：56 项
- 不采纳：11 项
- 待决定：0 项

## 待决定项（请先决策）

无（全部待决定项已完成决策并转入采纳项）

## 采纳项

### A1. 桌面端增加单实例锁

- 来源：bundle_v2_correctness, bundle_cross_validation, review_intensive
- 位置：src/desktop/main.js:189
- 优先级：CRITICAL
- 详细判断理由：未调用 app.requestSingleInstanceLock()。多开时第 2 实例关闭会调用 pg.stop() 误杀正在运行的 PostgreSQL，造成数据损坏与主实例崩溃。收益明确，成本低，无副作用。
- 修复说明：在 main.js 入口处调用 app.requestSingleInstanceLock()，若未获取则立即退出并唤醒/聚焦已有窗口。

### A2. 会话认证 Epoch 增加短期内存缓存

- 来源：bundle_v4_performance, bundle_cross_validation, review_intensive
- 位置：src/mail_core/security/auth.py:206-288
- 优先级：CRITICAL
- 详细判断理由：每次带有 Cookie 的请求均同步开启 DB Session 查询 AuthCredential，并发时瞬间耗尽连接池（默认 10）。
- 修复说明：在 auth.py 中增加带有短期 TTL（如 3-5 秒）的全局内存缓存，并在修改密码/主动失效时同步清理缓存，避免认证路径每次请求开启独立 DB 事务。

### A3. message_archive_state 核心状态表添加二级索引

- 来源：bundle_v4_performance, bundle_cross_validation, review_intensive
- 位置：src/mail_core/blobs/archive.py:158-216
- 优先级：CRITICAL
- 详细判断理由：Worker 调度器高频轮询 claim_archive_batch，缺失 (state, priority) 索引导致全表扫描，大量邮件下打爆磁盘 I/O。
- 修复说明：新建 Alembic 迁移脚本，添加复合索引 CREATE INDEX ix_archive_claim ON message_archive_state (state, priority) WHERE claimed_by IS NULL;。

### A4. 生产容器启动模式显式装配日志脱敏格式化器

- 来源：bundle_v6_robustness, bundle_cross_validation, review_intensive
- 位置：Dockerfile.mail-core:25, src/mail_core/api/app.py
- 优先级：CRITICAL
- 详细判断理由：Dockerfile 采用 uvicorn mail_core.api.app:app 启动，未走 __main__.py，app.py lifespan 未装配 RedactingTraceFormatter，导致生产容器日志敏感信息未脱敏。
- 修复说明：在 app.py 的 lifespan 初始化中显式调用 configure_logging(service_name="mail-core-api")。

### A5. 数据库迁移脚本移除硬编码默认密钥

- 来源：bundle_v1_security, bundle_v6_robustness, bundle_cross_validation, review_intensive
- 位置：scripts/migrate_from_legacy_db.py:68-69
- 优先级：HIGH
- 详细判断理由：脚本包含硬编码的 256 位密钥字面量，违反规范与安全约定。环境变量缺失时应 fail-closed。
- 修复说明：移除硬编码密钥 fallback，若 LEGACY_SECRET_KEY 环境变量未提供则抛错退出。

### A6. Chaos 脚本修正数据库名检查通配符

- 来源：bundle_v6_robustness, bundle_cross_validation, review_intensive
- 位置：scripts/mail-core-chaos-lease.sh:16
- 优先级：HIGH
- 详细判断理由：子串通配 *test* 会误放行带 test 的生产库名（如 attest_db）。
- 修复说明：改为严格前缀/后缀正则匹配（如 ^.\*\_test$）。

### A7. ColumnResize 拖拽优化与主组件 React.memo 包裹

- 来源：bundle_v4_performance, bundle_cross_validation, review_intensive
- 位置：src/frontend/src/App.tsx:108
- 优先级：HIGH
- 详细判断理由：拖拽期间 60Hz 触发父组件重渲与 localStorage 同步写盘，引发主线程严重掉帧。
- 修复说明：拖拽过程通过原生 style/CSS 变量调整，释放鼠标时才提交 store 持久化；对 Sidebar、MessageList、MessageReader 添加 React.memo。

### A8. 邮件列表过滤与排序增加 useMemo

- 来源：bundle_v4_performance, bundle_cross_validation, review_intensive
- 位置：src/frontend/src/components/MessageList.tsx:182
- 优先级：HIGH
- 详细判断理由：列表渲染时每次无条件重跑 filter 和 sort，数千次正则解析日期字符串消耗 CPU。
- 修复说明：将排序和过滤结果用 useMemo 缓存，并预先计算毫秒时间戳。

### A9. 路由层 accounts.py 操作 ORM 实体收拢至 application 层

- 来源：bundle_v3_contracts, bundle_v5_architecture, bundle_cross_validation, review_intensive
- 位置：src/mail_core/api/accounts.py:24
- 优先级：HIGH
- 详细判断理由：路由层直接导入 ORM 模型并手动管理事务，击穿分层架构。
- 修复说明：在 application 层封装 DTO 与业务逻辑，accounts.py 仅消费 application 接口。

### A10. conftest.py 统一 MAIL_CORE_REQUIRE_DB 门禁匹配

- 来源：bundle_v7_tests, review_intensive
- 位置：tests/mail_core/conftest.py:83
- 优先级：HIGH
- 详细判断理由：skip reason 为 database required 或 PG required 时未命中 MAIL_CORE_DATABASE_URL 子串匹配，导致 CI 门禁失效。
- 修复说明：放宽子串匹配条件或正则匹配所有数据库相关的 skip reason。

### A11. FastAPI 顶层补充基础安全响应头

- 来源：bundle_v1_security, review_intensive
- 位置：src/mail_core/api/app.py:59-76
- 优先级：HIGH
- 详细判断理由：Web/Docker 模式下缺失 X-Content-Type-Options: nosniff、X-Frame-Options、HSTS 等基础安全响应头。
- 修复说明：在 FastAPI 中间件中统一注入安全响应头。

### A12. 支持反向代理 proxy-headers 与 forwarded_allow_ips

- 来源：bundle_v1_security, review_intensive
- 位置：src/mail_core/api/app.py:79-94, src/mail_core/__main__.py
- 优先级：HIGH
- 详细判断理由：反代部署时 client IP 均为网关 IP，单人输错密码限流导致全员被封锁。
- 修复说明：支持通过环境变量或启动参数装配 uvicorn 的 proxy-headers 和 forwarded_allow_ips。

### A13. 修复 loadRemoteImages 状态切换滞后泄露远程请求

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/frontend/src/components/MessageReader.tsx:22
- 优先级：HIGH
- 详细判断理由：切换邮件时以旧的 loadRemoteImages=true 先渲染了一帧，导致新邮件远程图片请求外联泄露。
- 修复说明：为 iframe 添加动态 key（如 mailKey），强制随邮件切换销毁重建 DOM，或从当前选中邮件状态同步派生。

### A14. 桌面端退出时序调整为等 sidecar 退出后再停 PostgreSQL

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/desktop/main.js:231
- 优先级：HIGH
- 详细判断理由：关闭时立即 kill PG 导致 sidecar 退出收尾时抛异常。
- 修复说明：等待 sidecar 进程退出后再调用 pg.stop()。

### A15. 附件链接添加 download 与 target 避免 Electron 顶层白屏

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/frontend/src/components/MessageReader.tsx:202
- 优先级：HIGH
- 详细判断理由：点击 PDF/图片附件导致 Electron 顶层窗口被导航至文件流，整套 SPA 被替换白屏。
- 修复说明：为附件链接添加 download 属性，并在 Electron will-navigate 中拦截下载流。

### A16. 修复 SSE 连接槽位计数器异常泄漏导致 503

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/mail_core/api/sse.py:157-198
- 优先级：HIGH
- 详细判断理由：提前递增计数器且在生成器外异常时未递减，槽位虚假耗尽。
- 修复说明：将获取计数器移入异步上下文管理器或生成器内部最前端。

### A17. iframe 沙箱支持 allow-popups-to-escape-sandbox

- 来源：bundle_v3_contracts, review_intensive
- 位置：src/frontend/src/lib/mailBody.ts:40
- 优先级：HIGH
- 详细判断理由：Web SPA 模式下外部新窗口继承沙箱标记导致脚本失效无法浏览。
- 修复说明：在沙箱属性中声明 allow-popups-to-escape-sandbox。

### A18. messages 表为 internet_message_id 补全索引

- 来源：bundle_v4_performance, review_intensive
- 位置：src/mail_core/threading/rules.py:149-168
- 优先级：HIGH
- 详细判断理由：线程归约时按 internet_message_id 查询执行全表扫描。
- 修复说明：新建 Alembic 迁移添加 ix_messages_account_internet_id 复合索引。

### A19. IMAP 元数据与 Flags 拉取支持 UID 批处理

- 来源：bundle_v4_performance, review_intensive
- 位置：src/mail_core/providers/imap.py:249-388
- 优先级：HIGH
- 详细判断理由：串行逐条 FETCH 带来海量网络往返 RTT。
- 修复说明：按逗号分隔批次合并 UID，单次 FETCH 拉取。

### A20. 租约 assert_fencing 增加过期时间检查

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/mail_core/sync/leases.py:121-129
- 优先级：HIGH
- 详细判断理由：长 GC 导致租约过期后若无新抢占，旧 Worker 依然能提交数据，时效互斥失效。
- 修复说明：在 assert_fencing 校验中补全过期时间判定，并在释放时推进 token。

### A21. IMAP UID FETCH 空响应容错跳过

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/mail_core/providers/imap.py:255-258
- 优先级：HIGH
- 详细判断理由：远端邮件被删后返回空响应导致同步死循环崩溃。
- 修复说明：空响应判定为已删除，跳过该 UID 继续推进 cursor。

### A22. message_search 全文搜索 from_text 补全三元组索引

- 来源：bundle_v4_performance, review_intensive
- 位置：src/mail_core/search/index.py:40-89
- 优先级：HIGH
- 详细判断理由：from_text 缺少三元组索引导致包含 from_text 的 OR 表达式退化为全表扫描。
- 修复说明：新建 Alembic 迁移添加 GIN 三元组索引。

### A23. 移除 Sidebar 轮询不存在的 /api/accounts//folders 接口

- 来源：bundle_v4_performance, bundle_v5_architecture, review_intensive
- 位置：src/frontend/src/components/Sidebar.tsx:19
- 优先级：MEDIUM
- 详细判断理由：后端无此接口，固定产生 404 网络错误后再 fallback。
- 修复说明：直接调用已有的 /api/mail/accounts/{id}/folder-stats。

### A24. testing.md 补充后端测试命令 pytest tests/mail_core

- 来源：bundle_v7_tests, review_intensive
- 位置：docs/blueprint/testing.md:18
- 优先级：MEDIUM
- 详细判断理由：机器锚点 ## test_cmd 遗漏核心后端测试命令。
- 修复说明：在 ## test_cmd 补充 pytest tests/mail_core -q。

### A25. 会话 Cookie 默认 Secure 增强

- 来源：bundle_v1_security, review_intensive
- 位置：src/mail_core/security/auth.py:73-80
- 优先级：MEDIUM
- 详细判断理由：未配置环境变量且经由反向代理时缺少 Secure 保护。
- 修复说明：支持检测 X-Forwarded-Proto: https 或提供自适应判定。

### A26. 邮件正文渲染增强 noopener 与 no-referrer

- 来源：bundle_v3_contracts, review_intensive
- 位置：src/frontend/src/lib/mailBody.ts:36
- 优先级：MEDIUM
- 详细判断理由： 不被规范支持，外链点击存在 Referer 泄露与 opener 滥用风险。
- 修复说明：在 head 注入 ，并在 DOMPurify 钩子强制添加 rel 与 target。

### A27. ready 接口封装数据库健康检查至 storage 模块

- 来源：bundle_v5_architecture, review_intensive
- 位置：src/mail_core/api/app.py:144
- 优先级：MEDIUM
- 详细判断理由：路由层穿透执行裸 SQL，击穿分层。
- 修复说明：封装至 storage/health 辅助函数。

### A28. 前端增加模块级局部 ErrorBoundary 降级

- 来源：bundle_v5_architecture, review_intensive
- 位置：src/frontend/src/main.tsx:15
- 优先级：MEDIUM
- 详细判断理由：单点渲染报错导致全局白屏。
- 修复说明：为主要视图组件分别添加局部 ErrorBoundary。

### A29. security.md 修正 uvicorn 反代 IP 配置说明

- 来源：bundle_v8_docs, review_intensive
- 位置：docs/guides/security.md:71
- 优先级：MEDIUM
- 详细判断理由：指南自相矛盾（声称环境变量，实则需命令行参数）。
- 修复说明：更正为命令行参数说明。

### A30. troubleshooting.md 改密 SQL 示例补充 session_epoch 自增

- 来源：bundle_v8_docs, review_intensive
- 位置：docs/guides/troubleshooting.md:44
- 优先级：MEDIUM
- 详细判断理由：未递增 session_epoch 破坏会话吊销机制。
- 修复说明：SQL 示例补充 session_epoch = session_epoch + 1。

### A31. 后端版本号 __version__ 与 VERSION 文件对齐

- 来源：bundle_v8_docs, review_intensive
- 位置：src/mail_core/__init__.py:6
- 优先级：MEDIUM
- 详细判断理由：报告版本为 0.1.0 与全局 3.0.20 漂移。
- 修复说明：对齐为当前统一版本。

### A32. MessageReader 中 buildMailSrcdoc 增加 useMemo 缓存

- 来源：bundle_v4_performance, review_intensive
- 位置：src/frontend/src/components/MessageReader.tsx:190
- 优先级：MEDIUM
- 详细判断理由：每次组件渲染无条件重复调用 DOMParser 序列化大 HTML。
- 修复说明：以 body 和 loadRemoteImages 为依赖包裹 useMemo。

### A33. run-mail-core-tests.sh 补充数据库名保护检查

- 来源：bundle_v6_robustness, review_intensive
- 位置：scripts/run-mail-core-tests.sh:11
- 优先级：MEDIUM
- 详细判断理由：防止误传生产数据库导致测试脚本直接执行迁移与数据冲刷。
- 修复说明：执行前检查库名必须包含 test。

### A34. SSE 401/403 认证失效后派发 UNAUTHORIZED_EVENT

- 来源：bundle_v6_robustness, review_intensive
- 位置：src/frontend/src/hooks/useMailCoreRealtime.ts:151
- 优先级：MEDIUM
- 详细判断理由：失效后静默停止，前端页面不提示登录已失效。
- 修复说明：触发全局事件联动唤起登录态刷新。

### A35. 更新 handoff.md 记录最新 head_commit 与完成状态

- 来源：bundle_v8_docs, review_intensive
- 位置：docs/handoff.md:9
- 优先级：MEDIUM
- 详细判断理由：交接文档落后多个 commit。
- 修复说明：更新至最新已完成状态。

### A36. 扩展日志脱敏正则覆盖 Basic Auth 与代理 URL 凭据

- 来源：bundle_v1_security, bundle_v6_robustness, review_intensive
- 位置：src/mail_core/security/redact.py:14-23
- 优先级：MEDIUM
- 详细判断理由：未覆盖 Basic 认证或带密码的代理 URL。
- 修复说明：扩充正则脱敏规则。

### A37. 邮件列表分页合并增加 ID 去重

- 来源：bundle_v2_correctness, bundle_v4_performance, review_intensive
- 位置：src/frontend/src/components/MessageList.tsx:158
- 优先级：MEDIUM
- 详细判断理由：游标重叠产生重复 key 警告与渲染错乱。
- 修复说明：flatMap 后按 m.id 去重。

### A38. DOMPurify 启用 USE_PROFILES 禁用 XML 命名空间

- 来源：bundle_v3_contracts, bundle_v4_performance, review_intensive
- 位置：src/frontend/src/lib/mailBody.ts:12
- 优先级：MEDIUM
- 详细判断理由：黑名单过滤防 mXSS 不彻底。
- 修复说明：配置 USE_PROFILES: { html: true }。

### A39. RotatingLogStream 改用异步写盘避免主线程阻塞

- 来源：bundle_v4_performance, bundle_v6_robustness, review_intensive
- 位置：src/desktop/logRotation.js:87
- 优先级：MEDIUM
- 详细判断理由：fs.writeSync 阻塞 Electron 主事件循环导致界面掉帧。
- 修复说明：改用非阻塞文件流或缓冲异步写入。

### A40. 桌面端数据目录创建统一限制为 0700 权限

- 来源：bundle_v6_robustness, review_intensive
- 位置：src/desktop/postgresManager.js:131
- 优先级：MEDIUM
- 详细判断理由：0755 导致共享机器本地多用户可读取邮件和备份。
- 修复说明：目录权限收紧为 0700。

### A41. 账户同步异常处理补全 warning 日志与显式回滚

- 来源：bundle_v6_robustness, review_intensive
- 位置：src/mail_core/worker/handlers.py:190
- 优先级：MEDIUM
- 详细判断理由：except Exception: pass 静默吞掉异常导致事务脏状态。
- 修复说明：记录日志并显式 rollback。

### A42. 添加账户增加内网保留 IP 校验防止 SSRF

- 来源：bundle_v1_security, bundle_v6_robustness, review_intensive
- 位置：src/mail_core/providers/factory.py:72-80
- 优先级：MEDIUM
- 详细判断理由：允许填入 127.0.0.1 探测内网端口。
- 修复说明：增加 Host 私网地址过滤校验。

### A43. recompute_folder_stats 加行锁防止并发更新覆盖

- 来源：bundle_v2_correctness, bundle_v4_performance, review_intensive
- 位置：src/mail_core/mail/storage/folder_stats.py:15-39
- 优先级：MEDIUM
- 详细判断理由：并发更新未读数存在 Lost Update。
- 修复说明：查询行时增加锁保护或采用 ON CONFLICT DO UPDATE。

### A44. 线程关联并发创建 Thread 增加唯一冲突处理

- 来源：bundle_v2_correctness, bundle_v4_performance, review_intensive
- 位置：src/mail_core/threading/rules.py:176-184
- 优先级：MEDIUM
- 详细判断理由：并发插入同一 thread_key 抛出 IntegrityError 导致批次同步中断。
- 修复说明：捕获 IntegrityError 并重新查库加载。

### A45. 标记星标操作移除冗余文件夹统计重算

- 来源：bundle_v4_performance, review_intensive
- 位置：src/mail_core/mail/application/mutations.py:151
- 优先级：MEDIUM
- 详细判断理由：星标不影响未读数和总数，重算全表无意义。
- 修复说明：移除该处冗余统计更新。

### A46. 全量清理死代码与无用 import

- 来源：bundle_v5_architecture, bundle_v7_tests, review_intensive
- 位置：src/mail_core/backup/package.py:6,397, src/desktop/main.js:52, src/mail_core/api/mail.py:23, src/mail_core/blobs/archive.py:17, src/mail_core/realtime/dispatcher.py:190, src/mail_core/blobs/store.py:119, src/mail_core/api/deps.py:77, src/mail_core/db/session.py:57, src/mail_core/blobs/access.py:65, src/mail_core/api/app.py:80, tests/mail_core/\*
- 优先级：LOW
- 详细判断理由：已验证确定未引用的 dead code 与死 import。
- 修复说明：逐一安全删除。

### A47. 修正失效文档相对链接与过时路径

- 来源：bundle_v8_docs, review_intensive
- 位置：docs/guides/desktop.md:3,46,96, src/frontend/README.md:9,29, docker-compose.mail-core.yml:2, src/mail_core/__init__.py:3, docs/guides/security.md:79
- 优先级：LOW
- 详细判断理由：链接断裂或指向已被重构迁移的旧文档。
- 修复说明：修正为现存正确路径。

### A48. 前端 SettingsModal 拆分细粒度 selector 避免冗余重渲

- 来源：bundle_v5_architecture, review_intensive
- 位置：src/frontend/src/components/SettingsModal.tsx:11
- 优先级：LOW
- 详细判断理由：全量订阅 store 导致外部状态变动时弹窗频繁重渲。
- 修复说明：按字段传递选择器。

### A49. ColumnResize 修复渲染期直接访问 Ref

- 来源：bundle_v5_architecture, review_intensive
- 位置：src/frontend/src/components/ColumnResize.tsx:12
- 优先级：LOW
- 详细判断理由：破坏 React 渲染幂等性。
- 修复说明：移出 render 流程。

### A50. 桌面端更名旧项目遗留环境变量名并保持兼容

- 来源：bundle_v8_docs, review_intensive
- 位置：src/desktop/startup.js:100, startup.test.js:16, main.js:20
- 优先级：LOW
- 详细判断理由：遗留旧项目名称 OUTLOOK_DESKTOP_PORT。
- 修复说明：更名为 KKMAIL_DESKTOP_PORT 并回退兼容旧变量。

### A51. 桌面端补充 will-redirect 导航拦截

- 来源：bundle_v2_correctness, review_intensive
- 位置：src/desktop/main.js:166
- 优先级：LOW
- 详细判断理由：仅拦截 will-navigate，HTTP 重定向不受控。
- 修复说明：增加 will-redirect 监听与外链分流。

### A52. 前端契约类型复用 schemaTypes 消除手写重复

- 来源：bundle_v3_contracts, review_intensive
- 位置：src/frontend/src/api/mailCore.ts:87
- 优先级：LOW
- 详细判断理由：手写接口与 OpenAPI 自动生成类型存在漂移隐患。
- 修复说明：直接导入 OpenAPI 导出类型。

### A53. 彻底重写历史消除 Outlook 泄露凭据并在后台吊销

- 来源：bundle_v1_security, bundle_cross_validation, review_intensive
- 位置：outlook_mail_reader.py:20-25 (commit 34c8131069298bf14989f853decba8e3ee8c4dd2)
- 优先级：CRITICAL
- 详细判断理由：用户决策选 B。历史提交中硬编码了真实 Outlook 账号凭据与 OAuth Refresh Token，使用 git-filter-repo 彻底消除该提交历史并 force push，同时在微软控制台吊销该凭据。
- 修复说明：在微软后台注销 ClientID 及 Token；使用 git-filter-repo 重写历史清除凭据后 force push。

### A54. 彻底重写历史对手机号与个人隐私脱敏

- 来源：bundle_v1_security, review_intensive
- 位置：src/frontend/src/App.tsx:18-21 (commit 7931147f8722ff423e8f810aa7ef3bc7709bbf45), README.md:455-456 (commit d368f009f9ce80db31af91b26977b769dd7e0139)
- 优先级：HIGH
- 详细判断理由：用户决策选 A。与 A53 联动，统一使用 git-filter-repo 对历史提交中包含国内真实手机号邮箱（redacted_mobile@example.com）及 Telegram/个人邮箱的提交做脱敏重写。
- 修复说明：使用 git-filter-repo 对历史涉及隐私提交进行内容脱敏重写。

### A55. 实时通知收窄单 API 实例约束并在无本地目标时保护位点

- 来源：bundle_v2_correctness, bundle_cross_validation, review_intensive
- 位置：src/mail_core/realtime/dispatcher.py:144-150, docs/blueprint/architecture.md, docs/guides/deployment.md
- 优先级：CRITICAL
- 详细判断理由：用户决策选 A。符合自托管 KISS 原则，在架构文档与部署文档明确当前 EventDispatcher 仅支持单 API 实例；在 \_fanout 中若无本地目标不推进位点（返回 False）。
- 修复说明：在 \_fanout() 中将 targets 为空时返回 True 改为返回 False；在架构与部署文档补充单 API 实例约束说明。

### A56. 部署手册对齐 API 发布端口 37281

- 来源：bundle_v8_docs, bundle_cross_validation, review_intensive
- 位置：docs/guides/deployment.md:19
- 优先级：HIGH
- 详细判断理由：用户决策选 A。37281 是 kkmail 的专用特征端口，避免与宿主机常用 8000 Web 服务冲突；全仓多处配置已使用 37281，改文档影响面最小。
- 修复说明：修改 docs/guides/deployment.md:19 访问说明为 http://127.0.0.1:37281。

## 不采纳项

### R1. 初始密码 initial-password.txt 首次登录后自毁

- 来源：bundle_v1_security, bundle_v6_robustness
- 位置：src/mail_core/runtime/bootstrap.py:81
- 优先级：MEDIUM
- 详细判断理由：initial-password.txt 在自托管与容器部署下常作为排障或自动化运维提取初始凭据的文件（权限已严格限定为 0600）。若首次登录后自动删除该文件，会导致通过脚本查看初始密码的运维人员无法再次找回，引发不可预期的管理中断。若需改密应使用正常改密流程，不宜做静默删除。

### R2. Session Epoch 异常时坚持 Fail-Closed 拒绝会话

- 来源：bundle_v1_security
- 位置：src/mail_core/security/auth.py:233-235
- 优先级：LOW
- 详细判断理由：在数据库遭遇瞬时连接波动或网络抖动时，若直接 fail-closed 抛错拒绝，将导致所有在线用户立即掉线被踢出登录，用户体验极差。当前实现的内存默认值保底是权衡可用性与安全性的设计取舍，改动弊大于利。

### R3. 前端挂载 diagnostics 对象 context 递归脱敏

- 来源：bundle_v1_security
- 位置：src/frontend/src/lib/diagnostics.ts:44-101
- 优先级：LOW
- 详细判断理由：\_\_kkmail_diagnostics 仅用于开发调试与排障诊断，不会发送至外部远程服务器。生产构建已有剥离或受控机制，递归过滤所有 context 键值增加不必要的运行时开销与复杂性。

### R4. 桌面端外链过滤器严格禁止 http 本地回环地址

- 来源：bundle_v1_security
- 位置：src/desktop/paths.js:20-29
- 优先级：LOW
- 详细判断理由：桌面端自身托管的 API 和本地预览服务正是在 http://127.0.0.1，强行禁止 http 本地回环会导致合法的本地预览和系统浏览器交互被误杀。

### R5. Blob GC 全表扫描重构为 Keyset 分页

- 来源：bundle_v4_performance
- 位置：src/mail_core/blobs/gc.py:52-162
- 优先级：MEDIUM
- 详细判断理由：当前自托管邮件客户端的数据量级通常在数万封以内，GC 属于低频后台维护任务，当前逻辑清晰可靠。重构为复杂 Keyset 分页并调整级联删除逻辑会引入不必要的架构复杂度和竞态风险。

### R6. Worker 主轮询清理任务拆分独立定时器

- 来源：bundle_v4_performance
- 位置：src/mail_core/worker/main.py:68-85
- 优先级：MEDIUM
- 详细判断理由：\_reclaim_once() 内部已有轻量级前置条件检查，没有需要清理的数据时几乎无 DB 负担；引入多定时器或后台线程池增加死锁和资源竞争概率。

### R7. Reconcile 与 Delta 删除循环批量化重构

- 来源：bundle_v4_performance
- 位置：src/mail_core/sync/reconcile.py:84-114
- 优先级：MEDIUM
- 详细判断理由：删除属于离线或增量极小量操作，逐条处理可以精细控制外键和 blob 引用计数；批量化改动对现有复杂的同步状态机带来较高的回归风险。

### R8. 账号管理接口单个账号按需查询 Groups 优化

- 来源：bundle_v4_performance
- 位置：src/mail_core/api/accounts.py:170
- 优先级：LOW
- 详细判断理由：单用户账号数量极少（通常在 10 个以内），全量查 groups 开销在亚毫秒级，提前优化没有实际收益。

### R9. SettingsModal 表单 dirty 检测禁止覆盖

- 来源：bundle_v6_robustness
- 位置：src/frontend/src/components/SettingsModal.tsx:36
- 优先级：LOW
- 详细判断理由：设置弹窗打开时用户通常直接修改并保存，后台 react-query 刷新时间远大于用户操作时间，改动收益微小，且引入 dirty 状态跟踪增加状态管理复杂度。

### R10. freePort 探测 TOCTOU 漏洞重构为子进程 port 0 回传

- 来源：bundle_v6_robustness
- 位置：src/desktop/startup.js:117
- 优先级：LOW
- 详细判断理由：重构为 port 0 需要改造 sidecar CLI、IPC 管道和主进程通信协议，侵入性过大；本地单机极小概率发生此冲突，当前逻辑满足需求。

### R11. t001/t002/t003 规格契约达成 Info 确认

- 来源：bundle_v7_tests, review_intensive
- 位置：docs/archive/tasks/t001\_\*/spec.md, t002, t003
- 优先级：LOW
- 详细判断理由：审阅核验确认为已有归档 task 的规格达标事实（Info 级别），代码本身已在历史 task 完成，无需执行修改。
