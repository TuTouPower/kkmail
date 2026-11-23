---
pid: "p087"
slug: "gmail_virtual_folder_architecture_defect"
status: "closed"
resolution: "transferred"
reason: "已核实架构根因与完整修复面并转交该 task"
fix_ref: "t086"
---
# p087 Gmail 虚拟标签被建模为 paused 同步单元，缺 X-GM-LABELS 摄取与派生视图（p086 根因）

- 现象：Gmail 账号的「重要邮件」「所有邮件」两个一等导航视图永久为空、无统计行，侧栏显示蓝色 `-`；用户（2026-11-23，新加 `ecart95tr@gmail.com`）据此认为同步长时间未完成。表层由 p086 记录；本条记录其架构根因。
- 影响：
    1. 两个一等导航视图不可用；用户无法在客户端浏览全量邮件或重要邮件，且无说明区分"按设计不参与同步"与"同步卡住"。
    2. 在 `paused` 策略之前，同一封邮件因虚拟全量标签被当作独立同步目录重复下载，本地邮件数成倍膨胀（t056 记录 3,700 → 7,290）。
    3. 连续三层补丁叠加：`t056` 以 `paused` 回避重复 IO → `p060` 删除显式 `folder_id` 的手动兜底 → UI 用同形 `-` 渲染 `null`；`t056:72` 的兜底承诺与 `p060` 行为矛盾至今未更正。
    4. 已确认同类位点：`role=all` 与 `role=important` 同一代码路径；任何被置 `paused` 的目录同样产出 `unread_count=null`；`X-GM-LABELS` 缺失影响全部 Gmail 标签成员关系，不止这两个视图。
- 根因：产品架构缺陷（非环境、配置或测试假绿）。
    - 数据模型已是正确形态：`Message` 按 `(account_id, remote_id)` 唯一，`MessageLocation` 多对多承载标签位置（`src/mail_core/mail/storage/models.py:162-206`；`docs/blueprint/domain.md:11,14`）；`docs/blueprint/decisions/20261021_entry.md:28` 已确立"跨标签去重、每封单次呈现"。
    - 缺的一环：`src/mail_core/providers/imap.py:1041` 常规 FETCH 只取 `UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS ...]`，全仓无 `X-GM-LABELS` 摄取，虚拟标签成员关系无法从常规同步推导，只能单独 SELECT 整个虚拟目录重抓一遍。
    - `docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md:5,12,21,31` 以 `paused` 回避重复 IO，并在非范围明确排除 Labels 多对多重构；`p060:12-19` 进一步使显式 `folder_id` 指向 paused 目录解析为空目标集；无 `FolderStats` 行 → `src/mail_core/mail/application/queries.py:220` 返回 `null` → `src/frontend/src/components/Sidebar.tsx:342` 渲染蓝色 `-`。
    - 本质错误：把虚拟汇总标签当作带 `sync_status` 的 Folder 同步单元，而非基于 `message_locations` 的派生只读视图。
- 测试缺口：
    - `tests/mail_core/test_gmail_sync_strategy_and_timeout.py:69-104`（t056 AC-001）只断言虚拟目录 paused 不入队，未覆盖标签摄取、去重与视图可读性。
    - `src/frontend/src/components/Sidebar.test.tsx:1255-1257` 为虚拟目录 fixture 伪造 `unread_count=0` / `total_count`，掩盖真实的"无统计行 → null → `-`"状态。
    - 应补：Provider 层 `X-GM-LABELS` 解析与 capability 降级；label→`message_locations` 映射与跨目录去重；view 聚合计数与去重列表；迁移幂等与 `messages` 总数不增；前端真实计数（含 `0`）与空态；`t056`/`p060`/blueprint 文档一致性。
- 线索：`.scratch/repro_gmail_virtual_folder_dash.py`（p086 表层决策链复现）；`docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md:5,12,21,31,72`；`docs/pending/p060_gmail_virtual_folder_not_selectable.md:12-19`；`src/mail_core/providers/imap.py:1041`；`src/mail_core/mail/storage/models.py:162-206`。
- 处理：t086；resolution=transferred；reason=已核实架构根因与完整修复面并转交该 task
