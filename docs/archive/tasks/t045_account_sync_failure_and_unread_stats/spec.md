# Task spec

## 背景

当前当任意账号因口令/授权码错误或同步失败而尚未落库真实文件夹（`folders: []`）时，侧栏展开该账号仍无条件渲染前端虚拟快捷项「未读邮件」且无错误/空目录提示，造成“只能拿到未读邮件”的假象；同时全局与分组未读汇总未排除已禁用（`sync_enabled=false`）或同步/认证失败且无目标文件夹的故障账号，导致单个故障账号将全局「所有收件箱」与所属分组的未读角标永久传染为 `-`。此外，网易 126/163 密码错误未被识别为永久认证失败、空文件夹首次同步未初始化 `FolderStats`、以及后台跟进任务重入队时丢失 `payload`（`folder_id`），共同放大了账号同步失败与统计异常。

## 契约区

### 范围

- 侧栏账号行与展开区域处理同步失败与空文件夹状态：当账号 `folders` 为空数组时不单独裸露虚拟「未读邮件」入口，并根据账号 `sync_status`（`auth_failed` / `failed`）或空目录状态展示明确提示。
- 全局与分组收件箱统计聚合（后端 `/api/mail/stats` 与前端侧栏/列表汇总）排除已禁用（`sync_enabled=false`）或同步/认证失败且无目标角色文件夹的故障账号，使其不阻断其余正常账号的未读数与总数汇总；故障账号自身仍展示 `-` 与异常状态，正常同步中但缺 `FolderStats` 或含未知已读状态邮件时仍传播 `null`（`-`）；统一侧栏与邮件列表头部对缺目标文件夹账号的统计语义。
- IMAP 连接登录识别网易 `login error or password error` 等永久认证失败并抛出 `PermanentAuthError`（标记 `auth_failed` 并停止盲目重试）。
- 空文件夹首次元数据同步完成（`apply_metadata_page` 遇到空页且尚无 `FolderStats` 行）时立即初始化 `FolderStats(total_count=0, unread_count=0)`。
- Worker 任务完成跟进重入队（`_evaluate_result`）时保留原业务 `payload`（如 `folder_id`），仅剔除内部临时标记（`_followup_needed`、`_followup_run_after`）。

### 非范围

- 不修改真实邮箱账号的外部保存密码或授权码。
- 不改变正常账号包含 `is_read: null` 邮件时单文件夹及聚合传播未知未读数（`-`）的既有契约。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：当账号真实文件夹列表为空（`folders: []`）时，侧栏展开该账号不再单独显示虚拟「未读邮件」项；若账号处于认证失败或同步失败状态则展示明确的同步失败提示，否则展示暂无文件夹提示。
- [ ] AC-002：当实例或分组内存在已禁用（`sync_enabled=false`）或同步/认证失败（`sync_status` 为 `failed` / `auth_failed`）且无目标角色文件夹的账号时，全局与分组未读数及总数汇总排除该故障账号并返回其余正常账号的真实汇总值（故障账号自身仍为 `null` / `-`）；若正常启用账号仍缺 `FolderStats` 或存在 `is_read: null` 邮件，汇总仍返回 `null`（`-`）；侧栏与邮件列表头部对缺目标文件夹的统计表现一致。
- [ ] AC-003：IMAP 登录返回 `LOGIN Login error or password error` 时被判定为永久认证失败（`PermanentAuthError`），账号状态更新为 `auth_failed` 且 `sync_enabled=false`，不再进行无意义的退避重试。
- [ ] AC-004：空文件夹执行 `apply_metadata_page`（0 封邮件）后立即生成 `total_count=0, unread_count=0` 的 `FolderStats` 记录，文件夹统计接口不再因空目录未变更而长期返回 `unread_count: null`。
- [ ] AC-005：Worker 执行带 `folder_id` 等业务参数的任务并在 `has_more` 或 `_followup_needed` 触发跟进重入队时，新入队任务完整保留原业务 `payload`（不含 `_followup_*` 内部字段），后续执行不再抛出 `KeyError: 'folder_id'`。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p027`（2026-10-23 核实：`Sidebar.tsx:164-236`、`MessageList.tsx:178-216`、`queries.py:380-442`、`imap.py:326-332`、`metadata.py:168-201`、`worker/handlers.py:34-42` 缺陷均存在；用户已确认采用“排除故障无目录账号+含 worker 修复”口径）

### 有意不测

- 第三方外部 126 线上服务器真实错误口令拨测：由 IMAP 协议单元测试与模拟响应验证，不向公网发起错误密码轰炸。

### 测试策略

- 后端集成测试（`tests/mail_core/test_global_stats.py` 等）：验证含认证失败/同步失败/禁用且无收件箱账号时的全局与分组统计聚合、正常缺 `FolderStats` 账号传播 `null`、以及空文件夹 `apply_metadata_page` 初始化 `FolderStats(0, 0)`。
- 后端单元测试（`tests/mail_core/test_imap_provider.py`、worker handler 测试）：验证 `LOGIN Login error or password error` 抛出 `PermanentAuthError`，以及 `_evaluate_result` 跟进任务保留 `folder_id` 等业务 `payload`。
- 前端组件测试（`Sidebar.test.tsx`、`MessageList.test.tsx`）：验证 0 文件夹/同步失败账号展开提示、不裸露虚拟「未读邮件」以及侧栏与列表统计一致性。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：修改全局统计聚合条件可能影响 `t039` / `t041` 已有的未知未读数测试预期。
- 回退：精确区分“正常同步中尚未生成 `FolderStats` 的账号（保留传播 `null`）”与“已处于 `sync_enabled=false` 或 `sync_status in ('failed', 'auth_failed')` 且无目标文件夹的故障账号（从聚合分母排除）”，保持既有测试对正常账号缺统计行传播未知的语义。

### 依赖与约束

- 更新 `docs/blueprint/conventions.md` §七.4 时须与 `t040` / `t041` 的统计契约协调一致。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：更新 §七.4「未读数未知语义」中故障无目录账号的聚合排除规则及空文件夹统计初始化规范。
