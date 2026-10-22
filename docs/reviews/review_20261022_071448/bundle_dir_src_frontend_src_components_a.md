# Bundle Review — dir:src/frontend/src/components_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][96] src/frontend/src/components/MessageList.tsx:189-L189 — 最早优先只重排当前已加载的一页邮件 — 证据：本地 raw 列表反向排序；API 没有排序参数，后端固定按 sort_time DESC。超过 100 封时首屏仍取最新 100 封，无法展示真正最早邮件。 — 依据：src/frontend/src/api/mailCore.ts:50 无排序参数。 — 修复：提供服务端排序及匹配游标方向，或明确限制排序只作用于已加载页。
- [Medium][95] src/frontend/src/components/MessageList.tsx:268-L368 — 全部已读和未读数只处理已加载邮件 — 证据：按钮只把 visible 当前页传给 markReadOptimistic，禁用条件与角标也基于本地已加载项；后续页未读邮件会被当作不存在。 — 依据：全局精准统计应来自服务端计数与批量操作契约。 — 修复：增加服务端批量标记全部已读，或明确把控件限制为当前已加载邮件。
- [Low][99] src/frontend/src/components/MessageList.tsx:55-L55 — CJK 单字搜索仍等待 250ms 防抖 — 证据：所有输入统一走 250ms timer，CJK 单字也延后更新搜索状态。 — 依据：docs/specs/inbox_ui_and_search.md AC-004 要求 CJK 单字即时触发、纯英文防抖。 — 修复：CJK 输入即时更新，保留英文防抖及最短字符门槛。
- [Low][99] src/frontend/src/components/ErrorBoundary.tsx:30-L30 — 复制诊断日志在异步失败时仍提示成功 — 证据：未等待 Clipboard API Promise，立即设置已复制；权限拒绝会形成未处理 rejection 且错误提示不实。 — 依据：异步操作的成功状态应在 Promise resolve 后设置。 — 修复：await 写入并处理拒绝；仅成功后显示成功状态。
- [Low][100] src/frontend/src/components/LoginPage.tsx:74-L74 — 登录页建议检查不存在的 LOGIN_PASSWORD 环境变量 — 证据：提示列出 MAIL_CORE_LOGIN_PASSWORD / LOGIN_PASSWORD；仓库未使用后者，桌面初始密码由 main 随机生成并通过启动对话框展示。 — 依据：真实变量见 API/desktop startup 配置。 — 修复：按部署方式显示有效环境变量或桌面初始密码路径。

## Files examined

- src/frontend/src/components/ColumnResize.test.tsx
- src/frontend/src/components/ColumnResize.tsx
- src/frontend/src/components/ErrorBoundary.tsx
- src/frontend/src/components/LoginPage.tsx
- src/frontend/src/components/MessageList.test.tsx
- src/frontend/src/components/MessageList.tsx
- src/frontend/src/components/MessageReader.test.tsx
- src/frontend/src/components/MessageReader.tsx
