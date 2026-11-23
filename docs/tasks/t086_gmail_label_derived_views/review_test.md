# Task review t086（reviewer_focus: 测试）

- task：`t086_gmail_label_derived_views`
- spec：`docs/tasks/t086_gmail_label_derived_views/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：1
- reviewed_at：2026-11-23T14:51:13+08:00

reviewed_scope: 6fc055f3a2b256c9

## Findings

### t086_test_f001 - 迁移数据不变量零测试，AC-004/AC-006 打勾缺证据

- 严重度：important
- 锚点：AC-004、AC-006
- 位置：`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:40-55`；`tests/mail_core/test_gmail_label_views.py:38-95`
- 问题：全仓无任何测试执行迁移 `20261123_0004`。`tests/` 中 `kind` 相关断言（`test_gmail_label_views.py:59,67`、`test_gmail_label_views_discovery.py:110,128`、`test_sync_requests_paused_folder.py:58`）全部作用在测试中手工构造的 Folder 上，没有先落旧 schema/旧 paused 虚拟目录、跑迁移、再断言结果。因此 AC-004「历史虚拟目录已完成迁移且无残留 paused 标记」与 AC-006「迁移可重复执行且不产生重复 `message_locations` 行；迁移前后 `messages` 总数不增加；All Mail/Important 成员迁移后即可查询」均无对应测试或替代验证。PG runner 仅在初始化时 `alembic upgrade head` 一次，能发现迁移报错，但不能证明幂等、数据不增与回填正确。engine 的「既有 folder 由 paused→view」更新路径同样未被覆盖：两个 discovery 用例的 `existing_folders` 均为 `[]`（`test_gmail_label_views_discovery.py:106,124`）。
- 建议：新增一条 PG 集成测试，seed 旧 schema 的历史虚拟目录与若干 message/location，连续执行 `upgrade` 两次（或 `upgrade head` 后 `downgrade` 再 `upgrade`），断言 `folders.kind='view'`、`sync_status='idle'`、无残留 paused、`messages` 总数不变、`message_locations` 无重复、两个 view 计数与列表可查。

### t086_test_f002 - 标签→view 映射的生产路径被显式入参绕过，且未复现精确去重场景

- 严重度：minor
- 锚点：AC-003、AC-006
- 位置：`tests/mail_core/test_gmail_label_views.py:81-88`；`src/mail_core/sync/metadata.py:219-232`
- 问题：唯一覆盖「标签落为 view location」的集成用例以 `label_view_folders={"\\Important": important.id}` 显式注入映射，绕过了生产默认路径 `apply_metadata_page` → `_label_view_folders()`。若该函数漏识别 view folder 或映射错标签，Important 视图在生产中静默为空而测试仍绿。另该用例只有 INBOX 一个物理目录加 `\\Important` 一个虚拟标签（`:52-83`），未复现 AC-003 明写的「同一封邮件命中两个物理目录与一个虚拟标签 → 1 条 `messages` / 3 条 `message_locations`」，去重语义只被间接覆盖。
- 建议：补一条不传 `label_view_folders`、直接 `apply_metadata_page` 的用例，断言由库内 view folder 自动推导映射并写出 Important location；再补两个物理目录 + 一个标签的 message 使得 `messages=1`、`message_locations=3`。

### t086_test_f003 - 空账号/空 view 的真实 `0` 计数无测试

- 严重度：minor
- 锚点：AC-001
- 位置：`tests/mail_core/test_gmail_label_views.py:102-106`
- 问题：现有断言只验证非空视图 `total=2/unread=1`、`important=1/1`；AC-001 明确要求的「空账号为 `0`，不再为 `null`」没有断言。`view_stats` 的 `if not folder_ids: return 0,0`（`src/mail_core/mail/application/queries.py:206-207`）与前端空视图 badge 分支均无对应测试。
- 建议：在同一 PG 用例追加一个只有 view folder、没有任何 message/location 的账号，断言 `list_folder_stats_for_account` 对 `all`/`important` 返回 `total_count == 0 and unread_count == 0`。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 改测方向复核：无「迁就实现」的改测。删除 `test_sync_account_folders_pauses_gmail_virtual_folders`（旧 paused 语义按 spec 作废）、重命名并改写 discovery 用例（paused→view 为规格变更）、两处 Alembic head 改读 `CURRENT_HEAD_REVISION`（新迁移合法抬高 head）、t079 临时目录修正（测试基建缺陷）均有归因；INBOX/Sent 正常入队覆盖由 `test_sync_mode_policy.py`/`test_imap_protocol_suite.py` 等其他用例承担，不视为丢失。
- 本轮新发现：3 条（1 important、2 minor）。
- 未进表的提示：AC-010 `[deploy]` 在契约区撤销属实施期决策，上下文区「有意不测」已给出替代验证，测试轴不出 finding，但需 spec 侧确认该需求变更已获用户认可。`test_sync_request_for_paused_virtual_folder_completes_with_zero_targets`（`tests/mail_core/test_sync_requests_paused_folder.py:114-131`）只断言 `state == "complete"`，未直接断言 `target_count == 0`；目标数由 `:67-74` 的 `resolve_sync_targets == []` 间接覆盖，不单独进表。本环境无 `.env.test`/PG 密码，PG 集成用例未重跑；已实跑 `KKMAIL_TEST_MODE=unit` 下 `test_imap_gm_labels.py` 与 `test_gmail_label_views_discovery.py`（6 passed）及前端 `Sidebar.test.tsx` 的 p062 用例（1 passed）。
- 总体判断：迁移相关 AC-004/AC-006 打勾缺少有效测试，存在未解决 important，FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_views.py:102-106` 断言 `all=2/1`、`important=1/1` 为真实计数而非 null；空账号 `0` 分支缺口记为 f003（minor）。
- AC-002：TICK-VALID，re_verified。`test_gmail_label_views.py:108-111` 断言 view 列表按邮件身份去重；`test_gmail_label_views_discovery.py:116-130` 断言 view 不产生作业（`enqueued == []`），已实跑通过。
- AC-003：TICK-VALID，re_verified。`test_imap_gm_labels.py:5-36,61-67` 实跑通过，验证 FETCH 请求 `X-GM-LABELS` 与解析；`test_gmail_label_views.py:96-100` 断言 2 messages/3 locations。生产映射绕过与精确场景缺口记为 f002（minor）。
- AC-004：TICK-VOID，re_verified。新建 view 的 `kind=VIEW`/`IDLE`/无作业由 discovery 用例支撑，但「历史虚拟目录已完成迁移且无残留 paused」无任何测试，见 f001。
- AC-005：TICK-VALID，re_verified。`test_sync_requests_paused_folder.py:67-74` 断言 view 的 `resolve_sync_targets == []`，`:114-131` 断言同步请求 `complete` 不抛 `folder_not_selectable`；列表/计数走只读查询由 `test_gmail_label_views.py:102-111` 支撑。
- AC-006：TICK-VOID，re_verified。全仓无测试执行迁移 `20261123_0004`，幂等、messages 不增、location 不重复、迁移后视图可查均未验证，见 f001。
- AC-007：TICK-VALID，re_verified。`Sidebar.test.tsx:1290-1295` 断言两个视图真实未读数 5/2 且无 `.unread-badge-unknown`，已实跑通过；`-` 语义回归由 `:908-919` 既有断言覆盖。
- AC-008：TICK-VALID，re_verified。diff 中 `t056/task.md` 风险段、`p060` 描述、`architecture.md`/`conventions.md`/`domain.md` 均已改写为派生视图表述，无残留「手动点进触发同步」兜底。
- AC-009：TICK-VALID，trust_prior。依赖实施侧报告的全量门禁结果（后端 PG 套件、前端测试与门禁）；本环境无 PG 密码，仅重跑上述 unit 与前端局部用例，未重跑全量。

coverage = 8 / 9

verdict: FAIL

## Round 2 (2026-11-23T15:00:06+08:00)

- task：`t086_gmail_label_derived_views`
- spec：`docs/tasks/t086_gmail_label_derived_views/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：2
- reviewed_at：2026-11-23T15:00:06+08:00

reviewed_scope: 9cbbbd2e36eced05

### Findings

### t086_test_f004 - 迁移不变量断言在无 seed 数据下不可证伪

- 严重度：minor
- 锚点：AC-006
- 位置：`tests/mail_core/test_gmail_label_views.py:139,150`
- 问题：`test_view_labels_only_migrate_for_gmail_accounts_and_are_idempotent` 只 seed 两个 Folder（`:121-138`），未插入任何 Message / MessageLocation。`before = len(session.scalars(select(Message)).all())`（`:139`）恒为 `0`，`assert len(...) == before`（`:150`）实质是 `0 == 0`，无法证伪「迁移增加 messages 行数」；迁移 SQL（`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:31-44` 的 `VIEW_UPDATE`）本身也不写 location，「不产生重复 `message_locations` 行」同样缺少可证伪的数据基础。这两条 AC-006 不变量目前只有形式证据。
- 建议：执行 `view_update_statement` 前 seed 1 封 message 与 2 条 location（含一条 view folder 同键记录），断言连跑两次后 `messages` 仍 1 行、location 集合不变且无重复。

### 结论

- 前轮 finding 复核：
    - f001（important，已消除）：新增 `test_view_labels_only_migrate_for_gmail_accounts_and_are_idempotent` 对真实 PG 执行生产迁移语句 `migration.view_update_statement("view","idle")` 两次，断言 Gmail 历史虚拟目录 `CONTAINER/PAUSED → VIEW/IDLE`、非 Gmail 目录保持 `CONTAINER/PAUSED`、连跑两次幂等。核心证据已补，残余弱断言另记 f004（minor），不阻断。
    - f002（minor，修不彻底，残余 minor）：`test_label_mapping_is_derived_from_db_when_not_supplied`（`:153-187`）不传 `label_view_folders`，经生产 `_label_view_folders()` 自动推导 `\Important → view folder` 并断言 location 写出，显式入参绕过已消除。但 AC-003 明写「同一封邮件命中两个物理目录 + 一个虚拟标签 → 1 条 `messages` / 3 条 `message_locations`」仍未精确复现：`test_label_membership_becomes_location_and_views_return_real_counts` 是 2 封邮件 / 3 条 location、仅 INBOX 一个物理目录（`:68-96`）。残余属「可再加 case」minor，与 f002 同级，不阻断。
    - f003（minor，已消除）：新增 `test_empty_view_reports_real_zero_counts`（`:196-206`），对仅含空 view folder 的账号断言 `all.total_count == 0 / unread_count == 0`。残余 minor：未覆盖 `important` 空 view，属可选覆盖扩展，不阻断。
- 改测方向复核：本轮无「迁就实现」的改测；新增用例按 AC 预期写断言，未改旧断言迎合当前实现。
- 本轮新发现：1 条（minor）。
- 未进表的提示：历史邮件 Important / All Mail 成员回填已由实现侧转 `p089`（code review `t086_code_f002` minor 遗留），测试轴不重复出 finding；AC-006 本轮仅按当前迁移与标签摄取机制复验。契约区相对基准打勾并撤销 `[deploy]` AC-010 属实施期决策，前轮已记录，需 spec 侧确认用户认可。本环境未设 `MAIL_CORE_DATABASE_URL`，PG 用例未重跑；本地实跑 `KKMAIL_TEST_MODE=unit` 下 `test_imap_gm_labels.py` + `test_gmail_label_views_discovery.py` 6 passed，PG 用例 collection 8 collected 无导入错误；AC-009 保持 `trust_prior`。
- 总体判断：前轮唯一 important（f001）已由真实迁移语句测试消除，无未解决 critical / important，全部 AC `TICK-VALID`，PASS。
- 系统性 follow-up：`p089_gmail_label_historical_backfill`（已登记 pending，不重复报告）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_views.py:102-106` 断言 `all=2/1`、`important=1/1` 真实计数；新增 `:196-206` 断言空 view `all=0/0`，不再为 null。
- AC-002：TICK-VALID，re_verified。`test_gmail_label_views.py:108-111` 断言 view 列表按邮件身份去重；`test_gmail_label_views_discovery.py:116-130` 断言 view 不入队（`enqueued == []`）；unit 实跑 6 passed。
- AC-003：TICK-VALID，re_verified。`test_imap_gm_labels.py:5-36,61-67` 实跑通过，验证 FETCH 请求 `X-GM-LABELS` 与解析；`test_gmail_label_views.py:96-100` 断言 2 messages / 3 locations 且无重复 messages。精确「1 封 ×2 物理 +1 标签」场景残余记 f002（minor）。
- AC-004：TICK-VALID，re_verified。`test_gmail_label_views.py:141-149` 对真实 PG 连跑两次生产迁移语句，断言 Gmail 历史虚拟目录 `VIEW`/`IDLE`、非 Gmail 不变；discovery 用例断言新建 view 为 `IDLE` 且无作业（unit 实跑通过）。
- AC-005：TICK-VALID，re_verified。`test_sync_requests_paused_folder.py:67-74` 断言 view `resolve_sync_targets == []`（`kind=VIEW` 路径），`:114-131` 断言同步请求 `complete` 不抛 `folder_not_selectable`；列表/计数只读查询由 `test_gmail_label_views.py:102-111` 支撑。
- AC-006：TICK-VALID，re_verified。`test_gmail_label_views.py:141-149` 连跑迁移语句两次证实幂等与 kind 回填；`:108-111` 与 `:186-187` 分别证实 All Mail 视图可查、标签回填后 Important 成员可查。无 seed message/location 的弱断言记 f004（minor）；历史回填转 `p089`。
- AC-007：TICK-VALID，re_verified。`Sidebar.test.tsx:1290-1295` 新增循环断言两个视图真实未读 5/2 且无 `.unread-badge-unknown`；`is_read: null` 的 `-` 语义由 `:908-919` 既有断言覆盖。
- AC-008：TICK-VALID，re_verified。diff 中 `t056/task.md` 风险段、`p060` 描述与 `architecture.md`/`conventions.md`/`domain.md` 均改写为派生视图表述，无残留「手动点进触发同步」兜底。
- AC-009：TICK-VALID，trust_prior。依赖实施侧报告的全量门禁结果；本环境无 PG URL，仅重跑 unit 6 passed 与 PG 用例 collection，未重跑全量。

coverage = 8 / 9

verdict: PASS

## Round 3 (2026-11-23T15:07:39+08:00)

- task：`t086_gmail_label_derived_views`
- spec：`docs/tasks/t086_gmail_label_derived_views/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：3
- reviewed_at：2026-11-23T15:07:39+08:00

reviewed_scope: 9a939fa42968d147

### Findings

本轮无新增 finding。

### 结论

- 前轮 finding 复核：
    - f001（important，已消除，diff 复核）：`tests/mail_core/test_gmail_label_views.py:109-150` 对真实 PG 连跑两次生产迁移语句 `migration.view_update_statement("view","idle")`，断言 Gmail 历史虚拟目录 `CONTAINER/PAUSED → VIEW/IDLE`、非 Gmail 保持 `CONTAINER/PAUSED`、`messages` 行数不变；AC-004/AC-006 的迁移证据成立。
    - f002（minor，修不彻底，残余 minor）：`tests/mail_core/test_gmail_label_views.py:153-185` 不传 `label_view_folders`，经生产 `_label_view_folders()` 推导 `\Important → view` 并断言 location 写出，显式入参绕过已消除。AC-003 精确的「1 封 ×2 物理 +1 标签 = 3 locations」仍由 `:91-95` 的 2 封/3 location 近似覆盖，属可选 case，不阻断。
    - f003（minor，已消除）：`tests/mail_core/test_gmail_label_views.py:188-206` 断言空 view 账号 `all=0/0`，不再为 null。残余 minor：未覆盖 `important` 空 view，属可选扩展。
    - f004（minor，同意撤回，独立复核）：`src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:31-44` 的 `VIEW_UPDATE` 仅 `UPDATE folders SET kind, sync_status`，不写 `messages`/`message_locations`；`:150` 的 `messages == before` 是可证伪的回归守卫（迁移若插行即失败），location 去重由 `test_label_membership_becomes_location_and_views_return_real_counts:91-95` 覆盖。撤回理由成立，非仅采信处置表自述。
- 改测方向复核：本轮无改测；前轮新增用例均按 AC 预期写断言，未见「迁就实现」改写。
- 本轮新发现：0 条（finding 编号续编起点为 t086_test_f005，未触发）。
- 未进表的提示：`docs/tasks/t086_gmail_label_derived_views/task.md:21` 范围段仍写「更正 t056 风险段」，与收敛后的 AC-008（t056 历史文档不修改）措辞不一致，属可选文案清理，不影响 AC-008 判定。契约区相对基准的打勾、AC-010 撤销与 AC-008 收敛已由用户在本轮任务指令中明确确认，非未授权变更。本环境 `MAIL_CORE_DATABASE_URL` 未设，PG 用例未重跑，AC-009 保持 `trust_prior`。
- 总体判断：AC-008 收敛后的文档一致性由 diff 独立验证成立（t056 改动已撤回、p060 失效兜底已勘误、blueprint/决策文档一致），全部 AC `TICK-VALID`，无未解决 critical / important，PASS。
- 系统性 follow-up：`p089_gmail_label_historical_backfill`（已登记 pending，不重复报告）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_gmail_label_views.py:97-101` 断言 `important=1/1`、`all=2/1` 真实计数；`:204-206` 断言空 view `all=0/0`；`queries.py:251-262` 对 view 返回整型计数而非 null。
- AC-002：TICK-VALID，re_verified。`test_gmail_label_views.py:103-106` 断言 view 列表按邮件身份去重（重要仅 subject-1、所有邮件含两封各一次）；`test_gmail_label_views_discovery.py:128-130` 断言 view 不入队（`enqueued == []`）；`queries.py:374-380` 展开 view 作用域后 keyset 去重。
- AC-003：TICK-VALID，re_verified。`test_imap_gm_labels.py:14-20,41-48,82-88` 验证 FETCH 请求携带 `X-GM-LABELS` 且解析入 `RemoteMessageMeta.labels`；`test_gmail_label_views.py:91-95` 断言 2 messages / 3 locations 且重要 location 1 条。精确「1 封 ×2 物理 +1 标签」残余记 f002（minor）。
- AC-004：TICK-VALID，re_verified。`test_gmail_label_views.py:141-149` 对真实 PG 连跑两次生产迁移语句，断言 Gmail 历史虚拟目录 `VIEW/IDLE`、非 Gmail 不变、无残留 paused；`test_gmail_label_views_discovery.py:120-130` 断言精确虚拟标签为 `VIEW/IDLE` 且无作业。
- AC-005：TICK-VALID，re_verified。`test_sync_requests_paused_folder.py:67-74` 断言 view `resolve_sync_targets == []`；`:114-131` 断言显式 view 同步请求 `complete` 不抛 `folder_not_selectable`；计数/列表只读投影由 `queries.py:251-262,374-380` 支撑。
- AC-006：TICK-VALID，re_verified。`test_gmail_label_views.py:141-150` 连跑迁移两次证实幂等与 kind 回填、`messages` 总数不增；`:105-106` 与 `:103-104` 分别证实 All Mail / Important 成员可查；`:153-185` 证实标签回填派生。无 seed 弱断言残余 f004 同意撤回；历史成员回填转 `p089`。
- AC-007：TICK-VALID，re_verified。`Sidebar.test.tsx` 新增循环断言两个视图真实未读 5/2 且无 `.unread-badge-unknown`；`is_read: null` 的 `-` 语义由既有 `:908-919` 断言覆盖，未改动。
- AC-008：TICK-VALID，re_verified。当前 diff 已无 `docs/tasks/t056_*/task.md`（跨 task 改动撤回）；`p060_*.md` 失效路径已替换为勘误且所引旧文件经查确不存在；`architecture.md`/`conventions.md`/`domain.md` 均改 view/container 语义；决策文档 `20261123_gmail_label_derived_views.md:6` 记录 t056 风险段更正作废；`progress.md` 记录撤回与更正结论。四项子要求全部成立。
- AC-009：TICK-VALID，trust_prior。依赖实施侧报告的全量门禁结果（后端 PG 套件、前端测试、`doctor_cmd`/`test_cmd`）；本环境 `MAIL_CORE_DATABASE_URL` 未设，未重跑 PG 与全量门禁。

coverage = 8 / 9

verdict: PASS
