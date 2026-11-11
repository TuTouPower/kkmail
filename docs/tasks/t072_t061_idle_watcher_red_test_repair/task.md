# Task spec

## 背景

p071 记录 t061 IDLE watcher 测试套件的三处既有问题：`_manager()` 对 frozen `IdleWatcherConfig` 执行 `setattr` 导致 `test_ac005_quota_limits_sessions` 稳定抛 `FrozenInstanceError`；`test_load_candidates_ranks_by_arrival_not_checkpoint` 在 SQLAlchemy commit 后访问 detached `Account.id` 导致 `DetachedInstanceError`；`test_ac006_disabled_account_session_closed` 只等待 `held_account_ids() == set()`，而 `_close_watch` 先 pop 再 join，约 1/8 概率在旧会话 `close()` 前结束断言。三者均与生产 watcher 行为无关，但使 t061 回归门禁无法全绿。

## 契约区

### 范围

- `_manager()` 测试辅助按构造参数创建 `IdleWatcherConfig`，不再对 frozen dataclass 赋值。
- `test_load_candidates_ranks_by_arrival_not_checkpoint` 在 session 内取得稳定 ID 或使用不 detached 的标识，消除 commit 后 ORM 属性刷新。
- `test_ac006_disabled_account_session_closed` 的同步点改为等待会话 `close()` 完成（或 watch 线程退出），不再仅依赖注册表空集。
- 仅修改测试代码；不改变 `IdleWatcherManager` 生产行为。

### 非范围

- 不修复 t061 之外的其他既有红测试。
- 不改变 IDLE 席位选择、配额、断线重连或补偿 delta 行为。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：`test_ac005_quota_limits_sessions` 在 fresh PostgreSQL 下通过，且配额断言仍验证 2 个席位/3 个候选的行为。
- [ ] AC-002：`test_load_candidates_ranks_by_arrival_not_checkpoint` 在 fresh PostgreSQL 下通过，且仍验证按邮件到达时间而非 checkpoint 排序。
- [ ] AC-003：`test_ac006_disabled_account_session_closed` 连续 10 次独立运行全部通过，断言禁用账号后对应会话已关闭。
- [ ] AC-004：`tests/mail_core/test_t061_idle_watcher.py` 整个文件运行 0 failed。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p071`（2026-10-31 t071 review 期间复现并确认；两处确定性失败在 anchor `e4752c24` 同样发生，第三处为约 1/8 概率竞态）。

### 有意不测

- 其他测试文件的既有红测试：不在本 task 范围。

### 测试策略

- 只改测试辅助与同步点，不新增生产覆盖；以 fresh PostgreSQL 下文件级全量与关键用例重复运行验证。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：修改测试同步点可能掩盖真实断言；保持原有行为断言不变，仅替换等待条件。
- 回退：纯测试改动，回退即恢复旧测试文件。

### 依赖与约束

- 依赖 t071 已合入的建连补偿测试；测试文件路径不变。

### Finalization 时更新的 blueprint

- 无
