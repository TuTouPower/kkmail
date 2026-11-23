# Task spec

## 背景

t086 把 Gmail `\All` / `\Important` 从 `paused` 同步单元改为基于 `message_locations` 的派生视图。`Important` 成员只在常规 metadata FETCH 携带 `X-GM-LABELS` 时写入；迁移 `20261123_0004` 只回填 `folders.kind`，无法离线获知邮件标签。迁移前已入库的历史邮件从未经过带标签的 FETCH，后续增量同步只取 `(FLAGS UID)`，不为旧 UID 重取标签，且已完成的 full-scan checkpoint 不会自动重跑。结果：「重要邮件」视图对历史邮件永久缺条目、计数偏小；「所有邮件」视图因投影全部物理目录位置不受影响。p089 记录该遗留，本 task 实现显式一次性回填。

## 契约区

### 范围

- 新增一次性回填命令 `python -m mail_core --backfill-gmail-labels`，支持可选 `--account-id` 与 `--force`。
- 对未标记完成的 Gmail 账号，遍历物理 mailbox 并重放带 `X-GM-LABELS` 的 metadata 分页，把 `\Important` 成员补写为 view folder 的 `message_locations`；复用现有 FETCH/解析/落库路径，不另造标签协议。
- `accounts` 增加完成标记 `label_backfill_completed_at`；迁移提供升级与降级。
- 回填期间持有账号 lease 与常规同步互斥，不改写 `sync_checkpoints`；逐账号提交，单账号失败不阻断其它账号且不写完成标记，重跑可继续。
- 更新 blueprint/testing 与升级指南中的运维命令，p089 转办闭环。

### 非范围

- 不改 t086 的视图投影、paused 策略或 Gmail 判定；不新增 Worker 常驻作业类型。
- 不回灌 `All Mail` 成员（它本就由物理位置投影，无缺口）；不修改邮件正文、附件与搜索索引。
- 不在本 task 执行生产回填（部署后由运维按指南执行）；不 push、不改现役部署配置。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：`python -m mail_core --backfill-gmail-labels` 对未标记完成的 Gmail 账号扫描物理目录，把历史 `\Important` 成员写为 view folder 的 `message_locations`，成功后写入 `accounts.label_backfill_completed_at`。
- [x] AC-002：重复执行不增加 `messages` 行数、不产生重复 `(message_id, folder_id)`；已完成账号默认跳过，`--force` 可显式重跑且仍幂等。
- [x] AC-003：非 Gmail 账号被跳过且不留完成标记；Gmail 账号若没有 important view folder，跳过且不伪写完成标记。
- [x] AC-004：回填期间持有账号 lease，与常规同步互斥；执行前后 `sync_checkpoints` 内容与 `full_scan_complete` 状态不变。
- [x] AC-005：回填后「重要邮件」视图的 `folder-stats` 与列表包含历史成员；「所有邮件」视图计数与消息集合不变。
- [x] AC-006：迁移新增 `accounts.label_backfill_completed_at`，升级产生单一 head、降级可移除该列，ORM 与迁移无 drift。
- [x] AC-007：单个账号失败时其它账号继续处理，失败账号不写完成标记，重跑可续；命令对不存在或无权限的 `--account-id` 给出明确失败。
- [x] AC-008：PG 集成测试覆盖 AC-001~005，迁移测试覆盖 AC-006，失败/续跑测试覆盖 AC-007；后端 unit、前端测试与项目门禁全量通过，完整 PG 套件除 p091 记录的 2 条既存 idle watcher 回归外全部通过。
- [x] AC-009：`docs/blueprint/testing.md` 或 `docs/guides/upgrade.md` 记录回填运维命令与幂等语义，p089 转办指向本 task。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001~005/007 由 IMAP stub + 真实 PG 集成测试覆盖；AC-006 由迁移与单 head 门禁覆盖；AC-008 由门禁命令结果验证；AC-009 由文档内容断言验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p089（2026-11-23 核实：t086 遗留的一次性回填；增量同步不重取旧 UID 标签，必须显式扫描，已更正 pending 描述）

### 有意不测

- 真实 Gmail 账号的全量历史回填耗时与配额：用 IMAP stub 验证分页、幂等与完成标记状态机，真实账号回填作为部署后运维动作。
- 客户端 UI 变更：视图投影沿用 t086，无前端改动；不重复测 E2E 视觉细节，仅跑现有黑盒冒烟确认无回归。

### 测试策略

- Provider：IMAP stub 在 FETCH 中返回 `X-GM-LABELS`，验证回填走与常规同步相同的解析路径。
- 存储/应用：PG 用例断言历史 `\Important` 成员写入、重复运行幂等、checkpoint 不变、视图计数变化、`All Mail` 不变。
- 命令层：CLI 参数、`--force`、失败续跑与非 Gmail 跳过的可观察输出与标记状态。
- 迁移：单 head、可降级升级、ORM drift 为 0。
- 门禁：`doctor_cmd` / `test_cmd` / `blackbox_verify` 与完整 PG 套件全量通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。`X-GM-LABELS` 的 capability 探测与 FETCH 解析已在 t086 验证，本 task 复用同一路径。

### 风险与回退

- 风险：回填重放 metadata 会更新历史邮件的远端元数据字段，可能与本地未收敛的写回意图冲突；长时扫描占连接与 Worker 预算；并发账号 lease 争用。
- 回退：`git revert` 实现 commit 与迁移；已写入的 `message_locations` 为增量且幂等，可安全保留；不删除任何邮件或视图。

### 依赖与约束

- 依赖：t086 已合入 main,`X-GM-LABELS` 摄取、`folder_views` 判定与 `upsert_messages(label_view_folders=...)` 已存在。
- 约束：不扰动 `sync_checkpoints`;通过 lease 串行化;命令可在容器维护态一次性执行;`review_level=full`。

### Finalization 时更新的 blueprint

- `docs/blueprint/testing.md`：回填命令与 PG 集成验证入口。
- `docs/guides/upgrade.md`：升级后执行一次性回填的运维步骤。
