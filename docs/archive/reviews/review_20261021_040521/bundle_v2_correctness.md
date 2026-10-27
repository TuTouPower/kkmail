> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — 视角 2：正确性

目标：全库当前状态，非 diff。HEAD `daca631aec54c30ce02cdb5e6499ae196dc3a72d`。日期 `2026-10-21T04:12:53+08:00`。Findings：Critical 1 / High 22 / Medium 13。

本报告独立阅读 sync、worker、provider、blob、backup、邮件 application/storage、desktop 主链及前端缓存/交互。关联阅读测试、known-limitations、status、architecture；未读取其他视角报告。全量范围允许报告存量缺陷，下列均在 HEAD 仍存在，不能当作本轮新引入问题。

验证：仅只读命令、`python3 -B` 内存 provider double；未连接 DB、启动服务、运行有副作用测试。系统 Python 缺 `sqlalchemy`，因此 DB 并发项按完整静态执行时序说明，未声称完成集成复现。

## Critical / High

- [Critical][95] mail_core/providers/imap.py:471 L469-L481 — 单封邮件 trash 会 EXPUNGE 同邮箱其他已标记删除邮件 — COPY/MOVE fallback 对目标 UID 设置 `\\Deleted` 后调用无范围 `c.expunge()`；IMAP EXPUNGE 删除当前邮箱所有已带 `\\Deleted` 邮件。另一客户端已标记但尚未清除邮件会被此次单封操作永久删除。OP_MOVE 同样见 L454-L458。修复：能力协商 UIDPLUS 后 `UID EXPUNGE <target uid>`；没有安全定向删除能力时保留删除标记并明确结果，不能执行全邮箱 EXPUNGE。证据片段：`c.uid("STORE", uid_str, "+FLAGS", r"(\Deleted)"); c.expunge()`。规范：architecture §9，操作应限于目标消息。

- [High][100] mail_core/sync/engine.py:320 L320-L342 — 正常同步永远不会启动 MIME 归档 — metadata 完成仅 enqueue reconcile/delta，`rg ARCHIVE_MIME_BATCH mail_core` 全库唯一 enqueue 位于 `blobs/archive.py:333`，其前提却是已有 archive batch 完成 `if completed:`；启动、账户创建、worker reclaim 均无初始 archive job。新实例所有 MessageArchiveState 停在 metadata_synced，邮件原文永不下载。修复：metadata/delta 写入新增消息时同 TX enqueue 有 dedupe 的首个 archive job，并在失败/暂停恢复路径保留调度。测试 `test_archive_scheduler.py` 手工直接调用 `run_archive_batch`，没有验证生产调度链。证据：`enqueue_job(...RECONCILE_FOLDER...)`、`enqueue_job(...SYNC_FOLDER_DELTA...)`，无归档入口。规范：architecture §7/§8。

- [High][100] mail_core/blobs/archive.py:317 L296-L321 — 归档完成也不会生成正文和附件 — batch 仅写 MessageBlob、MessageBlobLink、archive_complete。全库生产代码没有 `MessageBody(...)`、`Attachment(...)` 创建点，没有 MIME parser；detail 只读 MessageBody，附件下载只读 Attachment.blob_id。即使外部手工 enqueue 归档，正常邮件依然正文空、附件列表空，正文搜索也只有 snippet。修复：归档后通过生产解析路径写入正文、附件 blob/关系和搜索索引，解析失败记录 parse_error；增加从 provider MIME 到 GET detail/download 的完整验证。`test_message_detail_api.py:57` 直接 seed MessageBody/Attachment，绕过缺失生产步骤。证据：`apply_transition(st, ArchiveState.ARCHIVE_COMPLETE)` 前后无解析调用。规范：architecture §8，read API 正文与附件产品行为。

- [High][99] mail_core/sync/remote_push.py:162 L42-L54,L156-L162 — remote write-back 未排后续批次，竞争 lease 也会丢唤醒 — push 只取 `limit=20`，处理后直接 return；LeaseBusy 直接 return。handlers.py:74 无论 status 都 complete_job；mutations.\_wake_push 用 `remote-op-push:<account>` dedupe，CLAIMED 任务也命中 existing。一次批量改 21 封、第 1 批 network 期间新增操作、或同步占 lease 时，剩余 pending 操作可以永久无任务执行。修复：push 结束同 TX 检查 pending 并安排后续唤醒；busy 明确 requeue；dedupe 的 CLAIMED 与新工作交接须防丢唤醒。证据：`limit(limit)` + 函数末尾没有 `enqueue_job`。规范：architecture §9 desired-state 最终一致。

- [High][98] mail_core/mail/application/remote_ops.py:64 L64-L79 — 复用已完成 idempotency 行导致旧操作排在新操作前，最终远程状态相反 — 先 read=true 的 A 完成，再 read=false 创建 B（pending），再 read=true。第三次先命中已完成 A 的 `idempotency_key` 并重置 pending；A.created_at 仍早于 B，push 按 created_at 排序，执行 true 后执行 false，最终远端 false、本地 true。修复：已完成历史行不能复活成当前命令；用每 entity 唯一当前 desired-state/revision，或只合并待处理行并移除/失效同 entity 旧 pending。证据：先查询所有状态 idempotency 行，`_coalesce_existing` 设置 status=pending 却不处理 B。关联 `test_remote_ops_coalesce_entity.py` 仅覆盖同一 pending 行，不覆盖 DONE→false→true。

- [High][96] mail_core/sync/remote_push.py:135 L93-L136 — 网络期间更新同一 operation 可被旧响应标记 DONE — worker 从 work snapshot 得到 desired 并标记 in_progress，API 的 idempotency 命中可把该行改回 pending/写入新 desired。网络旧请求返回后仅检查行存在，直接 `mark_remote_operation(...DONE)`，未比对 revision、desired 或 in_progress claim；新意图被旧请求完成状态吞掉。修复：claim 时记录单调 revision；完成仅条件更新匹配 claim/revision 的行，变化时保留 pending 并唤醒下一轮。证据：`work=(op.id, op.op_type, dict(op.desired_state))` 与 L132-L136 无版本比较。并发项静态时序核验，未连接 DB。

- [High][99] mail_core/providers/imap.py:364 L358-L382 — MODSEQ 一批超过 200 个旧 UID 时永久漏 flag 更新 — 仅处理 `flag_uids[:200]`，但立即保存全邮箱 `highest` 到 modseq；下一页从 highest+1 搜索，剩余变化全部跨过。内存复现：201 个变化、uid_next=500、modseq 10→20，返回 changes=200、next.modseq=20、exhausted=False。`_fetch_flags_for_uids` L301-L302 对失败 FETCH 直接 continue，同样推进最高 modseq，丢失失败项。修复：处理完捕获的 MODSEQ 范围后才推进水位；剩余 UID/成功边界放 cursor，失败 FETCH 不能被跨过。来源 blame：`1ce66644`。

- [High][99] mail_core/providers/imap.py:256 L254-L272 — UIDVALIDITY 已变化时原文下载和写回操作仍使用旧 UID — fetch_mime 解析出的 `_uv` 被丢弃，SELECT 后直接 FETCH；apply_remote_operation 同样只取 uid，不比较 namespace generation。重建被其他客户端触发后，旧 UID 可指向全新邮件，导致错归档、错已读、错 trash。内存复现：remote_id generation=1、server UIDVALIDITY=999，fetch_mime 仍返回 UID2 新邮件原文，完全未发 STATUS。修复：读取 SELECT UIDVALIDITY 并与 remote_id generation 比较，不匹配拒绝访问且触发重建；所有 STORE/MOVE/COPY 前同样核验。不能仅靠 delta 周期检查缩短窗口。来源：namespace commit `6610ec4`，当前仍丢弃 `_uv`。

- [High][96] mail_core/sync/delta.py:386 L386-L400 — IMAP 初次同步后远程删除永不自动清理 — exhausted delta 只继续 enqueue delta；IMAP delta 明确不产 delete，reconcile 只由 metadata 完成时安排一次。初次 reconcile 后在其他客户端删除邮件，后续轮询永远保留本地 MessageLocation/正文。修复：定期有界安排 reconcile，或实现 UID/VANISHED 删除变化；须覆盖首次全量后独立远端删除场景。证据：imap.py delta docstring “Deletions ... use reconcile”，engine.py:321 唯一 RECONCILE_FOLDER enqueue。规范：architecture §6.2/§7 增量完整性；known-limitations 无此例外。

- [High][98] mail_core/providers/gmail.py:243 L240-L247 — Gmail historyTypes 以一个逗号拼接 enum 发送，实际 History 请求无效 — transport 的 `urlencode(...doseq=True)` 只有 list 才重复字段，这里发送 `historyTypes=messageAdded%2CmessageDeleted%2ClabelAdded%2ClabelRemoved`，不是四个 enum 值。修复：传 `historyTypes: ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"]` 或不传默认全类型，HTTP 边界验证真实 query。内存输出确认编码结果。[Gmail 官方参数定义](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)把该字段定义为 repeated HistoryType。

- [High][100] mail_core/providers/parsing/gmail_history.py:77 L67-L78 — Gmail History stub 被当作完整元数据，新增邮件主题/发件人为空 — GmailProvider.delta_changes 未调用 messages.get hydration，直接 `_minimal_meta(msg)`；真实 History 通常只含 id/threadId。函数伪造空 subject/from、当前 sort_time、read=true，upsert_messages 无条件覆盖所有元数据字段，既可能创建空白新邮件也可能擦掉先前其他 label 同步出的完整字段。内存复现官方形状 stub 返回 subject=''、from=''、sort_time=当前时间。修复：provider 先按新增 id hydrate 完整 metadata，再 upsert；flag 事件保持局部补丁。[Gmail 官方响应说明](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)支持 stub 结论，baseline fetch_metadata_page 已有可复用 messages.get。

- [High][99] mail_core/providers/parsing/gmail_history.py:80 L80-L102 — Gmail label 增删没有维护文件夹成员，远端归档/移动后 Inbox 永久错误 — labelsAdded/Removed 仅处理 UNREAD，忽略当前 `folder_label`。其他客户端移除 INBOX 标签或给旧邮件新增 INBOX 标签不会产生 MessageLocation 增删；STARED 同样被忽略。内存复现 labelsRemoved(INBOX) 返回 0 changes。修复：当前文件夹 label 增删分别生成 hydrated upsert / location delete，已读与标记生成明确 flag patch，并处理多 label 同一 message 全局身份。[History label 事件](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)包含 labelIds；当前代码只判断 `"UNREAD" in labels`。

- [High][92] mail_core/providers/parsing/gmail_history.py:104 L104-L112 — Gmail History 分页中提前推进 startHistoryId — 每个含 nextPageToken 的响应都将 mailbox 当前 historyId 放 cursor，下一请求同时使用新 startHistoryId 和旧 pageToken；原查询边界被改变，未消费 history 可能跳过或 token 失效。修复：分页期间保留固定原 startHistoryId 和 pageToken，最终页才提交新 mailbox historyId。[Gmail 官方文档](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)明确无 nextPageToken 时才存返回 historyId 用于下次请求。未真实请求 API，故置信度低于内存确定项。

- [High][95] mail_core/providers/gmail.py:194 L192-L203 — 初次 Gmail 扫描结束才取 history 起点，扫描期间变化形成永久空窗 — 大邮箱从第 1 页到最终页期间，已扫描页产生删除/未读变化或新增邮件位于已扫描部分；最后才调用 profile 取得最新 historyId，delta 从该值后开始，永远不重放这些变化。修复：扫描开始先取得 history 水位并跨页保留，完成后从该起点补增量；最终 profile 失败不能静默完成无 delta 水位 baseline。证据：`if exhausted: profile = self._call(.../profile)`。规范：architecture §7 可恢复同步。

- [High][100] mail_core/providers/graph.py:47 L47-L52,L88-L103 — Graph 真实 folder 响应无法识别 inbox，所有 Outlook 邮件在收件箱不可见 — graph_folder_role 只读 `role` / `wellKnownName`，Graph v1.0 mailFolder schema 两字段均不存在；真实 `id/displayName/parentFolderId/...` 返回 role=other。unified_inbox 仅查询 role=inbox，故正常 Graph 账户列表为空。内存验证 `{"id":"opaque-id","displayName":"Inbox"}`→other。修复：以 well-known 路径 `/me/mailFolders/inbox` 等解析稳定 folder id 并映射角色，不依赖本地化 displayName。[Graph 官方 mailFolder schema](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0)。

- [High][98] mail_core/providers/graph.py:93 L88-L103 — Graph 文件夹发现只取首层首个 page，子文件夹完全不同步 — list_folders 单次 GET /me/mailFolders，不跟 @odata.nextLink，也不遍历 childFolderCount/childFolders。较多根文件夹或任意嵌套文件夹里的邮件不会产生同步任务。修复：分页遍历根层和 childFolders，填 parent_remote_id，并在完整发现后再处理删除。[官方 childFolders 文档](https://learn.microsoft.com/en-us/graph/api/mailfolder-list-childfolders?view=graph-rest-1.0)说明 mailFolders 快捷路径仅顶层。

- [High][99] mail_core/providers/base.py:32 L32-L50 — Provider metadata 契约缺 is_flagged，远端已有星标无法进入本地 — Message 有 is_flagged，但 RemoteMessageMeta 没该字段，metadata.\_META_FIELDS 无该项，Gmail metadata/History 未处理 STARRED、Graph delta 未读 flag。新接入账号所有已有星标显示 false，后续远端切换也无法同步（IMAP 仅已建立 MODSEQ 后旧 UID flag 分支能读）。修复：完整 metadata 加 is_flagged 并贯穿三 provider / upsert，增量各自解析 flag 更新；测试 baseline、外部修改与新邮件原有星标。known-limitations 明确 flags server-side，并非此项豁免。

- [High][97] mail_core/sync/metadata.py:99 L99-L111,L151-L175 — 新增文件夹位置但元数据相同时不刷新统计；delta 删除一个仍有其他位置的消息同样漏统计 — existing message 新增 MessageLocation 不设置 changed；metadata 仅 touched 时 recompute。Gmail 同一邮件首次同步 INBOX 后再同步 label，元数据相同，则该 label 统计保留 0。delta.py 删除 loc 后 remaining 非空时 deleted 保持 0，touched 为空则源文件夹统计也不刷新。共享 is_read 更新仅刷新当前文件夹，其他 location unread_count 保留旧值。修复：分离 metadata_changed/location_changed，收集所有受影响 folder，按实际 location/read 变化统一刷新并发事件。证据：`locs[msg.id]=loc` 后 `changed=created`；delta.py:170 `if touched or deleted:`。本地 mutation 已用 all_location_folder_ids，可沿用该语义。

- [High][96] mail_core/blobs/store.py:78 L74-L81 — 已存在文件被谎报成新 key_version，多个 DB blob 行共享路径，GC 可删活文件 — put 遇到 dest 存在直接返回 `self.key_version`，未读取实际文件 header。切 active key v1→v2 后新邮件原文与旧原文相同，archive 按 (digest,key_version) 创建 v2 行，却仍指向磁盘 v1 文件；旧 v1 行失去引用后 GC 删除该共享文件，v2 活链接损坏；rewrap.\_sync_key_version 同时把两行变同 version 还可能 UNIQUE 冲突。修复：一 digest 对应一逻辑 blob 行且 key_version 跟实际文件一致，或路径包含版本并真实独立写入；已有文件至少 read_key_version 后返回实际版本。证据：store.py `_rel_path` 不含版本，models.py unique 是 hash+version，gc.py 无同路径存活检查。

- [High][98] mail_core/blobs/gc.py:41 L34-L54 — GC 不计算 Attachment.blob_id 引用，会删除有效附件 — mark_unreferenced_blobs 仅 count MessageBlobLink；附件模型通过独立 Attachment.blob_id 引用 blob，FK ON DELETE SET NULL。附件 payload 有自己的 digest，与 MIME blob 不同，不会必然出现在 MessageBlobLink 中；冷相到期 sweep 删除 row 并使 attachment.blob_id 变 null，再删文件。修复：同时计算附件引用或统一 blob 引用表，活引用和 GC 判定同事务受锁保护。证据：`select(func.count()).select_from(MessageBlobLink)`；access.py 必须 Attachment.blob_id 才能下载。生产附件创建目前缺失见独立 finding，此项是已提供 attachment 存储/访问模型本身不正确。

- [High][90] mail_core/blobs/gc.py:130 L126-L131 — post-commit unlink 与同 digest 新归档之间无互斥，可能删刚创建活引用文件 — GC 删除无引用 blob 行并 commit 后，archive 可发现旧文件存在、创建新 blob 行和 link 并 commit，随后 GC unlink 同一路径，新行立刻悬空。冷相仅限制旧行 age，不保护 commit→unlink 窗口。修复：文件先在 digest 锁下重命名至独立 GC tombstone，事务确认无引用后删除 tombstone；writer 与 GC 用同 digest 同步机制，或 unlink 前在锁内确认无新存活 row，不能无锁检查。证据：`session.commit()` 后 `unlink_gc_paths(paths)`；store.put 相同 digest 复用固定文件名。DB/FS 并发未实测，时序静态成立。

- [High][92] mail_core/backup/package.py:201 L199-L213 — PG dump 与 blob tar 没有一致性保护，备份成功也可能无法恢复邮件原文 — pg_dump 先固定 DB 快照；dump 之后旧消息本地删除、blob GC 冷相到期 unlink，随后 tar 不再包含该文件，但 dump 仍保留 MessageBlob/Link。verify 只检查 tar 文件 checksum，不检查 DB blob 引用完整性，因此返回 ok。修复：备份期间 pin dump 快照所需 blob / 与 GC 共享排它或 epoch 屏障；备份完成验证引用文件齐全，恢复演练检查 blob 解密与引用。规范 architecture §10.2 明确“进行中的备份与重试需防误删”；当前无 backup lease/pin。

- [High][100] mail_core/api/http_headers.py:25 L24-L28 — 中文附件名未转 ASCII fallback，HTTP 响应编码抛错 — `ascii_name = _BAD.sub(...)` 仅替换控制字符/标点，保留中文；Starlette header 按 latin-1 编码，`filename="报告.pdf"` 触发 UnicodeEncodeError，下载返回 500。filename\* 虽正确但不能挽救 fallback。修复：fallback 用 ASCII 安全字符替换/转写，真实 UTF-8 名仅放 filename\*；加中文/emoji header encode 或下载验证。证据：`content_disposition_attachment("报告.pdf").encode("latin-1")` 必然失败，现有 tests 只验证 RFC5987 字符串含字段，未通过响应编码。

## Medium / Low / Info

- [Medium][100] frontend/src/components/Sidebar.tsx:40 L40-L42 — 创建任意分组后未分组账户从导航消失 — groups.length>0 仅 map 每个组内成员，没有 null/orphan group fallback；SettingsModal 添加账户从不传 group_id，也无分配分组 UI。正常创建首个空组即导致原有账户全部无法单独打开。修复：始终保留“未分组”项并包含未匹配组账户；测试混合 grouped/ungrouped。证据：`groups.map(...accounts.filter(a.group_id===g.id))`。

- [Medium][100] frontend/src/components/ColumnResize.tsx:18 L18-L22 — 连续 pointermove 用增量配合旧闭包，拖动宽度不累计 — move 在 pointerdown 注册并捕获当时 onDrag；App.tsx onDrag 使用当次 render 的 sidebarWidth/listWidth。100→120→140 两个事件各算 dx=20，却都 set 初始宽+20，第二次移动无效果，回拖还会跳宽。修复：store 暴露按当前 state 递增 action，或 listener 从 ref 获取最新 callback，或使用起点总 delta 配合起始 width。现 ColumnResize.test 只校验 onDrag 单个 delta，未覆盖真实 store 连续拖动。证据 App.tsx:105 `setSidebarWidth(sidebarWidth + dx)`；list 分割条同根因。

- [Medium][99] desktop/startup.js:195 L169-L205 — child.killed 被误当作进程已退出，升级终止被跳过 — child.kill 成功发送 SIGTERM 即设置 killed=true，不表示进程已退出。Windows 总走 child.kill，Unix process-group signal 失败 fallback 也如此；4秒 hardKill 第一行检查 child.killed 后 return，无法 taskkill /T 或 SIGKILL 未退出进程。修复：以 exit/close 事件、exitCode/signalCode 判断死亡，killed 只用于“是否已发信号”；Windows 软杀即需管理整个树。另 main.js before-quit 未 preventDefault/await，unref escalation timer 不能保证 Electron 退出后仍执行，需等待有界关闭流程。[Node 官方 killed 语义](https://nodejs.org/api/child_process.html#subprocesskilled)。

- [Medium][97] frontend/src/hooks/useMailCoreRealtime.ts:25 L23-L25 — SSE 与刷新只失效列表，不失效详情 cache — detail key 是 `['detail','mail-core',id]`，invalidation 是 `['mail-core']`；现 MessageReader 可持续显示更新前 subject、正文、附件，手动刷新列表也不会更新 detail，默认 staleTime 5分钟且 focus refetch 关闭。修复：统一 mail-core query 根层或针对相关 message 同时失效 detail；archive.progress/新解析完成也需要刷新详情。生产解析缺失见 High，不把“新正文到达”当作当前已实现路径。metadata subject 更新即足以触发本项。

- [Medium][99] mail_core/accounts/service.py:81 L81-L82 — sync_enabled=false 不能停止已有同步轮询 — API 保存 flag，但 worker/engine/delta 完全不检查；已排队 delta 自续排每30秒，无限访问已禁用账号。sync-all 仅对新发现任务过滤，不能暂停既有链。修复：执行每类 sync job 前检查账户状态，禁用时停止续排，启用时显式重启；账户删除后的旧 WorkerJob.account_id ON DELETE SET NULL 也应作为取消处理。证据：全库 sync_enabled 除模型/API只有 sync-all 过滤，无执行 guard。

- [Medium][100] mail_core/accounts/service.py:119 L112-L120 — sync_status 一旦变 running 就永不完成 — enqueue_account_sync 设置 running，engine 完成/失败/lease_busy 没有任何 Account.sync_status 写入；前端设置页显示状态，首次同步后永久“running”。修复：聚合 job/run 状态后更新 idle/error/last_sync，或者只报告真实现有作业进度。证据 `rg 'sync_status\s*=' mail_core` 唯一运行时赋值在此；Folder.sync_status 也从未推进。

- [Medium][98] mail_core/blobs/archive.py:324 L324-L340 — 一批原文下载全失败后不再调度重试 — fetch 失败把 state 退回 archive_pending/retry_count+1，但末尾仅 completed>0 时 enqueue next batch。全部20封瞬时断网时 completed=0，handler仍成功完成job；所谓5次 retry 永远不会自动发生，后面未归档邮件也被饿死。修复：只要有 pending/retryable 工作就按 backoff 续排，失败不能靠同批其他成功项唤醒；quota paused 也需要有显式恢复入口。与缺初始调度不同，本项在手工启动归档后仍发生。

- [Medium][97] mail_core/backup/package.py:472 L471-L476 — manifest 缺必须成员也能 verify ok — `_verify_plain_tree` 对 `members={}` 循环零次，没有要求 postgres.dump 或校验每项必须含 sha256，ok=not errors。一个合法 JSON 与自洽 MANIFEST.sha256、零 dump 的目录会被当作可恢复备份。修复：严格 manifest schema，postgres.dump 必须存在、method 非stub、checksum非空且长度正确；include_blobs/encrypted 语义显式记录并校验。证据 `_check_plain_members` 的 expected 为空则不比较。本项可纯代码推演，未落盘创建夹具。

- [Medium][100] mail_core/backup/package.py:139 L136-L142 — 空 MANIFEST.sha256 使 verify 抛 IndexError，未返回失败结果 — `.read_text().split()[0]` 没判空；截断 backup、并发生成或损坏校验文件时直接崩溃，CLI/worker 无结构化 restore verify 结果。修复：校验 token 数/hex digest，不合法 append error 并返回 RestoreVerifyResult(ok=False)。证据：`expected = ...split()[0]`。verify 中 manifest 类型错误/non-dict members 同样需 schema 处理，可同修。

- [Medium][98] mail_core/backup/package.py:248 L248-L258 — 同输出目录切加密模式后残留 backup.kkbak 干扰新备份验证 — 加密备份后再指定 encrypt=false，直接在 out 写新 plain manifest/dump，不清理旧 kkbak；verify 优先见 kkbak 进入 sealed 分支，并期待新 plain manifest 中有 backup.kkbak sha，产生失败或处理旧内容。默认 run_backup 固定目录；重复模式变更可触发。修复：每次新建独立 staging package，完成验证后原子发布为一个明确格式目录，禁止混用遗留成员。证据 verify_backup_package:369 `if kkbak.is_file()` 无视 manifest.encrypted。

- [Medium][99] mail_core/providers/imap.py:52 L46-L52 — 一封未知 charset 编码邮件可阻断整个文件夹同步 — `_decode_header` 对 chunk.decode(charset) 未捕获 LookupError；`=?bad-charset?b?YQ==?=` 内存复现抛 unknown encoding。metadata page 失败不推进 cursor，8次重试后 worker job failed，后续邮件都无法同步。修复：未知 charset 回退 utf-8/errors=replace，并对不可解析单邮件记录隔离错误，避免整个文件夹永久卡同页。证据 helper 直调结果；附件/正文 parser 缺失不影响本元数据问题。

- [Medium][98] mail_core/providers/imap.py:148 L144-L151 — IMAP Inbox 大小写变体被标 other 且不会补建正确 inbox — `_FOLDER_ROLE.get(name)` 大小写敏感，但补 INBOX 判断 `remote_id.upper()=="INBOX"`；LIST 返回 `"Inbox"` 时 role other，又阻止添加 INBOX，unified_inbox 永远不包含该账号。内存验证 Inbox→other。修复：INBOX 角色按 IMAP 大小写不敏感规则识别，其他 role 按明确 server special-use flags 映射，不把所有普通 mailbox 都大小写归一化。

- [Medium][95] mail_core/sync/delta.py:106 L100-L113 — 同页重复 upsert 未真正 last-change-wins，新消息可能唯一约束失败 — last_kind 仅过滤 delete，却保留同 remote_id 多个 upsert；upsert_messages 首次新建时把 MessageLocation 加入 session 但没有加入 locs，第二个相同 remote_id 再建同 folder location，最终 uq_message_locations 失败、checkpoint 不前进。既有消息重复 upsert 也多次执行 side effects，zip 的 o.message 可能已是最后内容却配早先 meta thread key。修复：先按 remote_id 折叠有序变化，合并 flag patch 或逐序应用；创建 loc 后即写 locs；测试 upsert→upsert/flag→upsert。规范：函数注释承诺 last-change-wins。

## 验证与证伪说明

- 已知限制不重复报告：SPA 100条不分页、未读徽标只计缓存首屏、无 archive/junk/move API、无浏览器端 E2E、桌面二进制未 vendor、单用户 UUID 能力模型。
- fencing 曾作为候选调查，但当前主调用链提交前 heartbeat/release 有 FOR UPDATE 二次校验，未拿到足够反证绕过证据，因此没有把“plain assert 不是锁读”当作已确认生产竞争漏洞。
- 内存 provider 验证成功：201个 MODSEQ 变化仅200条、Graph真实 folder shape→other、Gmail added stub空元数据、INBOX label removal→零变化、Gmail enum编码单字符串、旧 UIDVALIDITY MIME fetch仍成功、未知邮件charset异常、Inbox大小写role错误。
- DB 并发、备份实际 pg_dump/恢复、桌面真实终止、前端真实浏览器交互未执行；报告明确区分静态执行时序与实测。

## History / Traceability

当前源码永久定位统一为 `https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/<path>#L<line>`；各 finding 同时含行号与上下文片段，满足无需 mutable branch 的追溯。

只读执行 `git log --all --oneline -- <paths>`、`git blame -L ...`。关键历史：

|模块|相关历史证据|当前结论|
|---|---|---|
|IMAP namespace|`6610ec4` namespace remote_id|UIDVALIDITY已纳入ID，但MIME/写回仍未核验|
|IMAP MODSEQ|`1ce66644` / HEAD `61c2a1a92b97acb1d27ed18e58d69f082833204f`|flag patch已实现，截断仍提前推进水位|
|Archive|`e4f9a1d3` scheduler、`1faeff4e` FSM/refcount、`01a78ad66dff932889e072177408e6c283b86fd0` cleanup|初始调度和生产解析仍缺；重试全失败仍断链|
|Remote ops|`898c5a0` fencing/isolation、`4d89440e387de43ecbdd8f1ddadd042b808ea0b8` latest|per-op隔离改善不解决排空/版本竞争|
|Backup|`e9003e9` sealed checksum、`01a78ad66dff932889e072177408e6c283b86fd0` latest|checksum已有校验，但无强制成员与DB/blob快照屏障|
|Blob put|`61c2a1a92b97acb1d27ed18e58d69f082833204f` latest|现存文件返回active版本仍不匹配header|
|Desktop shutdown|blame `fcc1fcb6`|新增升级终止仍把killed误判为退出|
|Sidebar|`fd92b1d58d5fdc5c84d14a388c60ded61f8803be` latest|首屏计数限制已声明，未分组账户消失另属独立缺陷|

规范对照：architecture §6 provider语义、§7原子checkpoint/增量完整性、§8归档、§9 desired-state、§10.2 GC/备份；`docs/known-limitations.md` 已逐项核对。

Strengths：网络I/O与大部分DB事务分离；账户lease和page checkpoint具恢复骨架；本地mutation已考虑多位置统计；HTML统一sandbox/DOMPurify；邮件正文与附件API均以本地存储为源。以上设计值得保留，但尚不足以证明完整生产链可用。

Verdict：BLOCK（包含 Critical）。需要主任务去重与独立交叉验证。
