# Task spec

## 背景

测试 PostgreSQL/IMAP 由 `config/test_pg_compose.yaml` 的独立 Compose project `kkmail_test` 提供。现状把容器当成常驻基础设施：`start` 启动后永久保留，直到人工 `stop`；每轮 `run` 只清理自己的一次性数据库，不停止服务。结果是空闲时容器仍占用资源，中断遗留的 owned 数据库又会让 `stop` 拒绝，停止与清理互相阻塞。

根因是容器、一次性数据库、测试运行三者各有生命周期却没有统一所有者。按开发铁律，废除「永久常驻 + 人工停止」模型，引入「测试会话」作为一等生命周期：按需拉起、会话内复用、空闲自动回收、注册表驱动中断恢复。

## 契约区

### 范围

- `scripts/test_pg_runtime.py` 引入测试会话状态与注册表：会话持有容器、端口、cluster identity、全部 owned run 与最后活动时间。
- `scripts/run-mail-core-tests.sh` 改为会话入口：`run` 确保会话存在并刷新活动；提供 `session-status` 与 `session-end`；移除 `start` / `stop` 的永久常驻语义。
- 会话内连续多次 `run` 复用同一组容器，只轮换一次性数据库；每轮数据库仍按现有 guard 与所有权规则清理。
- 会话空闲超过阈值（环境变量 `KKMAIL_TEST_SESSION_IDLE_S`，默认 900 秒）后自动回收：先清理会话注册表内全部 owned 数据库与未结束 run，再销毁 postgres 与 imap 容器。
- 中断恢复由注册表驱动：下次调用识别残留会话，清理后重建，无需人工指定 run UUID；`cleanup` 保留为低层恢复原语但不是日常路径。
- 更新 `docs/blueprint/testing.md` 的命令与生命周期说明；`test_pg_runtime.py` 的相关单测同步改写。

### 非范围

- 不改业务 Compose、业务卷、生产数据库或 `.env` 凭据。
- 不削弱 guard：容器身份、loopback 绑定、库 comment、owner role 与密码校验保持或加强。
- 不改变 pytest 门禁的数据隔离语义（一次性 owned 数据库、TRUNCATE、拒绝外部 URL）。
- 不改应用代码与前端；不 push、不重新部署。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：无测试活动时测试服务的 postgres 与 imap 容器均不存在。
- [x] AC-002：执行 `run` 时测试服务按需拉起；同一会话内连续两次 `run` 复用同一组容器，容器 ID 不变，不发生重建或重启。
- [x] AC-003：会话内每轮 `run` 仍使用独立的一次性 owned 数据库，轮次结束清理本轮数据库；会话内容器持续运行。
- [x] AC-004：停止测试活动超过空闲阈值后，测试服务自动回收：会话注册表内全部 owned 数据库与未结束 run 先清理，随后 postgres 与 imap 容器销毁；无遗留 owned 数据库。
- [x] AC-005：`session-end` 立即完成与空闲回收相同的清理与销毁；旧的永久常驻入口移除，不再存在「启动后无限保留」路径。
- [x] AC-006：异常中断后再次调用能识别残留会话、完成注册表清理并建立新会话，全过程无需人工指定 run UUID。
- [x] AC-007：容器身份、loopback 绑定、owner role、库 comment 与专用密码守卫不削弱；业务 Compose 与业务卷未被使用，日志不打印密码。
- [x] AC-008：`docs/blueprint/testing.md` 与 `test_pg_runtime.py` 单测同步反映会话生命周期；`test_cmd`、`blackbox_verify` 与后端完整 PostgreSQL 套件全量通过。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- AC-001/002/004/005：由真实 Docker 集成测试驱动 `run` / `session-end` 与空闲阈值，断言容器存在性、容器 ID 与数据库残留。
- AC-003/006/007：由现有 owned DB guard 测试与中断恢复场景的集成测试覆盖。
- AC-008：由门禁命令实际执行结果验证；文档一致性由文件断言验证。

## 上下文区

- 关联 spec：docs/specs/testing_quality.md
- 来源：用户实报（2026-11-22）；现状 `scripts/test_pg_runtime.py` 的 `start` 永久保留 + 手动 `stop` 模型；`docs/blueprint/testing.md`「本地分层门禁与 CI 流水线映射」

### 有意不测

- 真实 CI 环境中的空闲回收：以本机 Docker + 可调低空闲阈值的集成测试覆盖同一状态机；CI 平台差异不另行模拟。
- 容器被外部进程手动删除的场景：只保证注册表识别与重建，不追踪外部删除原因。

### 测试策略

- 后端集成：真实 Compose 会话生命周期测试（拉起、复用、空闲回收、显式结束、中断恢复）。
- 单测：会话状态解析、空闲判定、注册表清理顺序。
- 门禁：`test_cmd` 与 `blackbox_verify` 全量通过；后端完整 PG 套件通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：空闲回收与新一轮 `run` 并发时可能误删在途数据库；detached 回收进程可能残留；不同 worktree 共用同一 Compose project 时会话归属冲突。
- 回退：以会话锁串行化状态变更；回收前二次确认最后活动时间；会话状态记录所属 worktree，跨 worktree 不复用；不通过缩短隔离或放宽 guard 规避问题。

### 依赖与约束

- 依赖：`config/test_pg_compose.yaml` 的 postgres 与 imap 服务定义保持不变；`KKMAIL_TEST_PG_PASSWORD` 仍由操作者提供。
- 约束：并发与资源生命周期按 `full` review level 执行；不引入旧常驻语义兼容层。

### Finalization 时更新的 blueprint

- `docs/blueprint/testing.md`：测试服务生命周期改为会话制。
