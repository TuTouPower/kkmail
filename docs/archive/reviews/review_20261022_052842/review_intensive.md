> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审阅归档：记录日期 2026-10-22（Generated: 2026-10-22T05:49:17+08:00；本包入库提交 `eb7685eec6828c8398aecbeaeb0712bb6cbb0c2c`，原报告未标注被审基线 SHA）。文中结论只反映记录时点的代码状态，已被后续审阅替代，现行结论以 [review_20261027_021416](../review_20261027_021416/review_intensive.md) 为准；同日后续复审见 [review_20261022_071448](../review_20261022_071448/review_intensive.md)。请勿将本报告 finding 视为当前状态。

# Intensive Review — Aggregate

- Generated: 2026-10-22T05:49:17.204130+08:00
- OUTDIR: docs/reviews/review_20261022_052842
- Bundles: 9 (bundle_cross_validation.md, bundle_v1_security.md, bundle_v2_correctness.md, bundle_v3_contracts.md, bundle_v4_performance.md, bundle_v5_architecture.md, bundle_v6_robustness.md, bundle_v7_tests.md, bundle_v8_docs.md)
- Findings: Critical=6 High=20 Medium=28 Low=27 Info=3 (deduped 84)
- Verdict: **BLOCK**

## Critical / High (必修)

- [Critical][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 泄露真实有效 Outlook 邮箱、明文密码与 OAuth Refresh Token
- [Critical][99] Dockerfile.mail-core:25 — 生产容器启动模式未装配日志脱敏格式化器击穿安全基线
- [Critical][98] src/desktop/main.js:189 — 桌面端缺失单实例锁导致多进程写同一数据库与共享服务被误杀
- [Critical][95] src/mail_core/realtime/dispatcher.py:144-150 — 多 API 进程部署下无本地订阅者误标 dispatched 导致跨进程实时通知静默丢失
- [Critical][95] src/mail_core/security/auth.py:206-288 — 会话认证每次 HTTP 请求无缓存直接建立 DB Session 查库消耗连接池
- [Critical][90] src/mail_core/blobs/archive.py:158-216 — 核心状态表 message_archive_state 缺少二级索引导致 Worker 高频全表扫描
- [High][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 泄露真实手机号及个人真实邮箱 PII 隐私
- [High][100] scripts/migrate_from_legacy_db.py:68-69 — 数据库迁移脚本硬编码默认 Fallback 解密密钥
- [High][98] src/mail_core/api/accounts.py:24 — 路由层直接导入并消费 ORM 存储模型击穿分层架构契约
- [High][98] scripts/mail-core-chaos-lease.sh:16 — Chaos 破坏性脚本数据库前置检查通配符包含可穿透到生产库
- [High][98] docs/guides/deployment.md:19 — 部署手册 API 发布端口与真实 Compose 配置严重冲突
- [High][96] tests/mail_core/conftest.py:83 — MAIL_CORE_REQUIRE_DB 门禁匹配漏洞导致 DB 测试静默跳过
- [High][95] src/mail_core/api/app.py:59-76 — Web/Docker 部署模式全局缺失关键安全响应头
- [High][95] src/mail_core/api/app.py:79-94 — 缺省反向代理配置导致登录失败限流产生全局拒绝服务 DoS
- [High][95] src/frontend/src/components/MessageReader.tsx:22 — loadRemoteImages 状态重置滞后导致邮件切换时瞬间泄露远程图片请求
- [High][95] src/frontend/src/App.tsx:108 — ColumnResize 拖拽触发全局组件树无节流全量重渲染与高频同步写 localStorage
- [High][95] src/frontend/src/components/MessageList.tsx:182 — 邮件列表过滤与排序未 memoize 导致每次渲染触发数千次正则解析
- [High][92] src/desktop/main.js:231 — 关闭流程中 PostgreSQL 先于 sidecar 停止导致后端事务与连接异常中断
- [High][92] src/frontend/src/components/MessageReader.tsx:202 — 附件下载链接触发 Electron 主窗口顶层导航导致 SPA 白屏被替换
- [High][90] src/mail_core/api/sse.py:157-198 — SSE 连接计数器提前递增且释放滞后于生成器导致连接槽位伪耗尽报 503
- [High][90] src/frontend/src/lib/mailBody.ts:40 — iframe 沙箱缺少 allow-popups-to-escape-sandbox 导致 Web SPA 模式下外部链接无法正常浏览
- [High][90] src/mail_core/threading/rules.py:149-168 — messages.internet_message_id 缺失索引导致线程推导全表扫描
- [High][90] src/mail_core/providers/imap.py:249-388 — IMAP 抓取元数据与 Flags 循环逐条 FETCH 引发大量网络往返 RTT
- [High][85] src/mail_core/sync/leases.py:121-129 — assert_fencing 忽略租约过期与主动释放状态失去互斥保护
- [High][85] src/mail_core/providers/imap.py:255-258 — IMAP UID FETCH 单封邮件空响应抛出异常导致文件夹同步死循环
- [High][85] src/mail_core/search/index.py:40-89 — 全文搜索 from_text 缺少三元组索引导致 GIN 索引失效退化为全表扫描

## Medium / Low / Info (建议)

- [Medium][99] src/mail_core/backup/package.py:397 — 全量死函数 \_extract_plain_tar 定义但从未被调用
- [Medium][98] src/frontend/src/components/Sidebar.tsx:19 — 轮询不存在的 API 产生确定性 404 网络开销与兜底放大
- [Medium][98] docs/blueprint/testing.md:18 — 长期真相文档机械锚点 test_cmd 遗漏核心后端测试命令
- [Medium][95] src/mail_core/security/auth.py:73-80 — 会话 Cookie 默认未启用 Secure 属性
- [Medium][95] src/frontend/src/lib/mailBody.ts:36 — base 标签滥用 rel 属性无法防止 opener 泄露且缺失 Referrer-Policy
- [Medium][95] src/mail_core/api/app.py:144 — ready 路由直接穿透至底层数据库连接执行裸 SQL
- [Medium][95] src/frontend/src/main.tsx:15 — 根级单个 ErrorBoundary 导致局部渲染异常直接造成整站白屏崩溃
- [Medium][95] docs/guides/security.md:71 — 反向代理受信 IP 配置说明内部自相矛盾
- [Medium][95] docs/guides/troubleshooting.md:44 — 故障排查手册 SQL 改密示例遗漏自增 session_epoch 破坏会话吊销
- [Medium][95] src/mail_core/__init__.py:6 — 后端版本号与全局 VERSION 与发版指南漂移
- [Medium][92] src/frontend/src/components/MessageReader.tsx:190 — DOMPurify.sanitize 在组件渲染主链路无缓存同步重跑
- [Medium][92] scripts/run-mail-core-tests.sh:11 — 测试执行脚本缺失目标数据库名安全性前置检查
- [Medium][92] src/frontend/src/hooks/useMailCoreRealtime.ts:151 — SSE 遭遇 401/403 认证失效后未同步派发前端登出事件
- [Medium][92] docs/handoff.md:9 — 交接文档记录严重滞后
- [Medium][90] src/mail_core/security/redact.py:14-23 — 日志脱敏正则未覆盖 HTTP Basic Auth 与通用代理协议 URL
- [Medium][90] src/mail_core/runtime/bootstrap.py:81 — 初始生成的登录密码以明文形式永久滞留磁盘
- [Medium][90] src/frontend/src/components/MessageList.tsx:158 — 分页游标重叠未去重导致 React 重复 key 警告与状态错乱
- [Medium][90] src/frontend/src/lib/mailBody.ts:12 — DOMPurify 依赖标签黑名单过滤而非 USE_PROFILES 禁用 XML 命名空间
- [Medium][90] src/desktop/logRotation.js:87 — RotatingLogStream 同步写盘阻塞 Electron 主进程事件循环
- [Medium][90] src/desktop/postgresManager.js:131 — 数据目录及其邮件存储目录采用 0755 权限存在多用户泄露风险
- [Medium][90] src/mail_core/worker/handlers.py:190 — 同步异常处理中静默吞掉账户状态更新异常
- [Medium][85] src/mail_core/providers/factory.py:72-80 — IMAP 提供商未对内网地址进行校验存在 SSRF 风险
- [Medium][85] src/mail_core/mail/storage/folder_stats.py:15-39 — recompute_folder_stats 缺乏行级锁导致并发未读数更新覆盖与初次插入竞争
- [Medium][85] src/mail_core/blobs/gc.py:52-162 — Blob GC 全表扫描所有记录及循环单条探测清理
- [Medium][85] src/mail_core/worker/main.py:68-85 — Worker 主轮询每次循环均无节制执行全表清理导致高频 DB 压力
- [Medium][85] src/mail_core/sync/reconcile.py:84-114 — Reconcile 与 Delta 删除循环内执行 3 次单个查询与 Flush (N+1)
- [Medium][80] src/mail_core/threading/rules.py:176-184 — 消息线索关联并发创建新 Thread 缺少冲突保护导致同步中断
- [Medium][80] src/mail_core/mail/application/mutations.py:151 — set_message_flagged 冗余重算全部未读数与聚合计数
- [Low][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 包含开发者个人 Telegram 账号与私有邮箱
- [Low][99] src/desktop/main.js:52 — 未使用的解构引用 rotateLogFile
- [Low][98] docs/guides/desktop.md:46 — 桌面端使用指南相对链接失效
- [Low][98] src/frontend/README.md:9 — 前端自述文件命令与链接失效
- [Low][96] src/mail_core/api/mail.py:23 — 未使用的 import AccountInboxStatsOut
- [Low][96] src/mail_core/blobs/archive.py:17 — 未使用的 import and\_, or\_, update
- [Low][96] src/mail_core/backup/package.py:6 — 未使用的 import io 与加解密辅助函数
- [Low][95] src/frontend/src/api/mailCore.ts:87 — 前端手写契约类型与 OpenAPI 生成类型重复存在漂移风险
- [Low][95] src/mail_core/realtime/dispatcher.py:190 — 全量死方法 run_forever 定义但从未被调用
- [Low][95] src/mail_core/blobs/store.py:119 — 全量死方法 key_version_of 未被使用
- [Low][95] src/mail_core/api/deps.py:77 — 安全依赖 helper require_auth_no_csrf 未被任何路由使用
- [Low][95] src/frontend/src/components/SettingsModal.tsx:11 — SettingsPage 未传 selector 导致全量订阅 store 产生冗余重渲染
- [Low][95] src/frontend/src/components/ColumnResize.tsx:12 — 渲染期间直接访问 Ref 破坏 React 幂等性
- [Low][95] docs/guides/desktop.md:3 — 引用已废弃或重组的旧路径文档
- [Low][92] src/mail_core/db/session.py:57 — 失效 helper session_scope 从未被使用
- [Low][92] src/desktop/startup.js:100 — 桌面端代码遗留旧项目命名环境变量
- [Low][90] src/mail_core/security/auth.py:233-235 — Session Epoch 异常降级容错可能导致历史已吊销会话短暂生效
- [Low][90] src/mail_core/blobs/access.py:65 — 数据类死方法 read_all 未被使用
- [Low][90] src/frontend/src/components/SettingsModal.tsx:36 — 后台 Query 静默刷新直接覆盖用户正在编辑的未保存表单数据
- [Low][90] tests/mail_core/test_remote_writeback.py:8 — 测试用例中散落的未使用 import 堆叠
- [Low][90] docs/guides/security.md:79 — 备份命令跨文件全文复制破坏单一权威
- [Low][88] src/desktop/main.js:166 — 桌面端未监听 will-redirect 导致 HTTP 重定向未受拦截保护
- [Low][85] src/frontend/src/lib/diagnostics.ts:44-101 — 前端挂载诊断对象且 context 字段未脱敏
- [Low][85] src/desktop/startup.js:117 — freePort 探测后立即关闭套接字存在 TOCTOU 竞态漏洞
- [Low][80] src/desktop/paths.js:20-29 — 桌面端外链过滤器未限制 http 本地回环地址
- [Low][80] src/mail_core/api/app.py:80 — 中间件函数类型注解引用未导入的 Request
- [Low][75] src/mail_core/api/accounts.py:170 — 账号管理接口为单个账号全量聚合统计所有 Groups
- [Info][100] docs/archive/tasks/t001_mail_core_sent_query/spec.md:29 — t001（mail_core_sent_query）规格契约完全达成
- [Info][100] docs/archive/tasks/t002_frontend_favorites_views/spec.md:29 — t002（frontend_favorites_views）规格契约完全达成
- [Info][100] docs/archive/tasks/t003_reader_toolbar_and_context_menu/spec.md:31 — t003（reader_toolbar_and_context_menu）规格契约完全达成

## Sources

- [bundle_cross_validation.md](bundle_cross_validation.md)
- [bundle_v1_security.md](bundle_v1_security.md)
- [bundle_v2_correctness.md](bundle_v2_correctness.md)
- [bundle_v3_contracts.md](bundle_v3_contracts.md)
- [bundle_v4_performance.md](bundle_v4_performance.md)
- [bundle_v5_architecture.md](bundle_v5_architecture.md)
- [bundle_v6_robustness.md](bundle_v6_robustness.md)
- [bundle_v7_tests.md](bundle_v7_tests.md)
- [bundle_v8_docs.md](bundle_v8_docs.md)

## Traceability

- Aggregate generated by `intensive-review/scripts/aggregate.py` from 9 bundle reports.
- Dedup key: `file:line | title[0:120]` normalized.
- 勘误（A199）：本 aggregate 不再复制 finding 证据全文，仅保留计数与标题行；证据全文以 Sources 所列 bundle 文件为准，避免同一 finding 多份复制存档导致脱敏/勘误逐份重复与漂移。
