---
tid: "t027"
slug: "account_group_ordering"
title: "完整改造账号分组侧栏与邮件范围"
status: "done"
branch: "t027_account_group_ordering"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "c8cee92446f9c24e7a0a2a501d52d0bd49068041"
depends_on: ""
conflicts_with: "t026"
note: "合并原 t027–t031，保留全部 40 条 AC；完整功能不减、无预置示例分组；t032 独立负责双端窗口适配"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建依据：2026-10-23 核对设计聊天、v3 本地原型与 main@26a8eee。仅登记 backlog，未 start、未实施。

- 用户要求合并为两个 task：本 task 接收原 t028–t031 全部范围与 AC，保留 t032 为后续双端窗口适配；合并前均为主仓 backlog，无执行分支、worktree 或 attempt 记录。

- 已完成的实施：新增账号总列表/组内顺序字段与迁移，分组重命名及带 revision 的完整布局快照 API；旧 revision 返回 409，组织写事务共用 advisory lock。邮件列表、搜索（含精确文件夹搜索）、统计和批量已读接受分组范围，并对空组、未知统计与范围冲突作 fail-closed 处理。前端实现三段侧栏，保留六类全局分类及对应分组入口、账号真实文件夹与未读快捷项、用户自定义分组管理、移组和整行拖拽；展开状态存入本地偏好。成员变化清空旧详情选择并重置组列表/搜索至首屏，组角标复用全局统计。未预置示例分组。

- attempt 1 因测试专用 PostgreSQL 门禁记录 stopped/blocked。随后确认主仓本地 `.env.test` 已有非空 `KKMAIL_TEST_PG_PASSWORD`，task-run 于 2026-10-23T04:38:05+08:00 登记 attempt 2 / `984c808877d347e8a6098ed0d3abafc6`；测试进程仅接收变量，不输出或复制密钥。

- Round 1 独立 code/test review 共报 21 项（代码 14、测试 7）；本轮处置表逐项登记修复，并新增真实 PostgreSQL API、组件和浏览器回归。

- Round 2 code/test review 共报 9 项（代码 6、测试 3）；新增 revision 冲突、未知统计、精确文件夹搜索及真实浏览器失败/无效拖放/连续拖动覆盖，处置表逐项登记。

- Round 3 code review 新报 3 条 important、1 条 minor；test review 重开设置入口跨组件刷新覆盖（t027_test_f006）。实施方清理所有组列表缓存、移除 20,000 项硬截断、删除账号后重置统计/列表，并将布局成员汇总改为单次分桶；补设置页创建/删除与侧栏同步、删除末个账号统计清理及超 20,000 项分页测试。

- Round 4 code review 确认 f021–f024 修复，新增 f025（添加账户后统计缓存未刷新）；test review 指出 t027_test_f006 首次跨组件测试缺少账号与布局快照断言。Round 5 前补添加账号统计刷新，并扩展设置页创建/移组/删除的共享账号与布局快照联动测试。

- Round 4 后前端全量 217 passed，TypeScript、生产构建、lint、OpenAPI 与 CSS 检查通过；真实全栈 E2E 8/8；布局快照 PostgreSQL 定向测试 3/3；Markdown 与 diff 检查通过。全量 PostgreSQL 405 passed 为此前同一 attempt 的已记录基线，Round 3 后改动另由定向 DB 用例覆盖。

- Round 5 code/test review 均 PASS，review scope `18514639e6c252b7`；处置项全部关闭。最终黑盒复验：轻量 E2E 9/9，真实全栈 E2E 8/8；前端 217/217，布局快照 PostgreSQL 定向测试 3/3，preflight 与格式检查通过。

- 最终验证基线：模板契约 149 passed；隔离 PostgreSQL 全量 405 passed；前端 38 个测试文件 / 213 passed；TypeScript、生产构建、lint、OpenAPI 与 CSS token 检查通过；快速浏览器 E2E 9 passed；真实全栈 E2E 8 passed（含组内/跨组排序、设置移组、保存失败回滚、自拖/取消/外部拖放与连续拖动）。Round 3 后增量验证见上文。

- 桌面基础与真实打包 PostgreSQL 生命周期测试通过。此次 Round 1 收敛未改动桌面代码。

- 桌面测试所需 Electron 依赖按锁文件安装到隔离 worktree；测试打包所需 PostgreSQL 二进制通过本地 symlink 指向主仓现有构建资源，主仓资源未改动。完整门禁通过后执行独立代码与测试 review，再填写 handoff、finish 并建立唯一执行 commit。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T05:15:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t027_code_f001|important|已修|分组删除与布局保存统一按组、账号顺序加锁。|src/mail_core/accounts/service.py|
|t027_code_f002|important|已修|布局写入期间禁止再次拖动，并等待失效查询完成后解锁。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f003|important|已修|分组 dragend 清除载荷；drop 校验当前 DataTransfer 与本次拖动。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f004|important|已修|拖到来源账号自身时不构造布局、不写入。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f005|important|已修|设置页删除当前分组后回到所有收件箱并清选择。|src/frontend/src/components/SettingsModal.tsx|
|t027_code_f006|important|已修|成员关系变化后清除邮件详情与批选状态。|src/frontend/src/components/Sidebar.tsx; src/frontend/src/components/SettingsModal.tsx|
|t027_code_f007|important|已修|组角标汇总现有全局账号统计，成员列新增索引。|src/frontend/src/components/Sidebar.tsx; src/mail_core/mail/storage/models.py; src/mail_core/db/alembic/versions/20261023_0016_sidebar_account_order.py|
|t027_code_f008|important|已修|账号标题与箭头均切换真实目录展开状态。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f009|important|已修|重命名请求期间禁用表单并以同步 ref 阻止重复提交。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f010|minor|已修|取消创建后焦点返回“新建分组”触发按钮。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f011|minor|已修|Pydantic 在长度检查前 trim 分组名称。|src/mail_core/api/accounts.py; tests/mail_core/test_accounts_api_unit.py|
|t027_code_f012|minor|已修|拆分完整布局校验与已验证布局写入。|src/mail_core/accounts/service.py|
|t027_code_f013|minor|已修|账号分组归属分支提取为局部函数。|src/mail_core/accounts/service.py|
|t027_code_f014|minor|已修|全部已读范围解析提取为独立查询函数。|src/mail_core/mail/application/mutations.py|
|t027_test_f001|important|已修|新增名称边界、失败重命名独立读取与非空组删除后凭据引用/账号/邮件/附件/顺序保留。|tests/mail_core/test_accounts_api_pg.py; tests/mail_core/test_accounts_api_unit.py|
|t027_test_f002|important|已修|新增默认/手动顺序、恢复默认、两套完整布局并发仅一方成功、旧 revision 冲突、锁序与迁移保留测试。|tests/mail_core/test_sidebar_group_scope.py; tests/mail_core/test_migration_validation.py|
|t027_test_f003|important|已修|覆盖 inbox/sent/drafts/trash/junk/archive、升降序同时间分页、唯一 offset 页、精确文件夹搜索/歧义、旗标已读、统计与移组后首屏重查。|tests/mail_core/test_sidebar_group_scope.py|
|t027_test_f004|important|已修|恢复全局/账号/组角标及未知计数测试，并断言成员变化刷新组角标、复用全局统计。|src/frontend/src/components/Sidebar.test.tsx|
|t027_test_f005|important|已修|真实浏览器断言 24px/48px 层级、三区独立折叠、760px 断点及双主题。|tests/e2e/sidebar_tree.spec.ts|
|t027_test_f006|important|已修|覆盖成功创建/重命名重查、删除取消保留成员、Escape 焦点、特殊字面量及真实浏览器设置下拉跨组/清组；同会话测试创建组、移入真实账号并删除组，断言 Sidebar 账号与布局快照重查且拖动重新可用。|src/frontend/src/components/Sidebar.test.tsx; src/frontend/src/components/SettingsModal.test.tsx; tests/e2e/full_stack.spec.ts|
|t027_test_f007|important|已修|真实浏览器覆盖排序、移组、自身/无效目标/外部拖动、保存失败回滚及连续拖动保护；组件断言首屏重置。|tests/e2e/full_stack.spec.ts; src/frontend/src/components/Sidebar.test.tsx; src/frontend/src/api/queries.cache.test.ts|

### Round 2 (2026-10-23T05:53:49+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t027_code_f015|important|已修|布局读取返回 revision；保存与恢复默认在事务锁下比较 expected_revision，旧版本返回 409 并刷新缓存；组织写共用 advisory lock。|src/mail_core/accounts/service.py; src/mail_core/api/accounts.py; src/frontend/src/components/Sidebar.tsx|
|t027_code_f016|important|已修|移组先锁目标组；移组与删组共享组织事务锁，删除竞态返回 404 而非 500。|src/mail_core/accounts/service.py; tests/mail_core/test_sidebar_group_scope.py|
|t027_code_f017|important|已修|成员集合比较改为 Set，复杂度降为线性。|src/frontend/src/components/Sidebar.tsx|
|t027_code_f018|important|已修|统计补全缺失账号并以 null 标未知；部分总计返回 null，侧栏、文件夹树与邮件列表不再把未知显示为零。|src/mail_core/mail/application/queries.py; src/mail_core/api/mail.py; src/frontend/src/components/Sidebar.tsx; src/frontend/src/components/MessageList.tsx|
|t027_code_f019|important|已修|设置页删除当前组时同时清除 search。|src/frontend/src/components/SettingsModal.tsx; src/frontend/src/components/SettingsModal.test.tsx|
|t027_code_f020|minor|已修|账号标题按钮的 aria-expanded 与展开状态同步。|src/frontend/src/components/Sidebar.tsx; src/frontend/src/components/Sidebar.test.tsx|
|t027_test_f008|important|已修|保存失败后断言账号仍在总列表且未进入目标组；真实浏览器另验 500 回滚。|src/frontend/src/components/Sidebar.test.tsx; tests/e2e/full_stack.spec.ts|
|t027_test_f009|important|已修|搜索分页两页 ID 互斥，且并集严格等于夹具预期邮件。|tests/mail_core/test_sidebar_group_scope.py|
|t027_test_f010|important|已修|组件覆盖切换其他组与清空；真实浏览器 selectOption 验证 PATCH 和服务端归属。|src/frontend/src/components/SettingsModal.test.tsx; tests/e2e/full_stack.spec.ts|

### Round 3 (2026-10-23T06:34:22+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t027_code_f021|important|已修|成员关系改变后重置所有组 inbox/search 缓存，避免重访时先显示旧组员邮件。|src/frontend/src/api/queries.ts; src/frontend/src/components/Sidebar.tsx; src/frontend/src/components/SettingsModal.tsx; src/frontend/src/api/queries.cache.test.ts|
|t027_code_f022|important|已修|账号分页持续读取至 has_more=false；若服务端声明仍有数据却返回空页则报错，不静默返回不完整清单。|src/frontend/src/api/queries.ts; src/frontend/src/api/queries.cache.test.ts|
|t027_code_f023|important|已修|删除账号后更新组和侧栏快照、重置全局统计并清空邮件列表缓存；删除末个账号时全局统计明确归零。|src/frontend/src/components/SettingsModal.tsx; src/frontend/src/api/queries.ts; src/frontend/src/components/SettingsModal.test.tsx|
|t027_code_f024|minor|已修|布局快照先单次按 group_id 分桶，再分别排序成员，避免每组扫描全部账号。|src/mail_core/accounts/service.py|

### Round 4 (2026-10-23T06:44:51+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t027_code_f025|important|已修|成功添加账号后等待账号列表刷新，再重置统计查询，避免旧全局 unread 总数与账号映射继续显示。|src/frontend/src/components/SettingsModal.tsx; src/frontend/src/components/SettingsModal.test.tsx|

无 finding 时写“Round N 零 finding”。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：40 条 AC 全部满足
- 测试：模板契约 149 passed；PostgreSQL 全量 405 passed（先前基线），Round 3 后布局快照定向 PostgreSQL 测试 3 passed；前端 38 files / 217 passed；TypeScript、生产构建、lint、OpenAPI 与 CSS token 检查通过；桌面基础与打包 PostgreSQL 生命周期测试通过且本 task 未改桌面文件。
- 黑盒：轻量浏览器 E2E 9 passed；真实全栈 Playwright E2E 8 passed，覆盖账号添加/同步、设置移组、分组拖拽持久化、失败回滚和无效拖放。
- review：Round 5 full code review PASS、test review PASS；scope `18514639e6c252b7`，无未处置 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- 账号分组、顺序、侧栏导航和分组邮件范围完整交付；六类既有分类、账号真实文件夹和全部账号管理功能保留。没有写入“工作/个人”等 demo 分组。无遗留 pending/finding。
