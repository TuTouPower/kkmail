# bundle_local_frontend_desktop

## responsibilities

- 管理 Electron 桌面端主进程生命周期：单实例锁（requestSingleInstanceLock）、主窗口创建、原生暗黑主题同步与多阶段单次优雅停机（shutdownAll）
- 管理内置 PostgreSQL 实例生命周期（PostgresManager）：规划并保护 OS 级数据目录权限（0700/0600）、初始化集群、自动探测二进制、生成并排他持久化密码、检查并调谐 postgresql.conf 强制绑定 127.0.0.1
- 管理 mail-core 后端 Sidecar 进程：动态探测空闲可用端口、执行严格的环境变量净化过滤（scrubEnv 阻断 PYTHONPATH/LD\_\* 代码注入）、启动健康探针检测与子进程树强杀管理（stopChildTree）
- 构建桌面端运行沙箱与安全加固（Hardening）：严格禁用 nodeIntegration，启用 contextIsolation 与 sandbox；通过 preload.js 仅暴露平台信息与版本号；拦截 webviewTag；全局 session 拦截注入 CSP 限制与严格权限校验（除同源顶层主框架的剪贴板写权限外一律拒绝）；全局拦截外部跳转与新窗口，只允许通过系统默认浏览器打开 https/mailto
- 提供主进程安全日志架构（DesktopLogger 与 RotatingLogStream）：控制台与未捕获异常捕获、落盘前自动执行密码/Token脱敏（redactSecrets）与文件按大小和数量轮转
- 实现前端 SPA 核心状态机（Zustand Store）：管理全局主题、视图状态、选信状态、侧边栏折叠与栏宽持久化（partialize 脱敏不存敏感数据）
- 实现 SSE 实时推送与智能节流缓存失效机制（useMailCoreRealtime 与 createThrottledInvalidator）：150ms 聚合窗口去重、精确定向消息失效与页面唤醒自愈
- 提供跨环境剪贴板降级机制（clipboard.ts）与脱敏前端诊断跟踪环形缓冲区（diagnostics.ts）

## interfaces

- src/desktop/main.js: Electron 主进程入口
- src/desktop/preload.js: contextBridge.exposeInMainWorld('kkmailDesktop', ...)
- src/desktop/hardening.js: appContentSecurityPolicy, mergeCspHeaders, isAllowedPermission, createPermissionRequestHandler, createPermissionCheckHandler
- src/desktop/postgresManager.js: PostgresManager (start, stop, status, initIfNeeded, ensureDatabase, password, databaseUrl, paths)
- src/desktop/paths.js: sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler, createNavigationGuardHandler, attachContentGuards
- src/desktop/startup.js: scrubEnv, redactSecrets, parsePort, freePort, waitForHealth, stopChildTree, forceKillChildTreeImmediately, collectSidecarExtras
- src/desktop/desktopLog.js: DesktopLogger, getDesktopLogger, formatIsoTimestamp, formatMessage
- src/desktop/windowOptions.js: createMainWindowOptions, windowBackgroundColor, shouldRemoveApplicationMenu
- src/frontend/src/store/mailStore.ts: useMailStore, providerColor
- src/frontend/src/store/accountIcon.ts: detectAccountBrand, getEmailInitial
- src/frontend/src/hooks/useMailCoreRealtime.ts: useMailCoreRealtime, createThrottledInvalidator, extractMessageIds, extractSyncRequestId, shouldInvalidateMailCoreInbox
- src/frontend/src/lib/clipboard.ts: copyTextToClipboard
- src/frontend/src/lib/diagnostics.ts: logDiagnostic, getDiagnosticLogs, exportDiagnosticsAsText, clearDiagnosticLogs, initGlobalDiagnostics
- src/frontend/src/lib/desktopShell.ts: getDesktopPlatform

## dependencies

- electron
- node:child_process
- node:crypto
- node:fs
- node:net
- node:http
- node:path
- node:os
- node:util
- zustand
- @tanstack/react-query

## flows

- 应用启动 -> session 注入 CSP 与权限守卫 -> PostgresManager 校验并启动本地 PG -> 动态获取空闲端口 -> 净化环境变量并启动 mail-core 后端 -> 轮询 /health 成功 -> 建立 BrowserWindow 并加载界面
- 应用关闭/收到终止信号 -> shutdownAll 单飞控制 -> 优雅终止 mail-core 子进程树 -> 调用 pg_ctl stop 停止 PG 集群 -> 刷新并关闭 RotatingLogStream 流 -> 彻底退出
- 渲染进程外部链接点击或导航 -> attachContentGuards 拦截 -> isAllowedExternalUrl 校验必须为 https:/mailto: 且无内嵌凭据 -> 调用 shell.openExternal 交由系统浏览器，主窗口阻止内嵌导航
- SSE 接收服务端事件 -> useMailCoreRealtime 派发给 createThrottledInvalidator -> 150ms 缓冲后对列表/详情/账号进行定向或全量 React Query invalidate
- 前端诊断信息 -> logDiagnostic 正则识别并脱敏敏感 key 及 value -> 写入环形缓冲区 -> 用户或 ErrorBoundary 触发 exportDiagnosticsAsText 导出

## constraints

- 渲染进程必须开启 contextIsolation: true、sandbox: true，且禁止 nodeIntegration: false 与 webviewTag: false
- PostgreSQL 实例绝对禁止对外监听，强制限定在 127.0.0.1 环回地址；数据目录与密码文件权限严格控制在 0700/0600
- 子进程启动环境必须经由 scrubEnv 白名单过滤，严禁将父环境中的 PYTHONPATH、PYTHONHOME、LD_LIBRARY_PATH、DYLD\_\* 透传给后端或 PG
- 外部跳转链接严禁包含任何内嵌认证信息（u.username || u.password），只允许 https: 与 mailto: 协议
- 打包生产环境（isPackaged === true）下必须显式移除默认 ApplicationMenu，禁止暴露 DevTools

## decisions

- 放弃 SQLite，桌面端内置管理单机 PostgreSQL 集群，保证本地开发、单机桌面版与线上部署版本采用完全一致的数据库引擎、迁移文件与查询行为，不妥协架构纯粹性
- 桌面日志与后端日志均采用本地双轨输出（控制台 + RotatingLogStream 轮转文件），落盘前统一经过 redactSecrets 密码与 Token 脱敏（A151）
- 前端持久化存储（useMailStore persist partialize）仅持久化 UI 布局、宽度与主题等非敏感配置，严禁在 localStorage 中持久化任何凭证、邮件正文或敏感查询（A94）

## evidence

- src/desktop/main.js:186-212
- src/desktop/hardening.js:9-55
- src/desktop/postgresManager.js:93-133
- src/desktop/postgresManager.js:342-368
- src/desktop/paths.js:20-32
- src/desktop/startup.js:17-63
- src/frontend/src/store/mailStore.ts:157-170
- src/frontend/src/hooks/useMailCoreRealtime.ts:60-173

## uncertainties

## Findings

- [Low][90] src/desktop/package.json:15 — npm test 串行执行 12 个集成测试可能超过标准 CI 超时阈值

    - ID: f_frontend_desktop_01; verification: reproduced
    - Evidence: "test": "node paths.test.js && node hardening.test.js && node postgresManager.test.js && node startup.test.js && node logRotation.test.js && node desktopLog.test.js && node clipboard.test.js && node windowOptions.test.js && node packLinux.test.js && node scripts/packaged_smoke_db.test.js && node scripts/packaged_smoke.test.js && node oauth_integration.test.js"
    - Impact: 测试脚本在单条命令中串行拉起多个真实的 PostgreSQL 启动/停止和真实的 Electron 端到端实例，累计耗时较大（超过常规单步 120 秒超时），容易在 CI 环境中因超时被中断。
    - Fix: 建议将纯逻辑单元测试与启动真实进程的集成冒烟测试拆分为独立命令（如 test:unit 与 test:e2e），提高测试执行效率与容错度。

- [Info][95] src/frontend/src/lib/clipboard.ts:48 — 非安全上下文使用已废弃的 document.execCommand 作为剪贴板降级方案

    - ID: f_frontend_desktop_02; verification: static
    - Evidence: ok = document.execCommand('copy')
    - Impact: document.execCommand 属于已被 Web 标准废弃的接口。在非 HTTPS/非安全自托管环境下作为唯一同步兜底方案目前仍有效，但存在未来浏览器版本完全废弃导致失效的潜在兼容性风险。
    - Fix: 保持现有降级逻辑，在部署文档中明确建议用户生产环境配置 HTTPS 以优先启用现代异步 Clipboard API。

- [High][95] src/desktop/startup.js:190-208 — 桌面端端口探测 TOCTOU 竞态写单测断言注释承认缺陷，严重违反拒绝妥协与架构至上铁律

    - ID: f_arch_desktop_startup_toctou_acknowledged_in_test; verification: static
    - Evidence: src/desktop/startup.js:190-208 注释自述: 'TOCTOU warning: this is a probe, NOT a reservation... Eliminating the race requires the backend to bind port 0 and report the assigned port back to the launcher (a backend protocol change); until that exists, treat the two failure shapes above as the port-raced signature and retry the launch.'; src/desktop/startup.test.js:64-78 专门编写单测断言注释承认缺陷: 'assert.match(docBlock, /TOCTOU/); assert.match(docBlock, /bind.\*0|port 0/)'
    - Impact: 由于根治竞态需要修改后端服务启动协议（绑定 port 0 并回传已分配端口），开发团队选择保留先监听再关闭释放的伪探测机制，留下严重 TOCTOU 窗口，并通过编写单元测试断言注释中承认了该缺陷，以此规避重构。
    - Fix: 彻底重写服务拉起协议：桌面端启动 mail_core 时传入 --port 0，后端在绑定成功后通过标准输出管道原子汇报分配端口，主进程直接健康检查，彻底移除 freePort 与 tryListen 伪探测机制及其对应单测。

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_frontend"
  }
}
```

## files_reviewed

```json
[
  "src/desktop/README.md",
  "src/desktop/clipboard.test.js",
  "src/desktop/desktopLog.js",
  "src/desktop/desktopLog.test.js",
  "src/desktop/hardening.js",
  "src/desktop/hardening.test.js",
  "src/desktop/icon.svg",
  "src/desktop/logRotation.js",
  "src/desktop/logRotation.test.js",
  "src/desktop/main.js",
  "src/desktop/oauth_integration.test.js",
  "src/desktop/packLinux.test.js",
  "src/desktop/package.json",
  "src/desktop/paths.js",
  "src/desktop/paths.test.js",
  "src/desktop/postgresManager.js",
  "src/desktop/postgresManager.test.js",
  "src/desktop/preload.js",
  "src/desktop/scripts/pack-linux.js",
  "src/desktop/scripts/packaged-smoke.js",
  "src/desktop/scripts/packaged_smoke.test.js",
  "src/desktop/scripts/packaged_smoke_db.js",
  "src/desktop/scripts/packaged_smoke_db.test.js",
  "src/desktop/startup.js",
  "src/desktop/startup.test.js",
  "src/desktop/windowOptions.js",
  "src/desktop/windowOptions.test.js",
  "src/frontend/.env.example",
  "src/frontend/.gitignore",
  "src/frontend/.oxlintrc.json",
  "src/frontend/ARCHITECTURE.md",
  "src/frontend/README.md",
  "src/frontend/index.html",
  "src/frontend/package.json",
  "src/frontend/playwright.config.test.ts",
  "src/frontend/playwright.config.ts",
  "src/frontend/public/favicon.svg",
  "src/frontend/public/theme_bootstrap.js",
  "src/frontend/scripts/check_css_tokens.mjs",
  "src/frontend/scripts/check_css_tokens.node-test.mjs",
  "src/frontend/scripts/check_openapi.mjs",
  "src/frontend/scripts/openapi-check.mjs",
  "src/frontend/scripts/run_e2e.mjs",
  "src/frontend/src/App.tsx",
  "src/frontend/src/app.errorBoundary.test.tsx",
  "src/frontend/src/app.test.tsx",
  "src/frontend/src/design-system/base.css",
  "src/frontend/src/design-system/components.css",
  "src/frontend/src/design-system/darkTheme.test.ts",
  "src/frontend/src/design-system/tokens.css",
  "src/frontend/src/hooks/useMailCoreRealtime.test.ts",
  "src/frontend/src/hooks/useMailCoreRealtime.ts",
  "src/frontend/src/index.css",
  "src/frontend/src/lib/account_icon_style.ts",
  "src/frontend/src/lib/account_providers.test.ts",
  "src/frontend/src/lib/account_providers.ts",
  "src/frontend/src/lib/actions.test.ts",
  "src/frontend/src/lib/actions.ts",
  "src/frontend/src/lib/apiBase.test.ts",
  "src/frontend/src/lib/apiBase.ts",
  "src/frontend/src/lib/clipboard.test.ts",
  "src/frontend/src/lib/clipboard.ts",
  "src/frontend/src/lib/concurrency.ts",
  "src/frontend/src/lib/desktopShell.test.ts",
  "src/frontend/src/lib/desktopShell.ts",
  "src/frontend/src/lib/diagnostics.test.ts",
  "src/frontend/src/lib/diagnostics.ts",
  "src/frontend/src/lib/displayName.test.ts",
  "src/frontend/src/lib/displayName.ts",
  "src/frontend/src/lib/error_stack.ts",
  "src/frontend/src/lib/formatSize.test.ts",
  "src/frontend/src/lib/formatSize.ts",
  "src/frontend/src/lib/listDate.test.ts",
  "src/frontend/src/lib/listDate.ts",
  "src/frontend/src/lib/listTitle.test.ts",
  "src/frontend/src/lib/listTitle.ts",
  "src/frontend/src/lib/mailBody.test.ts",
  "src/frontend/src/lib/mailBody.ts",
  "src/frontend/src/lib/mailDate.test.ts",
  "src/frontend/src/lib/mailDate.ts",
  "src/frontend/src/lib/mailKey.test.ts",
  "src/frontend/src/lib/mailKey.ts",
  "src/frontend/src/lib/previewText.test.ts",
  "src/frontend/src/lib/previewText.ts",
  "src/frontend/src/lib/sidebar_layout.ts",
  "src/frontend/src/lib/theme.ts",
  "src/frontend/src/lib/uiReference.test.ts",
  "src/frontend/src/lib/uiReference.ts",
  "src/frontend/src/lib/ui_reference_overlay.ts",
  "src/frontend/src/lib/ui_shortcut.test.ts",
  "src/frontend/src/lib/ui_shortcut.ts",
  "src/frontend/src/lib/viewport.ts",
  "src/frontend/src/lib/workspaceLayout.test.ts",
  "src/frontend/src/lib/workspaceLayout.ts",
  "src/frontend/src/main.tsx",
  "src/frontend/src/store/accountIcon.test.ts",
  "src/frontend/src/store/accountIcon.ts",
  "src/frontend/src/store/mailStore.test.ts",
  "src/frontend/src/store/mailStore.ts",
  "src/frontend/src/store/theme.test.ts",
  "src/frontend/src/test/persistence.test.ts",
  "src/frontend/src/test/render.tsx",
  "src/frontend/src/test/test_runtime.test.tsx",
  "src/frontend/src/test/test_setup.ts",
  "src/frontend/tsconfig.app.json",
  "src/frontend/tsconfig.json",
  "src/frontend/tsconfig.node.json",
  "src/frontend/vite.config.ts"
]
```
