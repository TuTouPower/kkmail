# bundle_local_frontend_ui

## responsibilities

- 实现与 mail-core 的安全 API 通信：管理 Cookie Session、单飞（Singleflight）获取 CSRF Token、为所有不安全写操作自动注入 X-CSRF-Token、拦截 401 广播未授权事件并提供请求超时控制
- 提供基于 OpenAPI 自动生成类型的 Typed API Client 与 View-Model 转换层（MailItem、MailDetail）
- 实现基于 React Query 的邮件列表与详情缓存，设计修订版本锁（Revision-guarded Rollback）和单路互斥门禁以支持乐观更新与并发安全回滚
- 实现邮件阅读器（MessageReader）：利用 DOMPurify 与沙箱 iframe 隔离渲染邮件正文，强制实施 CSP 规则；阻断第三方外部追踪图片，提供按需代理加载与发件人白名单控制；支持暗黑模式智能反色与原样视图切换
- 实现邮件列表（MessageList）：支持基于行高的虚拟化窗口渲染、滚动帧合并（rAF）、多选批量处理、首信点选自动读取、搜索防抖及 CJK 快速触发
- 实现侧边栏导航（Sidebar）：多账号与分组管理、文件夹层级树导航、拖拽排序布局持久化同步、全量与分组未读角标聚合统计
- 提供应用设置中心（SettingsModal）与账号配置表单（AccountDialog）：支持 IMAP / Microsoft Graph 双协议、OAuth 设备码与授权码流程、时区与超时偏好、登录密码修改及全局发件人图片白名单管理
- 提供全局 UI 错误兜底（ErrorBoundary）：支持模块级局部重试与刷新、堆栈脱敏与诊断日志导出，并集成 UI 引用编号快捷键覆盖层（UiReferenceOverlay）

## interfaces

- src/frontend/src/api/client.ts: api.checkSession, api.login, api.logout, api.getAccounts, api.addAccount, api.updateAccount, api.deleteAccount, api.getGroups, api.createGroup, api.renameGroup, api.deleteGroup, api.getSidebarLayout, api.saveSidebarLayout, api.resetSidebarAccountOrder, api.getSettings, api.updateSettings, api.changePassword, api.getOAuthMetadata, api.getActiveOAuthFlow, api.startOAuthFlow, api.getOAuthFlowStatus, api.pollOAuthFlow, api.cancelOAuthFlow, api.exchangeMicrosoftRedirectUrl, api.syncAll, api.syncAccount, api.getSyncRequest
- src/frontend/src/api/mailCore.ts: fetchMailCoreInbox, fetchMailCoreSearch, fetchMailCoreMessage, postMailCoreMessageRead, postMailCoreMessageFlag, postMailCoreMessageTrash, postMailCoreMarkAllRead, postMailCoreSyncMessageBody, allowMessageRemoteImages, allowSenderRemoteImages, fetchAllowedSenders, removeAllowedSender, mailCoreAttachmentUrl
- src/frontend/src/api/queries.ts: queryClient, queryKeys, fetchAccounts, fetchGroups, findCachedMail, setReadOptimistic, markReadOptimistic, flagOptimistic, applyCachedReadStateWithRollback, beginReadMutation, removeCachedMail, invalidateMailListQueries, invalidateMailStatsQueries, resetMailListQueries, resetGroupMailQueries
- src/frontend/src/api/sseStream.ts: subscribeMailCoreStream, parseSseChunk
- src/frontend/src/api/sync.ts: waitForSyncRequests, syncFailureDetail, isSyncTerminalState
- src/frontend/src/components/\*: MessageReader, MessageList, Sidebar, SettingsPage, AccountDialog, LoginPage, ErrorBoundary, ColumnResize, CopyAddress, UiReferenceOverlay, AccountIcon

## dependencies

- src/frontend/src/lib/apiBase
- src/frontend/src/lib/previewText
- src/frontend/src/lib/displayName
- src/frontend/src/lib/listDate
- src/frontend/src/lib/formatSize
- src/frontend/src/lib/mailKey
- src/frontend/src/lib/actions
- src/frontend/src/lib/mailBody
- src/frontend/src/lib/viewport
- src/frontend/src/lib/desktopShell
- src/frontend/src/lib/concurrency
- src/frontend/src/lib/account_providers
- src/frontend/src/lib/ui_shortcut
- src/frontend/src/lib/uiReference
- src/frontend/src/lib/ui_reference_overlay
- src/frontend/src/store/mailStore
- src/frontend/src/store/accountIcon
- @tanstack/react-query
- react
- react-dom
- lucide-react
- dompurify

## flows

- 用户操作或定时刷新 -> apiRequest 检查并附加 X-CSRF-Token -> 发送请求至 mail-core API -> 遇到 401 广播 UNAUTHORIZED_EVENT 重置状态到登录界面
- 标记已读/旗标 -> setReadOptimistic / flagOptimistic 递增本地 revision 并乐观修改 React Query 缓存 -> 发起异步变更 -> 成功提交新版本；失败则比对 revision 并按需精准回滚
- 选信 -> MessageReader 读取缓存或发起 fetchMailCoreMessage -> HTML 邮件由 prepareMailHtml 清洗并注入 CSP 与反色样式 -> 沙箱 iframe 渲染；纯文本直接由 React 文本节点安全转义渲染
- 列表滚动 -> 触发 handleScroll 并通过 requestAnimationFrame 合并帧更新 -> virtualWindow 计算可见视口切片并补齐前后占位符
- 侧边栏拖拽账号/分组 -> 派生新排序 -> 乐观更新本地状态并调用 api.saveSidebarLayout(expected_revision) -> 后端若冲突则回滚并重新拉取布局

## constraints

- src/frontend/src/api/generated/schema.ts 禁止手工编辑，必须由 scripts/gen-openapi.sh 权威链路同步生成
- 所有写操作（POST / PATCH / PUT / DELETE）必须强制携带有效 X-CSRF-Token，禁止无保护写请求
- 邮件 HTML 正文沙箱 iframe 严禁赋予 allow-scripts 或 allow-same-origin 权限，彻底隔绝 XSS 与 DOM/Cookie 越权访问
- 外部远程图片默认全量阻断，仅在用户授权后经由服务端代理同源输出
- 账号分页采用硬性上限限制（ACCOUNT_MAX_PAGES = 50），防止后端分页异常导致前端请求风暴

## decisions

- 邮件正文渲染使用独立 iframe + srcdoc 架构，而非 dangerouslySetInnerHTML，通过浏览器边界完全隔离不可信富文本内容（A384）
- iframe 沙箱保留 allow-popups-to-escape-sandbox，配合 rel='noopener noreferrer' 与 <base target='_blank'>，使正文链接在外部独立窗口安全打开，且切断 opener 句柄与 referrer 泄露
- 标记全部已读采用基于 revision 的回滚控制（applyCachedReadStateWithRollback）与并发互斥门禁（beginReadMutation），彻底避免与单封邮件点选的并发竞态（A149, A183）
- 列表采用固定高度（100px）与固定 overscan（8）的纯数学切片虚拟化，消除第三方大库依赖，保证极端列表规模下的极低内存占用与高帧率

## evidence

- src/frontend/src/api/client.ts:226-233
- src/frontend/src/components/MessageReader.tsx:629-657
- src/frontend/src/api/queries.ts:466-508
- src/frontend/src/components/MessageList.tsx:383-393
- src/frontend/src/components/Sidebar.tsx:387-410

## uncertainties

## Findings

- [Info][95] src/frontend/src/components/MessageReader.tsx:171 — setQueryData 内部使用 any 绕过类型安全检查
    - ID: f_frontend_ui_01; verification: static
    - Evidence: queryClient.setQueryData(['detail', 'mail-core', selected.id], (old: any) => (old ? { ...old, remote_images_allowed: true } : old))
    - Impact: 使用了 any 强制绕过 TypeScript 编译期检查，若 MailDetail 结构字段发生重构或扩展，编译器无法发现类型不一致风险。
    - Fix: 为 updater 参数提供显式类型标注 (old: MailDetail | undefined) => ...，消除 any 逃逸。

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
  "src/frontend/src/api/client.csrf.test.ts",
  "src/frontend/src/api/client.errors.test.ts",
  "src/frontend/src/api/client.ts",
  "src/frontend/src/api/deadExports.test.ts",
  "src/frontend/src/api/generated/README.md",
  "src/frontend/src/api/generated/schema.ts",
  "src/frontend/src/api/mailCore.client.test.ts",
  "src/frontend/src/api/mailCore.mutations.test.ts",
  "src/frontend/src/api/mailCore.test.ts",
  "src/frontend/src/api/mailCore.ts",
  "src/frontend/src/api/queries.cache.test.ts",
  "src/frontend/src/api/queries.scope.test.ts",
  "src/frontend/src/api/queries.ts",
  "src/frontend/src/api/schemaTypes.ts",
  "src/frontend/src/api/sseStream.test.ts",
  "src/frontend/src/api/sseStream.ts",
  "src/frontend/src/api/sync.test.ts",
  "src/frontend/src/api/sync.ts",
  "src/frontend/src/components/AccountIcon.test.tsx",
  "src/frontend/src/components/AccountIcon.tsx",
  "src/frontend/src/components/ColumnResize.test.tsx",
  "src/frontend/src/components/ColumnResize.tsx",
  "src/frontend/src/components/CopyAddress.test.tsx",
  "src/frontend/src/components/CopyAddress.tsx",
  "src/frontend/src/components/ErrorBoundary.test.tsx",
  "src/frontend/src/components/ErrorBoundary.tsx",
  "src/frontend/src/components/LoginPage.test.tsx",
  "src/frontend/src/components/LoginPage.tsx",
  "src/frontend/src/components/MessageList.test.tsx",
  "src/frontend/src/components/MessageList.tsx",
  "src/frontend/src/components/MessageReader.test.tsx",
  "src/frontend/src/components/MessageReader.tsx",
  "src/frontend/src/components/SettingsModal.test.tsx",
  "src/frontend/src/components/SettingsModal.tsx",
  "src/frontend/src/components/Sidebar.test.tsx",
  "src/frontend/src/components/Sidebar.tsx",
  "src/frontend/src/components/UiReferenceOverlay.test.tsx",
  "src/frontend/src/components/UiReferenceOverlay.tsx",
  "src/frontend/src/components/brand-icons/BrandIcons.tsx",
  "src/frontend/src/components/brand-icons/brandIconMap.test.ts",
  "src/frontend/src/components/brand-icons/brandIconMap.ts",
  "src/frontend/src/components/credential_help.test.tsx",
  "src/frontend/src/components/credential_help.tsx",
  "src/frontend/src/components/microsoft_account_form.test.tsx",
  "src/frontend/src/components/provider_account_form.test.tsx",
  "src/frontend/src/components/settings_account_form.countdown.test.tsx",
  "src/frontend/src/components/settings_account_form.tsx",
  "src/frontend/src/components/settings_redesign.test.tsx"
]
```
