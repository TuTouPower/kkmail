# Task spec

## 背景

三个 QQ IMAP 账号的 `其他文件夹` 均在服务器 `LIST` 中标记为 `\NoSelect \HasChildren`。Provider 已过滤这类目录，但 `sync_account_folders` 只 upsert，不处理已存在但本轮不再返回的目录，因此旧父目录仍显示为可点击邮箱并留下失败元数据任务。QQ 的只读探测确认 `SELECT` 后 `UID SEARCH` 返回 `[CLIENTBUG] No mailbox selected`。一个账号的 `QQ邮件订阅` 是该父目录下的可同步子目录。

## 契约区

### 范围

- 将 IMAP `\NoSelect` 文件夹作为不可选择的结构节点保留，不能对它执行邮件元数据同步。
- 文件夹发现将旧数据库目录与本轮远端目录集对账，使不再可选择的节点不再作为普通可点击邮箱呈现；已有子目录保留父子关系。
- 已排队或后续执行的不可选择目录元数据任务不得重试为普通邮箱任务。
- UI 对结构节点隐藏未读数未知标记，子目录仍可独立打开和同步。

### 非范围

- 不清除历史 `Message`、`MessageLocation`、checkpoint 或文件夹数据。
- 不把 `UID SEARCH NO` 通用地当作空文件夹成功；其它服务器错误仍须保留失败语义。
- 不改变 QQ 以外可选择 IMAP 文件夹的同步行为。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：LIST 返回 `\NoSelect \HasChildren` 的 QQ `其他文件夹` 在发现结果中标为结构节点，不创建新的元数据同步任务。
- [ ] AC-002：数据库已有该目录及待处理元数据任务时，后续发现将其转为不可选择状态；执行中的旧任务以可观察的 skipped 结果完成，不再因 `UID SEARCH NO` 重试至失败。
- [ ] AC-003：folder-stats API 与侧栏将结构节点呈现为不可打开、无未读数 badge 的父节点；`QQ邮件订阅` 仍嵌套其下并可打开。
- [ ] AC-004：处理结构节点不会删除其 `Folder`、历史邮件位置、邮件或 checkpoint；普通可选择文件夹仍正常排队和同步。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试；实时 QQ LIST/SEARCH 响应已通过只读探测记录，自动测试使用同一 flags/status fixture。

## 上下文区

- 来源：p038（2026-10-24 核实：三个 QQ 账号 raw LIST 均为 `\NoSelect \HasChildren`；历史 5 个元数据任务均重试 8 次后失败；当前过滤器不返回这些父目录，但旧 DB 记录仍在）。

### 有意不测

- 真实 QQ 邮件内容：只读探测仅访问 LIST、SELECT 与 UID SEARCH，不拉取邮件正文或修改远端数据。

### 测试策略

- IMAP Provider 测试覆盖 noselect 结构节点与普通可选择节点。
- PostgreSQL 集成测试先写入旧目录、checkpoint/消息位置及待处理任务，再执行 folder discovery，检查仅状态/任务行为变化、数据保留和子目录 parent id。
- Worker 测试检查已排队 noselect metadata 任务被跳过并完成；普通 SEARCH NO 仍为错误。
- API/前端测试验证结构节点禁用、无蓝色 `-`、子文件夹缩进与精确 folder id 导航。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。QQ 的 LIST flags、SELECT 状态及 SEARCH 响应已通过只读探测确认。

### 风险与回退

- 风险：结构节点与真实空文件夹可能同时没有统计；必须以 `\NoSelect` 协议标记识别，不能仅按空统计推断。
- 回退：恢复原 Provider/发现/UI 逻辑；数据不做物理删除，回退不需恢复数据库备份。

### 依赖与约束

- 保留当前账号范围隔离与 IMAP Modified UTF-7 remote_id；不可选择状态必须绑定明确的 LIST flag。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新 IMAP noselect 结构节点、任务调度和父子目录呈现约定。
