# Intensive Review — 独立交叉验证（证伪）

目标：全库 HEAD `daca631aec54c30ce02cdb5e6499ae196dc3a72d`，不是 diff。基于 intensive-review §4/5/6，逐条回读 C/H 所需源码、调用方、测试及已声明限制；不因早于 HEAD 而过滤。序号 Vn-xx 按原报告 C/H 列表顺序计数。只写本报告，未修改源/测试，未运行完整测试、DB、真实账户或真实网络攻击。

## 结论与验证边界

当前已核验 V1/V2/V3/V4/V5/V7：52 条原始 C/H。多数成立，重复较多；V2-20 对“当前正常生产可达附件数据丢失”提出 CHALLENGED，但保留模型缺陷。V5 无 C/H。其余条目并非因未复现而否定。AGREE 表示源码/契约支持，不等于已完成端到端复现；CONNECT 表示成立且和其他根因/阻断条件关联，聚合时按根因去重。

独立实测仅限无副作用 stdlib/内存探针：提取原 SPA handler 的 AST、SSL 缺省上下文、历史常量形状、中文响应头 latin-1 编码、IMAP provider double。系统环境无 FastAPI/SQLAlchemy 集成依赖，未声称 HTTP/PG 集成验证。所有历史真实凭据、私人邮箱只在内存分析；输出只含存在性和长度。

## V1 安全（3/3）

| ID | 结论 | 复核后等级/置信度 | 独立证据与限定 |
| --- | --- | --- | --- |
| V1-01 SPA 文件逃逸 | AGREE | Critical/98 | `api/app.py:149-164` 的 catch-all 未使用认证依赖；`candidate = _DIST / full_path` 无 resolve/root 校验。AST 原函数以 `frontend` 为根，传入百分号解码后的 `../requirements-mail-core.txt`，确实选中根外文件。是否经特定代理/浏览器归一化仍需原始 HTTP 验证；编码路径在 ASGI 解码后进入 handler 的攻击链静态成立。不能将 `/proc/self/environ` 等特殊伪文件成功返回当已验证事实；普通可读文件泄露已成立。 |
| V1-02 IMAP 不校验证书 | AGREE | High/100 | `providers/imap.py:123-129` 不传 ssl_context；本机 stdlib `IMAP4_SSL.__init__` 明确调用 `_create_stdlib_context()`，独立上下文 `verify_mode=0/check_hostname=False`，然后 LOGIN。尚未搭建 MITM TLS 服务，不影响缺校验证据。修复需 `ssl.create_default_context()`。 |
| V1-03 历史凭据 | AGREE | High/95 | 内存 `git show 34c8131069298bf14989f853decba8e3ee8c4dd2:outlook_mail_reader.py` + AST 确认四常量存在，EMAIL/PASSWORD/CLIENT_ID/REFRESH_TOKEN 长度分别 31/14/36/424，均非已知占位词。未输出值、未尝试登录；不能断言仍有效。文件已从当前树删除不构成历史清除反证。 |

## V2 正确性（23/23）

| ID | 结论 | 复核后等级/置信度 | 独立证据与限定 |
| --- | --- | --- | --- |
| V2-01 IMAP 全邮箱 EXPUNGE | AGREE | Critical/99 | `imap.py:454-481` 在 MOVE 失败的 COPY/STORE fallback、以及 trash fallback 调用无 UID 的 `c.expunge()`。RFC 3501 §6.4.3 明确删除当前邮箱所有 Deleted 消息；成功原生 UID MOVE 分支不会触发。没有其他客户端 Deleted 时不误删，仍是可达不可逆数据丢失。 |
| V2-02 首个归档任务缺失 | AGREE | High/100 | 全库 ARCHIVE_MIME_BATCH 入队只在 `blobs/archive.py:333-340` 已 completed 分支；`sync/engine.py:320-345` 只排 reconcile/delta，worker/main 只 reclaim archive 状态。与 V3-01 调度半项同根因。 |
| V2-03 无 MIME parser | AGREE | High/100 | `archive.py:287-321` 仅 blob/link/state；全库 `MessageBody(`/`Attachment(` 仅 ORM 类声明，没有生产构造/持久化。`queries.py` 读 body，`blobs/access.py` 读 attachment，无懒解析补偿。与 V3-01 解析半项同根因。 |
| V2-04 remote push 丢唤醒 | AGREE | High/99 | `remote_push.py:51-64,156-162` 只取 limit=20，无续批；busy 返回。`jobs.py:54-67` dedupe 包括 CLAIMED；`handlers.py:68-76` 对返回状态无条件 complete。worker 没有周期扫描 pending 并唤醒的补偿。 |
| V2-05 DONE 行复活次序错误 | AGREE | High/98 | `remote_ops.py:64-79` 优先按所有状态 idempotency_key 命中；`_coalesce_existing` 改 pending、不改 created_at、不移除另一个 pending。配合 `mutations.py:92-98` 状态决定的 key 及 push created_at 升序，true(DONE)→false(pending)→true 会留下早 true/晚 false，远端落错状态。 |
| V2-06 旧响应吞掉新意图 | CONNECT | High/96 | snapshot 在 `remote_push.py:66-68`，完成在 `:128-136` 只按 id，无 desired/revision 校验。具体可达序列：true 创建 A，尚 pending 时 false 合并 A（保留 true 的 idempotency key）；worker 发 false；并发 true 命中 A 改 pending/true；旧 false 响应将 A 标 DONE。不是“每次不同 desired 都会改同一 in_progress 行”，需要此复用前提。 |
| V2-07 MODSEQ 提前推进 | AGREE / SURFACE | High/100 | `imap.py:358-382` 切 200 flags 后写 highest；失败 FETCH `:301-302` continue。另发现 **51 个新 UID 也会永久漏第 51 个**：首批只 fetch 50，保存最高 modseq；下一轮 MODSEQ 无新变化在 `:350-355` 直接 exhausted，绕过尚未消费 UID。独立 provider double 返回首轮 50/False/modseq20，次轮 0/True，uid_next51 未消费。应扩展本根因标题而非再计独立 finding。 |
| V2-08 UIDVALIDITY 未核验 | AGREE | High/99 | `fetch_mime` 在 `imap.py:257-271` 抛弃 `_uv`，apply 在 `:412-425` 只取 UID；SELECT 后无 generation 比较，metadata/delta 的 `_check_uidvalidity` 不能覆盖这次请求。归档生产入口缺失限制 fetch_mime 当前自动可达性，远程 read/trash 仍可到达。 |
| V2-09 IMAP 删除无周期对账 | AGREE | High/97 | IMAP delta docstring/实现不产生 delete；`delta.py:386-403` exhausted 只排下一 delta；唯一 reconcile 入队是 metadata 完成 `engine.py:321`。手动全量同步可补救，但不构成自动最终一致性。 |
| V2-10 Gmail historyTypes | CONNECT | High/98 | `gmail.py:243` 为一个逗号字符串；真实 `oauth.py:318` doseq 编码不会拆字符串。官方是 repeated enum。与 V3-09 同根因；未真实请求，400 为协议推断。 |
| V2-11 Gmail History stub | CONNECT | High/100 | `gmail.py:245-250` 直接 parse，无 hydration；`gmail_history.py:11-44,64-72` 以缺字段空值构造完整 meta；`metadata.py:103-117` 写所有字段。官方支持 id/threadId-only 形态，非仅测试假设。与 V3-10/V7-02 同根因。 |
| V2-12 Gmail label 成员 | CONNECT | High/99 | `gmail_history.py:73-91` 两循环只识别 UNREAD，未处理 folder_label 成员变化和 STARRED。与 V3-11 同根因；label-only 移动没有其他生产解析分支补偿。 |
| V2-13 Gmail History 分页 | CONNECT | High/90 | 正确位置为 `gmail_history.py:93-101`，原 `104-112` 超出文件末行。parser 无条件用 mailbox head 生成下一游标；调用方下一页重用该值作为 startHistoryId。官方仅无 nextPageToken 时允许存新 head。实际 Google 是否由 token 固定完整查询未动态确认，保留较低置信度；与 V3-16 同根因。 |
| V2-14 Gmail baseline 水位 | CONNECT | High/96 | `gmail.py:194-207` 直到 exhausted 才 profile，整个分页 cursor 不持有 baseline 前 historyId。已扫区间发生变化后被末尾 head 跨过。与 V3-15 同根因；新信是否正好落入后页受服务分页行为影响，已扫旧信 read/delete 变化已足以证明空窗风险。 |
| V2-15 Graph inbox role | CONNECT | High/100 | `graph.py:44-49` 只 role/wellKnownName；factory 固定 v1.0；官方 v1.0 resource 无这两字段。`queries.py:168-174` 过滤 inbox。与 V3-06/V7-01 同根因；不能把 beta 字段在 beta 的存在误当 v1.0 反证。 |
| V2-16 Graph 子目录/分页 | CONNECT | High/100 | `graph.py:88-102` 单次 root call，无 nextLink 或 childFolders；RemoteFolder 未填 parent。已声明“SPA 只展示 inbox”不豁免后端同步全部目录合同。与 V3-07 同根因。 |
| V2-17 星标同步 | CONNECT | High/99 | `base.py:23-40` 无 is_flagged；`metadata.py:35-48` 无字段；graph_delta.py 不读 flag，Gmail baseline 不读 STARRED。IMAP MODSEQ flags 确有局部支持，应保留原限定。与 V3-12 同根因。 |
| V2-18 多位置统计 | AGREE | High/99 | `metadata.py:99-111` 新 location 后 changed 仍只等 created；`:165-175` 仅 touched 更新单 folder。`delta.py:153-170` 仍有其他 location 时不递增 deleted、不排统计；跨位置 read 也仅算当前目录。mutation 中多目录修复不覆盖同步代码。 |
| V2-19 digest/version 共享文件 | CONNECT | High/97 | `store.py:74-81` 文件存在返回 active version，磁盘 path 只 digest；archive 查 hash+version，模型此二列唯一；GC 按行删除路径无其他活路径检查。key rotation 是显式维护操作；首次自动归档缺失不消除该公开 blob utility 缺陷。 |
| V2-20 GC 忽略附件引用 | CHALLENGED（限定当前可达性） | Medium/25（当前生产丢附件）；模型缺陷 High/99 | 直接反证：全库无 Attachment 生产写入（V2-03），`archive.py:287-321` 只创建 MIME link。不能把“正常新账户同步产生独立附件 payload，随后 GC 删掉”当当前已可达链。**保留** `gc.py:37-42` 只数 MessageBlobLink、`models.py:213` attachment FK SET NULL 的确定缺陷；已有外部导入/手工 seed 附件或接通 parser 后即成立。本项不删除，报告需明示潜伏条件。 |
| V2-21 post-commit unlink race | CONNECT | High/87 | `gc.py:126-131` commit 后 unlink；`store.py:74-81` 旧文件存在直接复用；`archive.py:296-321` 可创建新行/link。无 digest 共享锁；冷相是 age 条件，不封住 commit→unlink。未运行 PG/FS 并发；当前需显式 GC 与手工归档/已有归档调度并发。 |
| V2-22 DB/blob 备份快照 | CONNECT | High/90 | `package.py:199-213` dump 后才 tar；无 GC pin/屏障；verify 只包 checksum，无 DB 引用对账。具体缺失链需要 GC 已 eligible 到期且恰逢 dump/tar 窗口，不能只写“删除后立刻因24h冷相被删”。有已有可回收 blob + concurrent GC 的时序仍成立。 |
| V2-23 中文附件响应头 | AGREE（条件可达） | High/100（helper）；当前常规入口受阻 | AST/stdlib 原 helper `content_disposition_attachment('报告.pdf').encode('latin-1')` 独立抛 UnicodeEncodeError，`http_headers.py:24-28` 只替换控制/符号，无 ASCII 保证。现缺附件生产 parser，常规新账户下载链受 V2-03 阻断；既有附件数据/未来接线后必现。不能声称完整 HTTP 复现。 |

## V3 契约（16/16）

| ID | 结论 | 复核后等级/置信度 | 独立证据与去重 |
| --- | --- | --- | --- |
| V3-01 正文/归档链 | CONNECT | High/100 | 对应 V2-02 + V2-03 两个不同断点；可在主报告合成用户可见“正文/附件永不产生”，但修复须两项一起完成。 |
| V3-02 Compose blob 不共享 | AGREE（条件可达） | High/100 | compose 仅 postgres volume；api/worker 均无 blob root/volume，`archive.py:40-41` 默认 /tmp；Dockerfile 也没有跨容器共享机制。常规自动归档先被 V2-02 阻断，但已归档文件仍会随 worker 容器重建丢失，API 容器不会读到。 |
| V3-03 IMAP JSON 密码 | AGREE | High/100 | `accounts/service.py:28-32,86-90` save_json_secret；`credentials.py:224-225` json.dumps；`factory.py:56` raw get_secret → ImapProvider.password → LOGIN。API credentials 只接受 dict，不存在 UI raw-string 逃生路径。 |
| V3-04 IMAP UI 无服务器 | AGREE | High/100 | `SettingsModal.tsx:98-121` submit 无 config；`factory.py:57-65` 必需 host。与 V3-03 串联但独立根因：补 host 仍用错密码，补密码仍缺 host。 |
| V3-05 重复创建覆盖凭据 | AGREE | High/100 | `service.py:28-42` 同邮箱默认相同 ref，先保存 secret 再 Account flush；`DbCredentialStore.put_secret:101-110` 独立 commit；Account.email unique。因此外层 400/rollback 回不去密钥覆盖。单用户能力模型不豁免事务一致性。 |
| V3-06 Graph role | CONNECT | High/100 | 同 V2-15/V7-01，重复计一次。 |
| V3-07 Graph folders | CONNECT | High/100 | 同 V2-16。 |
| V3-08 虚构 RECONCILE HTTP | AGREE | High/100 | `gmail.py:312-317`、`graph.py:204-209` 发 RECONCILE；`factory.py:24-36` 接真实 transport；`oauth.py:326` 原 method.upper() 进入 urllib Request，无伪动词解释器。`reconcile.py:66-74` 出错返回，handler complete；生产不是 MemoryProvider 测试协议。Graph delta 可清部分删除，故不应把所有 Graph 删除均归因本项。 |
| V3-09 Gmail historyTypes | CONNECT | High/98 | 同 V2-10。 |
| V3-10 History stub | CONNECT | High/100 | 同 V2-11/V7-02。 |
| V3-11 Gmail label 成员 | CONNECT | High/99 | 同 V2-12；STARRED 缺失同时归 V2-17/V3-12，避免重复累计。 |
| V3-12 星标导入 | CONNECT | High/99 | 同 V2-17。 |
| V3-13 凭据未参与 key rotation | AGREE | High/100 | `credentials.py:73-90` 从 blob keyring 按 row.key_version 派生 AES key；`rotate.py:64-139` 只同步 MessageBlob，无 CredentialSecret；`docs/upgrade.md:18` 允许 rewrap 完成后移除旧 key。不是 key 已被删才能发现的纯假设；文档允许的流程确实遗漏引用。若旧 key 仍有备份可恢复，不能一概断言凭据永久丢失。 |
| V3-14 Compose 改密不持久 | AGREE | High/100 | `auth.py:107-132` env HASH 优先，再 path，再 env plain；`:209-217` 仅缓存/可选path。compose api未给 PASSWORD_HASH_PATH，无密码 volume；正常重启重新读取旧 env。桌面 bootstrap 的持久 path 不能修复 compose 配置。 |
| V3-15 Gmail baseline 水位 | CONNECT | High/96 | 同 V2-14。 |
| V3-16 Gmail History 分页 | CONNECT | High/90 | 同 V2-13；此报告 `93-101` 行号正确，优于 V2 超范围定位。 |

## V4 性能（7/7）

| ID | 结论 | 复核后等级/置信度 | 独立证据与限定 |
| --- | --- | --- | --- |
| V4-01 全树配额扫描 | AGREE（条件可达） | High/100 | `quota.py:38` 无条件 dir_size，`archive.py:235` 每封调用；无配额同样遍历，O(N²) 累积成立。需执行归档 utility/先修生产调度，当前新账户不会自动达到该规模；100万/2100万为公式估算，不是测量。 |
| V4-02 GC N+1/缺索引 | AGREE | High/99 | `gc.py:37-42` 载所有 blob，每个 count link；模型/全部迁移无 MessageBlobLink.blob_id 索引（PK仅message_id）。显式运行 GC 即可达，是否实际 seq scan/耗时须 PG EXPLAIN，未测不得写成实测。 |
| V4-03 IMAP SEARCH 二次增长 | AGREE | High/100 | `imap.py:176-184` SEARCH start:*、完整 split/filter 再 slice；后续页重复剩余集。稀疏 UID/最后一页过滤不改变密集大邮箱累计增长。 |
| V4-04 全量备份内存 | AGREE | High/99 | `package.py:262-270` BytesIO→getvalue→整块 AESGCM；`:412` read_bytes→decrypt→plaintext；大小无界。公开 run_backup 可直达；API/worker是否同进程依部署而异，OOM波及范围不能一概而论。 |
| V4-05 similarity OR 索引 | AGREE | High/94 | `search/index.py:40-46` 为 similarity()>0.3 而非 pg_trgm `%` 操作符；GIN不直接服务此函数比较。全表判定风险成立，但未跑 EXPLAIN，具体执行计划/实际性能不升级为确定测量。 |
| V4-06 SSE 慢消费者阻塞全局 | AGREE | High/98 | `dispatcher.py:58-83` 满队列写 hint 仍 False；`:104-122` 任一订阅者失败整体False；`:141-158` 最早100条成功才标记。满队列持续不排空即可让最早100条永久重读，快客户端无法收到后续。不是简单日志 warning，测试固化“满时不标记”支持该时序。 |
| V4-07 reconcile 全量 ORM | AGREE | High/100 | `reconcile.py:112-121` 无 limit 的 Message join .all 后 Python count；只需 SQL aggregate。当前真实 IMAP reconcile 能进入，Gmail/Graph先被V3-08阻断；前面有chunk/上限不限制本查询。 |

## V5 / V7

V5 架构报告无 C/H。

| ID | 结论 | 复核后等级/置信度 | 独立证据与去重 |
| --- | --- | --- | --- |
| V7-01 Graph fixture | CONNECT | High/100 | `test_gmail_graph_contracts.py:266-278` 的确人工注入 role/wellKnownName；映射只验证假响应。并入 V2-15/V3-06 的测试缺口证据，不额外计一个生产故障。 |
| V7-02 Gmail History fixture | CONNECT | High/100 | 同测试 `:74-104` 的确有 payload/subject，生产走缺 hydration parser；并入 V2-11/V3-10。 |
| V7-03 IMAP 创建测试 | CONNECT | High/100 | `test_accounts_api_pg.py:28-54` 仅 memory；live IMAP测试手工 config/raw-secret 绕创建合同。并入 V3-03/V3-04，不能因为已有 live IMAP 用例而否定入口故障。 |

## 直接反证、引用校正与聚合约束

- **唯一当前可达性 CHALLENGED：V2-20。** 反证是生产没有 Attachment 写入，不是“没有复现”。模型遗漏引用继续保留、低置信当前生产损失叙述，修 parser 时必须一并修 GC。
- **行号校正**：V2 Gmail History分页主定位从 `104 L104-L112` 改 `93 L93-L101`（文件最大101）；V3 deps认证OpenAPI（Medium，非C/H）从 `73 L73-L76` 改 `16-63`（require_auth为55-58，文件最大63）；V3 key rotation 引用 `docs/upgrade.md:24` 应 `:18`。
- **已声明限制不误报**：单用户已认证 UUID 即能力、SPA仅 inbox/前100条、无发信/联系人/通知/扩展均不作为问题。没发现本轮 C/H 是多租户 IDOR 或这些范围限制误报。
- **修复先后**：先阻断目录逃逸/全邮箱EXPUNGE/不校验证书及撤销历史凭据；再修可达创建/真实协议/事务；正文链修复需同时接归档调度、parser、Compose持久blob、GC附件引用与中文header，否则接通前半链会暴露后半链缺陷。
- **去重映射**：V2-02↔V3-01(调度)，V2-03↔V3-01(解析)；V2-10↔V3-09；V2-11↔V3-10↔V7-02；V2-12↔V3-11；V2-13↔V3-16；V2-14↔V3-15；V2-15↔V3-06↔V7-01；V2-16↔V3-07；V2-17↔V3-12；V7-03↔V3-03+04。V2-19/21/22都是blob文件一致性但触发/修复不同，不能仅因同路径合并掉独立根因。

## 外部协议与溯源

全部源码锚点对应 [HEAD](https://github.com/TuTouPower/kkmail/tree/daca631aec54c30ce02cdb5e6499ae196dc3a72d)。独立重新打开官方合同：[Gmail History](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)（repeated historyTypes、id/threadId stub、无nextPageToken才存head）、[Graph v1.0 mailFolder](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0)（字段和well-known访问别名）、[IMAP RFC3501 §6.4.3](https://www.rfc-editor.org/rfc/rfc3501#section-6.4.3)（EXPUNGE删除整邮箱全部Deleted）。报告未复制真实敏感值。
