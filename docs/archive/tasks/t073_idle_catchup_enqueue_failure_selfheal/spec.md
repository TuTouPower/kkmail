# Task spec

## 背景

p072 记录 t071 的残余风险：建连补偿 `SYNC_FOLDER_DELTA` 入队失败时，`_enqueue_catchup` 只记录日志并继续 `idling`；账号仍 held，t057 收件箱轮询被跳过。若此后既无 IDLE 变化事件也不重连，断线窗口内到达的邮件会持续缺失，可能无限期。需要让一次瞬时入队失败可重试，持续失败时释放 IDLE 席位让轮询兜底，并在重连后再次补偿。

## 契约区

### 范围

- `_enqueue_catchup` 在入队失败时按有界指数退避重试；重试期间响应 watch 的 stop_event。
- 重试成功时保持当前 IDLE 会话与 held/idling 状态，仅产生既有去重键任务。
- 重试预算耗尽仍失败时，watch 进入 backoff 并关闭当前会话；账号不再出现在 held 集合，t057 收件箱轮询可入队；下一次重连继续尝试补偿。
- 不新增配置项，不改变 `enqueue_job` 去重语义，不绕过 baseline/lease/fencing，不把账号标记 failed。
- 补充覆盖瞬时失败、持续失败与停机中断的测试。

### 非范围

- 不新增持久化补偿队列或调度器；不改 t057 轮询间隔。
- 不处理非补偿路径的 delta 入队失败。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：补偿入队前 N 次（重试预算内）抛异常、随后成功时，收件箱 delta 任务最终存在，账号保持 held/idling，无需新的 IDLE 变化事件，账号 `sync_status` 不为 `failed`。
- [ ] AC-002：补偿入队持续失败直到重试预算耗尽时，watch 进入 backoff 且当前会话关闭，账号不再属于 held 集合；`schedule_periodic_inbox_sync` 可为该账号入队收件箱 delta，账号 `sync_status` 不为 `failed`。
- [ ] AC-003：重试退避期间收到停止信号时，watch 线程在 2 秒内退出，不再继续重试，也不影响其他 watch。
- [ ] AC-004：补偿首次成功或重试后成功的既有路径只产生一个同去重键任务，不出现并行重复执行（不回归 t071 AC-001/AC-002）。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p072`（2026-10-31 t071 代码 review Round 1/2/3 残余风险；AC-005 只要求失败隔离，未要求自愈）。

### 有意不测

- 真实 PostgreSQL 宕机/恢复时序：使用测试注入的入队异常覆盖重试与降级路径。
- 其他入队路径（IDLE changed、t057）的失败恢复：沿用既有行为，不在本 task 扩展。

### 测试策略

- `IdleWatcherManager` 层用假 IDLE 会话与可注入异常的 `_enqueue_delta`：瞬时失败后成功、持续失败后 backoff/释放 held、stop 中断退避。
- 复用 t071 首连/重连/去重测试回归 AC-004；fresh PostgreSQL 下验证 `schedule_periodic_inbox_sync` 在解除 held 后可入队。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：持续数据库故障时 watch 反复重连可能增加连接 churn；有界重试 + 指数 backoff 限制频率，且仅在补偿入队失败时触发。
- 风险：退避期间让出 held 会短暂失去实时 IDLE 信号；由 t057 轮询兜底，恢复后重新建连补偿。
- 回退：移除重试与降级分支，恢复 t071 的失败隔离行为；无数据模型或迁移变更。

### 依赖与约束

- 依赖 t071 已合入的建连补偿；与 t072 修改同一测试文件，执行顺序 t072 → t073。
- 不新增运行时依赖或配置键。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：t061 章节补充补偿失败重试与释放 held 让轮询兜底。
- `docs/specs/mail_sync_and_storage.md`：t061 契约补充补偿失败自愈边界。
