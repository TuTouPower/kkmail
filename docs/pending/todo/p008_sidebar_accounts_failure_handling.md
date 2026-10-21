# p008 AccountDTO slots致accounts接口500及侧栏错误提示失真

- 现象：访问网页时侧栏“邮箱账户”节点显示「账户加载失败，请确认已登录且后端可用」；但用户已正常登录，且中间邮件列表正常渲染展示（走 `/api/mail/inbox`）。
- 影响：用户无法查看与切换各账户，误以为登录失效或后端彻底崩溃；且因缺乏重试入口，无法就地恢复。
- 根因：
    1. 后端根因：`src/mail_core/mail/application/accounts.py` 中的 `AccountDTO` 使用了 `@dataclass(frozen=True, slots=True)`，实例不具备 `__dict__` 属性。而 `src/mail_core/api/accounts.py`（第 116、135、152 行）依然使用 `a.__dict__` 展开构造 `AccountOut`，只要数据库存在账户，`GET /api/accounts`（以及 POST/PATCH）即抛出 `AttributeError: 'AccountDTO' object has no attribute '__dict__'`，FastAPI 报 500。同类位点：全库扫描仅此 3 处使用 `.__dict__`。
    2. 前端根因：`Sidebar.tsx` 未使用 `errorMessage` 获取实际异常信息，而是对 `groupsQuery.error || accountsQuery.error` 硬编码了假定“未登录且后端可用”的兜底文案，且未提供 `refetch` 重试按钮。
- 测试缺口：
    1. 后端：`test_accounts_api_unit.py` 仅测试了 401 和 422，未包含对 `GET /api/accounts` 正常返回 200 的 Mock/单测验证；`test_accounts_api_pg.py` 因环境变量缺失在日常单测中被跳过。
    2. 前端：`Sidebar.test.tsx` 仅测试了 Happy Path，缺少 Query Error 场景下的真实错误展示与重试测试。
- 线索：`src/mail_core/api/accounts.py:116`；`src/frontend/src/components/Sidebar.tsx:219`；`.scratch/bug_repro/sidebar_error_repro.ts`。
- 处理：未开
