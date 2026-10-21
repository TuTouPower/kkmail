# p008 侧栏账户加载失败提示误导且缺乏重试交互

- 现象：当 `GET /api/groups` 或 `GET /api/accounts` 发生网络超时、后端 500 等异常时，侧栏“邮箱账户”节点显示假定未登录的静态文本「账户加载失败，请确认已登录且后端可用」；此时用户实际已登录，且中间邮件列表正常渲染展示（走 `/api/mail/inbox`），无重试入口。
- 影响：用户误判系统鉴权或全局后端崩溃，与正常可见的邮件列表产生认知割裂；同时因缺乏重试交互，网络抖动或瞬时错误后必须强制刷新整个页面。
- 根因：`Sidebar.tsx` 未使用 `errorMessage` 获取实际异常信息，而是对 `groupsQuery.error || accountsQuery.error` 硬编码了假定“未登录且后端可用”的兜底文案；且未向用户暴露 `refetch` 操作。扫描前端其它错误提示，未见同类直接假定未登录的误导硬编码（已扫无同类）。
- 测试缺口：`Sidebar.test.tsx` 仅测试了账户与统计接口成功的 Happy Path，完全缺失账户/分组查询失败时的错误展示与重试交互断言。应在前端组件测试中补充 Query Error 状态下的真实错误展示与重试按钮测试。
- 线索：`src/frontend/src/components/Sidebar.tsx` 217~221 行；`.scratch/bug_repro/sidebar_error_repro.ts`。
- 处理：未开
