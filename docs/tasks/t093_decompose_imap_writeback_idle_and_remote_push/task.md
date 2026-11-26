# Task spec

## 背景

`t091` 收尾 Review（`t091_code_f005`）转出遗留项 `p098`：当前 `src/mail_core/providers/imap.py` 全文达 2003 行，其中 `ImapProvider.apply_remote_operations` 长 276 行（圈复杂度 90，含 `\Seen`/`\Flagged` 重复验证分支）且 `open_idle_session` 长 45 行（圈复杂度 17）；`src/mail_core/sync/remote_push.py` 全文达 843 行，其中 `push_remote_operations` 长 451 行（圈复杂度 97，含 `build_provider` 与批内执行两处重复的 `CAPACITY_ERRORS` 退避重入块，及租约认领、分块执行、fencing + CAS 结算等高耦合职责）。

按开发铁律（架构至上、拒绝妥协），必须从职责分层根因彻底拆解这三处高复杂度协作者与重复分支（消除重复逻辑并收敛函数复杂度与文件膨胀），同时通过完整单元测试、真实 PostgreSQL 并发/结算集成测试与真实 IMAP Dovecot 协议回归，确保既有协议语义与 concurrency/fencing 契约零退化。

## 契约区

### 范围

- 拆解 IMAP 批量远端写回职责（输入归一化与分组、`SELECT`/`UIDVALIDITY` 门禁、统一 `\Seen`/`\Flagged` 标志写入与 `FETCH` 核验、原子 `MOVE`/`TRASH` 与 `COPYUID` 解析、异常归类传播），收敛圈复杂度至 `< 15`。
- 拆解 IMAP 专有 `IDLE` 会话开启职责（能力探测、只读选中、异常阶段归因与 socket 释放），收敛圈复杂度至 `< 15`。
- 拆解同步层远端写回协调状态机职责（待推筛选与批前认领、共享 `CAPACITY_ERRORS` 退避回滚助手、分块执行与跨块心跳、fencing + revision CAS 结算与退避重排），收敛圈复杂度至 `< 15` 并缓解文件膨胀。
- 补齐/确认覆盖拆解后协议分支与并发结算边界的自动化回归验证，并更新相关架构/模块文档说明（若职责拆分新增模块）。

### 非范围

- 不改变 `ImapProvider`、`BaseProvider` 或 `push_remote_operations` 对外公开签名、HTTP/OpenAPI 契约、前端交互逻辑或数据库表结构（不涉及 Alembic 迁移）。
- 不调整既有连接槽位预算策略、`RemoteOperation` 重试上限/退避公式、`FencingMismatch`/CAS 隔离语义与 `StructuredFailure` 白名单分类规则。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：完成 IMAP 批量远端写回（`apply_remote_operations`）的分层拆解并消除 `\Seen`/`\Flagged` 重复验证分支，使写回入口及全部新增/重构辅助函数圈复杂度均低于 `15`；且既有批量成功回写、`UIDVALIDITY` 失配拒写、无效 UID 与缺少目标路径拒写、`MOVE` 空号 pre-`FETCH` 拦截、`COPYUID` 解析，以及容量异常重抛与未成功传输异常传播语义完全保持不变。
- [x] AC-002：完成 IMAP 专有 `IDLE` 会话开启（`open_idle_session`）的协商与异常收口拆解，使入口及辅助函数圈复杂度均低于 `15`；且完整保持绕过并发槽位预算、`IDLE` 能力与 `SELECT` 检查抛出 `IdleNotSupportedError`、缓冲读端 `settimeout(None)`、容量异常透传以及非容量异常附加 `FailurePhase.IMAP` 与 socket 清理语义不变。
- [x] AC-003：完成同步层远端写回协调器（`push_remote_operations`）各阶段状态机拆解并消除 `build_provider` 与批次执行两处重复的 `CAPACITY_ERRORS` 退避回退逻辑，使协调入口及全部新增/重构辅助函数圈复杂度均低于 `15`；且严格保持 `LeaseBusy` 退出、批前 `IN_PROGRESS` 与 `heartbeat_lease`、跨块心跳与 fencing 校验、`fencing_mismatch` 留 `IN_PROGRESS` 交 reconcile、CAS 变更保留 `PENDING`、`RemoteIdentityConflict` 拒绝完成、限流/瞬时/永久失败结算以及 `execution_origin` 延续调度契约完全不变。
- [x] AC-004：若拆分引入新模块或调整分层，则同步更新对应模块注释与 `docs/blueprint/architecture.md`（不改变长期接口契约，无长期 spec 变更时按规范登记理由）；通过后端完整 PostgreSQL 测试套件、真实 IMAP Dovecot 契约测试、前端单测与构建、桌面端测试、E2E 冒烟及模板契约门禁。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 与 AC-002 通过 AST 圈复杂度静态检验、IMAP 写回与 IDLE 单元测试及真实 Dovecot IMAP 协议套件验证；AC-003 通过 AST 圈复杂度与无重复验证以及真实 PostgreSQL `remote_push`/并发 CAS/fencing/重试/血缘继承集成套件验证；AC-004 通过完整后端 PG 套件（含真实 IMAP）、前端与桌面端单测及构建、Playwright E2E 与模板契约验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p098（2026-11-26 从 t091 遗留项转办并核实：`imap.py` 全文 2003 行，`apply_remote_operations` CC=90/276 行、`open_idle_session` CC=17/45 行；`remote_push.py` 全文 843 行，`push_remote_operations` CC=97/451 行）

### 有意不测

- 无：全部分支与并发/协议边界均有本地单测、专用 PostgreSQL 与专用 Dovecot IMAP 测试覆盖。

### 测试策略

- 静态复杂度门禁：以 AST 脚本核验重构后 `imap.py`、`remote_push.py` 及新增/修改协同单元的所有新增与重构函数圈复杂度 `< 15`，且文件长度收敛，不新增高分支函数。
- IMAP 协议回归：运行现有 `test_t064_batched_remote_writeback.py`、`test_imap_provider_live.py`（真实 Dovecot）、`test_t061_idle_watcher.py`、`test_t091_structured_failure_and_diagnostics.py` 并补充细分单元测试覆盖写回异常传播、`\Seen`/`\Flagged` 对称路径及 `open_idle_session` 错误归因边界。
- 并发/状态机回归：运行 `test_t090_execution_origin.py`、`test_t091_pg_worker_diagnostics_integration.py`、`test_t064_*` 及全量 PostgreSQL 套件，并在必要时补测批内部分异常、CAS 冲突、容量退避与 `execution_origin` 续跑一致等价。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。所有协议与并发契约均已由当前 `main` 上既有实现及 `t061`/`t064`/`t089`/`t090`/`t091` 测试确立并已核实源码。

### 风险与回退

- 风险：拆分高复杂度的状态机与异常分支时若忽略局部 `try/except/finally`、`session` 事务提交边界或 `imap.py` 中 `has_succeeded`/`is_transport_or_imap` 传播条件，可能导致 Subtle 状态或异常语义漂移。
- 回退：全部工作在独立分支与 worktree 实施；单实现 commit 可直接整体回退，拆解期间严格保持对外公共函数与参数签名不变。

### 依赖与约束

- 依赖：`review_level: full`（因直接重构并发 fencing/CAS 与 IMAP 写回/IDLE 协议核路径）；基于当前 `main`（已含 `t092` 及 `p096`/`p097`/`p101`）。
- 约束：遵守 `AGENTS.md` 开发铁律与 `docs/blueprint/testing.md` 验证门槛；重构必须消除重复逻辑（例如 `\Seen`/`\Flagged` 验证分支与 `CAPACITY_ERRORS` 重入退避分支），严禁用“机械切三段但各自传十几个参数”的方式凑复杂度数字。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：若为写回拆解新增协作模块，更新模块职责分工描述；若仅内聚拆分且现有章节无滞后则保持准确说明。
