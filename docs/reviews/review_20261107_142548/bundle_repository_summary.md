# kkmail 全仓架构与认知汇总 (Repository Summary)

- 评审基线：`2d1752022dac0baa5f76bff3afa41e9d6a83bcfc`
- 评审范围：全仓（16 个单元，1473 个文件，213,960 行，排除本轮 review 产物与外部软链）
- 输出目录：`docs/reviews/review_20261107_142548`

______________________________________________________________________

## 1. 目标、范围、约束与前提

### 1.1 系统目标与产品范围

kkmail 是基于 mail-core 的现代化自托管多账号邮件客户端（FastAPI + PostgreSQL + React SPA + Electron 桌面端）。

- **产品范围约束**：聚焦于自托管收信、阅读、多账号集中管理、邮件归档与快速检索。
- **永久明确 Out of scope (wontfix)**：产品范围不含发信（SMTP/Graph Send）、联系人通讯录与操作系统桌面通知；浏览器扩展永久不开发。
- **历史脱钩事实**：项目最初 fork 自上游开源项目 `assast/outlookEmail`（基线 3.0.20），现已完全重构脱钩并独立演进，无任何上游代码继承。

### 1.2 核心架构铁律 (Core Architecture Directives)

- **架构至上**：始终选择最优雅、彻底、纯粹的顶层设计，完全忽略改动工作量；
- **拒绝妥协**：严禁使用临时补丁或局部修补规避底层重构，从根因修正；
- **零兼容性负担**：直接执行破坏性升级，不保留前后兼容层与过渡包袱。

______________________________________________________________________

## 2. 组件职责、依赖、数据流与信任边界

### 2.1 组件分层架构

1. **后端核心服务 (mail_core)**

    - `mail_core.api`：基于 FastAPI 提供 REST API 与 SSE 实时事件流，注入安全中间件（SecurityHeaders, TraceId, CSRF, Session/Bearer Auth）。
    - `mail_core.accounts`：管理多账号配置、分组归属与侧边栏布局，基于数据库全局咨询锁（`SIDEBAR_LAYOUT_LOCK_ID`）与 `expected_revision` 乐观锁消除竞态。支持 Microsoft OAuth2 PKCE 及设备码流程。
    - `mail_core.db`：维护 PostgreSQL 连接池、事务管理与 30 个 Alembic 线性版本迁移。
    - `mail_core.mail` & `blobs`：邮件状态机驱动、MIME 归档、基于 SHA-256 内容寻址的 BlobStore 存储、引用计数与分代垃圾回收。
    - `mail_core.backup`：备份包打包、验证与基于快照的灾难恢复机制。
    - `mail_core.providers` & `sync`：统一 `MailProvider` 协议抽象，隔离 IMAP 与 Microsoft Graph。基于 `AccountSyncLease` 行锁与单调递增 `fencing_token` 确保单账号单写者；限制全局出站连接槽位（默认 8 槽位）。
    - `mail_core.realtime` & `worker`：事务性 Outbox 模式、有序 `publication_seq`，结合 PostgreSQL `LISTEN/NOTIFY` 实现低延迟实时事件派发与 Worker 异步任务调度。

2. **前端与桌面端 (frontend & desktop)**

    - `frontend (React SPA)`：TanStack Query 驱动数据流与智能缓存；邮件内容使用受控沙箱 iframe 隔离渲染（`sandbox="allow-popups allow-popups-to-escape-sandbox"` + 严格内嵌 CSP `default-src 'none'; img-src 'self' data: cid:`）；虚拟列表渲染上万封邮件。
    - `desktop (Electron + Sidecar)`：Electron 主进程启用完整沙箱与上下文隔离（`contextIsolation: true, sandbox: true, nodeIntegration: false`）；内置 PostgreSQL 管理器（`PostgresManager`），严格管理 socket/port 与 0700/0600 文件权限；子进程 Sidecar 执行严格环境变量清理（`scrubEnv`）。

3. **开发规范与模板治理 (repo_template)**

    - 包含规范化任务引擎、跨进程文件锁（`locks.py`）、事件账本（`dispatch_ledger.jsonl`）、看板服务及预提交门禁脚本。

### 2.2 信任边界与安全防御

- **外部输入信任边界**：
    - 邮件正文（HTML/MIME）由外部邮件服务提供商获取，视为不可信内容。通过后端过滤 + 前端沙箱 iframe + 严格 CSP 进行防御，杜绝 XSS。
    - 外部图片加载：通过后端 `remote_image_proxy` 路由受控拉取，对对端 IP 实施私网/环回/元数据地址硬封锁与 DNS Rebinding 二次校验。
- **会话与认证边界**：
    - Session Cookie 结合集中存储的 `session_epoch`，实现单点改密/登出全局即时吊销。
    - 非幂等请求强制校验 X-CSRF-Token。

______________________________________________________________________

## 3. 数据与状态权威、重要契约与关键取舍

1. **状态唯一权威**：
    - 账号、分组、侧边栏布局：PostgreSQL 对应表为权威，写操作由 `SIDEBAR_LAYOUT_LOCK_ID` 保护。
    - 邮件归档与内容：BlobStore 为正文/附件原始权威，数据库 `messages`/`attachments` 维护检索与关联元数据。
    - 任务与工作流状态：以 `.repo_template/scripts/repo_task` 及 `docs/tasks/` 为工作区规范权威。
2. **关键架构取舍**：
    - 取消发信能力：换取系统免受滥用风险与更简洁的单向同步模型。
    - 彻底废弃 Gmail API：全部 Google 邮箱统一走 IMAP + 应用专用密码，消除高复杂度的 Google OAuth 审核与 API 配额包袱。
    - 放弃兼容性层：彻底重写替代原 outlookEmail，采用破坏性迁移演进。

______________________________________________________________________

## 4. 局部 Findings 的系统影响与线索分析

本轮 16 个单元审查共检出 28 项 Findings（0 Critical, 7 High, 13 Medium, 12 Low, 4 Info）：

1. **核心架构铁律专项违规项（High / Medium）**：

    - `f_arch_deprecated_v1_replay_api` (High)：`src/mail_core/realtime/outbox.py:83-123` 保留废弃 v1 回放接口 `fetch_since` 并保留 `test_a380_fetch_since_deprecated.py` 专门测试废弃接口，严重违背零兼容负担铁律。
    - `f_arch_secret_write_busy_spin` (High)：`src/mail_core/runtime/bootstrap.py:41-55` 写入密钥文件遇并发时采用 `time.sleep(0.01)` 自旋死等，未采用标准临时文件原子替换，违背拒绝妥协铁律。
    - `f_arch_desktop_startup_toctou_acknowledged_in_test` (High)：`src/desktop/startup.js:190-208` 端口探测 `freePort` 先探再关存在 TOCTOU 竞态，`startup.test.js:64-78` 甚至编写单测断言注释承认该缺陷以规避重构后端启动协议（绑定 port 0 并回传），严重违背拒绝妥协与架构至上铁律。
    - `f_arch_patrol_state_in_checkpoint_cursor` (High)：`src/mail_core/sync/patrol.py:8-9` 为规避数据库迁移，将 STATUS 巡检基线塞入 Checkpoint 游标 JSONB，破坏领域模型纯粹性。
    - `f_arch_inbox_priority_numerical_tweak` (Medium)：`src/mail_core/sync/engine.py:386-425` 对收件箱分配 priority=55（其余60）数值微调治标，未解耦“先全量目录发现、再同步文件夹”的强耦合拓扑。
    - `f_arch_runtime_shim_and_deprecated_aliases` (Medium)：`src/mail_core/providers/connection_slots.py:60-70` 使用 `__getattr__` 动态反射挂载废弃常量；`system_metrics.py` 保留 `@property max_sync_lag_seconds` 历史别名。

2. **公开仓个人隐私与敏感信息外泄（High / Medium）**：

    - `f_docs_archive_general_p060_pii_leak` (High)：归档文档 `docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3` 曾泄露真实用户个人邮箱（已脱敏为 `user@example.com` 并勘误）。此为公开仓脱敏违规。
    - `f_docs_archive_general_p027_credential_characteristic_leak` (Medium)：`p027` 原存在口令长度特征描述（已脱敏并勘误）。
    - `f_docs_archive_tasks_b_absolute_paths_in_reviews` (Medium) 与 `f_docs_reviews_execution_log_absolute_path` (Medium)：多份归档文档及执行日志中硬编码开发者宿主机绝对路径（已脱敏为占位符并勘误）。
    - **系统影响**：不影响运行时逻辑正确性，但对公开开源仓库存在个人隐私泄露和环境信息泄露合规风险。

3. **测试门禁有效性与断言退化（Medium / Low）**：

    - `f_tb_fake_assertion_ac008` (Medium)：`test_t062_outbox_and_job_notify_wake.py` 未实际提交事件，导致断言脱靶。
    - `f_tb_overmock_delta_result_counts` (Medium)：单测中过度 mock 导致只测三元表达式，未能保护真实的增量同步逻辑。
    - `f_tse_tautological_body_visible_assertion` (Medium)：全栈 E2E 双页同步断言退化为恒真断言。
    - **系统影响**：造成虚假的测试通过信号，可能在后续演进中掩盖真实回归。

4. **文档与规范时效性（Medium / Low）**：

    - `f_docs_current_handoff_stale` (Medium)：`docs/handoff.md` 滞后于最新提交，需补齐交接记录。
    - `f_docs_archive_general_pending_readme_index_drift`、`f_docs_current_specs_index_empty_tasks`、`f_docs_reviews_readme_missing_session`：索引漂移。

5. **代码级类型标注缺陷（Low / Info）**：

    - `f_backend_sync_01`、`f_backend_runtime_01`、`f_backend_runtime_02`：函数签名引用未导入的类型（`Sequence`, `Any`）。静态分析与运行时内省有潜在影响。

______________________________________________________________________

## 5. 覆盖与证据入口

|单元|文件数|行数|状态|证据入口|
|---|---|---|---|---|
|backend_core|53|6,757|Completed|`src/mail_core/api/app.py`, `src/mail_core/accounts/service.py`|
|backend_storage_backup|31|8,410|Completed|`src/mail_core/backup/package.py`, `src/mail_core/blobs/archive.py`|
|backend_sync_providers|25|10,240|Completed|`src/mail_core/providers/imap.py`, `src/mail_core/sync/remote_push.py`|
|backend_runtime_security|34|8,820|Completed|`src/mail_core/worker/main.py`, `src/mail_core/security/ratelimit.py`|
|tests_backend|321|48,200|Completed|`tests/mail_core/test_accounts.py`, `tests/mail_core/test_backup.py`|
|tests_scripts_e2e|34|5,600|Completed|`tests/e2e/full_stack.spec.ts`, `tests/scripts/test_check_dep_locks.py`|
|frontend_ui|48|15,200|Completed|`src/frontend/src/components/MessageReader.tsx`, `Sidebar.tsx`|
|frontend_desktop|108|9,800|Completed|`src/desktop/index.js`, `src/desktop/postgresManager.js`|
|scripts_and_ops|57|4,200|Completed|`scripts/deploy_mail_core.sh`, `Dockerfile.mail-core`|
|repo_template_core|29|8,426|Completed|`.repo_template/scripts/repo_task/locks.py`, `control.py`|
|repo_template_misc|90|11,200|Completed|`.repo_template/scripts/repo_sync.py`, `check_review_status.py`|
|docs_current|29|6,500|Completed|`docs/blueprint/architecture.md`, `docs/specs_index.md`|
|docs_archive_tasks_a|108|6,740|Completed|`docs/archive/tasks/t001_...` ~ `t027_...`|
|docs_archive_tasks_b|208|18,900|Completed|`docs/archive/tasks/t028_...` ~ `t075_...`|
|docs_archive_general|79|12,400|Completed|`docs/archive/legacy_architecture/`, `docs/archive/pending/`|
|docs_reviews_historical|219|42,500|Completed|`docs/reviews/review_20261027_021416/` 等|

## Local uncertainty resolutions

```json
{
  "docs_archive_general:0": {
    "reason": "已通过正则表达式全仓复扫 @ 符号邮箱，确认除 p060 外其余已归档文档均使用 example.com 或符号化占位符",
    "evidence": [
      "docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3"
    ]
  },
  "docs_archive_tasks_a:0": {
    "reason": "docs/archive/tasks/README.md 已经显式做出免责声明，明确指出早期任务仅供历史追溯，不作为现行行为规范",
    "evidence": [
      "docs/archive/tasks/README.md:1-11"
    ]
  },
  "docs_archive_tasks_b:0": {
    "reason": "后续可在 pre-commit 钩子或 repo-hygiene 中引入路径扫描正则拦截 /Users/ 与 /home/ 路径",
    "evidence": [
      ".repo_template/hooks/pre-commit:1-30"
    ]
  },
  "docs_current:0": {
    "reason": "task 流程规范明确要求在 task finish / merge 时维护 specs_index.md",
    "evidence": [
      "docs/blueprint/conventions.md:20-40"
    ]
  },
  "docs_reviews_historical:0": {
    "reason": "历史 rejected 疑点已经作为永久设计决策沉淀于 docs/blueprint/decisions.md，不会反复摇摆",
    "evidence": [
      "docs/blueprint/decisions.md:1-100"
    ]
  }
}
```
