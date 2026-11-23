# Task review t086（reviewer_focus: 代码）

- task：`t086_gmail_label_derived_views`
- spec：`docs/tasks/t086_gmail_label_derived_views/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：1
- reviewed_at：2026-11-23T14:53:21+08:00

reviewed_scope: 6fc055f3a2b256c9

## Findings

### t086_code_f001 - 迁移误将非 Gmail 账号的物理 all/important 目录标为 view 并强制 idle

- 严重度：important
- 锚点：行为缺陷：非 Gmail IMAP 账号的实体「All Mail / Important」目录被迁移判为只读派生视图并停止同步，直到下一次全量 folder discovery 才自愈；违反 `folders.kind` 正确区分 view/container 的不变量。
- 位置：`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:47-58`（`_view_predicate` / `upgrade` 的 UPDATE 无账号来源过滤）；对照 `src/mail_core/sync/engine.py:304-317`
- 问题：`_view_predicate` 只按 `role IN ('all','important') OR remote_id IN (Gmail 6 个 ID)` 匹配，没有像 discovery 那样先用 email/imap_host 判定 Gmail。而 `src/mail_core/providers/imap.py:242-247,978-979` 会把任意 IMAP 账号中名为 `All Mail`/`Important`/`所有邮件`/`重要` 或带 `\All` 特殊用途标志的实体目录赋 `role='all'/'important'`。迁移后这些目录被写成 `kind='view'`、`sync_status='idle'`，而所有同步路径（`sync/engine.py:453`、`sync/delta.py:365`、`sync/reconcile.py:173`、`sync/patrol.py:120`、`sync/idle_watcher.py:389`、`mail/application/sync_requests.py:216`）统一以 `kind==container` 过滤，导致该目录不再排作业、不再收新信，其 `list_folder_stats_for_account` 统计被改写为跨目录投影（`mail/application/queries.py:203-268`）。周期同步为 delta，不触发 `sync_account_folders` discovery，错误状态可持续存在。
- 建议：迁移 UPDATE 增加账号来源过滤，复用与 `sync/engine.py:304-307` 一致的 Gmail 判定（`accounts.email` 后缀 / `config.imap_host` 含 gmail），只命中 Gmail 账号；更彻底的做法是把 Gmail 判定收敛到 `mail/domain/folder_views.py`，供迁移与 discovery 共用，避免两处规则再次分叉。

### t086_code_f002 - 一次性迁移未包含历史 \\Important 标签回填，存量账户 Important 视图可能为空

- 严重度：minor
- 锚点：AC-006；规格范围「一次性迁移：…从 Gmail `\Important` 标签回填 Important 视图成员行，完成后不再重拉」
- 位置：`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:36-55`；`src/mail_core/sync/metadata.py:219-232`
- 问题：迁移只 `add_column(kind)` 并 UPDATE `kind/sync_status`，既未重置任何 `SyncCheckpoint.full_scan_complete`，也未抓取 `X-GM-LABELS`。存量邮件只有在后续 metadata 同步被重新 FETCH 时才由 `upsert_messages` 写入 `\Important` location；delta 只处理变更 UID，因此升级前已入库且未变更的 Important 邮件不会进入 Important 视图，AC-006 的「在完成一次标签回填后即可查询」在存量账户上没有保证。决策文档 `docs/blueprint/decisions/20261123_gmail_label_derived_views.md` 改为「由常规标签感知同步惰性摄取」，与契约区「一次性迁移…回填…完成后不再重拉」的表述不一致，需要确认该需求变更已获用户认可。
- 建议：补一次性回填（迁移内无法联网则提供 post-migration job：重置 Gmail container 目录的 checkpoint 触发一次带 `X-GM-LABELS` 的全量重抓），或在契约区明确改为「由后续常规同步惰性摄取」并去掉「完成后不再重拉」，使 spec 与已批准决策一致。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 本轮新发现：2 条（1 important、1 minor）。
- 未进表的提示：
    - 范围外观察：`git status --short` 中的未跟踪 `.coverage` 为测试覆盖率产物，非交付文件，不影响 review scope 指纹。
    - 范围外观察（建议 follow-up）：Important 视图的 `message_locations` 只在 `sync/metadata.py:156-166` 新增，远端移除 `\Important` 标签时不删除；`sync/reconcile.py:78-97` 因 view location 仍存在而保留已无任何物理目录的 Message，Important 视图可能长期保留过期成员。AC 未覆盖该生命周期，未进 finding 表。建议 follow-up 标题「派生视图成员在标签移除后的清理」，slug `view_membership_lifecycle`（非阻断）。
    - 范围外观察：迁移按 `role` 匹配会命中 Gmail 用户自建且精确命名为 `Important`/`All Mail` 的标签；该行为与既有 discovery 的 `is_gmail_view` 一致，非本 task 引入。
    - 文件过大：本 task 触及的实现源码均低于 400 行阈值，无提示。
    - 圈复杂度：`providers/imap.py:641-687` `_parse_gm_labels` 手算近似 CC≈8，未达 ≥10 提示线；其余新增函数均低于阈值。
    - 实跑验证：`KKMAIL_TEST_MODE=unit` 下 `tests/mail_core/test_imap_gm_labels.py` 与 `tests/mail_core/test_gmail_label_views_discovery.py` 共 6 passed；本环境无 `MAIL_CORE_DATABASE_URL`/PG 密码，PG 集成用例与全量门禁未重跑。
- 总体判断：1 条 important 行为缺陷（迁移误伤非 Gmail 实体目录并停止其同步）未解决，FAIL。
- 系统性 follow-up：无（派生视图成员清理为局部功能缺口，见上方非阻断建议）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`mail/application/queries.py:203-268` 对 view 走 `view_stats`，`folder_ids` 为空时返回 `(0,0)`，count 为 int 且不再为 `null`；`docs/tasks/.../task.md` 打勾成立。
- AC-002：TICK-VALID，re_verified。`queries.py:276-310` 以 `group_by(Message.id)` 去重，`queries.py:374-390` 展开 view 作用域；`sync/engine.py:342`、`mail/application/sync_requests.py:215-222` 排除 view 入队。
- AC-003：TICK-VALID，re_verified。`providers/imap.py:1097-1126` 在 `X-GM-EXT-1` 下 FETCH `X-GM-LABELS`，`sync/metadata.py:156-166` 落 view location；`tests/mail_core/test_imap_gm_labels.py` 实跑通过验证解析与 FETCH 字段。
- AC-004：TICK-VALID，re_verified。`mail/domain/folder_views.py` 定义 `kind` 二分，`sync/engine.py:317-345` 将 Gmail 虚拟目录设为 `VIEW/IDLE` 且不入队，迁移回填 `kind`；迁移误伤非 Gmail 目录另记 f001（行为缺陷，非本 AC 声称的 Gmail 语义）。
- AC-005：TICK-VALID，re_verified。`sync_requests.py:215-222` 对 view 返回空目标集，`create_sync_request` 以 `state=complete`、0 target 完成且不抛 `folder_not_selectable`；`engine.py:453-455`、`delta.py:365`、`reconcile.py:173` 均跳过 view。
- AC-006：TICK-VALID，re_verified。迁移为 `add_column` + 幂等 UPDATE，不新增 `message_locations`、不改 `messages` 总数；`queries.py:203-211` 使 All Mail 迁移后即可查询，`tests/mail_core/test_gmail_label_views.py:81-111` 证明一次带标签的 `apply_metadata_page` 后 Important 成员可查。历史数据回填缺口记为 f002（minor）。
- AC-007：TICK-VALID，re_verified。后端返回真实计数；`src/frontend/src/components/Sidebar.tsx:342` 对非 null 计数渲染真实值，`Sidebar.test.tsx:1290-1295` 断言两个视图不再出现 `.unread-badge-unknown`，非 view 的 `is_read: null` `-` 语义分支未改。
- AC-008：TICK-VALID，re_verified。diff 中 `docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md`、`docs/pending/p060_*.md`、`docs/blueprint/architecture.md`/`conventions.md`/`domain.md` 均已改写为派生视图表述，无残留「手动点进触发同步」兜底。
- AC-009：TICK-VALID，trust_prior。依赖实施侧 `progress.md` 记录的全量门禁结果；本环境无 PG 密码/数据库，仅重跑上述 unit 用例，未独立重跑后端完整 PG 套件与前端全量门禁。

coverage = 8 / 9

verdict: FAIL

## Round 2 (2026-11-23T15:00:05+08:00)

reviewed_scope: 9cbbbd2e36eced05

### Findings

本轮无新发现。

### 前轮 finding 复核

- t086_code_f001（important）：已消除。`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:31-44` 的 UPDATE 增加 `EXISTS (SELECT 1 FROM accounts a WHERE a.id = folders.account_id AND (...))` 账号来源过滤；`lower(a.email) LIKE '%@gmail.com'` / `'%@googlemail.com'` 无尾通配符，等价 `endswith`，`lower(COALESCE(a.config ->> 'imap_host','')) LIKE '%gmail%'` 为含 gmail。与 discovery `src/mail_core/sync/engine.py:304-307` 的 `endswith("@gmail.com","@googlemail.com")` / `"gmail" in imap_host` 判定一致；非 Gmail 账号的 all/important 目录不再被写成 view/idle。测试 `tests/mail_core/test_gmail_label_views.py:109-150` 断言 Gmail folder→VIEW/IDLE、非 Gmail folder→CONTAINER/PAUSED、重复执行幂等且 `messages` 总数不变。
- t086_code_f002（minor）：同意遗留。`docs/pending/p089_gmail_label_historical_backfill.md` 已登记（status `todo`，来源指向 `t086_code_f002`，内容明确一次性 `X-GM-LABELS` 回填作业设计），`progress.md` 处置表标注「遗留 → p089」。minor 非阻断；AC-006「完成一次标签回填后即可查询」由 `src/mail_core/sync/metadata.py:216-254` 的 `label_view_folders` 派生路径满足，打勾成立。

### 结论

- 前轮 finding 复核：f001 已修（diff 与代码核实）；f002 minor，同意遗留至 p089。
- 本轮新发现：0 条。
- 未进表的提示：
    - 未跟踪文件：`.coverage`（覆盖率产物）、`docs/pending/p089_*.md`（pending 流程文件，指纹排除）、`review_code.md`/`review_test.md`（review 报告，流程文件排除）；无 reviewer 不可见的未跟踪交付文件。
    - 范围外观察：f002 的一次性历史标签回填作业留 p089 实施，本轮不重开。
    - 文件过大/圈复杂度：f001 修复仅改迁移文件（65 行），无新增阈值命中。
    - 实跑验证：环境无 `MAIL_CORE_DATABASE_URL`，迁移 PG 用例未重跑；以代码与 SQL 静态复核确认过滤语义正确（email `endswith`、imap_host 含 gmail、bindparams 防注入、`COALESCE` 空值处理）。
- 总体判断：前轮唯一 important 已消除，f002 为可接受 minor 遗留，未引入新 critical / important。
- 系统性 follow-up：p089（非阻断，已登记）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`queries.py:203-268` 对 view 走 `view_stats`，`folder_ids` 为空返回 `(0,0)`，计数为 int 且非 `null`；f001 修复不改此路径。
- AC-002：TICK-VALID，re_verified。`queries.py:374-390` 以 view 作用域展开并复用 keyset 去重；`sync/engine.py:342`、`sync_requests.py:215-222` 排除 view 入队。
- AC-003：TICK-VALID，re_verified。`providers/imap.py:1094-1126` 在 `X-GM-EXT-1` 下 FETCH `X-GM-LABELS`，`sync/metadata.py:153-165` 落 view location。
- AC-004：TICK-VALID，re_verified。`folder_views.py` 定义 kind 二分；`engine.py:304-340` 将 Gmail 虚拟目录设为 VIEW/IDLE 且不入队；迁移已加 Gmail 账号过滤（f001 修复），历史非 Gmail all/important 不再误判、无残留 paused。
- AC-005：TICK-VALID，re_verified。`sync_requests.py:215-222` 对 view 返回空目标集，`create_sync_request` 以 0 target 完成且不抛 `folder_not_selectable`；`engine.py:453-455` 跳过 view。
- AC-006：TICK-VALID，re_verified。迁移为 `add_column` + 幂等 UPDATE，不新增 `message_locations`、不改 `messages` 总数；All Mail 迁移后即可查询，Important 经一次带标签 metadata 同步即可查询（`tests/mail_core/test_gmail_label_views.py:81-111`）；历史回填缺口记 f002 遗留。
- AC-007：TICK-VALID，re_verified。后端返回真实计数；`Sidebar.test.tsx:1287-1295` 断言两个视图不再出现 `.unread-badge-unknown` 且渲染真实未读数，非 view 的 `is_read: null` `-` 语义未改。
- AC-008：TICK-VALID，re_verified。diff 中 `t056/task.md`、`p060`、`docs/blueprint/architecture.md` 已改写为派生视图表述，无残留「手动点进触发同步」兜底。
- AC-009：TICK-VALID，trust_prior。依赖实施侧 `progress.md` 记录的全量门禁结果；本环境无 PG 密码/数据库，未独立重跑后端完整 PG 套件与前端全量门禁。

coverage = 8 / 9

verdict: PASS

## Round 3 (2026-11-23T15:08:18+08:00)

reviewed_scope: 9a939fa42968d147

### Findings

本轮无新发现。

### 前轮 finding 复核

- t086_code_f001（important）：仍为已消除。迁移 `src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:35-43` 的 `EXISTS` 账号来源过滤保留，与 discovery `src/mail_core/sync/engine.py:304-307` 的 Gmail 判定一致；本轮未改代码，无回归。
- t086_code_f002（minor）：仍为遗留 `p089`。本轮未改代码与 `p089`，维持 Round 2 结论。

### 结论

- 前轮 finding 复核：f001 已修状态不变；f002 minor 遗留 p089 不变。
- 本轮新发现：0 条。
- AC-008 收敛复核（本轮重点）：诚实，打勾成立。
    - 工具写权边界属实：`lifecycle.py:765-772` 的 `validate_task_core_asset_changes(..., {task_dir.name})` + `monitoring.py:66-83` 明确把 `docs/tasks/{tid}/task.md` 列为该 task 的核心资产，非 owner（t086）修改会在 finish 被阻断。撤回对 `docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md` 的修改是真实约束所致，非借口。
    - 交付侧一致：`git status --short` 与 diff 均无 t056 路径；更正结论落在允许写入的两处——`docs/tasks/t086_gmail_label_derived_views/progress.md:31`（「t056/task.md …已撤回该改动；更正结论以本条与决策记录为准」）与 `docs/blueprint/decisions/20261123_gmail_label_derived_views.md:6`（「t056 的『手动点进触发同步』与 p060 的前端同步路径表述作废」）。
    - p060 与 blueprint/决策文档无失效兜底：`docs/pending/p060_gmail_virtual_folder_not_selectable.md:17` 勘误明确 `use_scope_sync.ts`/`sync_scope.ts`/`POST /api/mail/sync/delta` 已不存在；`docs/blueprint/architecture.md:39,129`、`conventions.md:162`、`domain.md:11` 均改为 view/container 语义；决策文档无残留。
    - 收敛后 AC-008 行为面与实现/文档一致，无 TICK-VOID。
- 未进表的提示：
    - 范围外观察（建议 follow-up）：`docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md:72` 风险段仍保留「默认 paused 需手动点进该文件夹触发同步」失效表述，受写权边界限制本 task 不能改；决策文档已记录其作废，但原文仍在历史 task 文档中。建议由独立 task 清理（非阻断）。
    - 未跟踪文件：`review_code.md`/`review_test.md`（review 过程文件，指纹排除）、`.coverage`（覆盖率产物），无 reviewer 不可见的未跟踪交付文件。
    - 文件过大/圈复杂度：本轮仅文档变更，无新增阈值命中；代码文件沿用 Round 1/2 复核结论。
    - 实跑验证：本轮未改代码，未重跑测试；AC-009 仍 trust_prior。
- 总体判断：前轮唯一 important 已消除且未回归，AC-008 收敛诚实、打勾成立，无新 critical / important，PASS。
- 系统性 follow-up：建议标题「t056 风险段失效兜底表述清理」，slug `t056_stale_fallback_cleanup`（非阻断，待独立 task）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`queries.py:229-242` 对 view 走 `view_stats`，`folder_ids` 为空返回 `(0, 0)`，计数为 int 且非 `null`；本轮未改此路径。
- AC-002：TICK-VALID，re_verified。`queries.py:309` 以 `group_by(Message.id)` 去重、`queries.py:377` 展开 view 作用域；`sync/engine.py:342`、`sync_requests.py:242,259` 排除 view 入队。
- AC-003：TICK-VALID，re_verified。`providers/imap.py:1097-1125` 在 `X-GM-EXT-1` 下 FETCH `X-GM-LABELS`，`sync/metadata.py` 落 view location；本轮无代码改动。
- AC-004：TICK-VALID，re_verified。`folder_views.py:7-10,26-35` 定义 kind 二分与判定；`engine.py:304-340` Gmail 虚拟目录设 VIEW/IDLE 且 `kind==container` 过滤；迁移已加 Gmail 账号过滤（f001 修复保留）。
- AC-005：TICK-VALID，re_verified。`sync_requests.py:216-226` 对 view 返回空目标集，0 target 完成且不抛 `folder_not_selectable`；`engine.py:457` 以 `derived_view` 跳过。
- AC-006：TICK-VALID，re_verified。迁移 `20261123_0004` 为 `add_column` + 幂等 UPDATE（`:34-43`），不新增 `message_locations`、不改 `messages` 总数；All Mail 迁移后即可查，Important 经一次带标签 metadata 同步可查。
- AC-007：TICK-VALID，re_verified。`Sidebar.tsx:342` 非 null 计数渲染真实值；`Sidebar.test.tsx` 断言两视图不再出现 `.unread-badge-unknown`，非 view 的 `is_read: null` `-` 语义未改。
- AC-008：TICK-VALID，re_verified。本轮逐处核实收敛诚实：t056 未改（写权边界属实），更正记录于本 task `progress.md:31` 与决策文档 `:6`；p060 `:17` 勘误 + blueprint architecture/domain/conventions 均为 view/container 表述，无失效「手动点进触发同步」兜底残留。
- AC-009：TICK-VALID，trust_prior。依赖实施侧 `progress.md` 记录的全量门禁结果（PG 2224 passed、前端测试与 `tsc -b`/`build`、E2E 23 passed）；本环境无 PG 密码/数据库，未独立重跑。

coverage = 8 / 9

verdict: PASS
