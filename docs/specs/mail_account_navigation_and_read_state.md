# 需求规格：账号导航、未读统计与邮箱地址复制

## 背景

多账号邮件客户端须将可见账号、邮件聚合范围和未读统计保持一致；账号导航应能快速过滤和复制邮箱地址，邮件详情应支持逐地址复制且保留不可解析文本。

## 契约区

### 范围

- 禁用账号在侧栏与全局/分组聚合列表、搜索、统计和批量已读中的处理。
- 已读/未读状态在列表、全局、账号、分组、角色及精确文件夹缓存中的即时同步。
- 分组和总账号列表互相独立的本地账号搜索。
- Reader、Sidebar 和 Settings 已有邮箱地址展示位置的复制交互。
- 邮件列表/搜索的文件夹归属数据，以及详情 API 的结构化收件人和抄送人地址。

### 非范围

- 发信、联系人、系统通知和浏览器扩展。
- 新增数据库迁移、邮件列表新增归属邮箱展示位点、正文 iframe 复制、剪贴板读取权限或新 Electron IPC。

### 验收标准

- [x] AC-001：`sync_enabled=false` 账号从全局分类、分组账号项和总账号列表隐藏；设置页仍可管理。聚合 inbox/search/stats/mark-all-read 只覆盖启用账号；空范围返回空结果与零统计，直接账号/文件夹访问不变。
- [x] AC-002：隐藏禁用账号不删除分组、布局成员关系或排序；重新启用后恢复原位置。当前选中账号被禁用后回到所有收件箱并清除选择与搜索。
- [x] AC-003：列表和搜索 DTO 的 `locations` 包含同一账号内邮件全部文件夹 ID/角色，按页批量读取；原代表性 `folder_id` 保留。
- [x] AC-004：读/未读状态按 `mailKey` 去重并更新所有已知匹配缓存；多文件夹分别计数，`null` 不推测。相同邮件写入串行，失败仅撤销仍属于该操作的变化；部分批量失败后刷新服务端事实。
- [x] AC-005：本地读状态操作期间合并并延后 list/stats SSE 失效，完成后刷新权威数据。普通视图列表头使用权威未读统计；搜索不把已加载结果冒充全量统计。
- [x] AC-006：每个分组及总账号列表分别保存本地搜索词；按邮箱、域名、`display_name` 大小写不敏感包含匹配，首尾空白不参与过滤。禁用账号不参与匹配，全局分类账号入口不受总列表搜索影响。
- [x] AC-007：搜索只影响本区账号入口，不改变邮件 scope、分组成员数、统计或选择。无匹配显示空态；清空/Esc/再次点击关闭时清词并恢复原展开状态；搜索不持久化，过滤区禁用账号与分组拖放。
- [x] AC-008：Reader 归属邮箱、发件人、每个收件人与抄送人、Sidebar 账号入口及 Settings 账户邮箱可复制纯邮箱地址。普通地址文本可点击复制；已有导航或展开行为的行使用独立兄弟按钮。
- [x] AC-009：详情响应保留原 `to`/`cc` 文本，并返回必需 `to_addresses`/`cc_addresses` 数组。标准邮件地址解析器提供 `{name, address}`；不可靠片段通过 `text` 保留，不提供复制目标。
- [x] AC-010：复制成功提示“已复制地址”约 2 秒，重复点击重置计时；API 缺失或写入失败显示原因与手动复制提示，不伪报成功。组件卸载清理计时器，并忽略卸载后才完成的写入。
- [x] AC-011：浏览器与 Electron 均由用户点击触发既有 `navigator.clipboard.writeText`；不开放读取，不放宽邮件 iframe 权限，不新增 IPC。

### 接口与数据

- inbox/search 列表项新增 `locations: [{folder_id, role}]`。
- Message detail 新增必需 `to_addresses`、`cc_addresses`；每项含 `name`、`address`，无法可靠解析时用 `text` 保存显示文本且 `address=null`。
- 兼容保留 `to`/`cc` 格式化字符串。无需数据库迁移。

### 验证

- 前端：`npm test`、`npx tsc -b`、`npm run build`、OpenAPI/CSS 检查；侧栏、Reader、Settings 与 `CopyAddress` 组件测试。
- 后端：`scripts/run-mail-core-tests.sh run -k "folder_role_inbox_api or fts_inbox_api" --no-cov` 与详情 API PostgreSQL 用例。
- 黑盒：`npm run test:e2e` 验证 180px 侧栏、移动抽屉与浏览器剪贴板；`python3 scripts/run_full_stack_e2e.py` 验证真实全栈。
- Electron：`npm test` 中的 `clipboard.test.js` 验证系统剪贴板写入、邮件 iframe 隔离及剪贴板读取拒绝。

## 上下文区

- 来源：`docs/archive/pending/p041_unread_badge_stale_on_mark_read.md`、`docs/archive/pending/p042_copy_account_email_on_click.md`、`docs/archive/pending/p043_sidebar_account_search_button.md`。
- 侧栏搜索和禁用账号过滤只影响显示，不改变完整布局快照；全部列表、搜索和统计缓存均按完整 scope 语义维护。
