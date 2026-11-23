# Task spec

## 背景

用户新加 Gmail 账号后，侧栏「重要邮件」「所有邮件」长期显示蓝色 `-`，被理解成"还在同步、没同步完"。实际按 `t056` AC-001 这两个虚拟标签被判定为 `paused` 且不进入抓取队列，永不产出 `FolderStats`；`queries.py:219-220` 因无统计行返回 `unread_count=null`，`Sidebar.tsx:342` 把 `null` 渲染成 `unread-badge-unknown` 的蓝色 `-`。该角标与"统计暂未生成"完全同形，且无 tooltip、状态标签或空态说明，用户无从区分"等一会儿就好"与"按设计永不同步"。此外 `t056` 风险段曾把"手动点进该文件夹触发同步"作为依赖 All Mail 用户的兜底，而 `p060` 修复后显式 `folder_id` 指向 paused 目录解析为空目标集，兜底已失效却无文档更正，形成承诺与行为矛盾。

## 契约区

### 范围

- 侧栏对 `sync_status=paused` 的 Gmail 虚拟目录（`role=all` / `role=important`）改用可解释的非数字状态呈现，不再渲染与"未读数未知"同形的蓝色 `-`，也不冒充 `0` 或真实未读数。
- 选中上述 paused 虚拟目录时，邮件列表给出明确空态说明：该目录按设计不参与同步、因此无邮件；不显示同步错误，不呈现无限等待的加载态。
- 更正 `docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md` 风险段与 `p060` 相关描述，删除/改写已失效的"手动点进触发同步"兜底，明确虚拟目录不参与同步、手动点入不会触发同步。
- 前端组件测试覆盖上述状态，并修正现有 Gmail 虚拟目录 fixture 使用伪造 `unread_count=0/total_count` 的问题，使其贴近真实的"无统计行"场景。

### 非范围

- 不撤销 `t056` 的 paused 决策，不为 All Mail / Important 重新启用自动或手动全量同步（避免同一封邮件重复拉取、本地邮件数再次膨胀）。
- 不改变"目录含 `is_read: null` 邮件时未读数严格显示 `-`"的既有语义（`docs/specs/inbox_ui_and_search.md` 统计权威与未知状态条）；非 paused 目录的蓝色 `-` 行为保持不变。
- 不改动同步引擎、作业队列、`FolderStats` 计算或 `folder-stats` API 契约；`sync_status` 已由 `queries.py:217` 与 `AccountFolderStatsItemOut` 返回前端，本 task 仅消费该字段。
- 不修改生产 Compose、数据库、部署配置；不 push。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：Gmail 账号侧栏中 `sync_status=paused` 的「重要邮件」与「所有邮件」不渲染蓝色未读未知角标 `-`，而是显示与"统计暂未生成"可区分的状态；该状态不显示为 `0` 或任何未读数字。
- [ ] AC-002：选中上述 paused 虚拟目录后，邮件列表显示空态说明其按设计不参与同步、故无邮件；同视图不显示同步错误提示，也不显示永久加载态。
- [ ] AC-003：`sync_status` 非 `paused` 且尚无 `FolderStats` 的目录，侧栏仍显示蓝色 `-`；含 `is_read: null` 邮件的目录未读数仍严格显示 `-`，不回归既有未知语义。
- [ ] AC-004：`docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md` 风险段不再声称手动点进可触发同步，改为明确虚拟目录不参与同步且点入后内容为空由 UI 说明；`p060` 的相关描述与新行为一致，仓库内无残留的失效兜底表述。
- [ ] AC-005：组件测试以 `unread_count=null` 的 paused 虚拟目录为 fixture，断言 AC-001/002/003；前端测试与项目门禁全量通过。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001/002/003/005 由前端组件测试断言渲染结果与空态文案；AC-004 由文档内容断言验证。

## 上下文区

- 关联 spec：docs/specs/inbox_ui_and_search.md
- 来源：p086（2026-11-23 核实；新加 Gmail 账号后重要/所有邮件永久显示蓝色 `-` 属 UI 状态语义缺失，非同步卡死；根因链已由 `.scratch/repro_gmail_virtual_folder_dash.py` 复现）

### 有意不测

- 真实跨国 Gmail IMAP 连接与全量同步耗时：本 task 不改同步引擎，虚拟目录按设计不入队；用组件测试与文档断言覆盖，不接真实邮箱。
- 撤销 paused 后 All Mail / Important 的同步行为：属非范围的产品决策反转，不测也不实现。

### 测试策略

- `src/frontend/src/components/Sidebar.test.tsx`：新增/改写 paused 虚拟目录用例，`unread_count=null`、`sync_status=paused`、`role=all|important`，断言无裸 `-`、无可疑数字、有可解释标记；并断言非 paused 无统计目录仍显示 `-`。
- 邮件列表组件测试：选中 paused 虚拟目录断言空态说明出现、同步错误与加载态不出现。
- 文档断言：扫描 `t056` / `p060` 中"手动点进触发同步"表述已清除。
- 门禁：前端测试与项目 `doctor_cmd` / `test_cmd` 全量通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：把 paused 虚拟目录的角标与"统计待生成"拆成两种呈现，可能与 `inbox_ui_and_search.md` 既有"- 表示未知"规则产生理解冲突；空态文案若写成"暂未同步"会再次诱导等待。
- 回退：git revert 本 task 实现 commit；UI 状态回退后 `t056` 的 paused 策略与数据行为不受影响。

### 依赖与约束

- 依赖：`folder-stats` 响应已含 `sync_status`（`AccountFolderStatsItemOut.sync_status`）；无需后端契约变更或迁移。
- 约束：仅消费既有字段，不改变后端同步策略；`review_level=single`。

### Finalization 时更新的 blueprint

- `docs/specs/inbox_ui_and_search.md`：在侧栏组织规范中记录 paused 虚拟目录的可解释状态呈现，与"未读数未知 `-`"语义并列。
