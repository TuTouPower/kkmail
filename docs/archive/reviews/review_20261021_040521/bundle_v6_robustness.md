> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — 视角 6：健壮性与可观测性

- Target：当前整个仓库，非 diff；主 bundle 为 168 files / 23508 lines。
- HEAD：`daca631aec54c30ce02cdb5e6499ae196dc3a72d`。
- 审查方式：独立阅读生产调用链、关联测试与规范；未阅读其他视角报告，未修改源代码，未运行完整测试或构建。
- Findings：Critical / High / Medium / Low / Info = 0 / 16 / 3 / 0 / 1。
- Verdict：REQUEST CHANGES。

## High

- [High][98] mail_core/sync/remote_push.py:58 L58-L68 — **R01：出站队列只有一次性唤醒，限批、处理中新增操作及崩溃恢复都能永久遗留操作**。
    证据：`select(...status == PENDING).limit(limit)` 默认 `limit=20`；函数末尾直接返回，`worker/handlers.py:74-77` 随即完成唯一 push job。`mutations.py:62-70` 的唤醒按账号去重，`jobs.py:58-67` 连 CLAIMED job 也复用。触发一：首次批量标记超过 20 封，只推前 20 封；触发二：batch 快照之后创建操作，唤醒被当前 CLAIMED job 吞掉；触发三：worker 崩溃后 5 分钟回收 job，但 remote op 15 分钟才可回收，此次 push 为空后 job DONE，15 分钟之后没有调用者再次回收。实际影响：本地操作已成功，远端永久未写入，必须依赖后续人工动作偶然唤醒。修复：完成 job 前，在同一账号排他事务中检查残留 PENDING/IN_PROGRESS 并安排下一次执行；CLAIMED 去重需记录 dirty/后继唤醒，不能直接吞掉；将 stale remote op 回收纳入定时维护并创建对应 push job。规范：架构 §9 local-first desired-state 最终收敛、skill §3 视角 6 重试/幂等。

- [High][100] mail_core/sync/remote_push.py:67 L67-L69、L93-L118、L132-L136 — **R02：读取批次时复制 desired_state，之后合并的新期望会被旧快照完成掉**。
    证据片段：`work = [(op.id, op.op_type, dict(op.desired_state or {})) ...]`；实际发送使用 `provider.apply_remote_operation(op_type, desired)`。发起网络操作前只复查 `op.status == PENDING`，未重新读取 payload 或比较版本；网络结束后无条件 DONE。`remote_ops.py:25-29` 可在此期间更新同一 row 的 desired_state，甚至把 IN_PROGRESS 改回 PENDING。无副作用探针执行原函数 AST：批次快照 `is_read=True` 后模拟 API 合并 `False`，provider 收到 `True`，最终数据库对象 `desired_state=False,status=done`，返回 `pushed=1`。修复：认领时锁定 row、捕获 revision 和最新 payload；完成时用 `WHERE id=:id AND revision=:claimed_revision AND status='in_progress'` 做 CAS。新 revision 保留为待推任务，不能被旧结果标 DONE。规范：架构 §9 desired-state、§14.2 与最终期望一致。

- [High][99] mail_core/sync/remote_push.py:117 L117-L142 — **R03：任何瞬时提供商失败直接终结 remote operation，没有退避重试或人工恢复入口**。
    证据：网络异常被捕获后 `ok=False`，随后 `mark_remote_operation(...FAILED)`；任务仍返回 `status='ok'` 并 DONE。全仓只有此处设置 FAILED，没有 FAILED→PENDING 的恢复调度；`reclaim_stale_in_progress` 仅处理 IN_PROGRESS。触发：HTTP 429、临时 5xx、网络中断一次即可。实际影响：已读/星标丢远端写入；删除时本地 Message 已被移除，UI 也无法重新对同 UUID 发起操作，下一轮同步可能重新出现该邮件。修复：区分可重试与永久错误，持久化 next_attempt_at，尊重 Retry-After 并按 attempts 指数退避，超过上限再隔离；提供安全的重试入口，并以远端状态核对处理结果未知的请求。规范：skill §3 视角 6 重试/幂等，架构 §14.2 第 4 点失败可重试。

- [High][98] mail_core/sync/jobs.py:59 L59-L78 — **R04：任务去重存在 SELECT→INSERT 竞态，唯一冲突会回滚邮件变更**。
    证据：先 SELECT，无结果即 `session.add(job); session.flush()`，未处理 IntegrityError；`storage/models.py:339-341` 有 active dedupe_key 部分唯一索引。同账号两条并发操作都看不到 active push job，然后其中一个 INSERT 被唯一约束拒绝。`mutations._wake_push` 与本地修改同事务，因此后一个请求连本地变更都回滚并返回 500。前端 `MessageList.tsx:113` 批量删除使用 `Promise.allSettled`，正常 UI 即可产生该并发。修复：使用 `INSERT ... ON CONFLICT DO NOTHING` 后查询胜者，或 savepoint 捕获唯一冲突后复用；不能在外层事务失败后直接查询。规范：skill §3 视角 6 幂等/竞态保护；函数自身承诺“匹配 active row 返回现有 job”。

- [High][97] mail_core/worker/handlers.py:39 L39-L42、L63-L77、L89-L90、L129-L132 — **R05：所有 handler 返回状态统一当成功，lease_busy/提供商失败/备份校验失败会丢任务**。
    证据：`result = ...; log.info(...result); complete_job(...); return True`。`engine.sync_account_folders:61-62`、`remote_push:53-54`、`reconcile:48-49`、`archive:177-178` 的 lease_busy 均无自身续调度；`reconcile:65-74` 捕获 provider 异常后返回 provider_error 也未续调度；`backup.package.run_backup:488` 可返回 verify_failed。触发：多个 worker 同账号竞争，或一次 reconcile 网络失败。实际影响：工作未执行却永久 DONE；手动同步可能没有后续文件夹发现，出站操作被遗留，失败备份被任务层记作成功。修复：定义明确任务结果类型与状态表：只有成功或已事务性安排后继任务才 DONE；lease_busy 延迟重排，provider_error 按失败重试，verify_failed 必须失败。metadata/delta 已自行重排的状态需避免二次重复调度。规范：架构 §7.5 多 worker 互斥与继续推进、skill §3 错误处理。

- [High][96] mail_core/worker/main.py:83 L83-L94；mail_core/worker/handlers.py:25 L25-L25 — **R06：一次预领 5 个 job 后无心跳，旧 worker 还能执行已被他人接管的任务并冒用新 owner**。
    证据：主循环预领 5 个 ID、提交，再串行处理；执行前只检查 `job is not None`，未校验 CLAIMED / locked_by。`jobs.reclaim_stale_claims:153-173` 在 5 分钟后回收锁；handler 把当前 row 的 `job.locked_by` 当成自身 worker_id。触发：第一个 metadata/archive/backup job 超过 5 分钟，另一 worker 回收后续等待项并 claim；旧 worker 随后读到新 owner 后执行同一任务，以新 owner 身份获取 lease、complete_job。实际影响：重复网络副作用、同 owner 重新获取 lease 导致互相踢 fencing，任务所有权检查失去意义。修复：将实际 worker_id 从 `_tick` 显式传入 handler；执行前原子校验 claim token/owner/status；按可立即执行数量领取，并为正在执行任务续期；完成/失败使用带 claim token 的条件 UPDATE。规范：架构 §7.5 层 1 避免多 worker 抢同一任务；`JobOwnershipError` 既有不变量。

- [High][99] mail_core/blobs/archive.py:333 L333-L340 — **R07：归档调度只有自我续批，没有首次启动路径，正常同步不会归档 MIME**。
    证据：全仓搜索 `ARCHIVE_MIME_BATCH` / `archive_mime_batch`，唯一生产 enqueue 位于 `run_archive_batch` 的 `if completed` 分支；其他出现仅 enum、handler、导出与测试。metadata 写入 MessageArchiveState 后，engine 同步完成只调度 reconcile/delta，不创建 archive job；worker 启动也只领取已有任务。触发：全新实例经真实 UI 创建账号并同步。实际影响：状态永远停 metadata_synced，MIME/离线存档能力不可达，单独调用 run_archive_batch 的测试掩盖该缺口。修复：metadata 首次生成可归档状态时事务性按账号去重唤醒归档，或由维护调度器按可归档状态发现工作；补充从公开同步入口到 archive_complete 的集成覆盖。规范：架构 §8.2 批量归档调度、§8.4 状态推进。

- [High][98] mail_core/blobs/archive.py:270 L270-L285、L323-L340 — **R08：归档批次全失败后永不再运行；混合成功批次又会无退避地耗尽重试**。
    证据：单条失败时设置 ARCHIVE_PENDING（retry_count\<5），但后继 job 仅在 `if completed` 中创建；handler 对 `completed=0,failed=N,status=ok` 标 DONE。stale archive reclaim 也只改状态，不唤醒调度。触发：一个批次碰到临时断网，全部下载失败一次；恢复网络后这些 pending 状态没有任务。若批次同时有成功项，后继 job 立刻重试失败项，没有 next_attempt_at 或退避，短暂故障即可迅速进入 ARCHIVE_FAILED。修复：按仍可重试/尚未处理工作决定续调度，持久化每条 next_attempt_at 与指数退避；reclaim 后创建唤醒任务。规范：架构 §8.2 明确要求可重试错误指数退避、隔离不堵队列。

- [High][99] mail_core/blobs/archive.py:131 L131-L139、L183-L205、L233-L252 — **R09：配额暂停后没有恢复机制，释放磁盘或提高配额也不会继续归档**。
    证据：中途超配额把剩余状态迁至 ARCHIVE_PAUSED_QUOTA，调度查询 `claim_archive_batch:66-71` 只收 metadata_synced/pending；全仓没有 paused_quota→pending 调用者。入口已超配额时虽未改状态，也直接结束 job 且不安排检查。触发：一次容量达到阈值后清理空间/调整配置。实际影响：暂停永久化，与“空间恢复后继续”契约相悖。修复：提供受控 resume 操作或定期配额检查，把 quota 原因暂停项转回 pending 并创建归档唤醒；恢复动作必须保持账号范围与 claim 所有权。规范：架构 §8.2、§8.4 双向状态图及 M3“硬配额暂停可恢复”。

- [High][96] mail_core/blobs/archive.py:176 L176-L180、L233-L292 — **R10：归档整批占有 120 秒 lease，却从不续约**。
    证据：run_archive_batch 导入和调用只有 acquire/assert/release，没有 heartbeat；默认串行下载 20 封，HTTP 单次可能 60 秒。触发：归档总耗时超过 120 秒，另一个同账号 delta/metadata job 获取过期 lease。旧归档在成功写 blob 后才 assert_fencing，失配直接返回，剩余整批状态仍是 IN_PROGRESS；handler 随即 DONE。实际影响：正常大邮件批次频繁中断；未持久化 blob 成为孤儿，残余消息依赖 15 分钟 reclaim，且 R08 导致没有后继任务。修复：下载期间按明确心跳间隔续租，至少每条下载前后续期；单次最大网络耗时必须低于 TTL；fence loss 时显式安排受控后继恢复。规范：架构 §7.5 短事务心跳、§8 归档进度推进。对照：metadata/delta/remote push 都已有 heartbeat。

- [High][95] mail_core/blobs/archive.py:272 L272-L283 — **R11：归档失败写回不校验 fencing 或 claimed_by，旧 worker 可撤销新 worker 的 claim**。
    证据：下载异常分支直接 `session.get(MessageArchiveState, mid)`、增加 retry_count、apply_transition、`claimed_by=None`，未检查当前 state/owner/fencing；`_pause_quota` 同样如此。触发：旧下载拖延超过 stale claim 时间，新 worker reclaim 并重新认领，此时旧下载返回异常。旧 worker 把新 worker 的 IN_PROGRESS 退回 PENDING 并清 owner；新 worker 下载成功后在 `294-295` 发现状态不符跳过。实际影响：新工作被旧结果覆盖、误累计失败次数、归档中断；若新 worker 已 COMPLETE，旧异常会制造 IllegalArchiveTransition 并失败整个批次。修复：成功、失败、quota 暂停所有状态迁移都使用 owner+claim generation 的条件更新；账号任务还必须在同事务校验 fencing，失配不写。规范：架构 §7.5“旧 worker 不得提交状态迁移”、§8.4 FSM。

- [High][90] mail_core/blobs/gc.py:126 L126-L127；mail_core/blobs/store.py:78 L78-L80 — **R12：GC 提交删除 row 后再删文件，可删掉刚被重新归档引用的同哈希 blob**。
    证据：GC `session.commit()` 后调用 `unlink_gc_paths(paths)`；BlobStore.put 对存在路径直接复用，archive 随后新建 MessageBlob+Link，没有与 GC 共用的 digest 锁/删除墓碑。可构造交错：GC 提交移除旧无引用 blob row → archive 复用仍存在的同哈希文件、提交新活引用 → GC unlink 同一路径。实际影响：活 MessageBlobLink 指向不存在文件，已归档内容无法读取；冷却期只约束旧引用归零时间，无法保护删除后重新引用。另一个后果：提交后 crash 会留下无 DB row 的孤儿文件，此后 GC 只枚举 DB，不能自动清理。修复：用持久化待删状态和每 digest 的 DB advisory lock/同等机制串行化 put+建引用与最终 unlink；删除前重新核对所有活引用与删除 generation，并使 crash 后可恢复。规范：架构 §10.2 延迟 GC、防误删；文件头宣称不会留下活 row 指向缺文件，当前交错反例违背该不变量。仅静态交错分析，未运行真实 PG 并发试验。

- [High][96] mail_core/backup/package.py:199 L199-L201、L269-L287、L483-L486 — **R13：备份复用固定目录并原地覆盖，失败会破坏上一份成功备份**。
    证据：run_backup 默认总是同一 MAIL_CORE_BACKUP_DIR；plain 模式直接让 pg_dump 写原 postgres.dump、tar 以 `w` 覆盖 blobs.tar；sealed 模式 `kkbak.write_bytes(sealed)` 原地截断原 backup.kkbak，再写 manifest。触发：第二次备份在 dump、写密文或写 manifest 阶段断电/磁盘写满；原来成功包部分被新数据覆盖，旧 manifest 与新文件不一致。实际影响：备份失败同时丢失上一份可恢复副本，worker 自动重试还会继续覆盖残留。修复：每次生成独立 staging/版本目录，完整校验、fsync 后以原子发布指针/目录替换公开；完成前保留上一成功版本。规范：skill §3 失败回滚；架构 §10.2 备份范围及恢复可靠性。

- [High][100] mail_core/backup/package.py:471 L471-L479 — **R14：备份验证接受没有数据库转储的空 manifest，并报告可用**。
    证据：`manifest.get('members') or {}` 被允许为空，`_check_plain_members` 只迭代列出的成员，最后 `ok=not errors`。无副作用探针执行原 `_verify_plain_tree`、`_check_plain_members`、checksum 辅助函数和内存 Path：只有正确 hash 的 `MANIFEST.json:{members:{}}` 与 MANIFEST.sha256，结果 `RestoreVerifyResult(ok=True,members_checked=0,errors=[])`。同样可删除 postgres.dump 的 manifest 项后让 verifier 完全不检查数据库。实际影响：不可恢复包被认作备份成功，run_backup 返回 ok。修复：严格验证 manifest schema、必需 postgres.dump 成员、非空有效 sha256/size/method，验证 PG custom dump 格式；include_blobs 应有明确必需性标记。缺必要成员必须失败，不能只校验“恰好列出的文件”。规范：模块定义“PG dump + blob tar + checksums”、测试已有 sql_stub 不可恢复约束。

- [High][99] frontend/src/api/client.ts:65 L65-L69、L154-L162、L214-L225 — **R15：HTTP 超时未覆盖 CSRF 获取和登录，首次写操作/登录可无限 pending**。
    证据：unsafe 请求先 `await fetchCsrfToken()`，之后才创建 withTimeout；CSRF 内部 fetch 和 res.json 没 signal/timeout。login 完全直接 fetch/json。触发：/api/auth/me 或 /api/auth/login 连接/响应体悬挂，用户设置 timeoutMs 也无效，csrfInflight 让全部并发写请求一起挂住。主审无副作用探针：原 client.ts 内存转译，fetch 永不完成，postJson timeoutMs=5，30ms 后仍 pending 且唯一调用是 /api/auth/me。修复：在整个请求入口建立 deadline；CSRF 单飞请求有自己的有界 timeout，等待者尊重自己的取消/deadline；login 使用同一受控 transport 并覆盖 body parse。规范：client.ts:4 唯一 transport + timeout，RequestOptions 注释承诺指定毫秒后中断。

- [High][100] desktop/startup.js:193 L193-L197 — **R16：child.killed 仅表示信号已发送，却被当成退出判据，Windows 强杀永不执行**。
    证据：softKill 在 Windows 调 `child.kill()`；hardKill 一开始 `if (child.exitCode !== null || child.killed) return`。ChildProcess.killed 在成功发送信号后就为 true，进程不一定退出，故 taskkill /T /F 分支不可达；Unix fallback child.kill 同样受影响。原模块 VM 探针使用 Windows 平台、模拟仍 `exitCode=null` 的子进程：执行 soft/hard 两阶段只记录 SIGTERM，hardKillSkipped=true。实际影响：忽略 SIGTERM 或卡住的 sidecar/后代进程可能残留，退出时后端/PG 关闭顺序也无法保障。修复：退出判据依赖 exit/close 事件及 exitCode/signalCode，不用 killed；等待有界退出后升级终止，Electron before-quit 应保持运行直到清理结束。规范：函数注释承诺 SIGTERM 后 SIGKILL/taskkill 全树升级，架构 §4.3 有序停止。

## Medium

- [Medium][97] mail_core/realtime/dispatcher.py:141 L141-L159 — **R17：多 API 进程时 outbox 事件只发给抢到 row 的本地订阅者，其余连接永久漏实时事件**。
    证据：每进程 dispatcher 有独立 `_subs`，fetch_undispatched 使用 SKIP LOCKED，投递后更新全局唯一 dispatched_at；LISTEN 通知虽广播给所有 API 进程，但只有一个进程能取得 row。空闲进程也可调用 dispatch_once 并在无订阅者时标已发。触发：uvicorn --workers 2 或多 API 副本；当前 compose 默认单 API，因此标条件性 Medium。实际影响：另一个进程上的持续 SSE 连接没有事件，也没有 gap/resync_hint；只有主动断连重放或查询刷新才恢复。修复：每 API consumer 独立持久化 cursor 并从 outbox 读取，或先统一消费再跨进程广播；若产品只支持单 API，则显式启动限制并写入部署契约。规范：架构 §13 事务 outbox + 所有客户端最终可见；dispatcher 注释声称 SKIP LOCKED 覆盖其他 API workers，说明该拓扑被考虑过。

- [Medium][100] mail_core/realtime/dispatcher.py:114 L114-L120 — **R18：全局事件在实时投递中漏掉 account 过滤订阅者，与重放行为不同**。
    证据：`targets = self._subs.get('*',[])`，仅 event.account_id 非空时追加对应账号订阅者；NULL 账号事件没有广播所有账号订阅。`outbox.fetch_since:64-69` 明确包含账号及全局事件，注释还声称 live fanout 已一致。触发：`/api/events?account_id=<uuid>` 订阅期间产生 account_id=None 事件。实际影响：全局归档配额事件等实时遗漏，重连又能回放。修复：NULL 账号事件 fanout 给所有键下订阅队列并去重；添加 live/replay 同语义测试。规范：代码显式全局事件注释、SSE endpoint:161 保留 NULL 事件规则。

- [Medium][98] mail_core/backup/package.py:168 L168-L173 — **R19：pg_dump 无总超时、连接超时及锁等待上限，可永久占住唯一 worker**。
    证据：subprocess.run 配 check/capture_output/env，没有 timeout；传入 URI 也未设置 connect_timeout，pg_dump 无 --lock-wait-timeout。触发：目标网络黑洞，或数据库存在长时间 ACCESS EXCLUSIVE 锁。实际影响：单 worker 停在备份，邮件同步/出站操作不再推进；其他 worker 在 5 分钟后 reclaim 同 job 又可启动重复 pg_dump。修复：明确总执行期限，配置连接及锁等待超时，超时后终止并回收子进程；与 R06 的 job heartbeat/ownership 配合避免重复备份。规范：skill §3 外部 I/O 超时与资源回收。

## Info / 待证伪

- [Info][25] mail_core/sync/leases.py:118 L118-L125 — **R20：fencing 读取和后续写入是否存在 TOCTOU，需要真实 SQLAlchemy/PG 验证**。
    assert_fencing 用 session.get 无 FOR UPDATE；后续 heartbeat/release 才锁 lease。若同 Session 有跨接管存活的强引用，ORM identity map 有可能保留旧 owner/token，后续 FOR UPDATE 不自动刷新对象，造成旧值通过。反证约束：assert_fencing 局部 row 在返回时释放；SQLAlchemy identity map 默认弱引用，主链也可能随后重新查询，所以不能据此断言生产漏洞。主审提示已有其他视角调查，尚未发现足够生产强引用证据。建议真实 PG 编排“旧 worker 校验→新 worker 接管→旧 worker 提交”，确认 SQL 和对象刷新语义；必要时锁定 fencing 行至写事务提交，并使用 populate_existing/条件 UPDATE。此项不计为确定 bug，不据此阻塞。

## 规范、历史与测试追溯

- 规范权威：[架构](../../archive/legacy_architecture/mail-core-architecture.md) §7.5/7.6、§8.2/8.4、§9、§10.2、§13、§14.2（原文链接为 `../../mail-core-architecture.md`，目标已迁至 `docs/archive/legacy_architecture/mail-core-architecture.md`）；项目 AGENTS.md 的凭据脱敏、事务与可恢复原则；用户明确调用的 intensive-review SKILL.md §3 视角 6。
- 原始代码固定版本：[remote_push](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/sync/remote_push.py)、[jobs](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/sync/jobs.py)、[archive](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/blobs/archive.py)、[backup](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/backup/package.py)、[desktop startup](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/desktop/startup.js)。各 finding 的片段/明确交错亦构成定位证据。
- 已核对 git log/blame：jobs dedupe 来自 21e10bda；remote push 从 f0f8a061/89d4e1ca 实现，898c5a0d 加 fencing；archive 自续调度源于 e4f9a1d3；desktop 停止逻辑来自 fcc1fcb6；GC commit→unlink 来自 1ce66644；backup validator 来自 e9003e93/7ff217ce。它们是当前 HEAD 的既存问题；本次是用户指定全库审阅，不主张为 HEAD 单次提交引入，也不做 diff 增量计分。
- 关联测试已读：test_remote_ops_reconcile.py、test_sync_high_hardening.py、test_worker_loop.py、test_jobs_backoff.py、test_archive_scheduler.py、test_medium_hardening.py、test_high_blobs_providers_metadata.py、test_backup_package.py、test_backup_verify_drill.py、desktop/startup.test.js。它们验证单次成功、隔离、reclaim 单步、checksum 等；未覆盖报告所列端到端唤醒、时间窗口和并发交错。
- 无副作用验证：R02 原函数 AST + 内存 Session/边界替身；R14 原 validator/checksum 函数 + 内存 Path；R16 原 JS 模块 VM + 模拟 ChildProcess；R15 使用主审交接的原客户端内存转译探针结果。全部未连接数据库、未发网络请求、未写业务数据。
- 验证限制：环境没有 .venv，当前 python3 未安装 sqlalchemy/cryptography/fastapi/pytest；未自行安装依赖。PG 并发、IMAP/Gmail/Graph 真实服务、Electron 全生命周期与恢复演练未运行。未把静态检视描述成完整测试通过。
- 全库范围内通过 rg 扫描错误捕获、timeout/retry、subprocess、线程/任务和资源释放路径；重点逐文件阅读 sync/worker/realtime/archive/GC/rotation/backup、HTTP 客户端、desktop 生命周期及关联 API。纯展示组件、生成 OpenAPI DTO、迁移等只做与错误路径相关的检索，未宣称逐行完成其他正交视角审查。
- 明确保留的设计：网络 I/O 大多已移出 DB 事务；remote push 做单操作异常隔离；metadata/delta 有心跳与 cursor-invalid 回退；SSE 队列满有 resync hint；blob 有 fsync+原子替换；备份默认拒绝把 sql_stub 当成功。修复应保留这些边界。
