> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — 视角 4：性能与资源

审阅快照：`daca631aec54c30ce02cdb5e6499ae196dc3a72d`。范围为当前全库，不是 diff；本报告不因问题早于 HEAD 而剔除当前仍存在问题。仅静态阅读、搜索、blame/history；未运行测试、构建、基准、SQL EXPLAIN。下列复杂度来自控制流推导，绝不表示已测得延迟、RSS 或生产执行计划。

## Summary

- Findings：Critical/High/Medium/Low/Info = 0/7/10/0/0。
- Verdict：REQUEST CHANGES。
- 性能瓶颈集中于反复全量扫描、逐行 SQL、无界内存与慢消费者阻塞。

## Critical / High

- [High][100] mail_core/blobs/quota.py:38 L19-L38 — 每归档一封邮件都重新遍历全部 blob，累计文件检查呈平方增长（V4-01） — `run_archive_batch` 在批次前及循环内 `archive.py:235` 调用 `check_quota`，后者无论是否配置任何软硬配额都执行 `os.walk`，对每个文件调用 `stat()`。归档 N 个不同 blob 时，循环至少检查约 `0+1+…+(N-1)` 个文件；默认无配额也支付相同成本。已有 100 万 blob 时，一个 20 封批次至少遍历约 2100 万文件条目，尚未计算目录扫描。实际影响：归档吞吐随历史库规模下降，磁盘元数据 IO 挤占其他任务。证据片段：`used = dir_size_bytes(root)` / `for idx, ... in enumerate(work): quota = check_quota(...)`。修复：无配额时跳过扫描；批次初始扫描一次，成功写入后按新增密文大小更新计数，周期性做完整校准；并发写入时以共享计数/预留预算控制。历史：`e4f9a1d3` 引入目录扫描，后续批次修复仍保留逐封检查。测试 `test_archive_scheduler.py` 只验证 3 封及配额结果，没有检查扫描次数。依据：skill §视角4 算法/IO。

- [High][98] mail_core/blobs/gc.py:37 L37-L42 — GC 为每个 blob 执行一次未建立索引的引用计数查询（V4-02） — `select(MessageBlob).all()` 将所有 blob ORM 行载入内存，然后每行执行 `SELECT count(*) FROM message_blob_links WHERE blob_id = ...`。`MessageBlobLink` 主键是 `message_id`，当前全部迁移和模型均无 `blob_id` 索引。触发：任意真实库上执行 GC，即使没有垃圾也执行全部查询。实际影响：N 个 blob 产生 N+1 次 SQL；引用表 L 行时缺索引计数需检查 L 行，整体工作量可达 O(N×L)，另占 O(N) ORM 内存；删除 blob 时 FK 检查也受该索引缺失影响。未运行 EXPLAIN，实际计划和耗时未实测，N+1 与缺索引由源码/迁移确定。修复：迁移新增 `message_blob_links(blob_id)`；通过一次 `GROUP BY blob_id` / 聚合 UPDATE 对账，候选使用 keyset 分批，限制单事务。历史：`45cec36c` 引入循环计数；`1ce66644` 增加 GC 冷却/原子性但保留。测试 `test_blob_crypto_gc.py`、`test_medium_hardening.py` 覆盖正确性，没有查询预算。依据：skill §视角4 查询/分页。

- [High][100] mail_core/providers/imap.py:177 L176-L184 — IMAP 每页 SEARCH 全部剩余 UID，仅消费前 50 个（V4-03） — `SEARCH UID {start}:*` 返回全部剩余 UID，随后两次构造全量列表并执行 `batch = uids[:50]`。后续页再从下一个 UID 重复同样过程。N 封初始同步需接收/解析约 `N+(N-50)+…` 个 UID，即 O(N²/50)；每页内存峰值仍 O(N)，max_pages=20 只拆 job，不改变累计复杂度。实际影响：大型 IMAP 邮箱初始同步产生大量重复网络传输、解析和临时内存；“分页”未对 SEARCH 响应规模设限。证据：`uids = [int(x) for x in (data[0] or b'').split() if x]` 后才切片。修复：使用支持部分结果的 SEARCH/ESEARCH 扩展，或按有界 UID 区间推进（正确处理 UID 稀疏），或一次搜索结果以受控方式保存并分批消费；同时避免重建所有剩余 UID。历史：`59993f3b` 引入，`32752bc7` 只补 UIDVALIDITY 检查。现有 IMAP 测试使用小 UID 集，未反证。依据：skill §视角4 算法/over-fetching。

- [High][98] mail_core/backup/package.py:262 L260-L270 — 加密备份与验证都把整个归档放入内存（V4-04） — `BytesIO` 收集整个 `postgres.dump + blobs.tar`，随后 `encrypt_bytes(buf.getvalue())` 通过单次 AESGCM 产生同量级密文；`backup/crypto.py:encrypt_bytes` 再拼接头与密文。验证端 `package.py:412` 使用 `decrypt_bytes(kkbak.read_bytes())`，同时持有完整密文和明文，解包再包成 BytesIO。触发：默认桌面 bootstrap 配置备份 key，真实数 GB blob 库执行备份/校验。实际影响：至少 O(总库字节数) 内存且存在多份副本；备份大小超过可用 RAM 时备份/恢复验证失败或 worker 被 OOM，嵌入 worker 与 API 同进程时波及 API。代码没有总大小门限。修复：使用分块认证的备份格式，把 tar 流直接写入加密输出；验证使用流式解密并落到受控工作目录，维持路径 allowlist、完整性验证和原子替换；不能只将 BytesIO 换成磁盘临时文件而仍调用全量 read。历史：`7ff217ce` 引入；后续 sealed 校验修复未改变内存路径。测试 `test_backup_package.py`、`test_backup_verify_drill.py` 使用极小数据，不涵盖内存上限。依据：skill §视角4 资源/IO。

- [High][95] mail_core/search/index.py:45 L40-L46 — 不可被当前 GIN 索引服务的 similarity 函数进入 OR，使全文查询需逐行判定（V4-05） — 条件是 `FTS OR ILIKE OR ILIKE OR similarity(from_text,:q)>0.3`。迁移 0003/0006 提供 tsvector/trigram GIN，但 trigram opclass 支持 `%` 等相似性运算符，不将任意 `similarity(...) > 常量` 自动转为该索引谓词。任一 OR 分支无法索引时，不能用其余分支的 bitmap 候选覆盖完整结果；无 account 过滤时必须检查整张搜索表（可以选择全索引/表扫描，未实测具体计划），count 查询又重复一次。实际影响：页面看似拥有全文/三元组索引，却仍随全库规模扫描；每次键入搜索会放大。修复：使用 `from_text % :q` 并在事务内固定 `pg_trgm.similarity_threshold` 为预期值，或以可索引候选条件加精确函数复核；在一次性大数据 PG 上核对 EXPLAIN 与严格阈值边界。依据：[PostgreSQL pg_trgm 官方索引支持](https://www.postgresql.org/docs/current/pgtrgm.html#PGTRGM-INDEX) 展示索引查询为 `WHERE t % 'word'`，而非函数比较。历史：`4c207681` 引入 `_MATCH`；之后仅新增 subject 索引。测试 `test_fts_inbox_api.py` 验证结果，没有检查执行计划。SQL 计划/耗时未实测。

- [High][98] mail_core/realtime/dispatcher.py:156 L141-L158 — 一个满 SSE 队列会把全局 outbox 消费速度降到最慢订阅者（V4-06） — `_put` 在 QueueFull 后删除旧项、插入 resync_hint，但返回 False；`_fanout` 对任意一个订阅者失败即返回 False；`dispatch_once` 因此不标记该行，下次始终读取最早 100 条 undispatched。触发：一个连接网络不读/持续慢读，队列达到 256；累计 100 个无法标记事件后，后续事件无法进入任何快客户端。实际影响：慢消费者形成全局队头阻塞，快客户端反复收到旧事件后只能依赖自身去重，新的实时更新停止或被限速；未分发 outbox 持续增长且 prune 不删除。现有 `test_medium_hardening.py:test_dispatch_queue_full_does_not_mark_and_sends_resync_hint` 明确固化该局部行为，但未覆盖两消费者与超过 100 行。修复：把慢连接切换为“需 resync”状态并断开/隔离其队列；成功通知 resync 后允许全局分发游标继续，恢复使用持久 outbox replay。不能让一个进程内订阅者决定全局事件是否完成。历史：`cc8ec278` 引入失败不标记，属现存回压设计缺口。依据：skill §视角4 缓存/并发/资源；架构 §13 慢客户端 resync。

- [High][95] mail_core/sync/reconcile.py:113 L112-L121 — 对账结束仅为计算两个数字，加载整文件夹全部 Message ORM（V4-07） — `select(Message).join(...).where(folder_id...).all()` 之后才 `len(rows)` 和 Python `sum`；此查询没有 limit/yield_per，加载 subject/snippet/地址 JSON 等所有字段。触发：完成大型文件夹首次同步后必排 reconcile，即使没有待删除邮件也执行。实际影响：一次性 O(N×行宽) DB 传输与 Python ORM 内存；此前 `local_remote_ids_for_folder` 的 chunked fetch 与 500k 上限并未约束这一步，嵌入进程可能内存耗尽。修复：直接复用已有 `recompute_folder_stats` 的 SQL `count` / filtered count，返回固定大小结果；删除动作仍应分批。历史：`f0f8a061` 引入，公共 SQL 聚合 helper 后来增加却未替换此处。证据片段：`).all(); stats.total_count = len(rows); stats.unread_count = sum(...)`。未实测 RSS，加载行为确定。依据：skill §视角4 SELECT\*/缺分页。

## Medium

- [Medium][98] mail_core/sync/metadata.py:167 L165-L167 — 每一页 metadata 与每次 flag/read mutation 都重新统计整文件夹（V4-08） — `recompute_folder_stats` 执行整个 folder 的 join aggregate；首次同步每增加 50 封就重新 count 已有全部邮件，累计约 O(N²/50) 行处理。`mutations.py:_recompute_stats_for_folders` 对无计数影响的 flag 和无状态变化 read 也执行，同目录批量“全部已读”通过 100 个单封请求重复 count 并竞争同一 stats 行。修复：根据新增 location/读状态变化计算净增量并原子更新，批次内按 folder 聚合增量；保留完整 aggregate 作为定期修复/对账。测试应验证同目录批量行为的 aggregate 次数。历史：`61c2a1a` 将 ORM 全量加载改成 SQL aggregate，减少内存但没有消除重复全量计数。计划/耗时未实测。依据：skill §视角4 重复计算/查询。

- [Medium][95] mail_core/threading/rules.py:163 L159-L172 — References 逐个查找父邮件，但缺少 account+Message-ID 索引（V4-09） — 每个 References ID 查询 `Message.account_id == account_id AND Message.internet_message_id == mid`。当前 messages 索引只有 account+remote、account+sort、sort+id，没有 internet_message_id；已有 account 前缀索引最多缩小到整个账户，仍需逐封判定。长 References 且父级尚未同步时，一个 message 触发多次账户级扫描，首次同步进一步放大。修复：迁移新增 `(account_id,internet_message_id)`（可对非 NULL 建 partial index），一次 IN 查询候选并按 References 顺序选最近父级。历史 `f3c44b2c` 引入父级查找；所有后续迁移未补索引。现有 `test_threading.py` 只验证小数据正确性。未跑 EXPLAIN，索引缺失与逐个 SQL 由源码确定。依据：skill §视角4 N+1/索引。

- [Medium][95] mail_core/providers/gmail.py:178 L176-L190 — Gmail metadata 逐封串行 messages.get，IMAP 同样逐 UID FETCH（V4-10） — Gmail 每页最多 50 封，在 `for stub in msgs` 内同步 `_call`；IMAP `imap.py:186` 对每 UID 单独发 FETCH。这是获取真实元数据必需，但执行方式使 50 封页耗时叠加约 50 个 RTT；Gmail transport 超时 60 秒，页内无 lease heartbeat，慢网络可拖过 120 秒账户 lease。实际影响：初始同步吞吐受 RTT 限制且可能提交前 fencing 失效。修复：Gmail 使用官方 batch 或受 quota 限制的小并发池，IMAP 使用 UID set 批量 FETCH，保持失败不推进游标语义；长页期间续租。静态确认串行，真实 RTT 未测。`test_high_blobs_providers_metadata.py` 名为 batches 但只验证逐条请求存在，没有证明请求为网络批处理。历史 `1ce66644` 引入真实 detail 拉取。依据：skill §视角4 独立 IO 串行。

- [Medium][100] mail_core/api/sse.py:168 L142-L169 — 长连接 seen 集合永久保存每个事件 ID（V4-11） — `seen.add(eid)` 对 replay/live 全部事件执行，没有清理。队列虽有 256 上限，但单连接内存仍随连接存活期间事件数量无限增长，128 个连接各保存一份。条件 `eid <= cursor_local` 已覆盖所有已发旧事件，当前 seen 对单调 cursor 逻辑冗余。修复：移除长寿命 seen 并以 cursor 去重；如确需乱序支持，使用明确大小窗口并设计相应游标语义。历史：`e2b149ff` 引入，后续订阅顺序与连接 cap 修复未限制 seen。依据：skill §视角4 资源。

- [Medium][90] frontend/src/components/MessageList.tsx:57 L42-L64 — 搜索值直接作为 query key，逐字符触发后端全文与 count（V4-12） — input `onChange -> setSearch` 后 term 即 queryKey；从第二字符开始每次变化就调用 `fetchMailCoreSearch`。虽然 AbortSignal 取消浏览器请求，但后端同步 SQL handler 没有相应取消 DB 查询路径，无法据此保证前一条扫描停止；与 V4-05 叠加会让一次词输入产生多次大范围查询。修复：将输入显示与已提交查询分开，以约 200–300ms debounce 或显式提交发起查询，保留 AbortSignal。置信度未定为 100：具体浏览器/输入法事件频率与 DB 取消效果未动态测量。依据：skill §视角4 重复 IO/缓存。

- [Medium][90] frontend/src/hooks/useMailCoreRealtime.ts:25 L23-L25 — 每条 SSE 都立即 invalidate 相同列表，批量操作会产生请求风暴（V4-13） — metadata 一页会连续发 message.upserted、folder.stats_updated；单封 mutation 还产生 remote_operation.updated，多选 100 封逐请求产生数百事件。每条事件执行 `invalidateQueries(['mail-core'])`，没有合并时间窗、账户范围或 message ID 精确更新。活动 query 在有缓存 refetch 时可被后续 invalidate 取消并重新发起，慢查询与大量事件组合放大请求/取消/重绘。修复：每个短时间窗合并一次 invalidate，按 account/list 范围失效，或使用事件 payload 更新缓存；重同步提示走完整刷新。测试目前仅检验事件名集合。实际请求次数未测，报告保留为 Medium。依据：skill §视角4 over-fetching/重复渲染。

- [Medium][98] mail_core/sync/jobs.py:114 L114-L120 — 周期 poll 每次新增 worker_jobs，完成记录没有保留上限（V4-14） — `complete_job` 只改 done，不删除；`delta.py:395-403` 每个已同步 folder 每 30 秒 enqueue 新 delta job。全库搜索只有账号 FK cascade 和迁移 drop_table，没有运行时清理 completed worker_jobs。单文件夹约每天 2880 条，100 文件夹约每天 28.8 万条，长期增加 DB/备份与 claim 索引体积，即使邮箱毫无变化。修复：采用可重调度的长期 poll job，或按明确诊断保留期增量清理 DONE/终结 FAILED 行，活跃行保留；索引可只包含可认领状态。历史：初始 job 设计；当前只 prune outbox，不 prune jobs。依据：skill §视角4 资源/数据库增长。

- [Medium][85] mail_core/blobs/archive.py:62 L62-L75 — 有界 LIMIT 归档认领缺少状态筛选索引（V4-15） — `MessageArchiveState` 在模型和所有迁移只有 message_id 主键；claim 按 state 筛选、priority+message.sort_time 排序，再 LIMIT 20，stale reclaim 每个 worker tick 按 state+claimed_at 筛选。大多数邮件已完成时，即使取不到任何 pending，仍可能扫描大量完成状态行；LIMIT 不为状态谓词提供定位能力。修复：至少新增 pending 状态 partial index，以及 in_progress(claimed_at) partial index；针对跨表排序用实际 PG 数据 EXPLAIN 决定是否持久化调度 sort_time，避免凭空加索引。未跑计划，故不将具体 Seq Scan/耗时当已验证事实。依据：skill §视角4 查询/索引；架构 §8 有界调度。历史：`e4f9a1d3` scheduler，后续迁移未补 archive index。

- [Medium][98] desktop/startup.js:194 L178-L211 — killed 被误当作已退出，Windows/Unix fallback 不再升级终止（V4-16） — Windows `softKill` 调用 `child.kill()`，Unix process group kill 失败时 fallback 也调用 `child.kill('SIGTERM')`。成功发信号即令 `child.killed=true`，即使进程忽略 SIGTERM 仍存活；4 秒后 `hardKill` 因 `child.killed` 直接返回。实际影响：sidecar/worker 残留，占用资源和端口；下次启动可能重复。正常 Unix process.kill(-pid) 分支不会设置 child.killed，因此此问题明确限定 Windows/fallback 路径。修复：使用实际 exit/close 事件状态判断结束，不能以 killed 判断进程存活；并让 before-quit 等待退出/升级完成，而非依赖 unref timer。依据：[Node 官方 killed 语义](https://nodejs.org/api/child_process.html#subprocesskilled) 明确 killed 不代表进程已经终止。历史：`b108475` 引入停止辅助；现有 startup mock 测试不等价真实 ChildProcess 的 killed 生命周期。未运行真实进程实验。

- [Medium][95] mail_core/sync/metadata.py:151 L144-L164 — metadata 虽有两次批量预读，search/thread 投影仍逐封 SELECT+flush（V4-17） — 每个 changed message 调用 `upsert_message_search`，后者 `session.get(MessageBody)`、`session.get(MessageSearch)`、`session.flush()`；常规新消息不在 identity map 的 body/search 都产生单封 SQL，再按需执行 thread 查询/flush。初始 upsert 新消息循环也每封 flush 一次以取得 Python 已能预生成的 UUID。实际影响：50 封页仍产生数量随邮件数线性增长的往返与小写入，两次 metadata lookup 不等于整页只有常量 SQL；网络 DB 时 RTT 被放大。修复：预生成 message UUID；对 body/search/thread 所需字段按页批量读取，使用 bulk upsert 或一次 flush 写入投影，保留“未改变 metadata 不重写正文”的不变量。历史：`61c2a1a` 改两次查找但保留投影循环。未计实际 SQL 条数，N+1 控制流静态确认。依据：skill §视角4 查询/重复计算。

## Spec Compliance / Strengths

架构要求大邮箱资源有界、有界归档/渐进后台处理；V4-01/02/03/04/07/14 在运行时间、内存或持久化增长上仍缺界限。V4-06 与慢客户端 resync 目标冲突。SQL inbox 已采用 keyset 与 limit；连接池显式配置；下载解密、key rotation 使用 framed AEAD 流式路径；SSE replay 已迁至 thread 且限制连接数/队列长度。这些已有设计应保留。

## Appendix — Traceability and Coverage

固定源码链接基址：[HEAD daca631aec54c30ce02cdb5e6499ae196dc3a72d](https://github.com/TuTouPower/kkmail/tree/daca631aec54c30ce02cdb5e6499ae196dc3a72d)。每项均提供当前路径/范围和上下文片段；history 用 blame/log 核对，未将历史修复标题当当前行为证明。未读取其他视角 findings。排除旧 review 报告。只写本文件，未改生产代码、测试或配置。

深入覆盖：mail application queries/search/mutations/remote_ops/attachments；storage models/folder_stats 及全部索引迁移；sync engine/metadata/delta/reconcile/remote_push/jobs/checkpoints/leases 的调用链；providers IMAP/Gmail/Graph/factory/oauth/http 与解析器；blob store/crypto/archive/quota/GC/rotate/access；backup package/crypto；worker main/handlers；API app/sse/mail/accounts/auth 与 db session；前端 App/MessageList/MessageReader/Sidebar/queries/realtime/mailBody/store，API AbortSignal 与缓存链；desktop main/startup/PostgresManager/hardening 及相关启动资源路径。

补充测试只读：test_archive_scheduler、test_blob_crypto_gc、test_high_blobs_providers_metadata、test_backup_package、test_backup_verify_drill、test_medium_hardening、test_fts_inbox_api、test_threading、test_sse_outbox、test_sse_medium_remaining、IMAP/provider/metadata/delta 测试相关断言；前端 useMailCoreRealtime 测试及列表/客户端测试相关断言；desktop startup 测试相关 mock。文档针对架构 §7/8/10/11/13 的资源不变量与当前配置核对。未逐条复核 CSS、生成 OpenAPI 类型中纯声明与本视角无关内容；安全、完整业务正确性、契约、文档全量由各对应视角负责。

需要后续验证但本轮未执行：一次性 PG 大数据 EXPLAIN（V4-02/05/09/15），归档 stat 调用计数（V4-01），IMAP UID 返回量（V4-03），备份 RSS（V4-04），慢/快 SSE 双消费者（V4-06），搜索与事件突发请求次数（V4-12/13），真实 Windows/fallback 子进程退出（V4-16）。
