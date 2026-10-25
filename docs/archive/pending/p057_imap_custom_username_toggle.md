# p057 IMAP 账户表单独立登录名应默认隐藏并由勾选触发自定义

- 现象：添加/编辑 IMAP 账户对话框中，`IMAP 登录名` 作为一个常规独立输入框始终平铺展示，造成绝大多数用户困惑（以为邮箱地址和登录名必不相同或需要重复输入），未采用渐进式披露。
- 影响：前端账户设置弹窗 `src/frontend/src/components/settings_account_form.tsx`。所有新增或修改 IMAP 账户的用户均暴露于冗余字段，增加填写与理解成本。
- 根因：交互设计缺陷。95% 以上现代邮箱（QQ/网易/Gmail/Outlook 等）IMAP 登录名与邮箱地址完全相同（后端也已有未设 `imap_user` 时回落至 `email` 的兜底机制），但仅约 5% 的特殊场景（自建 Linux 邮件服务器 Dovecot/Postfix 系统用户名、别名 Alias、特定高校/旧版 ISP）需要独立登录名；前端未做勾选展开控制，直接全局平铺。已扫无同类。
- 测试缺口：现有前端测试 `src/frontend/src/components/provider_account_form.test.tsx` 假定 `#account-username` 始终平铺存在，未覆盖“默认折叠/不传 `imap_user`、勾选后展开自定义、已有不同 `imap_user` 账户编辑时自动勾选回显”等交互与断言。应在组件单测补测该渐进披露逻辑。
- 线索：`.scratch/imap_username_analysis.md`
- 处理：fix/review-20261026-commits
