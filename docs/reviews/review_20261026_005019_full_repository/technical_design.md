# 修复技术设计：代码、数据、测试与文档改造

- 文档状态：**未来实施设计，未实现、未运行下述新增测试**。
- 代码复核基准：`60366915c5efe5b0eeb7c7303835f2c58883faaa`；相对排期基准只提交了 review 文档，生产代码未变化。
- 适用范围：P1-01 至 P1-05，P2-01 至 P2-04、P2-06 至 P2-10，以及 p045–p052；**排除 P1-06、P2-05**。
- 分工、分支、worktree、并发与合入依据：[执行编排计划](repair_plan.md)。本文件定义技术交付内容，不启动 task 流程。
- 原始证据：[审阅报告](review_report.md)、[验证记录](review_evidence.md)。函数名、字段、文件和状态在本文标“新增”者均为拟实现接口，不得误读为仓库已有能力。

## D00. 实施约束与文件组织

### D00.1 实现原则

1. 复用现有 SQLAlchemy、psycopg、Pydantic、React Query、Zustand、Vitest、Playwright，不新增队列服务器或浏览器状态框架。
2. 当前 `Session` 为 `autoflush=False`，所有“改 ORM → SQL 聚合/跨连接读取”均显式 flush/commit；Session 不跨线程共享。
3. 网络拉取在业务事务外；短事务内完成状态锁、fencing、关联写入和 Outbox。文件发布保留 digest 锁、配额和 GC 二次确认。
4. 新普通模块使用 snake_case；现有文件保持原名，不借修复重排全部源码。
5. 每个来源先有触达生产入口的失败用例，再修实现。下文列的是行为用例，不要求把测试写成实现内部函数逐行镜像。
6. 本轮不批量改旧测试预期。测试语义确已失效时，整体替换该用例并记录原断言与新契约，保留仍有效断言。

### D00.2 文件边界

后端新增逻辑优先落在既有责任模块。仅对跨调用点确实复用的职责新增以下模块：

|拟新增文件|责任|负责人|
|---|---|---|
|`src/mail_core/realtime/publication.py`|提交后发布序号分配、发布状态查询|F07|
|`src/mail_core/mail/application/sync_requests.py`|scope 解析、请求/目标记录、delta/full 调度|F10|
|`src/mail_core/providers/connection_slots.py`|跨进程 mail-provider 连接准入与释放|F10|
|`src/frontend/src/hooks/use_scope_sync.ts`|当前 scope 的手动/自动同步、冷却和请求状态|F10|
|`src/frontend/src/lib/sync_scope.ts`|ViewState 到同步 scope 的纯函数转换|F10|
|`src/frontend/src/lib/ui_shortcut.ts`|可持久化快捷键解析、显示和匹配|F11|

队列后继 helper 保留在 `sync/jobs.py`；备份校验 helper 保留在 `backup/package.py`；Sidebar 搜索关闭 helper 优先放同文件并复用主列表/分组调用，不为一次性功能建通用事件框架。

## D01. F01：provider 日志与异常链

### 代码改造

|文件|具体改动|
|---|---|
|[security/redact.py](../../../src/mail_core/security/redact.py)|在 `_PATTERNS` 增加精确 token 键的引号/非引号/URL 参数匹配；保留现有 access_token 等字段；修正匹配边界避免吞掉后续日志字段|
|[logging_config.py](../../../src/mail_core/logging_config.py)|`RedactingTraceFormatter` 在格式化异常时识别 provider 异常及其 cause/context，输出受控摘要和调用帧，不输出原始异常 message/body；最后仍执行通用 redact|
|[sync/delta.py](../../../src/mail_core/sync/delta.py)、[sync/reconcile.py](../../../src/mail_core/sync/reconcile.py)、[sync/remote_push.py](../../../src/mail_core/sync/remote_push.py)|provider 捕获分支用 `safe_provider_summary`，不传原始 `exc_info=True`；记录 account/message/job UUID、错误类型与状态|
|[worker/handlers.py](../../../src/mail_core/worker/handlers.py)|检查上层 DEBUG traceback 不能把刚被下层摘要处理的异常重新完整输出|

新增私有 helper `_format_safe_exception_chain(exc_info) -> str`：遍历 cause/context，保留异常类型、受控 status 和 traceback 文件/函数/行号；若任一节点属于 ProviderHttpError/OAuth provider 错误，整条链禁止输出原始 `str(exc)` 或 `repr(body)`，包括复制了 provider 内容的外层普通异常。普通应用异常仍按当前受控策略输出并最终脱敏，日志不携带局部变量。

不得仅在 logger message 中摘要后继续由 Formatter 自动追加原始 traceback；不得以“DEBUG 默认关闭”作为保密边界。

### 测试改造

- 扩展 `tests/mail_core/test_logging_trace_and_redact.py`：使用真实 logger、StreamHandler 和生产 Formatter，分别测试 INFO/ERROR/DEBUG、异常 cause/context、JSON/URL/Bearer/token 标记。断言最终输出无合成秘密标记，并保留 trace/type/status。
- 扩展 `test_remote_ops_redact.py`、`test_sync_hardening_a27_a28_a29.py`：通过真实 delta/remote push 失败路径，核对日志与 DB last_error，不只断言 `logger.error` mock 参数。
- 新增“下层摘要、上层重抛”案例，防止只有直接 provider 捕获分支安全。
- F01 commit 同时交付调用点修复和上述测试；不修改 P2-05 路由权限。

## D02. F02：备份包路径与源库保护

### D02.1 校验与暂存函数

在 [backup/package.py](../../../src/mail_core/backup/package.py) 新增私有 helper，`restore_backup_package` 只编排步骤：

|拟新增函数/类型|输入/输出|规则|
|---|---|---|
|`_validate_blob_members(tar) -> list[ValidatedBlobMember]`|tar 元信息 → 规范化成员|只允许 `blobs` 根、合法子目录及普通文件；拒绝链接、设备、绝对路径、盘符、反斜杠、空/重复分隔、`.`/`..` 和重复写入同一路径|
|`_validate_restore_destination(path) -> Path`|原始目标 → 已核对目标|先 lstat 原始末端再 resolve；目标必须不存在或为空普通目录；拒绝末端/内部链接与非空目录|
|`_extract_blobs_to_staging(tar, members, parent) -> Path`|全量校验后的成员 → 本次私有目录|每级目录检查后创建；文件 `O_EXCL`，支持处使用 no-follow；写入 fsync，目录边界持续核对|
|`DatabaseIdentity`|cluster ID、database OID、database name|用户名、密码和连接别名不是身份字段|
|`_read_database_identity(url) -> DatabaseIdentity`|只读 DB 连接|读取实际实例/数据库，不打印 URL；读取失败拒绝进入恢复|

路径规则以 `PurePosixPath` 和原始 member name 双重判断，不让 `Path` 在校验前吞掉 `//` 或 `.`。先校验**所有成员**，再写 staging；发现一个恶意成员即整包失败，不静默跳过。合法目录布局以生产 `create_backup_package` 生成包为回归样本，不擅自把当前文件格式收紧成尚未声明的唯一命名模式。

### D02.2 源身份与灾难恢复

仅比较 URL 会漏别名；要求源永远在线又会破坏灾难恢复。采用同一种 `DatabaseIdentity`，区分证据来源：

1. 新创建的加密备份在**内层认证 manifest**保存 `source_database_identity`，由真实源连接读取。外层用于定位/校验的非认证摘要不能替代该值。
2. 源可连接时读取源/目标实际身份；若 manifest 也有源身份，二者必须一致，否则拒绝。源目标 cluster ID + database OID 一致即拒绝，无论用户名/地址如何变化；名称用于诊断和一致性检查。
3. 源离线时，仅在成功认证/解密的新备份含源身份、且目标身份可独立读取时允许继续。旧包或未加密普通包只有 checksum，不能作为离线源身份权威；这类场景要求在线源证据或另行提供经独立核验的恢复前置，不靠跳过校验继续。
4. `pg_control_system()` 权限与 PG16 实际行为在隔离环境验证；需要只读权限时明确最小 grant，不能默认为全部角色已有权限，不能扩大成 superuser。
5. system identifier 可能被物理克隆保留；相同身份无法证明目标独立时保守拒绝，记录该限制。操作者独占恢复目标，禁止恢复期间换库/换代理路由。

新 manifest 字段为向后读取可选元信息；旧包在有在线源证据时仍走**同一身份验证函数**，不保留旧的不安全恢复分支。

### D02.3 恢复顺序与失败状态

```text
snapshot package
→ verify/decrypt manifest + checksums
→ validate all tar members and destination
→ verify source/target identity and empty target DB
→ extract private staging
→ pg_restore single transaction into owned empty target
→ atomically publish Blob directory
→ decrypt/sample-check restored data
→ report complete
```

`pg_restore` 使用 `--exit-on-error --single-transaction --no-owner --no-privileges`，取消常规新库恢复中的 `--clean`。目标为空校验只忽略 PG 系统对象，发现业务表/对象即拒绝。密码继续只经受控环境传递，不放 argv。

|失败阶段|允许留下的状态|处理|
|---|---|---|
|成员/身份/权限预检失败|仅包 snapshot|删除本次临时目录；目标 DB/Blob 未改变|
|解包失败|私有 staging|只清理本次目录；源不变|
|pg_restore 失败|空目标事务回滚、staging|保留脱敏错误，清理 staging；不能对源重试|
|DB 成功、目录发布失败|已恢复但尚未启用的独占目标 DB|标为部分成功，保留诊断及可重试 staging；不自动接入业务，不删除用户目标|
|最终抽检失败|隔离目标，未切流量|停止启用；由明确恢复流程决定重建目标或前向修复|

函数内部没有对业务源的回滚/删除权限。恢复和生产切换仍需执行时单独授权。

### 测试改造

- `test_backup_restore_drill_live.py`：保留真实 pg_dump/pg_restore/解密附件演练；增加同库不同角色、不同数据库合法目标、目标非空和事务中途失败。
- `test_backup_package.py` / `test_backup_verify_drill.py`：新增成员矩阵：`blobs//absolute`、`..`、Windows 路径、symlink/hardlink、设备、重复成员、先合法后恶意；根外哨兵和已存在目标逐字节不变。
- 新增 `tests/mail_core/test_backup_restore_identity.py`（拟新增）：源在线/离线、认证 manifest、无认证旧包、权限不足、别名及克隆身份；断言拒绝时 pg_restore 未调用。
- 涉及 socket/实例权限的案例使用真实测试 PG；纯 URL/路径校验可无 DB。合成 dump 只验证防护，不当成真实可恢复证据。

## D03. F03：去重任务、后继描述与原子完成

### D03.1 持久表示与函数签名

不新增 WorkerJob 表/列；利用现有 JSONB payload 的保留字段，业务载荷从传给 provider 的 payload 中剥离。采用一个私有后继描述，不再并行维护多套 `_followup_*` 状态。

```json
{
  "folder_id": "业务目标UUID",
  "poll_round": 0,
  "_queue_next": {
    "payload": {"folder_id": "同一业务目标UUID", "poll_round": 1},
    "priority": 75,
    "requested_at": "带时区时间",
    "run_after": "期望执行时间",
    "not_before": null,
    "request_target_ids": []
  }
}
```

这只是结构示意，不是可用账号/凭据配置。`not_before` 是已知 provider 冷却下界，不与普通期望执行时间混用。

|函数|改造|
|---|---|
|`enqueue_job`|增加明确 `cause`（periodic/user/continuation/provider_backoff）；所有现有调用点更新；返回可识别当前/后继承载关系的结果，不把终态行返回成成功入队|
|`_merge_requested_run`（新增私有）|按 job 类型与 cause 合并待执行描述，验证 folder/message/account/type 身份|
|`complete_job`|在持锁、刷新后的行上完成原任务并原子派生后继，返回后继 ID 或空；不再由 handler 在外部复制旧 payload 后入队|
|`fail_job` / stale reclaim|重排时保留未消费请求；终态失败不得把新请求埋进不可执行行；自动后继不重置失败计数制造无限重试|
|`_evaluate_result`|只解释业务结果和受控后继建议，调用统一完成入口；移除自身的“complete 后另开 enqueue”逻辑|

### D03.2 精确状态协议

|查到状态|持锁后动作|新请求落点|
|---|---|---|
|无活跃行|savepoint 插入 PENDING；唯一约束竞争后重查并锁活跃行|新任务|
|PENDING|刷新 ORM，合并 business payload、priority、执行时间与请求关联|同一行，下一次 claim 执行|
|CLAIMED|当前业务输入保持不变，仅合并 `_queue_next`|原任务完成事务创建的唯一后继|
|等待后变成 DONE/FAILED/CANCELLED|重新检查活跃集合，必要时插入|不得返回该终态行|
|完成时存在 `_queue_next`|原行标 DONE 并 flush，插入同 dedupe_key 后继，清除原私有字段|与完成同一 DB commit 可见|

核心伪代码：

```python
def finish_and_schedule(session, job_id, claim_owner, result):
    job = lock_and_refresh_job(session, job_id)
    assert_current_claim(job, claim_owner)
    successor = merge_next_description(job, result)
    mark_done_and_clear_claim(job)
    session.flush()  # 释放活跃唯一约束占位，仍在同一事务
    child = insert_successor_if_required(session, job, successor)
    update_sync_targets_in_same_transaction(session, job, child, result)
    return child
```

这是算法示意；事务由既有调用方统一 commit，不在 helper 内隐式提交。若任一步失败，旧任务完成和后继均回滚。

其中 `update_sync_targets_in_same_transaction` 由 F10 C01 接入；F03 先交付不依赖尚不存在请求表的原子队列核心，不能提前 import 未来模块导致中间 commit 不可运行。

不依赖 identity map 中旧 job.payload：锁定查询使用刷新语义。队列完成事务只锁 WorkerJob → 同步目标 → 请求汇总，按 UUID 排序；账号状态恢复移至完成提交后的独立短事务，避免“API 持账号锁等 job、Worker 持 job 锁等账号”的循环。

### D03.3 字段合并规则

|字段/来源|确定规则|
|---|---|
|account_id、job_type、folder_id/message_id|同 dedupe_key 必须一致；不一致拒绝，防串账号/串任务|
|普通业务字段|只替换调用方明确提交的字段；不把未传字段默认为空|
|poll_round|continuation 提交的新计数有效；user 请求不带计数时不能重置现有计数；下轮普通 polling 从引擎明确传入值|
|priority|多个待执行请求选实际最高 urgency；完成后的新周期描述可回到周期级别，不能永久继承一次 user 请求的高优|
|run_after|普通请求取最早期望时刻；不得早于 not_before|
|not_before|provider_backoff 采用仍有效的最大冷却下界；user/focus 不能清除|
|request_target_ids|集合并集并去重；只随对应待执行输入流转，不复制到无限后续周期|
|detail/错误摘要|保留受控最新诊断；不同字段不被空 periodic payload 清掉|

旧 `_followup_*` 在线 Worker 必须在切换前退出。由 F03 提供一次性受控转换入口，锁住活跃行将旧描述归一化，输出计数/异常 UUID，不把无法解析时间默认为立即执行；转换前备份，转换后不保留旧运行协议。此数据转换不引入新 schema revision，避免与同波 F07 迁移抢 head。

### 测试改造

- 扩展 `test_sync_leases_jobs.py`、`test_sync_retry_queue.py`、`test_jobs_backoff.py`：PENDING/CLAIMED 合并、provider 冷却不可绕过、周期优先级恢复、每 20 轮 reconcile。
- 新增 `tests/mail_core/test_job_successor_atomicity.py`（拟新增）：两个真实 Session 通过 barrier 控制 SELECT/complete/UPDATE 交错；唯一约束 insert race；整事务 rollback；原 owner 丢失；SIGKILL 后重新领取。
- `test_worker_loop.py`：把原来“handler 自己再 enqueue”的用例整体替换为统一完成入口行为测试，保留 owner 验证、失败计数、回收和非法 payload 覆盖。
- 原 `test_a27_sync_folder_delta_sanitizes_errors` 保留原样直到完整新语义测试到位；若旧检查对象从当前 job 变为 successor，整体替换并记录原因，不原地把 None 作为正确输出。

## D04. F04：搜索关闭、树顺序与几何

### 搜索状态与事件

`Sidebar.tsx` 内增加复用的 `useScopedSearchDismiss({open, containerRef, triggerRef, onClose})` 或等价同文件逻辑。主账号列表、每个 GroupTree 都给搜索内容及触发按钮稳定 ref，不使用全局“关闭全部”状态。

- pointerdown：composedPath 在输入/清空/触发范围内则保留，否则 `close('outside')`。
- focusout：relatedTarget 仍在范围内不关闭；为 null 时下一帧检查 activeElement，避免浏览器暂时转焦误关。离开范围后关闭并清空该区域搜索词。
- Esc/toggle：关闭后恢复本区域原展开状态，焦点回触发按钮。
- outside/blur：关闭但不抢回焦点，用户刚点击的新控件应获得焦点。
- 清空按钮：按现有已批准语义处理清词/收起；不因输入先 blur 而吞掉点击。监听器只在打开时注册，卸载清理。
- 输入法 composition 不把中间拼音送入持久偏好或改全局邮件搜索；关闭仅影响侧栏本地过滤。

### 树顺序与布局公式

不重写服务器 Folder 树，不按 role 合并真实文件夹。先把 roots 分为“自身或后代含 inbox”与其余两组，组内保留稳定树排序；完整渲染 inbox-bearing roots，再渲染同层虚拟未读入口，再渲染剩余 roots。这样嵌套 inbox 不被从父目录拆出，多 inbox 保持独立入口。

统一行几何：`indent_step=24px`、`disclosure_slot=18px`、`column_gap=4px`、`icon=16px`。account 行 depth=1，直属 folder/unread depth=2，子目录递增。有无箭头均占相同 disclosure slot。

```text
row padding = depth * 24
icon x relative to tree origin = row padding + 18 + 4
label x = icon x + 16 + 4
child icon x - parent icon x = 24
```

`index.css` 使用局部 `--tree-depth` 和统一 grid/flex 槽；将 `48 + level*24` 与额外 gap 的多重补偿改为 depth 参数。status/loading/error 行文本与对应层 label 列对齐；顶层标题原有 ≤1px 对齐要求保留。

`.footer-btn` 常态 background 透明、边框透明；hover/active 使用已有 surface token，focus-visible 保留可见轮廓。只改该控件局部样式，不新增全局颜色值。

### 测试与文档

- `Sidebar.test.tsx`：主搜索与两组同时打开、内部点击不关、外部关闭、键盘离开、Esc、清空、展开状态恢复、过滤期间拖放限制；验证 inbox/unread DOM 顺序及多 inbox 不合并。
- `tests/e2e/sidebar_tree.spec.ts`：真实 boundingBox 验证各层 icon 差 24px、同层对齐及状态行 label；180px 侧栏、移动抽屉、输入法/焦点流程。保留旧顶层几何测试；仅语义已改的旧期望整例替换并记原因。
- `conventions.md` 更新搜索失焦/焦点恢复及统一槽位规则，`inbox_ui_and_search.md` 对应行为契约更新；不把绝对像素坐标当跨布局要求。

## D05. F05：共享状态、位置删除和真实 Trash

### 状态变更返回值

扩展 `metadata.UpsertOutcome`，至少返回 `read_changed`、`location_created` 和现有 message/created/changed；不要仅用 changed 推断所有目录统计都变了。`_apply_flag_patches` 返回实际读状态变化的 message ID 集与详情失效集。

页应用过程：

1. 在改/删前批量读取必要 MessageLocation，校验 Folder.account_id 与 Message.account_id 一致。
2. 应用本地意图保护后比较旧/新 read；确有变化的邮件，把其全部位置加入 `dirty_folder_ids`。
3. 新位置加入当前 folder；移除位置把移除前 folder 加 dirty，即使 Message 不成为孤儿。
4. 删除孤儿 Message 前保存事件所需 UUID；清理保持已有 FK/Blob 语义，不在同步事务直接删除 Blob 文件。
5. 显式 flush，再按 folder UUID 排序调用 `recompute_folder_stats`；每个 dirty folder 每页只算一次并产生一个 stats_updated。
6. 邮件仍存在但位置改变时发 `message.upserted` 使位置/详情失效；整个 Message 真删除才发 `message.removed`。重复删除与同值 flag 重放不额外生成变化。

新增私有批量 helper 可落在 `metadata.py` 或既有存储统计模块，两个入口共用；禁止逐封再逐文件夹查询形成 N+1。

### Trash 解析

`mutations.py` 新增 `_resolve_imap_trash_folder(session, account_id)`，查询 role=trash 且可选择的本账号目录：恰好一个则返回 remote_id，零/多个抛受控目标不可用异常。该异常归入既有可处理的 409 地址不可用类别，**F05 不修改 api/mail.py**，避免与同波 F08 冲突。

`trash_message` 在删本地 Message 前解析目标并写入 desired_state；不对 Gmail/Graph 强行指定 IMAP 目录。`remote_push.py` 对尚未发出的旧 IMAP trash 任务重解析真实目标；解析失败保持可诊断失败，不发送猜测命令，不回退 EXPUNGE。

### 测试改造

- `test_metadata_apply.py`、`test_delta_flag_patch.py`、`test_unknown_mail_status.py`：多位置 False→True、True→False、未知值、本地意图保护、同值重放；所有目录总数/未读正确。
- `test_delta_result_counts.py` / `test_sync_delta.py`：只移除标签而保留消息，验证 dirty folder 事件、总数、其他位置和幂等性。
- `test_primary_location.py`、`test_message_mutations_api.py`：目标解析在本地删除前失败时数据原样；验证账户范围不串。
- `test_imap_protocol_suite.py`：Dovecot 创建含空格/非默认 Trash 目录，实际查询 MOVE 后目标 UID；缺目标/多个目标不进行无关删除。
- 新增批量页查询次数上界或使用现有性能基准验证，无需为每个 helper 添加镜像单测。

## D06. F06：进程健康线程

### 代码与生命周期

在 `worker/heartbeat.py` 增加进程级 `WorkerHeartbeatLoop`，只在 `worker.main.run` 创建/关闭；不另起独立守护服务。

|成员/方法|定义|
|---|---|
|`start(worker_id, session_factory, interval_s)`|同步写首个健康记录，再启动线程|
|`set_active_jobs(count)`|线程安全更新进程内活跃计数，不带 Session|
|`_tick()`|每次创建自己的 Session，事务写 AppSetting；失败仅安全摘要，不能刷新虚假成功时间|
|`stop()`|Event 停止，有限 join；线程退出后不再发健康记录|

`run` 包住主循环的 try/finally 统一关闭该对象；保留 job claim heartbeat 独立线程。F10 ThreadPool 后从 futures 集合计算 active_jobs，避免并发增减丢失。检查数据库连接 timeout 小于正常停止预算，避免 join 超时还残留活线程。

`system_metrics.py` 用 `SyncRunStatus.DONE.value` 筛选。此修复只纠正成功状态，不擅自把现有全局 latest 改成每账号最慢 lag；口径变化单列需求。

### 测试改造

- `test_system_health.py`：真实 PG 插入 DONE/RUNNING 记录，断言 latest 时间、空值；不 mock scalar 绕过 WHERE。
- `test_worker_loop.py`：启动/停止、重复 run、写心跳异常恢复、active_jobs 并发计数；保留锁续期测试。
- `test_worker_process_recovery.py`：受控慢 provider，处理跨 60 秒期间另一进程读取 healthcheck 始终正常；kill 后自然过期，停止后无新心跳。快速层可用短阈值，最终至少一次默认阈值实测。
- 文档说明 heartbeat=进程存活，不等于所有请求有进展；unhealthy 不自动等同 Docker 重启。

## D07. F07：Outbox 提交后发布与游标

### D07.1 数据模型

|表/字段|类型与约束|用途|
|---|---|---|
|`outbox.publication_seq`（新增）|BIGINT NULL；非空 UNIQUE 索引|持久发布顺序；与原 id 分离|
|`outbox.published_at`（新增）|TIMESTAMPTZ NULL|实际发布事务时刻、保留窗口|
|`outbox_publication_state`（新增）|单例主键 id=1，CHECK(id=1)|发布器互斥与流状态|
|`state.epoch`|UUID NOT NULL|流版本；不是会话 epoch|
|`state.next_seq`|BIGINT NOT NULL，初始 1|事务性下个可分配序号，不用单独 nextval 当提交证明|

索引新增 `(publication_seq)`、待发布局部索引 `id WHERE publication_seq IS NULL`；最终删除 `dispatched_at` 与旧索引/ORM 字段。原 Outbox.id、account_id、event_type、payload 不变，原始业务事务不争抢发布计数锁。

### D07.2 发布算法与接口

`publication.py` 提供 `publish_committed_batch(session, limit=100) -> PublicationBatch`：

```text
BEGIN
SELECT state WHERE id=1 FOR UPDATE
SELECT committed outbox WHERE publication_seq IS NULL
    ORDER BY id FOR UPDATE LIMIT 100
assign seq = state.next_seq ... next_seq + n - 1
set published_at, advance state.next_seq
COMMIT
```

只有发布器扫描**可见已提交行**。计数行锁串行化发布事务直到 commit；事务 rollback 时计数和行同时回滚，不把空洞当已交付事实。后台旧业务事务稍后提交的小 id 行会在下一批分配更大的 publication_seq。

新增 `PublishedOutboxItem` 包含原 event_id、seq、epoch、payload。`outbox.py` 提供 `publication_head()`、`fetch_published_after(seq, account_id, limit)`、`retained_floor()`；原按业务 id 的 replay 实现移除。

`OutboxListenThread` 每次 NOTIFY/idle：先发布有限批，再由本 API 自身 cursor 排序扫描已发布事件并 fanout。限制单轮工作量，未耗尽时继续调度，不能一次 notification 永远只读 100 条。无订阅者可发布（不是消费），不向空队列 fanout；新订阅通过 durable replay 补齐。

每个 API 进程独立维护 fanout cursor，其他 API 发布/已广播不影响本进程；不得继续全局 mark_dispatched。丢 NOTIFY 时 idle 恢复扫描，NOTIFY 只是唤醒，不是唯一事件来源。

### D07.3 SSE 协议与前端

游标字符串：`v2:<epoch UUID>:<decimal seq>`。`Last-Event-ID` 优先于 after；after 改为 string。解析器拒绝负数、溢出、非规范 UUID/seq，不从客户端游标直接构造 SQL。

|游标情况|行为|
|---|---|
|无游标|先订阅、捕获当前发布 head，发送携该 head 的 resync hint；客户端刷新权威查询后，从 head 之后持续增量，不盲目回放全部历史|
|同 epoch、保留范围内|严格按 seq 升序回放，在线队列去重同一 seq|
|旧整数、格式错误、epoch 不同|一个 `client.resync_hint`，携新 head，切到新协议；不进入旧回放实现|
|seq 超过 head 或低于保留 floor|显式 resync，不静默返回空结果冒充已补齐|
|队列满|发送 resync hint 后关闭慢流；重连以新协议恢复|

重连回放上限沿用 500；发布范围内超过 500 条时发送 resync hint，不能截断后把游标直接推进到 head。订阅先于捕获 head，缓冲队列中 seq≤已回放游标的事件丢弃，较大 seq 保留；避免 replay 与实时监听之间出现空窗。

`api/sse.py` 的 `_ReplayPlan`、format、BoundedSet 全部使用发布 cursor；前端 `sseStream.ts` 只原样保存/发送 opaque ID，不数值解析。`useMailCoreRealtime.ts` 对 resync 刷新 accounts/groups/layout、列表、统计和详情，仍通过读状态变更期间的延后失效机制，不破坏乐观更新。

多个连接重复事件允许；丢失有效事件不允许。账号过滤仍包含 account_id=NULL 的全局事件，不能因某个账号没有序号就误判断全局发布缺口。

### D07.4 两个 commit 的迁移边界

1. C01 迁移 A 添加列、状态表和索引；旧代码继续使用原字段，新的 publication 模块可独立测试但不切流。
2. C02 迁移 B 与完整运行协议切换同 commit。停止旧 writer/API，结束未决事务后升级；保留窗口内历史行按可见顺序背填，生成新 epoch，删除旧全局消费列。大表背填与索引创建需在测试规模测量，超出维护窗时先设计分批迁移，不在 Alembic 中做不受限内存加载。
3. downgrade 必须停止新进程，重建旧字段并使客户端 resync；邮件/正文/附件不得因 SSE 降级删除。旧事件无法恢复旧连接已知进度，应写清重新全量失效的恢复语义。

### 测试改造

- 新增 `tests/mail_core/test_outbox_publication_order.py`：乱序提交、计数回滚、两个发布进程、发布器 kill、LIMIT 多批、没有订阅者后重放。
- `test_sse_outbox.py`、`test_sse_medium_remaining.py`、`test_sse_session_revocation.py`：整体迁移到新 opaque cursor 契约；保留 Session 撤销、连接上限、账号过滤、断开清理和队列溢出断言。
- `test_dispatcher_nonblocking.py`、`test_outbox_listen.py`：不再断言全球 dispatched 标记；分别验证发布进度和每 API fanout。原“不对无 subscriber fanout”仍有效，不能为迁移删除。
- `test_migration_validation.py`：A/B 升降级、旧行背填、唯一 head、ORM drift=0、业务数据不变。
- 前端 `sseStream.test.ts` 验证 opaque ID 往返；`useMailCoreRealtime.test.ts` 验证 resync 所有缓存且本地读意图不被早刷新覆盖。
- 真实双 API + PG + 双页面：先较大业务 id 发布、后较小业务 id 提交，两页均收到两次变化；断连重放同样成立。

## D08. F08：按需正文同步幂等

### 应用结果与 HTTP DTO

在 `message_details.py` 定义 `BodySyncResult(message_id, status, job_id=None)`；保留异常用于不存在/不可寻址/状态缺失，移除“已完成即错误”的语义。

```text
BodySyncOut:
  message_id: UUID
  status: queued | in_progress | complete
  job_id: UUID | null
```

|归档状态|操作|HTTP/结果|
|---|---|---|
|ARCHIVE_COMPLETE|不重置状态、不建任务|200 complete/null|
|ARCHIVE_IN_PROGRESS|保留 claim；返回真实处理状态|202 in_progress；只有找到真实关联任务才给 job_id|
|METADATA_SYNCED/PENDING|锁行后提升按需优先级，调用 F03 去重|202 queued/真实 job_id|
|FAILED/PAUSED_QUOTA|按既有显式重试 FSM 转 PENDING，清理可重试错误|202 queued；quota 仍可能由 Worker 再次暂停|
|消息不存在/不可寻址/状态缺失|按现有类别失败|404/409；不与 complete 混用|

锁顺序统一 Message → MessageArchiveState → WorkerJob，Worker 归档提交也用相同顺序，避免新 API 锁与 Worker 反序。锁住后重读实际状态，检查解析错误/合法空正文规则保留。

F08 保留当时既有按需优先级0；F10 C03 统一迁移为 JobPriority 按需10。对应测试分别证明“按需高于例行归档”与最终集中常量，避免两个包各自写不同数值。

`api/mail.py` 以 Response 设置 200/202，两个成功码声明同一结果 DTO；`schemaTypes.ts`/`mailCore.ts` 改用新结果，生成 OpenAPI 与 TS。`MessageBodyAlreadyArchived` 无调用点后删除，不保留字符串匹配兼容分支。

### 阅读器状态处理

`handleSyncBody` 捕获 message_id、selectedKey 与本地 request generation；await 后仅当仍是同一选择/代次时更新局部状态。queued/in_progress/complete 都 invalidate 当前 detail；complete 不设置 syncError。详情返回归档完成且空 body 时显示合法空邮件，不再自动重入排队。

SSE/详情回取可以先于 POST 返回，后到的 queued 不覆盖已完成详情；局部 submitting 与权威 archive_state 分开。真正网络错误显示重试，用户切换消息后清理，但旧请求不得把新消息标为失败。

### 测试改造

- `test_on_demand_body_sync.py` 新建 complete 幂等用例，不修改原 409 断言为 200 就结束；旧契约用例整体替换并写明废弃原因。
- 真实两 Session 控制 GET 未完成 → Worker 完成 → POST；同时两 POST 仅一个有效排队；processing 不清 claim；状态缺失仍失败。
- `MessageReader.test.tsx` 使用 deferred Promise：A→B 切换、SSE 提前完成、POST 迟到、complete 空正文、真正失败重试。断言具体正文/反馈，不只断言 invalidate 被调用。
- full-stack E2E 在 Worker 归档完成边界点击消息，无整页刷新出现正文，避免 fake 409 隐藏后端缺陷。

## D09. F09：设置布局、OAuth 返回、modal 复制

### 布局与返回

`SettingsModal.tsx` 删除 `.settings-page-head` 和“返回邮件”；ST01 按钮移动至 `.settings-nav` 顶部。桌面导航列内显示，移动端与分类一起合理排列；主 App 的 macOS 标题拖动区保持 no-drag 按钮边界。返回邮件依靠主侧栏导航及已存在关闭设置行为，不新增第二条冗余通栏。

`uiReference.ts` 将已删除 ST02/ST03 标记为 retired，不复用其编号。删除只因本次变更失效的 imports、样式和组件断言，不清理其他死代码。

OAuth 返回改为一个显式回调 `completeSessionCheck(authenticated)` / `handleLoginSuccess()`：在 Promise/登录事件中确认认证后读取并消费 hash，设置 `oauthReturnPending` 并打开设置，再 replaceState 清 hash。注册 hashchange 时由事件处理消费；不在 render 中写 store/history，也不再由 effect 同步 setState。StrictMode 的过期会话请求受已有取消/代次检查约束，返回标记只消费一次。

### modal 复制具体实现

`clipboard.ts` 增加私有 `copyHost()`：优先当前 activeElement 所属活动 modal，其次 `document.querySelector('dialog:modal')`，否则 body。保存 activeElement、DOM Range 和可选 input/textarea 的 selectionStart/End/Direction。

临时 textarea 添加到 host，设为只读且不可见但可选中；focus/select 后调用真实 execCommand。finally 无条件移除；原控件仍连接且非 inert 时恢复焦点和选区。回退失败返回原 async Clipboard 错误或明确失败，不吞掉。

先做真实浏览器验证：此前只观察到 focus 失败，未证明原生命令最终结果。若真实复制内容已正确，仍分析焦点恢复副作用，但不为了凑修复提交而强改正确路径。

### 测试改造

- `SettingsModal.test.tsx`、`settings_redesign.test.tsx`：无旧通栏/返回按钮，侧栏按钮可用且 aria-expanded 正确；不再查找已退休编号。
- `app.test.tsx`、`provider_account_form.test.tsx`：首次会话检查、登录回调、hashchange、重复回调、失败后重试，打开设置一次且没有同步 effect lint。
- `clipboard.test.ts`：临时节点清理、焦点和 input 选区恢复、API 缺失/拒绝、execCommand 异常，jsdom 仅覆盖可模拟部分。
- 新增 `tests/e2e/native_dialog_clipboard.spec.ts`（拟新增）：隔离浏览器上下文/剪贴板，禁用现代 Clipboard API，真实点击对话框内复制再粘贴核对文本；覆盖回调地址和设备码。Electron 顶层复制通过，邮件 iframe 仍拒绝。

## D10. F10：同步 API、数据模型和调度

### D10.1 最终 API 形状

新增 `POST /api/mail/sync/delta`、`GET /api/mail/sync/requests/{request_id}`、`GET /api/mail/sync/requests?state=active` 和 `POST /api/mail/sync/activity`。已有 `POST /api/accounts/{account_id}/sync`、`POST /api/accounts/sync-all` 改为明确 full 服务，返回同一 `SyncRequestOut`，客户端同 commit 更新，不保留旧 job_id/job_ids 响应兼容层，不再由列表调用。

新路由沿用现有 session、CSRF 与 scope 授权边界，不增加匿名入口。active 查询最多返回最近 50 个未终结请求，按当前 scope 过滤；详情不存在返回404。activity 使用相同 scope 解析，只更新服务端活动表并返回204，不创建 SyncRequest，也不额外触发一次 delta。

delta 输入使用现有互斥 scope 语义：

```json
{
  "account_id": null,
  "group_id": null,
  "folder_id": null,
  "folder_role": "inbox",
  "trigger": "manual",
  "client_request_id": "客户端本次操作UUID"
}
```

trigger 枚举 manual/focus/navigation；只允许 group 与 account/folder 互斥，folder 与 account 一起时校验所属关系。无 ID 表示全局启用账号；空组返回 complete/零目标，不退化为全账号。full 服务复用组织范围校验，但操作固定 full，不接收前端任意 job_type/priority。

接收返回 HTTP 202 `SyncRequestOut`；零目标可直接 200。请求状态由 GET 返回，客户端的 `client_request_id` 在实例内唯一去重，重试 POST 不创建重复请求；它不是鉴权凭据。

```text
SyncRequestOut:
  id, mode(delta|full), trigger, state(queued|running|complete|failed)
  target_count, queued_count, running_count, completed_count, failed_count
  created_at, finished_at, errors[{target_id, code, safe_message}]
```

禁用账号显式请求返回409 account_disabled，未知 scope 返回404，不可选择目录返回422 folder_not_selectable；自动范围解析直接排除禁用和 Noselect。基线缺失时关联已存在初始化 full 作业，目标保持 queued/running 并标明 initializing；不存在该初始化作业则返回409 baseline_required。列表入口不自行创建重型 full，也不把缺基线目标直接计为完成。

### D10.2 持久模型与不变量

|拟新增模型|核心字段/约束|
|---|---|
|`SyncRequest`|UUID PK；client_request_id UNIQUE；mode/trigger/state；scope JSON（仅非秘密 ID）；created_at/finished_at|
|`SyncRequestTarget`|UUID PK；request_id FK CASCADE；account_id 可空 FK SET NULL；folder_id 可空 FK SET NULL；current_job_id FK SET NULL；target_key NOT NULL；requested_generation UUID；state/error_code/safe_error；UNIQUE(request_id, target_key)|
|`AccountSyncActivity`|account_id PK FK CASCADE；last_foreground_at、expires_at；不保存浏览器历史或明文凭据|
|`MessageArchiveState.claim_revision`|BIGINT NOT NULL DEFAULT 0；单调递增，另见 D10.4|

target_key 固定为 `account:<UUID>:folder:<UUID|all>:role:<role|all>`，接受请求后不再修改，不用含 null 的 UNIQUE 语义赌重复。一个逻辑目标表示一个账号的指定目录或目录集合，集合内所有阶段完成才结束该目标。mode/trigger/state 用 CHECK 限定枚举；新增 request(state, created_at)、target(account_id, state)、target(current_job_id)、activity(expires_at) 索引。

请求计数在查询时聚合 targets，避免两个 Worker 对持久汇总计数 lost update；终态在短锁事务下确认所有目标结束：全部成功为 complete，任一失败且已无运行目标为 failed。generation 是每次实际逻辑执行的 UUID；PENDING 合并复用该代，CLAIMED 后新请求分配后继代，不用 poll_round 代替执行身份。

账号/文件夹删除事务先按既定锁序将仍活跃的相关 target 标 failed，error_code 分别为 account_deleted/folder_deleted，再删除对象；FK SET NULL 保留结果，target_key 保留原非秘密 UUID。删除应用入口与后台失联检测共用该规则，防御性巡检将 FK 已为空且仍活跃的 target 收敛为同类失败。请求自身到期删除才 CASCADE 清理 targets，不能因账号删除丢掉错误结果并误报零目标成功。

删除路径不得先锁 Account/Folder 再等待 Target：先无锁解析候选 UUID，再依次锁 Target → Request → 待删除实体并重新验证；不在该事务反向等待 WorkerJob。创建路径也不得持 Account 更新锁等待 enqueue。针对删除与请求创建/完成交错增加真实 PG barrier 回归；死锁重试不能代替锁序设计。

任务输入携当前 `request_target_ids` 与 generation；claimed 命中产生后继时关联后继代次。某个旧执行完成只能结束它确实处理的目标，不能把还在 `_queue_next` 的请求提前标 complete。Worker failure/defer/reclaim 全部走统一目标更新入口。

请求记录推荐保留 7 天，已终结记录按 request/targets 同事务分批删除；activity 过期可清理。前台刷新用已知 request ID 和服务端当前未完成请求查询恢复，不把服务端运行状态持久化为 localStorage boolean。

### D10.3 全量与增量应用服务

新增 `sync_requests.py` 提供：

- `resolve_sync_scope(session, input) -> resolved targets`：复用 enabled_account_ids 与 Folder selectable 判断，固定接受时目标集合。
- `create_delta_request`：使用 client_request_id UNIQUE + savepoint 处理并发创建，唯一冲突后读取已提交请求；不存在的行不靠 SELECT FOR UPDATE 充当锁。相同 ID、不同规范 scope/mode/trigger 返回409 idempotency_conflict。建立 request/targets 后经 F03 enqueue 关联真实执行；账号/目录分批，单次事务不加载所有邮件。
- `create_full_request`：生成全量扫描 generation，文件夹发现/metadata/reconcile 共用该次请求 ID，不能目录发现一完成就把 full 请求标完成。
- `record_target_started/finished/deferred`：调用顺序 Job → Target UUID 升序 → Request；网络期间不持这些锁。

一次接收固定全部目标 ID，以分块 SQL 批量建立 targets/入队，但整个接收操作单事务提交，避免 Worker 在仅建立一半目标时误判请求完成。分块只限制 SQL 参数/内存，不制造可见的半请求；千账号接收事务耗时与锁等待纳入规模验收。

full 扫描在合法租约下重置 provider scan cursor、`full_scan_complete=False`，保留 Message 与本地意图。目录全扫描成功才允许 reconcile；异常/限流不能把半扫描当“远端已删”。同一账号已有 full 运行时复用其 generation/后继，不清空另一个 Worker 的有效 cursor。

### D10.4 归档所有权解耦

`claim_archive_batch` 改返回 `ArchiveClaim(message_id, owner, revision, remote_id_snapshot)`，每次领取使 claim_revision+1；reclaim 先递增 revision 再撤销 owner。为长 MIME 读取续 MessageArchiveState claim 心跳，不再 renew 扫描 AccountSyncLease。

`run_archive_batch` 删除其围绕网络阶段的扫描账号 acquire/assert/release 路径，替换成：

```text
短事务：锁 Message → ArchiveState，合法 FSM 认领并记录 revision
提交 → 获 provider permit → 拉 MIME / 关闭或复用连接
短事务：同序锁 Message → ArchiveState
        比对 owner/revision/state/remote_id_snapshot
        → 配额/digest 锁 → Blob/附件/正文发布 → COMPLETE + Outbox
```

验证失败时丢弃本次派生提交、释放本次 quota reservation；不删除可能已被其他消息引用的 Blob。Message 已删除、remote_id 已变化、状态已被新 claim 接管，都不能让旧 Worker 提交。保持 `apply_transition` 为 FSM 唯一入口，不能直接把非法状态强制写 complete。

例行归档每作业一封，按需仍为明确 message 目标；多账号有多个独立作业并发，同账号 metadata 可与下载网络阶段并发。网络期间不持 DB 业务事务，最后发布只短暂串行。

### D10.5 Worker 执行器与连接 permit

`worker/main.py` 将 `_tick` 的“claim 5 后串行”改为最多 4 个活跃 futures 的有界执行器：只认领空闲槽数量，不为已满执行器预领。每个 future 自己创建 Session；主线程维护所有权 token 和结果集合，进程健康由 F06 独立续期。

身份拆分：`claim_worker_id` 用于 WorkerJob.locked_by 完成检查；`execution_owner=<process id>:<job id>:<claim generation>` 用于账号/归档操作，不把同进程并发执行误认成同一租约持有者。shutdown 停止 claim，等待有界预算，未完成作业保留可回收状态，不强杀 Python 线程造成半提交。

`connection_slots.py`：固定 8 个跨进程 session advisory lock key，命名空间固定且不含秘密。metadata/用户按需可尝试 0–7；background archive 仅尝试 2–7，保留 2 个给前台/metadata。专用 psycopg 控制连接 autocommit，try-lock 失败立即抛 `ProviderCapacityUnavailable`，不在持业务行锁时等待。

permit 在实际 HTTP 请求或 IMAP session 打开前取得、关闭后 finally 释放：

- IMAP `_connect` 获取，logout/异常关闭释放；复用会话仍计一个连接。
- Gmail/Graph `urllib_json_request` 的每次真实连接计入，包括内部并行 hydration；不能只给外层 provider 一个 permit。
- token refresh 与后续 API 分别取得/释放，不在同一线程已占 permit 时递归等待第二个；容量不足应退出凭据事务、延后 job，不算永久认证失败。
- `ProviderCapacityUnavailable` 在 Worker、remote push、archive、delta 分别显式处理：不增加业务 failure_attempts/retry_count、不推进 checkpoint、不把 remote op 误标终态；按合法短延迟继续。
- 控制连接丢失时停止新外联、取消/关闭对应 socket，并在退出前清理租约。严格峰值上限的故障态验证必须覆盖 DB 断连，不以 advisory lock 自动释放代替外部连接已经关闭的证明。

调度常量集中定义 JobPriority，覆盖所有入队点：按需 10、delta 20、写回 40、初始化 50、例行 archive 80、reconcile 90。旧 pending 作业按类型与是否含 message_id 一次性重分类；不能把全部 archive 都提升成按需。

为了可测的后台进度，在没有更高优、已经到期的按需作业时，为持续积压的 archive/reconcile 提供有界等待预算：维护计时/年龄，最多每 10 次常规 delta 准入允许一个已老化后台作业使用空闲后台槽；不抢保留的 metadata 连接槽，不忽略 provider not_before。具体预算首次压力测试确认后写入常量和文档，不做无依据动态调参框架。

### D10.6 活跃轮询与前端状态

服务端参数初值：hot interval=8 秒、cold=30 秒、自动事件冷却=12 秒、activity TTL=45 秒、visible activity heartbeat=20 秒、全局自动 top hot=3。12秒冷却只约束 focus/navigation 请求，不约束 Worker 的8秒周期轮询；二者通过 F03 合并在途请求，不能把 hot 周期意外延长到12秒。后端用 DB 时间判断跨进程 cooldown；前端 cooldown 只是降噪，不能作为唯一限流。

`use_scope_sync.ts` 接收 `SyncScope`、enabled、visible。监听 focus/visibility/navigation：页面 visible 且 scope 改变/恢复时自动请求；每 20 秒续活动但不每次活动上报都额外发 delta；离开/隐藏停止续期。StrictMode 重挂或多个 Tab 不能绕过后端 cooldown。

手动按钮跳过自动 cooldown，但复用 client_request_id 和服务端在途/冷却规则。全局 manual 可分批覆盖全范围；全局自动只选最近 3 个热账号；单账号显式操作不串组。

React Query key 新增 `['sync-request', requestId]`，SSE 的请求状态事件仅 invalidate 相应 ID；SSE 不可用时 queued/running 期间最多每 2 秒查询一次，可见性隐藏暂停，终态立即停止。重新显示先取权威结果，不无限维持本地 spin。

MessageList 只调用 delta，queued/running 旋转并禁掉重复同请求提交；complete 停转，failed 停转且显示错误。设置页单账号/全账号调用 full，tooltip 明确重扫，保留失败明细与重试；移除 list-note 成功横条而非删除错误提示。

### D10.7 测试改造

|层|具体测试与断言|
|---|---|
|API/PG|拟新增 `test_sync_requests.py`：幂等 client_request_id、组/账号/精确目录隔离、空组、未知组、禁用/Noselect、基线缺失、target 延后/失败/删除后的终态|
|任务/请求|`test_sync_retry_queue.py`：claimed 后继的 request_target_ids 不丢、旧执行不提前完成新请求；provider_backoff 仍有效|
|full|`test_sync_engine_failure_unit.py` 加真实 PG 场景：游标重新扫描、失败不 reconcile、完成只在所有阶段闭环后置位|
|archive|`test_archive_scheduler.py`、`test_archive_state_machine.py`、`test_worker_process_recovery.py`：revision 抢占、迟到回写拒绝、同账号慢归档不挡 metadata、配额/GC 安全|
|连接/多进程|拟新增 `test_provider_connection_slots.py`：真实 PG + 本地计数服务器，两个 Worker/Gmail 并发真实连接峰值≤8，archive≤6，保留槽可用于 delta；DB 断连/进程 kill 后资源收敛|
|Worker|`test_worker_loop.py`：活跃 futures≤4，不预领，任务 Session 不共享，execution_owner 不重入，停机没有重复完成|
|前端组件|MessageList/SettingsModal/useMailCoreRealtime 测试：202 不停转、终态停转、SSE 断连查询恢复、错误显示、成功横条消失、自动触发12秒去重|
|真实全栈|新增 sync 场景并显式加入 runner：真实 IMAP 新邮件、后台归档积压、focus/切账号、全局 manual 与自动 top3；记录五段耗时，不能只观测 API enqueue|
|规模|1000 账号夹具、不发真实公网请求：全局自动最多3目标、队列去重、不一次开启1000连接、冷账号/后台最终推进|

时间类测试大部分使用可控时钟，但连接/进程/PG 竞争必须有真实系统证据。延迟门槛采用本地 fixture 正常 RTT 场景：自动检测≤hot 间隔+允许调度余量，主动触发在可用槽后不等待冷轮询；真实公网 RTT/429 单列，不能把其不可控耗时包装成必达 SLA。

## D11. F11：生产浮层与快捷键

`App.tsx` 直接声明 lazy UiReferenceOverlay，不再用 DEV 条件删组件；挂载是否启用读取本地偏好。不得将浮层代码注入邮件 srcdoc。

新增偏好：`uiReferenceEnabled: boolean=true`、`uiReferenceShortcut: Shortcut|null`，null 表示平台默认。`Shortcut` 为 code 与 ctrl/meta/shift/alt 四个 boolean，不保存可执行字符串。

`ui_shortcut.ts` 提供 `parseShortcut`、`formatShortcut`、`matchesShortcut`、`validateShortcut`。默认 macOS Meta+Shift+Period，其他 Ctrl+Shift+Period；自定义要求合法非修饰 code 和明确修饰组合，拒绝 Escape、仅修饰键、保留浏览器/系统组合。匹配要求全部 modifier 精确相等，忽略 repeat/composing；录入模式捕获按键、不触发旧浮层。

`mailStore.ts` 在 partialize 增加两个字段，读取旧存储保留已有 theme/width/icon/展开偏好；对损坏 shortcut 单独回退默认，不能因新增版本重置整份用户偏好。若 bump persist version，migrate 保留全部已有合法字段并增加回归。

`SettingsModal.tsx` 通用区域增加启用开关、当前快捷键、录入/取消/恢复默认及错误反馈；不要求服务端设置接口，切换即时生效。Escape 退出浮层时阻断级联关闭设置/抽屉。

### 测试改造

- `uiReference.test.ts` / 拟新增 `ui_shortcut.test.ts`：平台默认、精确 modifier、code、输入法、repeat、非法/损坏配置。
- store 测试：旧偏好迁移不丢 theme/尺寸/展开；新增字段刷新持久化。
- `UiReferenceOverlay.test.tsx`：录入时不触发、禁用不触发、Escape 不级联、复制仍用统一 helper。
- `SettingsModal.test.tsx`：配置读取、错误组合、取消录入、恢复默认、启用/关闭。
- 新增 `tests/e2e/ui_reference_production.spec.ts`（拟新增），从生产 Vite preview 经 App 打开，验证自定义及刷新后仍可用，不能仅 mount 单个组件。

## D12. 迁移、测试入口和文档改造总表

### D12.1 数据迁移顺序

|顺序|负责 commit|内容|升级/回退验证|
|---|---|---|---|
|M1|F07 C01|Outbox 发布字段、状态表和索引|旧 runtime 仍可运行；历史行保留，ORM drift=0|
|M2|F07 C02|历史发布背填/epoch，移除旧全局消费字段|停旧进程切新协议；downgrade 触发客户端全量 resync，邮件不变|
|M3|F10 C01|SyncRequest、Target、Activity 模型|空表升级、级联/终态/唯一约束、请求状态恢复|
|M4|F10 C02|ArchiveState claim_revision|旧 claim 在停机后受控重置/回收，新 claim fencing；原 MIME/附件不变|

实际 revision 在前置迁移合入后按唯一 head 分配，不能把 M1 等当 Alembic ID。F03 JSON 转换是一次性数据维护，不抢上述 schema head；F02 新 manifest 与旧包读取矩阵单独验证。

每次迁移前有可恢复备份；先在临时库重放旧数据升级/降级/再升级。发布时停止旧 Worker/API，不能靠兼容分支维持旧新协议混跑。本计划不授权真正执行生产迁移。

### D12.2 测试入口必须接入

1. Python 新文件在 `tests/mail_core/` 自动收集，使用现有隔离 fixture 与运行器；不另开绕过 guard 的数据库 URL。
2. 新 Playwright 文件不会自动进入当前默认 `run_e2e.mjs` 的三个目标。F09/F11 将 native_dialog_clipboard、ui_reference_production 场景加入明确 runner 目标；F10 新同步场景接入 full-stack 控制器及相应测试选择。
3. 新单元测试能通过不代表实际 runner 选择了它：交付记录保存 collected 数和 nodeid；出现 0 selected 即门禁失败。
4. CI Python3.13/Node22 与本机 Python3.14/Node24 分开记录；依赖从既有 lock 安装，不在修复中顺手升级。
5. 原始 `.scratch` 诊断探针不移入正式测试原样断言缺陷存在；按本设计目标写新的生产回归，记录红→绿。

### D12.3 旧测试的具体处置

|旧用例/文件|保留部分|需要整体替换/新增的契约|
|---|---|---|
|`test_dispatcher_nonblocking.py` 的 LISTEN/无订阅者用例|非阻塞和无 subscriber 不 fanout|两个监听通道；发布与广播不再共用 dispatched 标记|
|`test_outbox_listen.py`|真实 PG NOTIFY/rollback|先注册 subscriber，再验证本进程发布序列；无 subscriber 另测只发布不广播|
|`test_imap_remote_id.py`|目录转义/命令精确值|COPYUID 替身返回协议二元组；新增真实 Trash 目的地|
|`test_imap_provider_live.py`|真实 LIST/FETCH|只在隔离 fixture 配置允许私网；生产拒绝测试独立保留|
|`test_medium_providers_sync_blobs.py` 的 status 用例|成功/失败状态持久化|安全摘要不再要求原始错误文本；新测试验证不泄漏|
|`test_sync_hardening_a27_a28_a29.py`|敏感错误不落库|新 successor 载荷是错误 detail 的正确载体，不原地接受 None|
|`test_start_mail_core_imap.py`|0600 passfile、不放 argv、清理|标准环境复跑；本机 rm shim 冲突仍记环境问题，不改保护器|
|`test_on_demand_body_sync.py`|只入队、不在 API 拉取；错误类别|完成状态不再409，整体替换旧冲突用例并增加真实并发|
|archive account-fencing 相关旧用例|迟到 Worker 不得发布、进程重领|由 archive claim_revision 保证，新增同账号 metadata 不被下载租约占用|
|现有侧栏几何/设置/浮层测试|稳定编号、键盘、非邮件沙箱边界|仅更新已改契约，保留未变部分；新生产入口用真实构建验证|

### D12.4 文档具体改什么

执行时由 I 在 F12 统一更新，下表是明确修改清单，不在实施分支同时抢写。各作者在本包 delivery 记录提供已验证的新行为和证据，由 I 核对后写当前文档。

|文档|具体修改内容|来源|
|---|---|---|
|[docs/blueprint/architecture.md](../../blueprint/architecture.md)|Outbox 业务 ID/发布 seq 分离、每 API 广播游标；Worker 4槽/全局8连接与保留槽；archive claim 与扫描租约分工；正文幂等结果；请求/目标/活动生命周期|F03/F06/F07/F08/F10|
|[docs/blueprint/conventions.md](../../blueprint/conventions.md)|原子后继字段/事务规则；日志异常链策略；多位置统计与位置删除事件；按需10/delta20/写回40/初始化50/archive80/reconcile90；搜索关闭/24px槽位；生产浮层/快捷键；ST编号退休|F01/F03/F04/F05/F09/F10/F11|
|[docs/blueprint/decisions.md](../../blueprint/decisions.md)|追加发布序号、归档所有权、连接准入、恢复身份依据的取舍；明确取代旧“归档优先于轮询”与旧游标假设；决策仍标拟实施直到执行获授权并验证|F02/F07/F10|
|[docs/blueprint/testing.md](../../blueprint/testing.md)|新 PG 并发/迁移/真实连接峰值、modal剪贴板、生产浮层与同步时延场景入口；更新新测试收集要求；只用本批最新证据更新当前计数|所有包|
|[docs/guides/security.md](../../guides/security.md)|provider 原始 body/traceback 策略；恢复路径与源身份；保持 UUID capability 和现有公开健康路由描述，不处理 P2-05|F01/F02|
|[docs/guides/upgrade.md](../../guides/upgrade.md)|空库/空目录恢复，在线源与认证 manifest 离线源的前置；权限与目标独占；DB成功/Blob发布失败的部分成功处置；SSE/归档切换停机和回退|F02/F07/F10|
|[docs/guides/deployment.md](../../guides/deployment.md)|进程心跳与任务心跳区别、额外 permit 控制连接容量、固定调度参数、旧进程停止；不修桌面CI资产问题|F06/F10|
|[docs/guides/troubleshooting.md](../../guides/troubleshooting.md)|新邮件五段时延排查、queued/running/failed请求判断、provider限流与本地容量不足区别、正文完成不再报冲突、恢复身份权限错误|F02/F08/F10|
|[src/mail_core/README.md](../../../src/mail_core/README.md)|新增 publication/sync_requests/connection_slots 的分层职责，禁止网络期持业务事务|F07/F10|
|[src/frontend/README.md](../../../src/frontend/README.md)、[ARCHITECTURE.md](../../../src/frontend/ARCHITECTURE.md)|统一同步 hook、request query key、opaque SSE游标、本地快捷键偏好及生产浮层入口|F07/F10/F11|
|[docs/specs/mail_sync_and_storage.md](../../specs/mail_sync_and_storage.md)|同步场景、幂等正文、请求终态、连接上限、归档所有权、多位置统计、真实恢复验收；删除已被替代的旧优先级语义|F02/F03/F05/F07/F08/F10|
|[docs/specs/inbox_ui_and_search.md](../../specs/inbox_ui_and_search.md)|侧栏搜索关闭、树顺序/缩进、设置布局、增量按钮/全量设置、旋转状态、生产浮层与快捷键行为AC|F04/F09/F10/F11|
|[docs/specs/testing_quality.md](../../specs/testing_quality.md)|真实多进程/协议/浏览器回归及明确跳过语义，不把旧报告计数抄成当前基线|F12|
|`schemas/openapi.json`、`src/frontend/src/api/generated/schema.ts`|由对应 API 源码生成；F07/F08/F10 各 commit 保持自身一致，合入后再统一生成|F00/F07/F08/F10/F12|
|本目录未来 `repair_results.md`|22来源→commit→测试nodeid→实际结果；单列排除项、未验证平台和环境干扰|F12|

既有需求级 spec 按本批用户明确执行授权同步最终生效行为，不创建 task/spec 工作区，也不伪造任务状态。新增模型/游标契约不需要给用户展示内部字段；指南只写用户操作所需内容。

### D12.5 生成、格式与提交要求

每个 API commit 从自身源码执行现有 `scripts/export_openapi.py` 与 frontend `openapi:gen`；生成物和源码同 commit，检查 live schema/TS一致。I 合并后从组合源码重生成，不手工解决生成 TS 的冲突。

文档只格式化点名文件；使用 `.repo_template/scripts/md_format.py`，不全仓格式化。交付记录列生产文件、测试文件、迁移、生成物、文档五类 diff，逐条映射来源；发现无关代码即停止该 commit。

本文件没有声称新增 API、模型、测试或参数已实现。后续执行若证明某个设计不成立，应先写清反例、调整本技术设计与对应 commit 边界，再继续实施，不能静默替换为减少断言、增加重试窗口或关闭安全门禁的方案。
