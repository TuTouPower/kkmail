# Task review t039（reviewer_focus: 通用）

- task：`t039_folder_stats_scope_truth`
- spec：`docs/tasks/t039_folder_stats_scope_truth/spec.md`
- diff_anchor：`852c01372e17a4d858050eb2e9fed148870e5495`
- target：`git -C '/Users/karson/kar/code/kkmail_t039' diff 852c01372e17a4d858050eb2e9fed148870e5495`
- round：1
- reviewed_at：2026-10-23T08:32:07+08:00

reviewed_scope: 929569c71c225685

## Findings

### t039_gen_f001 - 统计请求未完成时仍展示已加载行数为完整总数

- 严重度：important
- 锚点：AC-002：全账号统计仅在所有账号请求成功后展示完整总数。
- 位置：`src/frontend/src/components/MessageList.tsx:220`、`src/frontend/src/components/MessageList.tsx:280`
- 问题：全账号统计请求仍在进行时，`folderStatsQuery.data` 为 `undefined`，`statsUnknown` 因只检查 `isError` 和 `data === null` 而为 `false`。邮件列表请求先完成且已有邮件行时，`totalCount` 为 `null`，`displayTotal` 就回退为 `visible.length`，界面把当前已加载行数显示成全账号邮件总数；此时尚未有全部账号统计成功结果，违反 AC-002。账号列表请求慢于邮件列表时也会出现该状态，因为统计查询尚未启用。
- 建议：统计查询启用期间，将尚无成功结果的状态显示为未知（或明确的加载态）；仅在所有账号统计请求成功后显示完整统计值。增加统计请求延迟且邮件列表先完成的组件测试。

## 结论

- 本轮新发现：1 条。
- 未进表的提示：已检查安全、契约与类型、性能与资源、架构与可维护性、健壮性与可观测、测试与文档一致性；未发现其他需报告问题。

### AC 复验方式

- AC-001：`re_verified`。`MessageList.tsx:172-177` 按目标 folder ID 或 role 查找，缺失时回 0；组件测试分别覆盖目标 role 缺失及跨账号中某账号缺失 role（`MessageList.test.tsx:203-220`、`271-293`）。
- AC-002：`re_verified`。独立运行 `npx vitest run src/components/MessageList.test.tsx src/components/Sidebar.test.tsx`，33 项通过；`MessageList.test.tsx:223-268` 验证已失败时隐藏部分合计、全部成功时合计正确。代码复核发现请求尚未完成时仍回退显示 `visible.length`，因此该 AC 当前未满足，见 `t039_gen_f001`。
- AC-003：`re_verified`。`Sidebar.tsx:200-208` 无 inbox role 或缺少数值时返回 `null`，`Sidebar.tsx:258-282` 将其作为未知处理；组件测试验证请求失败及无 inbox role 时总 badge 与账号 badge 均显示 `-`（`Sidebar.test.tsx:91-132`、`134-168`）。
- AC-004：`re_verified`。上述 33 项目标测试通过；新增与既有断言覆盖目标 role 缺失、全账号成功、部分账号请求失败、Sidebar 无 inbox role 和请求失败场景。
- coverage = 4 / 4
- 总体判断：存在未解决的 important finding，AC-002 在统计加载期间仍显示不完整数值，判定 FAIL。
- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-23T08:37:01+08:00)

reviewed_scope: deba6f7b41c7e43a

### Findings

本轮无新 finding。

### 结论

- 前轮 finding 复核：`t039_gen_f001` 已消除。`MessageList.tsx:220-224` 将统计请求尚无数据、返回 `null` 或失败统一视为未知；`MessageList.tsx:285-287` 在列表已有邮件行时仍显示 `—`。新增延迟统计响应测试在统计请求完成前断言未知、全部响应完成后断言准确总数（`MessageList.test.tsx:223-258`）。
- 本轮新发现：0 条。
- 未进表的提示：无。已独立检查安全、正确性、契约与类型、性能与资源、架构与可维护性、健壮性与可观测、测试与文档规格视角；无其他需报告问题。
- 总体判断：前轮 important finding 已修复；AC-001 至 AC-004 满足，无未解决 critical / important，判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。`MessageList.tsx:172-177` 与 `190-192` 仅取目标 folder ID/role；缺失时按 0 计。组件测试覆盖单账号与全账号中目标 role 缺失（`MessageList.test.tsx:203-220`、`308-330`）。
- AC-002：`re_verified`。`MessageList.tsx:180-194` 任一账号统计请求失败即返回未知；`MessageList.tsx:220-224` 将尚未完成、`null` 与错误识别为未知。延迟、部分失败、全成功测试均覆盖（`MessageList.test.tsx:223-305`）。独立运行 `npx vitest run src/components/MessageList.test.tsx src/components/Sidebar.test.tsx`，34 项通过。
- AC-003：`re_verified`。`Sidebar.tsx:200-208` 只读 inbox role 的 unread_count；缺 inbox 或缺 unread_count 返回未知。fallback 聚合中任一未知使全局总数未知（`Sidebar.tsx:258-282`）。测试覆盖请求失败与无 inbox role（`Sidebar.test.tsx:91-168`）。
- AC-004：`re_verified`。独立运行目标组件测试，34 项通过；断言覆盖缺 role、统计请求未完成、全账号成功、部分失败、Sidebar 无 inbox 与请求失败场景。
- coverage = 4 / 4

verdict: PASS
