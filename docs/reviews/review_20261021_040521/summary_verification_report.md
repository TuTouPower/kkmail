> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

> [!NOTE]
> **横幅限定注记（A395 / R3-H20）**：上方横幅「已在后续版本（截至 da57df7）彻底修复并闭环」仅适用于当时已逐条验证的条目，不构成全量闭环结论。第四轮审阅 `docs/reviews/review_20261027_021416/regression.md` 的逐条复测仍有 26 条 STILL PRESENT，例外清单以该文件为准。

> [!NOTE]
> **状态注记（A34，泄露凭据处置口径）**：本文件 §二.1 对历史泄露凭据的「不执行破坏性 Git 历史重写」决策，已被次日 `docs/reviews/review_20261022_052842/adoption_decision.md` 的 A53/A54 决策（使用 git-filter-repo 重写历史并吊销凭据）取代，不再是现行口径；`docs/reviews/review_20261021_064335/review_da57df7_findings_and_decisions.md` 仅处置报告脱敏与状态横幅、未处置历史重写，其「唯一的修复基准」仅指该轮修复清单，不构成凭据处置口径；`docs/blueprint/decisions.md` 中 2026-10-21「历史泄露凭据资产处置」条目仍保留与本文件 §二.1 相同的「不重写」旧口径、未随 A53/A54 更新。凭据处置口径以日期较新的 A53/A54 为准；但第四轮审阅 `docs/reviews/review_20261027_021416/regression.md` 核实该重写截至其基线尚未执行、相关 commit 仍可达，执行状态以该文件为准。

> [!NOTE]
> **未完成披露注记（A400 / R3-H05）**：本包该轮审阅并未完整跑完——`_meta/_meta.json` 记录 phase=timeout、deadman 已触发，聚合终产物 `review_intensive.md` 始终未生成（pending 中仅余该文件、至今缺失）。本报告是超时终止时的阶段性核验产物，包内结论不完整；引用本包结论时须连同此注记，不得以完整审阅包面貌引用。

# kkmail 全量审查问题真实性核验与源头溯源总报告

- **审查基线**：最新审查目录 `docs/reviews/review_20261021_040521/`
- **代码基线 SHA**：Git HEAD `c9b67a2`（对应源码 `daca631aec54c30ce02cdb5e6499ae196dc3a72d`）
- **核验覆盖范围**：全量核查 `bundle_v1` 到 `bundle_v8`、`bundle_cross_validation.md` 及 `bundle_parent_followups.md` 中提出的全部 **106 项**原始问题。
- **核验原则**：不带预设立场，逐条回读当前源码、数据库模型、协议定义与测试，清晰标明每一项问题在审查包中的**源头 Bundle 文件**与代码位置。

> [!NOTE]
> **勘误注记（A393 / R3-H15）**：头部「代码基线 SHA」一行中的两个 SHA 不是同一提交的两种写法：`c9b67a2` 是本审查包入库时的 Git HEAD（该提交本身即 vendor 本审查包），`daca631aec54c30ce02cdb5e6499ae196dc3a72d` 才是本报告逐条回读核验的代码基线，正文各条结论以 `daca631` 的代码状态为准。本报告及下表反复出现的「全部真实存在」是核验时点针对该代码基线的一揽子真实性裁决，本文件未给逐条 open/fixed 状态；各条目当前处置状态以第四轮审阅 `docs/reviews/review_20261027_021416/regression.md` 的逐条四态结论（FIXED / STILL PRESENT / MOOT / CHANGED）为现行口径。

______________________________________________________________________

## 一、 总体核验裁决与分类统计

全量核查 106 项 Finding，最终裁决统计如下：

> [!NOTE]
> **勘误注记（A398 / R3-H01）**：本节首行与头部「核验覆盖范围」所称总数 106 与下表逐行数字自相矛盾：下表各行计数（9+36+23+17+2+20+6+22+4）合计为 139，与第三节逐项清单条数一致；106 在本文件内无推导记录、无法由表内数字复算。引用本包条目数时以逐行合计 139（未去重口径）为准，106 勿再引用；去重后根因总数见 A394 注记（122）。正文数字未改，此注记即为勘误。

|视角编号|源头 Bundle 产物|审查维度|严重级别分布 (C / H / M / L / I)|真实性结论|
|:---|:---|:---|:---:|:---|
|**V1**|`bundle_v1_security.md`|安全漏洞|1 / 2 / 4 / 1 / 1|9 项全部真实存在（V1-03 确认为上游继承）|
|**V2**|`bundle_v2_correctness.md`|数据与业务正确性|1 / 22 / 13 / 0 / 0|36 项全部真实存在（V2-20 为客观模型缺陷）|
|**V3**|`bundle_v3_contracts.md`|协议与契约一致性|0 / 16 / 7 / 0 / 0|23 项全部真实存在（部分与 V2 共享根因）|
|**V4**|`bundle_v4_performance.md`|性能与资源瓶颈|0 / 7 / 10 / 0 / 0|17 项全部真实存在（多处 $O(N^2)$ 算法与无界内存）|
|**V5**|`bundle_v5_architecture.md`|架构与死代码|0 / 0 / 0 / 2 / 0|2 项全部真实存在|
|**V6**|`bundle_v6_robustness.md`|健壮性与可观测性|0 / 16 / 3 / 0 / 1|20 项全部真实存在（R20 保持防御性观察）|
|**V7**|`bundle_v7_tests.md`|测试断言与覆盖缺陷|0 / 3 / 0 / 3 / 0|6 项全部真实存在（测试存在假协议与绕过）|
|**V8**|`bundle_v8_docs.md`|文档、规范与注释|0 / 4 / 8 / 10 / 0|22 项全部真实存在（存在多处破坏性误导与过时说明）|
|**FOL**|`bundle_parent_followups.md`|主任务补充排查|0 / 0 / 4 / 0 / 0|4 项全部真实存在（交互与事务细节）|

> [!NOTE]
> **去重注记（A394 / R3-H23）**：上表 V3 行的 23 项为未去重计数，其中 9 项与 V2 共享根因：V3-01（合并对应 V2-02、V2-03）、V3-06（=V2-15）、V3-07（=V2-16）、V3-09（=V2-10）、V3-10（=V2-11）、V3-11（=V2-12）、V3-12（=V2-17）、V3-15（=V2-14）、V3-16（=V2-13）；V3 去重后新增独立根因为 14 项，V2 与 V3 合计去重根因为 50 项（而非 36+23=59）。全包另有 V4-16（=V2-26）与 V6 的 R01（=V2-04）、R02（=V2-06）、R07（=V2-02）、R08（=V2-30）、R12（=V2-21）、R14（=V2-31）、R16（=V2-26）同为跨节复述；按逐行合计 139 项（见 A398 注记）扣除上述 17 个重复行后，全包去重根因总数为 122 项。引用本包问题规模时以去重口径 122 为准。

______________________________________________________________________

## 二、 负责人关键决策记录 (Decision Record)

针对核查中暴露的核心争议与架构分歧，经评审已确立以下基准决策：

1. **Commit `[REDACTED_HISTORICAL_COMMIT]` 历史泄露凭据处置（针对 V1-03）**：
    - **溯源事实**：该 Commit 是上游原仓库 `assast/outlookEmail`（作者 `luekongbai`）在 2026-01-13 的首个初始化提交。文件由 fork 自动继承，泄露责任在上游，凭据为原作者历史测试资产。
    - **最终决策**：**不执行破坏性 Git 历史重写**。避免与上游分叉及破坏下游 clone，在安全审计基线中将其标记为“上游遗留已知资产”，保持 Git 树稳定。
2. **Compose 部署登录密码持久化（针对 V3-14）**：
    - **最终决策**：**采纳方案 A（统一持久化至 PostgreSQL）**。密码 Hash 统一存储于数据库表中。环境变量仅作为首次启动 bootstrap 初始值；一旦数据库初始化完成，密码 Hash 以数据库为权威源，API 改密直接写库，彻底解决 Compose 容器重启密码回滚问题。
3. **IMAP 删除行为与防止全邮箱误删（针对 V2-01）**：
    - **技术背景**：标准 IMAP (RFC 3501) 原生无单封物理删除命令，传统两步删除（标记 `\Deleted` + `EXPUNGE`）会清空全文件夹中其他客户端标记的所有已删邮件。
    - **最终决策**：**采纳安全阻断报错策略**。优先执行 `UID MOVE` 移入废纸篓；若服务器不支持或移动失败，**严禁调用全邮箱 `c.expunge()`，且不要打 `\Deleted` 标记，直接向调用方报错返回失败**（提示当前 IMAP 服务器不支持安全删除），100% 杜绝连带误删风险。
4. **修复实施节奏**：
    - **最终决策**：**采纳分批推进模式**。第一批先执行 P0 紧急安全阻断；第二批推进 P1 业务主链路打通；第三批推进 P2 密码入库与健壮性改造。

______________________________________________________________________

## 三、 全量问题清单与源头 Bundle 逐项核验

### 1. 安全漏洞 (V1 Security)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v1_security.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V1-01**|`bundle_v1_security.md:13`|`mail_core/api/app.py:155-164`|**Critical**|**真实存在**|`candidate = _DIST / full_path` 未做路径 resolve 包含校验，且 catch-all 无认证保护。请求 `/%2e%2e/requirements-mail-core.txt` 可逃逸出 dist 目录读取任意系统及进程文件。|
|**V1-02**|`bundle_v1_security.md:15`|`mail_core/providers/imap.py:123-129`|**High**|**真实存在**|`imaplib.IMAP4_SSL` 未传入 `ssl_context`，Python stdlib 默认 `verify_mode=0`、`check_hostname=False`，导致 IMAP 流量极易遭受中间人攻击窃取密码与邮件。|
|**V1-03**|`bundle_v1_security.md:17`|Git Commit `[REDACTED_HISTORICAL_LOCATOR]`|**High**|**真实存在**|Git 历史中硬编码 Outlook 账号、密码及 424 位 OAuth Token。**已溯源确认系上游原作者初始提交**，按决策在安全基线中标记，不强推重写历史。|
|**V1-04**|`bundle_v1_security.md:21`|`mail_core/security/auth.py:152-217`<br>`api/auth_routes.py:75-78`|**Medium**|**真实存在**|Session Cookie 仅验证签名与 30 天期限，改密和登出不更新服务端 session generation/epoch，被盗 Cookie 在改密后 30 天内依然完全可用。|
|**V1-05**|`bundle_v1_security.md:23`|`mail_core/security/redact.py:46`<br>`sync/remote_push.py:122`|**Medium**|**真实存在**|`safe_error` 仅截断前 120 字符且仅能脱敏已知 key；多处使用 `log.exception` 打印整个未脱敏的异常调用栈，可能泄露包含个人信息的 provider 原始响应体。|
|**V1-06**|`bundle_v1_security.md:25`|`mail_core/backup/package.py:244`|**Medium**|**真实存在**|未配置 `MAIL_CORE_BACKUP_KEY` 时，备份静默降级为明文 dump，且依然返回 status=ok，与文档宣称的“密封加密备份”相悖。|
|**V1-07**|`bundle_v1_security.md:27`|`mail_core/backup/package.py:249, 289`|**Medium**|**真实存在**|先写明文 dump 后加载密钥，加密失败时无 `finally` 清理；且成功分支调用 `shutil.rmtree(ignore_errors=True)`，权限异常时会静默残留明文数据。|
|**V1-08**|`bundle_v1_security.md:29`|`mail_core/backup/crypto.py:49-56`|**Low**|**真实存在**|缺少防御性检查，若误将 backup key 配置为与 blob keyring 相同，系统不报错，削弱离线备份与在线数据的相互隔离。|
|**V1-09**|`bundle_v1_security.md:31`|`mail_core/providers/oauth.py:188-193`|**Info**|**真实存在**|`BearerTransport` 处理绝对分页链接时不检查目标 host 是否与当前 provider 一致，重定向可能转发 Authorization 头。|

______________________________________________________________________

### 2. 数据与业务正确性 (V2 Correctness)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v2_correctness.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V2-01**|`bundle_v2_correctness.md:11`|`mail_core/providers/imap.py:469-481`|**Critical**|**真实存在**|缺少 MOVE 扩展时 fallback 调用无参数 `c.expunge()`。RFC 3501 规定其清空当前目录下所有已标删除的邮件，导致误删其他客户端已删邮件。|
|**V2-02**|`bundle_v2_correctness.md:13`|`mail_core/sync/engine.py:320-342`|**High**|**真实存在**|元数据同步完成后仅 enqueue reconcile/delta，全库唯一 ARCHIVE 入队位于 archive 自身的 completed 分支，导致新账户永远不会触发首轮归档。|
|**V2-03**|`bundle_v2_correctness.md:15`|`mail_core/blobs/archive.py:296-321`|**High**|**真实存在**|生产代码没有 `MessageBody(` 和 `Attachment(` 构造调用，缺少 MIME parser；归档下载 raw blob 后不解析，正文与附件永久为空。|
|**V2-04**|`bundle_v2_correctness.md:17`|`mail_core/sync/remote_push.py:42-54, 156`|**High**|**真实存在**|出站推送取 limit 20 后直接返回无续批，且 handler 无论结果统一 complete；批量标记超过 20 封时剩余操作永久卡在 pending。|
|**V2-05**|`bundle_v2_correctness.md:19`|`mail_core/mail/application/remote_ops.py:64`|**High**|**真实存在**|read=true(DONE) -> read=false(PENDING) -> read=true 时，命中已完成旧行并复活，保留早先 created_at，导致 push 按时间升序先执行 true 后执行 false，远端落错状态。|
|**V2-06**|`bundle_v2_correctness.md:21`|`mail_core/sync/remote_push.py:93-136`|**High**|**真实存在**|worker 网络调用期间 API 发生的新意图被旧快照完成状态无条件标 DONE 吞掉，缺少 CAS 版本或 revision 校验。|
|**V2-07**|`bundle_v2_correctness.md:23`|`mail_core/providers/imap.py:358-382`|**High**|**真实存在**|MODSEQ 变更超过 200 个旧 UID 时仅取前 200 个，但游标提前更新为全邮箱最高 highest，导致剩余 flag 变更与第 51 个新 UID 永久遗漏。|
|**V2-08**|`bundle_v2_correctness.md:25`|`mail_core/providers/imap.py:254-272`|**High**|**真实存在**|`fetch_mime` 丢弃 `_uv`，未比较 UIDVALIDITY 是否匹配即直接按 UID FETCH 原文，服务器重建后可能拉错全新邮件或写错状态。|
|**V2-09**|`bundle_v2_correctness.md:27`|`mail_core/sync/delta.py:386-400`|**High**|**真实存在**|IMAP delta 不产出 delete 变化；而 reconcile 仅在首次元数据完成排一次，后续 30 秒轮询只有 delta，远端被删邮件本地永不清理。|
|**V2-10**|`bundle_v2_correctness.md:29`|`mail_core/providers/gmail.py:240-247`|**High**|**真实存在**|Gmail `historyTypes` 传逗号拼接字符串，urlencode 未展开为 repeated query 参数，导致真实 History 接口请求报 400 失败。|
|**V2-11**|`bundle_v2_correctness.md:31`|`parsing/gmail_history.py:67-78`|**High**|**真实存在**|真实 Gmail History 的 message 通常只有 id 和 threadId，解析器伪造空主题/当前时间直接入库，未补 `messages.get` 元数据拉取。|
|**V2-12**|`bundle_v2_correctness.md:33`|`parsing/gmail_history.py:80-102`|**High**|**真实存在**|增量仅判断 UNREAD 标签，对 INBOX 标签的增删（移出/移入收件箱）完全忽略，未维护 `MessageLocation`。|
|**V2-13**|`bundle_v2_correctness.md:35`|`parsing/gmail_history.py:93-101`|**High**|**真实存在**|Gmail History 分页带 nextPageToken 时提前用当前响应的 historyId 更新 startHistoryId，破坏分页查询边界。|
|**V2-14**|`bundle_v2_correctness.md:37`|`mail_core/providers/gmail.py:192-203`|**High**|**真实存在**|Gmail 全量扫描在所有分页拉取完后才调用 profile 获取 historyId，扫描期间产生的新邮件和变更形成永久遗漏空窗。|
|**V2-15**|`bundle_v2_correctness.md:39`|`mail_core/providers/graph.py:47-52`|**High**|**真实存在**|Graph v1.0 mailFolder schema 不返回 role 与 wellKnownName，真实响应全部被判为 other，收件箱视图永久为空。|
|**V2-16**|`bundle_v2_correctness.md:41`|`mail_core/providers/graph.py:88-103`|**High**|**真实存在**|Graph 文件夹列表仅发单次 GET，未遍历 `@odata.nextLink`，未递归 `childFolders`，嵌套子文件夹邮件无法同步。|
|**V2-17**|`bundle_v2_correctness.md:43`|`mail_core/providers/base.py:32-50`|**High**|**真实存在**|RemoteMessageMeta 和 metadata 表缺少 `is_flagged` 字段，导入已有邮件星标全落为 False，Gmail/Graph 星标变更不进入本地。|
|**V2-18**|`bundle_v2_correctness.md:45`|`mail_core/sync/metadata.py:99-111, 151`|**High**|**真实存在**|已有邮件新增 MessageLocation 时设置 changed=created (False)，touched 为空导致新增目录的未读与总数统计保留为 0。|
|**V2-19**|`bundle_v2_correctness.md:47`|`mail_core/blobs/store.py:74-81`|**High**|**真实存在**|磁盘文件路径仅含 digest，切 key_version 后同 hash 新邮件返回活跃 version，数据库两行共享文件，旧行 GC 时物理删除该共享文件。|
|**V2-20**|`bundle_v2_correctness.md:49`|`mail_core/blobs/gc.py:34-54`|**Medium/High**|**真实存在 (模型缺陷)**|GC 仅统计 `MessageBlobLink`，漏掉 `Attachment.blob_id`。因上游缺解析器暂无附件数据，当前未达，但模型缺陷客观存在。|
|**V2-21**|`bundle_v2_correctness.md:51`|`mail_core/blobs/gc.py:126-131`|**High**|**真实存在**|GC 提交 DB 删除到 unlink 文件无互斥锁，期间同 hash 新归档复用该文件并提交，紧接着文件被 GC 删掉导致活记录悬空。|
|**V2-22**|`bundle_v2_correctness.md:53`|`mail_core/backup/package.py:199-213`|**High**|**真实存在**|pg_dump 与 blobs.tar 打包之间无一致性快照屏障，期间若发生 GC 到期 unlink，备份得到的 dump 包含 blob 记录而 tar 实际缺失。|
|**V2-23**|`bundle_v2_correctness.md:55`|`mail_core/api/http_headers.py:24-28`|**High**|**真实存在**|中文附件名未在 fallback 中剥除中文，返回 `filename="中文.pdf"`，Starlette 响应头按 latin-1 编码抛 UnicodeEncodeError (500)。|
|**V2-24**|`bundle_v2_correctness.md:59`|`frontend/src/components/Sidebar.tsx:40`|**Medium**|**真实存在**|存在任意分组时只 map 组内成员，`group_id=null` 的未分组账户在侧边栏导航中彻底消失无法访问。|
|**V2-25**|`bundle_v2_correctness.md:61`|`frontend/src/components/ColumnResize.tsx:18`|**Medium**|**真实存在**|onPointerDown 闭包捕获初次渲染的 onDrag 回调，鼠标连续拖动时 width 永远基于初始值计算，宽度无法累加。|
|**V2-26**|`bundle_v2_correctness.md:63`|`desktop/startup.js:169-205`|**Medium**|**真实存在**|softKill 发送信号后 Node 立即设置 `child.killed=true`，被 hardKill 误判为退出直接 return，Windows taskkill /F 与 Unix 强杀永不执行。|
|**V2-27**|`bundle_v2_correctness.md:65`|`frontend/src/hooks/useMailCoreRealtime.ts:23`|**Medium**|**真实存在**|SSE 只失效 `['mail-core']` 列表，不失效 `['detail','mail-core',id]` 详情缓存，服务端主题或正文更新后，阅读器持续显示旧内容。|
|**V2-28**|`bundle_v2_correctness.md:67`|`mail_core/accounts/service.py:81`|**Medium**|**真实存在**|API 保存 `sync_enabled=false`，但 worker 和 delta 调度完全不检查该字段，已排队任务每 30 秒无限继续轮询访问已禁用账户。|
|**V2-29**|`bundle_v2_correctness.md:69`|`mail_core/accounts/service.py:112`|**Medium**|**真实存在**|`enqueue_account_sync` 设置 `sync_status='running'`，同步结束或失败没有任何代码将其改回 idle，前端设置页永久显示 running。|
|**V2-30**|`bundle_v2_correctness.md:71`|`mail_core/blobs/archive.py:324`|**Medium**|**真实存在**|一批 20 封邮件若因临时断网全下载失败，completed=0 导致无续批 job，重试机制失效，后续邮件饿死。|
|**V2-31**|`bundle_v2_correctness.md:73`|`mail_core/backup/package.py:471`|**Medium**|**真实存在**|验证器仅循环 manifest 中声明的项，若 `members={}` 为空字典，校验器返回 ok=True，无法确保 postgres.dump 真实存在。|
|**V2-32**|`bundle_v2_correctness.md:75`|`mail_core/backup/package.py:136`|**Medium**|**真实存在**|空 MANIFEST.sha256 导致 `read_text().split()[0]` 抛 IndexError 崩溃，无法返回结构化验证失败结果。|
|**V2-33**|`bundle_v2_correctness.md:77`|`mail_core/backup/package.py:248`|**Medium**|**真实存在**|同一目录切换加密模式后，残留旧 `backup.kkbak` 文件，校验器优先检查 kkbak 分支导致明文备份校验失败。|
|**V2-34**|`bundle_v2_correctness.md:79`|`mail_core/providers/imap.py:46`|**Medium**|**真实存在**|`_decode_header` 解码遇到未知字符集抛 `LookupError` 未捕获，单封异常邮件直接导致整个文件夹同步失败中断。|
|**V2-35**|`bundle_v2_correctness.md:81`|`mail_core/providers/imap.py:144`|**Medium**|**真实存在**|IMAP LIST 返回大写 `Inbox` 时被标为 other，且 `remote_id.upper()=="INBOX"` 阻止补建，导致该账号收件箱邮件丢失。|
|**V2-36**|`bundle_v2_correctness.md:83`|`mail_core/sync/delta.py:100`|**Medium**|**真实存在**|同页多个同 remote_id 的 upsert 未合并折叠，第二个相同 ID 创建位置触发 `uq_message_locations` 唯一约束冲突报错。|

______________________________________________________________________

### 3. 契约、类型与环境破坏 (V3 Contracts)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v3_contracts.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V3-01**|`bundle_v3_contracts.md:13`|`sync/engine.py` / `archive.py`|**High**|**真实存在**|正文/附件生产断链（同 V2-02 + V2-03）。元数据入库后无归档调度，无生产 MIME 解析器。|
|**V3-02**|`bundle_v3_contracts.md:15`|`docker-compose.mail-core.yml:45-99`|**High**|**真实存在**|Compose 仅 postgres 挂卷，api 与 worker 容器未挂载共享持久化 blob 卷，跨容器读取附件 404 且重启丢失。|
|**V3-03**|`bundle_v3_contracts.md:17`|`mail_core/providers/factory.py:53-65`|**High**|**真实存在**|API 存入的 credentials JSON 字典被整体 dumps 存储，factory 获取后直接作为 IMAP 密码发给 LOGIN，登录必失败。|
|**V3-04**|`bundle_v3_contracts.md:19`|`frontend/src/components/SettingsModal.tsx:98`|**High**|**真实存在**|设置页添加 IMAP 账户只有 email/credentials，无 host/port 输入，后端 factory 强制校验缺失报 ValueError。|
|**V3-05**|`bundle_v3_contracts.md:21`|`mail_core/accounts/service.py:28-42`|**High**|**真实存在**|同邮箱重复创建账户，`put_secret` 独立事务提前覆盖凭据，主表 flush 触发 email 唯一约束回滚，已有账号凭据被毁。|
|**V3-06**|`bundle_v3_contracts.md:23`|`mail_core/providers/graph.py:44`|**High**|**真实存在**|同 V2-15。Graph v1.0 不存在 role / wellKnownName 字段，真实收件箱全被标为 other。|
|**V3-07**|`bundle_v3_contracts.md:25`|`mail_core/providers/graph.py:88`|**High**|**真实存在**|同 V2-16。Graph list_folders 缺少分页 nextLink 与递归 childFolders。|
|**V3-08**|`bundle_v3_contracts.md:27`|`gmail.py:312` / `graph.py:204`|**High**|**真实存在**|对账逻辑直接向 Google/Microsoft REST 端点发送内部自造伪动词 `RECONCILE`，必报 HTTP 405/400 失败。|
|**V3-09**|`bundle_v3_contracts.md:29`|`mail_core/providers/gmail.py:240`|**High**|**真实存在**|同 V2-10。Gmail historyTypes 传单逗号字符串导致 400。|
|**V3-10**|`bundle_v3_contracts.md:31`|`parsing/gmail_history.py:64`|**High**|**真实存在**|同 V2-11。Gmail History ID stub 伪造空元数据未补全 messages.get。|
|**V3-11**|`bundle_v3_contracts.md:33`|`parsing/gmail_history.py:73`|**High**|**真实存在**|同 V2-12。Gmail 增量忽略 INBOX/STARRED 目录标签增删。|
|**V3-12**|`bundle_v3_contracts.md:35`|`mail_core/providers/base.py:23`|**High**|**真实存在**|同 V2-17。统一元数据缺少 is_flagged 导致已有星标丢失。|
|**V3-13**|`bundle_v3_contracts.md:37`|`mail_core/blobs/rotate.py:64-69`|**High**|**真实存在**|密钥轮换 run_rewrap 仅遍历 `.blob` 文件，遗漏 CredentialSecret 表，退休旧 key 导致账户凭据无法解密。|
|**V3-14**|`bundle_v3_contracts.md:39`|`mail_core/security/auth.py:209-217`|**High**|**真实存在**|Compose 改密仅改内存 `_password_hash`，无文件卷，容器重启重新读取环境变量旧密码。按决策采用方案 A 写入数据库。|
|**V3-15**|`bundle_v3_contracts.md:41`|`mail_core/providers/gmail.py:198`|**High**|**真实存在**|同 V2-14。Gmail baseline 扫描结束后才取 profile historyId 产生空窗。|
|**V3-16**|`bundle_v3_contracts.md:43`|`parsing/gmail_history.py:93`|**High**|**真实存在**|同 V2-13。Gmail History 分页提前推进 startHistoryId。|
|**V3-17**|`bundle_v3_contracts.md:47`|`mail_core/providers/base.py:36-37`|**Medium**|**真实存在**|DTO 包含 `to_addresses`/`cc_addresses`，但三个真实 provider 从未解析填充，阅读器收件人始终为空。|
|**V3-18**|`bundle_v3_contracts.md:49`|`mail_core/accounts/settings_store.py:9`|**Medium**|**真实存在**|设置页保存时区和拉信超时返回成功，但全库无任何底层消费逻辑，配置完全无效。|
|**V3-19**|`bundle_v3_contracts.md:51`|`mail_core/api/accounts.py:52-80`|**Medium**|**真实存在**|API schema 缺少字段长度约束与 provider 枚举限制，超长参数或未处理约束直接导致 500 报错。|
|**V3-20**|`bundle_v3_contracts.md:53`|`mail_core/mail/application/search.py:45`|**Medium**|**真实存在**|搜索结果返回 `next_offset > 10000`，而路由限制 `offset <= 10000`，前端翻页直接触发 422 报错。|
|**V3-21**|`bundle_v3_contracts.md:55`|`mail_core/api/mail.py:72-74`|**Medium**|**真实存在**|文件夹统计响应声明为 `list[dict]`，OpenAPI schema 丢失字段定义与非负计数契约。|
|**V3-22**|`bundle_v3_contracts.md:57`|`mail_core/api/sse.py:112-119`|**Medium**|**真实存在**|OpenAPI 将 `/api/events` 声明为 `application/json`，与实际 `text/event-stream` 冲突，客户端解析挂起。|
|**V3-23**|`bundle_v3_contracts.md:59`|`mail_core/api/deps.py:16-63`|**Medium**|**真实存在**|OpenAPI 模式缺少 SecuritySchemes 定义，生成客户端将受保护业务路由误当无认证接口。|

______________________________________________________________________

### 4. 性能与资源隐患 (V4 Performance)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v4_performance.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V4-01**|`bundle_v4_performance.md:13`|`blobs/quota.py:38` / `archive.py:235`|**High**|**真实存在**|每归档一封邮件都执行全盘 `os.walk` 和 `stat()`，无配额同样遍历，$O(N^2)$ 累加 I/O 导致归档严重卡死。|
|**V4-02**|`bundle_v4_performance.md:15`|`mail_core/blobs/gc.py:37-42`|**High**|**真实存在**|GC 载入所有 blob 执行单条未加索引的 count 查询（$N+1$ 次 SQL），`MessageBlobLink` 缺少 `blob_id` 索引。|
|**V4-03**|`bundle_v4_performance.md:17`|`mail_core/providers/imap.py:176-184`|**High**|**真实存在**|每次分页 SEARCH 拉取全部剩余 UID，在 Python 内存中全量分割后再切前 50 个，大邮箱重复消耗巨额网络与内存。|
|**V4-04**|`bundle_v4_performance.md:19`|`mail_core/backup/package.py:260, 412`|**High**|**真实存在**|加密备份与验证使用 BytesIO 把数 GB 的 dump 与 blob 一次性压入单块内存，极易导致进程被系统 OOM Kill。|
|**V4-05**|`bundle_v4_performance.md:21`|`mail_core/search/index.py:40-46`|**High**|**真实存在**|OR 条件中使用 `similarity(from_text, :q) > 0.3` 无法走 GIN 索引，导致全文检索退化为全表扫描。|
|**V4-06**|`bundle_v4_performance.md:23`|`realtime/dispatcher.py:141-158`|**High**|**真实存在**|任一订阅者队列满导致整个 batch 不被标记为已分发，dispatcher 重复拉取前 100 条，造成快客户端全局队头阻塞。|
|**V4-07**|`bundle_v4_performance.md:25`|`mail_core/sync/reconcile.py:112-121`|**High**|**真实存在**|对账结束仅为计算总数与未读数，直接无分页加载整个文件夹全部 Message ORM 实体到内存算 len/sum。|
|**V4-08**|`bundle_v4_performance.md:29`|`mail_core/sync/metadata.py:165-167`|**Medium**|**真实存在**|首次同步每增加 50 封邮件就重新执行全目录 SQL aggregate 统计，导致累计重复处理 $O(N^2/50)$ 行。|
|**V4-09**|`bundle_v4_performance.md:31`|`mail_core/threading/rules.py:159-172`|**Medium**|**真实存在**|References 向上逐个查找父邮件，messages 表缺少 `(account_id, internet_message_id)` 索引，引发频繁账户级扫表。|
|**V4-10**|`bundle_v4_performance.md:33`|`mail_core/providers/gmail.py:176-190`|**Medium**|**真实存在**|Gmail 和 IMAP 元数据逐封串行发送网络请求，50 封邮件叠加 50 个 RTT，慢网络极易超出 120 秒租约。|
|**V4-11**|`bundle_v4_performance.md:35`|`mail_core/api/sse.py:142-169`|**Medium**|**真实存在**|SSE 长连接内部 `seen` 集合永久追加每个事件 ID 无清理，连接存活期间内存无界增长。|
|**V4-12**|`bundle_v4_performance.md:37`|`frontend/src/components/MessageList.tsx:42`|**Medium**|**真实存在**|搜索输入框未加 debounce 防抖，从第二字符开始逐字触发后端全表检索与 count 查询。|
|**V4-13**|`bundle_v4_performance.md:39`|`hooks/useMailCoreRealtime.ts:23-25`|**Medium**|**真实存在**|每条 SSE 立即无差别调用 `invalidateQueries(['mail-core'])`，批量操作产生海量并发请求风暴。|
|**V4-14**|`bundle_v4_performance.md:41`|`mail_core/sync/jobs.py:114-120`|**Medium**|**真实存在**|每 30 秒轮询持续创建 worker_jobs，已完成的 DONE/FAILED 任务无 TTL 自动清理，导致数据库长期膨胀。|
|**V4-15**|`bundle_v4_performance.md:43`|`mail_core/blobs/archive.py:62-75`|**Medium**|**真实存在**|归档任务认领查询按 state 过滤和时间排序，但 `MessageArchiveState` 缺少针对 pending/in_progress 的 partial 索引。|
|**V4-16**|`bundle_v4_performance.md:45`|`desktop/startup.js:178-211`|**Medium**|**真实存在**|同 V2-26。child.killed 误判导致退出流程跳过 taskkill /F 与 SIGKILL。|
|**V4-17**|`bundle_v4_performance.md:47`|`mail_core/sync/metadata.py:144-164`|**Medium**|**真实存在**|每页 metadata 虽有批量查找，但后续 search/thread 投影仍在循环中逐封 SELECT + flush，放大了往返延迟。|

______________________________________________________________________

### 5. 架构与可维护性 (V5 Architecture)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v5_architecture.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V5-01**|`bundle_v5_architecture.md:9`|`mail_core/providers/oauth.py:207-232`|**Low**|**真实存在**|遗留未使用的 `build_gmail_api_transport` 与 `build_graph_api_transport`，且默认抛异常，与生产 factory 形成死代码分叉。|
|**V5-02**|`bundle_v5_architecture.md:10`|`__pycache__/email.cpython-313.pyc:1`|**Low**|**真实存在**|已删除模块的 Python 字节码缓存仍被 git 追踪提交，违反干净工作区与不提交构建缓存的规范。|

______________________________________________________________________

### 6. 健壮性与可观测性 (V6 Robustness)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v6_robustness.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**R01**|`bundle_v6_robustness.md:11`|`mail_core/sync/remote_push.py:58-68`|**High**|**真实存在**|同 V2-04。出站队列只取 20 条无续批，CLAIMED 去重吞掉新唤醒，导致大量待办操作永久遗留。|
|**R02**|`bundle_v6_robustness.md:14`|`mail_core/sync/remote_push.py:67, 132`|**High**|**真实存在**|同 V2-06。批次快照复制 desired_state，网络返回后无条件标 DONE，API 发生的新意图被旧结果覆盖。|
|**R03**|`bundle_v6_robustness.md:17`|`mail_core/sync/remote_push.py:117-142`|**High**|**真实存在**|任何瞬时网络失败（429/5xx）直接将操作标为 FAILED 并不再重试，本地已删邮件直接孤立在远端。|
|**R04**|`bundle_v6_robustness.md:20`|`mail_core/sync/jobs.py:59-78`|**High**|**真实存在**|任务去重先 SELECT 无结果再 INSERT，并发操作触发唯一索引异常，导致本地邮件修改一同被回滚抛 500。|
|**R05**|`bundle_v6_robustness.md:23`|`mail_core/worker/handlers.py:39, 63`|**High**|**真实存在**|所有 handler 捕获 `lease_busy`、`provider_error` 或 `verify_failed` 后直接 return 并把 job 标 DONE，任务静默丢失。|
|**R06**|`bundle_v6_robustness.md:26`|`worker/main.py:83` / `handlers.py:25`|**High**|**真实存在**|Worker 预领 5 个 job 无心跳，超时被其他 worker 抢占后，旧 worker 继续执行并冒用新 owner 身份，导致租约踢脱。|
|**R07**|`bundle_v6_robustness.md:29`|`mail_core/blobs/archive.py:333-340`|**High**|**真实存在**|同 V2-02。归档调度只有自身完成后的自我续批，无首次唤醒入口。|
|**R08**|`bundle_v6_robustness.md:32`|`mail_core/blobs/archive.py:270, 323`|**High**|**真实存在**|同 V2-30。归档整批全失败时无续批任务，且混合成功批次无退避重试，瞬时断网即可耗尽重试次数。|
|**R09**|`bundle_v6_robustness.md:35`|`mail_core/blobs/archive.py:131, 233`|**High**|**真实存在**|配额超限迁至 ARCHIVE_PAUSED_QUOTA 后无任何恢复通道，清理磁盘或提高配额后依然永久暂停。|
|**R10**|`bundle_v6_robustness.md:38`|`mail_core/blobs/archive.py:176, 233`|**High**|**真实存在**|归档占用 120 秒租约，网络下载期间从不续期心跳，大邮件下载易触发过期并被其他任务抢占。|
|**R11**|`bundle_v6_robustness.md:41`|`mail_core/blobs/archive.py:272-283`|**High**|**真实存在**|归档失败写回不校验 fencing 与 claimed_by，超时重领后旧 worker 会撤销新 worker 的 claim。|
|**R12**|`bundle_v6_robustness.md:44`|`blobs/gc.py:126` / `store.py:78`|**High**|**真实存在**|同 V2-21。GC commit 到 unlink 之间无锁，与同 digest 新归档产生竞态，活文件被删。|
|**R13**|`bundle_v6_robustness.md:47`|`mail_core/backup/package.py:199, 269`|**High**|**真实存在**|备份原地覆盖固定输出目录，写盘失败或断电会截断损坏上一份成功的备份副本。|
|**R14**|`bundle_v6_robustness.md:50`|`mail_core/backup/package.py:471-479`|**High**|**真实存在**|同 V2-31。备份验证器接受空 manifest 报告成功，无法保证关键数据库转储存在。|
|**R15**|`bundle_v6_robustness.md:53`|`frontend/src/api/client.ts:65, 154`|**High**|**真实存在**|HTTP timeoutMs 未覆盖 CSRF 获取和登录，网络悬挂时所有写请求无期限等待挂起。|
|**R16**|`bundle_v6_robustness.md:56`|`desktop/startup.js:193-197`|**High**|**真实存在**|同 V2-26。child.killed 误判导致 Windows taskkill /F 与 Unix 强杀永远无法执行。|
|**R17**|`bundle_v6_robustness.md:61`|`realtime/dispatcher.py:141-159`|**Medium**|**真实存在**|多 API 进程时，单一进程抢占 outbox row 标记已发，其余 API 进程上的 SSE 连接永久漏实时事件。|
|**R18**|`bundle_v6_robustness.md:64`|`realtime/dispatcher.py:114-120`|**Medium**|**真实存在**|全局事件（account_id=None）在实时分发中漏掉带 account_id 过滤的订阅者，导致实时遗漏。|
|**R19**|`bundle_v6_robustness.md:67`|`mail_core/backup/package.py:168-173`|**Medium**|**真实存在**|pg_dump 未配置总超时、连接超时与锁等待上限，外部阻塞可永久占死 worker 任务流。|
|**R20**|`bundle_v6_robustness.md:72`|`mail_core/sync/leases.py:118-125`|**Info**|**保持观察**|fencing 检查与后续写入是否存在 TOCTOU，当前已有 FOR UPDATE 保护，未证实为确定 bug。|

______________________________________________________________________

### 7. 测试规格与真实性 (V7 Tests)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v7_tests.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**V7-01**|`bundle_v7_tests.md:11`|`tests/test_gmail_graph_contracts.py:266`|**High**|**真实存在**|Graph 文件夹测试人工注入 role 和 wellKnownName，通过测假响应掩盖了生产 v1.0 收件箱不可见的严重缺陷。|
|**V7-02**|`bundle_v7_tests.md:13`|`tests/test_gmail_graph_contracts.py:74`|**High**|**真实存在**|Gmail History 测试给 stub 塞入完整邮件 payload，掩盖了生产代码未调用 messages.get 导致标题为空的缺陷。|
|**V7-03**|`bundle_v7_tests.md:15`|`tests/test_accounts_api_pg.py:28-54`|**High**|**真实存在**|账号生命周期测试全走 memory，真实 IMAP 添加入口从未被测试覆盖，掩盖了 UI 缺参数和密码被传为 JSON 的问题。|
|**V7-04**|`bundle_v7_tests.md:19`|`tests/test_oauth_transport.py:121`|**Low**|**真实存在**|Gmail 工厂测试返回 Graph 响应断言成功，断言完全未保护 Gmail History 的真实协议解析。|
|**V7-05**|`bundle_v7_tests.md:21`|`tests/test_remote_ops_reconcile.py:28`|**Low**|**真实存在**|对账集成测试统一 mock 为 MemoryProvider，未覆盖 Gmail/Graph 发送自造 RECONCILE 动词的真实 HTTP 边界。|
|**V7-06**|`bundle_v7_tests.md:23`|`tests/test_imap_provider_live.py:24`|**Low**|**真实存在**|L2 真实 IMAP 协议测试在 Dovecot 不可用时静默 skip，未纳入强制测试流水线。|

______________________________________________________________________

### 8. 文档、规范与发布说明 (V8 Docs)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_v8_docs.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**DOC-01**|`bundle_v8_docs.md:12`|`docs/upgrade.md:17`|**High**|**真实存在**|文档要求 run_rewrap 完成即可退休旧 key，遗漏凭据表导致密码无法解密。|
|**DOC-02**|`bundle_v8_docs.md:14`|`docs/upgrade.md:5-9`|**High**|**真实存在**|独立 Python 备份命令未加载环境与 bootstrap，且镜像缺 pg_dump，会生成空明文备份。|
|**DOC-03**|`bundle_v8_docs.md:16`|`docs/upgrade.md:14-17`|**High**|**真实存在**|通用 downgrade 提示未说明 0002 迁移会破坏性删除 messages/accounts 核心表。|
|**DOC-04**|`bundle_v8_docs.md:18`|`RELEASE.md:7-8`|**High**|**真实存在**|发布文档仍宣称推送 tag 触发 GitHub Actions（远程工作流已全部删除）。|
|**DOC-05**|`bundle_v8_docs.md:22`|`docs/upgrade.md:10-12`|**Medium**|**真实存在**|Compose 升级仅给 build 命令，未重新运行 migrate 或重启容器，返回旧 schema 200 假象。|
|**DOC-06**|`bundle_v8_docs.md:24`|`docs/upgrade.md:9`|**Medium**|**真实存在**|所谓“恢复演练脚本”固定无效 DB 且允许 sql_stub，从不执行真实 pg_restore。|
|**DOC-07**|`bundle_v8_docs.md:26`|`docs/deployment.md:35-42`|**Medium**|**真实存在**|拆分 API/worker 示例未给出 `--data-dir` 与共享密钥配置，独立 worker 无法加载密钥。|
|**DOC-08**|`bundle_v8_docs.md:28`|`docs/deployment.md:25-31`|**Medium**|**真实存在**|TLS 部署宣称设置环境变量即可，但 Compose 未把 `MAIL_CORE_COOKIE_SECURE` 传入 API。|
|**DOC-09**|`bundle_v8_docs.md:30`|`RELEASE.md:7-20`|**Medium**|**真实存在**|发版说明只改 VERSION，桌面 `package.json` (3.0.20) 与后端 `__init__.py` (0.1.0) 不会跟随。|
|**DOC-10**|`bundle_v8_docs.md:32`|`desktop/README.md:19-23`|**Medium**|**真实存在**|说明声称父进程 secrets 不会继承，但实现对 `MAIL_CORE_*` 白名单全盘继承。|
|**DOC-11**|`bundle_v8_docs.md:34`|`RELEASE.md:26-30`|**Medium**|**真实存在**|发版示例使用 `git commit -am`，容易将用户未暂存的无关修改打包进 release。|
|**DOC-12**|`bundle_v8_docs.md:36`|`docs/deployment.md:33-42`|**Medium**|**真实存在**|非 Docker 部署未提 SPA 构建步骤，直接启动访问同源前端报 404。|
|**DOC-13**|`bundle_v8_docs.md:40`|`docs/mail-core-status.md:7`|**Low**|**真实存在**|状态页仍把 schema head 记录为 0007（实际已到 0009）。|
|**DOC-14**|`bundle_v8_docs.md:42`|`docs/troubleshooting.md:32`|**Low**|**真实存在**|忘记密码指引寻找 `secrets/initial-password.txt`（实际在 data-dir 根目录）。|
|**DOC-15**|`bundle_v8_docs.md:44`|`docs/api.md:42-46`|**Low**|**真实存在**|检查命令连续执行 `cd frontend` 导致工作目录错误失败。|
|**DOC-16**|`bundle_v8_docs.md:46`|`docs/api.md:49-53`|**Low**|**真实存在**|认证例外清单称只有 health/ready/login，与实际公开的 /docs, /openapi.json, SPA 冲突。|
|**DOC-17**|`bundle_v8_docs.md:48`|`docs/mail-core-desktop.md:78`|**Low**|**真实存在**|KKMAIL_PACK_STRICT=1 并不能将所有构建失败转为硬失败（缺 builder/PG 仍 exit 0）。|
|**DOC-18**|`bundle_v8_docs.md:50`|`docs/mail-core-architecture.md:139`|**Low**|**真实存在**|拓扑仍称 web/worker/postgres，与实际 api/worker/postgres/migrate 命名分叉。|
|**DOC-19**|`bundle_v8_docs.md:52`|`docs/security.md:75-83`|**Low**|**真实存在**|备份与能力模型在 security.md 与 upgrade.md/architecture.md 双重定义且发生漂移。|
|**DOC-20**|`bundle_v8_docs.md:54`|`mail_core/accounts/settings_store.py:10`|**Low**|**真实存在**|注释写写入时忽略未知字段，实际实现是抛出 ValueError (400)。|
|**DOC-21**|`bundle_v8_docs.md:56`|`mail_core/blobs/rotate.py:3-6`|**Low**|**真实存在**|docstring 宣称“每个文件后都 commit”，实际带外部 session 分支只 flush 不 commit。|
|**DOC-22**|`bundle_v8_docs.md:58`|`CHANGELOG.md:1279-1293`|**Low**|**真实存在**|历史 2.0.0 早期版本被批量追加入后来的修复记录，版本历史失真。|

______________________________________________________________________

### 9. 主任务补查 (Followups)

> **源头文件**：`docs/reviews/review_20261021_040521/bundle_parent_followups.md`

|ID|源头定位|目标文件及行号|级别|真实性状态|技术实质与危害|
|:---|:---|:---|:---:|:---:|:---|
|**FOL-01**|`bundle_parent_followups.md:9`|`mutations.py:197-206`|**Medium**|**真实存在**|trash 在 DELETE flush 前执行 SQL aggregate 重算目录计数，由于禁用 autoflush，统计仍包含已删邮件。|
|**FOL-02**|`bundle_parent_followups.md:11`|`frontend/src/components/MessageList.tsx:204`|**Medium**|**真实存在**|多选框聚焦时按空格键冒泡到整行，触发 openMessage 展开邮件并误标已读，多选勾选失效。|
|**FOL-03**|`bundle_parent_followups.md:13`|`desktop/main.js:173-187`|**Medium**|**真实存在**|macOS 关闭唯一窗口后进程驻留，Dock 点击缺少 `activate` 事件监听，无法重新打开主窗口。|
|**FOL-04**|`bundle_parent_followups.md:15`|`frontend/src/api/queries.ts:103-110`|**Medium**|**真实存在**|findCachedMail 遍历所有 query 缓存直接取首个命中项，旧列表缓存可能覆盖当前视图的新状态。|

______________________________________________________________________

## 四、 修复执行路线图（Roadmap）

### 第一批（P0 紧急安全阻断）

1. **修复 SPA 目录逃逸** (`mail_core/api/app.py:155-164` / V1-01)
2. **启用 IMAP TLS 证书严格校验** (`mail_core/providers/imap.py:123-129` / V1-02)
3. **落实 IMAP 删除安全阻断** (`mail_core/providers/imap.py:469-481` / V2-01)
4. **历史凭据标记确认** (V1-03)

### 第二批（P1 业务核心断链打通）

1. **归档调度与生产 MIME 解析器接通** (V2-02, V2-03, V3-01)
2. **Compose 共享持久化卷挂载** (V3-02)
3. **IMAP 前端输入与密码 JSON 解包修复** (V3-03, V3-04)
4. **Graph 与 Gmail 协议适配器修复** (V2-10, V2-11, V2-12, V2-15, V2-16, V3-08)

### 第三批（P2 密码数据库化、状态机与 GC 健壮性）

1. **密码 Hash 写入 PostgreSQL（方案 A 落地）** (V3-14)
2. **出站推送状态机与自动续批** (V2-04, V2-05, V2-06, R03, R04, R05)
3. **GC 附件引用与文件安全锁** (V2-19, V2-20, V2-21)
4. **备份一致性与中文 Header 修复** (V2-22, V2-23)

### 第四批（P3 性能治理、交互体验与文档校准）

1. **性能瓶颈清理**（配额累加计数、索引补充、IMAP SEARCH 分页）(V4-01 ~ V4-17)
2. **前端与桌面交互体验修补** (V2-24, V2-25, V2-26, FOL-01 ~ FOL-04)
3. **测试 Fixture 与文档勘误** (V7-01 ~ V7-06, DOC-01 ~ DOC-22)
