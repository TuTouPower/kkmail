# 提交审阅问题修复技术方案

状态：已实施（2026-10-26）。R01–R18 与 p053–p057 全部按本方案落地，实现完成点为提交 `cd90a5ca`（其后为收尾 docs 提交）；验证结果记于 `docs/handoff.md` 最新一节。两项有意偏差：① p055 的收敛只作用于前端新增入口，后端经 API 直接创建 `provider=gmail` 未封堵，留待产品裁决；② 测试门禁在本机以 unit 模式运行（沙箱无 Docker、PG 运行时不可用），PG 门控与真实 E2E 未在本机执行，另有 2 项后端测试因沙箱 DNS 将测试域名解析进受限网段触发 SSRF 守卫而失败，属环境问题、测试未改动。

基线：`820781e5`。问题编号与证据以同目录 [review_report.md](review_report.md) 为准。本方案覆盖 R01–R18；不直接创建 backlog task、执行迁移或部署。

## 1. 修复边界与成功标准

沿用现有约定，不增加产品功能：

- 列表刷新触发当前 scope 的增量同步；设置页触发全量元数据重扫及完成后的远端对账。
- 全量请求完成不等待正文、附件重新下载；已有原文、正文、本地读写意图保持有效，未归档正文由独立归档队列推进。
- 同账号已有全量扫描时复用其扫描 generation，避免重复清空在途游标；请求会显示现有扫描进度。增量请求命中已 claimed 的作业时，等待真正的后继执行，不把旧执行完成误认为新请求完成。
- 全局邮件供应商连接预算 8 个，后台归档最多占用其中 6 个；请求、Outbox 结果保留期沿用 7 天。
- 复用 PostgreSQL、SQLAlchemy、现有队列、TanStack Query 与 API 客户端；不引入新调度服务、消息中间件或第二套前端传输层。

成功标准：18 项问题都有生产逻辑回归覆盖；当前隔离测试全部执行完，不再排除那 6 项 SSE 流式用例；前端、数据库结构、后端、桌面及项目规定的真实端到端门禁通过。环境条件不足的项目单列，不能将未执行记为通过。

## 2. 工作包与问题映射

|工作包|问题|主要修改|专项验收|
|---|---|---|---|
|A 请求入口与前端隔离|R01、R02、R09、R10、R15|统一传输、UUID、scope、阅读器请求身份|真实 Cookie/CSRF；单账号 202；各角色；A→B→A 迟到结果|
|B 归档所有权与失败收敛|R04、R05、R18|行锁及 revision 校验、心跳、统一错误和配额状态|双会话竞争、配额、构造失败、崩溃回收|
|C 同步执行跟踪及全量生命周期|R06、R08|有限执行与周期轮询分离、关系型作业绑定、扫描 generation|共享任务、后继、分页、发现/重扫/对账全链路|
|D 前端权威进度|R07|查询请求终态、SSE 失效、可见性及 scope 隔离|正常完成、失败、断流、重载、切 scope|
|E 真实 I/O 连接准入|R11|IMAP session、HTTP 单次连接、OAuth 刷新接入 permit|真实多进程计数服务器；8/6 上限；取消和异常释放|
|F 安全跨卷恢复|R12|目标卷暂存、先 Blob 后 DB、操作日志及恢复检查|真实跨文件系统恢复、失败与中断演练|
|G Outbox 保留期与结构一致性|R13、R14|发布游标清理水位、过期重放提示、模型对齐|两 API 广播、7 天清理、小缺口重放、零 drift|
|H 账号锁序|R16|组织锁先于账号行锁，事务内读取旧偏好|组合 PATCH 与布局/OAuth/删除竞争|
|I CI 与回归门禁|R03、R17|解释器、测试契约、存储公共导出、流式结束条件|干净 Python3.13 CI；完整后端和真实 E2E|

## 3. A：请求入口与前端隔离

### 3.1 传输与错误处理（R01）

`use_scope_sync.ts` 的 delta、activity 均调用现有 `postJson`。复用 CSRF singleflight、令牌刷新、401 处理、超时和 ApiError 解析。UI 经现有 `errorMessage` 取可展示文本，不把对象传给 Error 构造器。

自动触发的重复保护、请求 ID、AbortSignal 与进度查询由同一 hook 管理。activity 仅在页面可见且登录有效时上报；失败进入现有脱敏诊断渠道，不产生每 20 秒重复的用户错误横条。

### 3.2 ID 约束（R02、R10）

统一使用 `uuid.uuid4().hex` 作为服务端默认 client_request_id；scope 与 mode 已有独立字段，不再拼接账号 ID。保留数据库 VARCHAR(64)，输入增加 `min_length=1, max_length=64`，超长输入返回 422。补齐 uuid 导入。

同一 ID、相同规范化 scope/mode/trigger 返回同一请求；同一 ID、不同意图返回 409。唯一冲突通过 savepoint 后重读处理，避免并发重试变成 500。

### 3.3 scope（R09）

inbox、sent、drafts、trash、junk 原样映射为 folder_role；unread 映射 inbox 并保留其列表过滤语义。真实文件夹使用精确 folder_id，后端验证所属账号；group 与 account/folder 互斥。空组保持零目标，未知 ID 不退化为全局。

测试覆盖全局分类、账号分类、分组分类、精确文件夹及禁用账号，不能只测两个字符串分支。

### 3.4 阅读器请求身份（R15）

将正文提交的瞬时状态与 `{message_id, request_generation}` 绑定。每次提交生成新的本地序号，选中项变化同步使旧序号失效；请求回调写状态时同时校验当前选中邮件和序号。渲染也按当前邮件筛选状态，避免 effect 清理前短暂显示旧提示。

AbortController 用于取消不再需要的网络等待，generation 校验负责隔离已经到达服务端、无法撤销的请求结果。正文入队已成功时继续在后台执行。A→B→A 也必须区分两次 A 请求，不能只比较邮件 ID。

## 4. B：归档所有权与失败收敛

### 4.1 所有归档写入使用同一 claim（R04）

claim 返回明确的 `ArchiveClaim(message_id, owner, revision, remote_id_snapshot)`。成功、错误、配额暂停、主动释放、心跳都接收该对象，禁止只按 worker_id 判断所有权。

执行边界：

1. 短事务认领，revision 递增，提交后再执行网络。
2. MIME 下载、解析及附件内容摘要计算在业务事务外完成；解析失败仍保留原文及允许保留的部分结果。
3. 发布事务按 Message → MessageArchiveState 顺序加 `FOR UPDATE` 锁，重新校验 state、owner、revision、remote_id。
4. 验证成立后才取得配额和 digest 锁，并原子保存 Blob 引用、正文、附件、归档状态与 Outbox。归档状态行锁一直持有至提交。
5. 验证失败不提交本次派生结果；本次临时内容和配额预留按所有权释放，已发布但无引用的文件交给既有安全 GC。

多个 digest 按稳定顺序取锁；与 quota、GC、消息删除的锁序一起核对，禁止持 digest 锁反向等待消息/归档状态行。已经完成的新 claim 不能被旧 Worker 的成功、失败或 finally 清理覆盖。

对正在处理以及仍属于本批次的 claim 定期续 claimed_at，更新条件包含 revision、owner、state；回收只处理过期 claim，撤销时递增 revision。续期失败的旧执行退出派生提交。保留同账号批次 IMAP 复用，批量大小受现有上限控制，网络期间不持业务行锁。

### 4.2 统一失败与配额分支（R05、R18）

删除失效的 AccountSyncLease/fencing 分支，不重新让正文下载占用扫描租约。使用统一的归档状态结算入口：

|结果|状态与行为|
|---|---|
|本地连接槽不足|短延迟续跑，不计 retry_count/failure_attempts|
|provider 构造或拉取失败|持久化脱敏 last_error、累计对应重试、释放本 claim，并发出目标消息事件|
|MIME 解析失败|保留 raw MIME，记录 parse_error；可读正文按现有契约保留|
|存储 I/O 失败|回滚本次派生事务，另开短事务在有效 claim 下记录归档错误及重试状态|
|硬/软配额拒绝|archive_paused_quota、pause_reason=quota，释放 claim 和本次预留，不计普通网络失败|
|成功|archive_complete，清除历史错误/暂停原因，并发出目标消息事件|

provider 初始化失败不能只恢复 pending；Worker 终态耗尽后，详情必须仍可见错误并允许显式重试。provider/session 与 permit 通过 finally 关闭，覆盖中途 return、异常和取消。

## 5. C：同步执行跟踪与全量生命周期

### 5.1 数据模型采用一个作业绑定表（R06）

继续使用 SyncRequest、SyncRequestTarget，不再建立第二套请求表。补充最少的执行关系：

- WorkerJob 增加唯一、非空 execution_generation UUID。创建作业及新后继时生成；同一作业的失败重试、回收保留该 UUID，认领 attempts 继续区分陈旧执行。
- 新增 `SyncRequestTargetJob`，记录 target_id、execution_generation、job_id（等待后继创建时可空）、phase、folder_id、状态和脱敏结果；唯一键为 `(target_id, execution_generation)`。job_id 删除后置空，已终结的请求结果仍可读取。
- SyncRequestTarget.requested_generation 表示该逻辑同步的根 generation。全量扫描的多个阶段及观察同次扫描的多个请求共享该根 generation。
- SyncCheckpoint 增加可空 scan_generation，判断全量扫描是否已经初始化，避免每次续批再次清空游标。

绑定表解决一个 target 对多个阶段/续批作业、多个请求观察同一个去重作业的关系。不能只让 current_job_id 指向最后一个作业，也不将不断增长的观察者 ID 数组塞进 JSON payload。旧 current_job_id 在迁移完成后移除，公开 API 仍返回既有请求 DTO。

### 5.2 去重、续批与终态

|情况|执行身份与请求行为|
|---|---|
|命中 pending delta 作业|复用该作业 execution_generation，并建立请求绑定|
|命中 claimed delta 作业|在 `_queue_next` 中一次性预分配后继 generation；新请求先绑定该 generation，不绑定当前执行|
|claimed 作业续批|complete_job 在同一事务创建/绑定后继、传递仍未结束的目标、结束当前执行|
|失败后可重试|目标保持未终结并保留进度，作业 generation 不变|
|失败耗尽/账号或文件夹消失|相关目标 failed，持久化稳定 error_code 和脱敏说明|
|delta 已读完本轮分页|结束该请求目标；下一次定时轮询使用独立 generation，不继承观察者|
|已有 full 在执行|在根 generation 锁保护下复用在途扫描，并绑定已有及后续阶段|

请求创建、作业绑定和入队一次提交。分页续批、发现后的子作业入队、阶段收尾在各自短事务内完成，必须先登记后续工作，再允许当前阶段完成，避免瞬间“没有 pending”被误判为全量结束。

Worker 结算锁序固定为 WorkerJob → generation 协调锁 → 绑定行/Target（UUID 升序）→ Request（UUID 升序）。创建/绑定后继沿用相同顺序；持请求/目标锁时不反向等待 WorkerJob。业务 I/O 与此结算事务分开，网络期间不持这些锁。账号/文件夹删除必须先收敛关联流程、再删除实体；实施时与扫描租约、写回及组织事务逐项核对锁序并增加真实竞争测试。

请求计数由 targets 聚合；所有目标结束且全部成功才 complete，有失败且已无未结束目标才 failed。状态与 finished_at 在写入事务中持久化，GET 只读。request 状态变化写 `sync.request_updated` Outbox 事件；job 缺失、丢失后继绑定由 Worker 巡检收敛为明确失败，不长期伪装 running。

### 5.3 全量扫描（R08）

全量 generation 包含文件夹发现 → 每个可选择目录的 metadata 全扫描 → 成功目录的 reconcile。发现完成本身不代表请求完成。

在账号扫描租约保护下，目录首次进入 generation 时重置 cursor、uid_next/MODSEQ/history/delta 相关扫描状态和 full_scan_complete；设置 scan_generation。相同 generation 的重试续用游标。旧 generation 作业即使后来重新取得租约，也不能修改新 generation 的 checkpoint。

metadata 全部成功才设置该目录 full_scan_complete 并排 reconcile；中途超时、容量不足、限流、解析响应失败不能进入删除对账。已有 Message、正文、附件、远端待写意图保持不变，重复 upsert 保持幂等。对账结束及全部子阶段终结后才结束 full target。

delta 基线缺失时关联已有初始化扫描；没有初始化扫描则返回明确 baseline_required，不由列表隐式启动重型全量扫描。新账号初始化统一使用可跟踪的 initialization 请求。

## 6. D：前端权威进度（R07）

保留 TanStack Query，增加 `['sync-request', requestId]` 查询。POST queued/running 后立即开始查询，页面可见且未终结时最多每 2 秒查询一次；收到 sync.request_updated SSE 只失效对应请求。终态停止轮询，成功停转，失败停转并显示可读错误。

网络错误表示“暂时无法取得进度”，不能伪造后台成功或后台终态失败。隐藏页面暂停轮询，恢复可见先读权威状态。按 scope 保存请求 ID，重新显示同一 scope 时恢复；补查询当前 scope 最近未结束请求，最多返回 50 项，支持重载恢复。

切 scope 后旧请求继续执行，其事件更新自己的缓存，不影响新 scope 按钮；相同 scope 的在途请求禁止重复手动提交。界面上的 running boolean 由当前请求状态推导，不单独持久化。

## 7. E：真实 I/O 连接准入（R11）

替换现有基于业务 Session 的 session advisory lock helper：每个活动连接使用一条专用 psycopg autocommit 控制连接，持有一个 slot 锁，释放后关闭。禁止将持 session 锁的连接放回业务连接池，也不能复用同一控制连接递归获取相同可重入锁。

8 个固定槽位，后台归档只能使用 2–7，交互/metadata 可使用 0–7。traffic_class 从实际 job 类型及是否指定 message_id 显式传到 provider/transport，Gmail 并发线程沿用实例参数，不能依赖未传播的线程局部值。

- IMAP：在实际连接建立前取得 permit，认证失败、peer 校验失败、logout、复用 session 关闭时释放；复用 session 始终计一个连接。
- HTTP：每次 urlopen 的连接生命周期取得 permit；重试等待期间释放。Gmail 并行 hydrate 每个请求独立计数，不能只给外层 page 一个 permit。
- token refresh：先完成并释放 refresh 请求 permit，再打开邮件 API 连接，避免嵌套占槽；沿用原有不重放写请求策略。
- 容量不足：保留 ProviderCapacityUnavailable 类型，Worker/delta/archive/remote push 明确延后，不将其转成永久认证错误、业务失败计数或 remote op 终态。

控制连接异常时停止新的供应商 I/O，关闭本执行的远端连接并使工作可续跑。健康控制面下精确验证 8/6 上限；进程 kill、数据库断连单列验证关闭和恢复时间，不将单进程 helper 测试当成生产接入证据。

## 8. F：安全跨卷恢复（R12）

采用“先完整 Blob，后数据库提交”。继续要求独占恢复目标、空数据库和空 Blob 根；恢复期间应用与 Worker 保持停止。

1. 读取并校验备份私有快照、目标数据库身份和目标空状态，申请本恢复操作的独占锁。
2. 在目标 Blob 根内部创建本操作私有 staging，保证与最终文件同一文件系统；先验证所有 tar 成员，再流式解包、fsync 并核对包内校验和。
3. 全部校验成功后，将 staging 中内容逐项发布至空目标的标准路径；目标目录包含 mount point 时也只在其内部 rename。操作日志完成原子写及 fsync 后标记 blobs_published。
4. 执行 pg_restore --single-transaction --exit-on-error。数据库成功时所有 Blob 已就位，不再有后置跨卷发布步骤。
5. 核对 schema、业务关联及 Blob 解密抽样，操作日志标记 complete 后才允许启动应用。

日志只记录 operation_id、包摘要、规范目标路径、数据库 cluster/database 身份和阶段，不保存密码或密钥。DB 失败时保留本操作已发布文件与日志；`resume` 只在身份、包摘要和文件校验全部一致时复用，拒绝覆盖其他文件或恢复到不匹配的非空数据库。

在 DB 提交结果不确定的崩溃窗口，保留全部 Blob，进入 needs_verification；验证前不自动重放恢复，不自动删除数据库。确认数据库仍空可重试；非空目标须核实恢复结果后完成收尾。清理必须指定本操作 ID，并验证所有权。

真正验收使用不同挂载文件系统的测试路径和独立测试库，覆盖 EXDEV 环境；故障注入覆盖每个发布阶段、DB 失败及提交后中断。不能用同文件系统目录测试替代跨卷证据。

## 9. G：Outbox 保留期与结构一致性

### 9.1 结构对齐（R14）

模型登记 ix_outbox_unassigned 的相同 PostgreSQL partial predicate；publication_seq 只保留一个显式唯一索引，移除重复的列级 unique=True。不修改已经应用的 0022 迁移来迎合模型。

迁移 head 测试验证唯一线性 head、历史 revision 可到达 head、升级后数据库与 head 一致。针对旧 0021 的独立测试仍验证其历史作用，不再断言它永远是最新版本。

### 9.2 发布保留期（R13）

清理以 publication_seq 和 published_at 为依据，只删除已发布且超过 7 天的连续序号前缀，每批最多 5,000 行；publication_seq 为 null 的事件不删除。OutboxPublicationState 新增 pruned_through_seq，删除前缀与推进水位同一事务提交。

同 epoch 的客户端游标小于清理水位时，返回 client.resync_hint(reason=retention_gap)，即使距离 head 不超过 500 也不能当作完整重放。空保留窗口、account 过滤及 API 长时间落后同样处理；落后的本地 dispatcher 发出重新取数提示后重建本地游标。

发布序号先提交再广播，避免客户端拿到未提交游标。移除 dispatched_at、旧消费索引及仅服务旧模型的生产 helper，调用点统一使用新保留期服务。此结构变更使用新的线性迁移，不重写历史；保留公开 v2 epoch/seq 游标语义。

## 10. H：账号锁序（R16）

`update_account_app` 在请求可能改变组织或保存 OAuth 时先取组织锁，再锁 Account，锁内读取 prior_sync_enabled，完成配置、凭据与分组更新并发送事件。普通只改同步偏好也必须遵守同一入口的锁域规则，避免早期快照读取先取得 Account 行锁。

组织相关路径统一 sidebar → Account → OAuth 流程/凭据；布局保存、恢复排序、账号移动、OAuth 保存、账号删除一起核对。数据库死锁重试不替代锁序修复。

## 11. I：CI 与测试契约（R03、R17）

CI 导出 OpenAPI、检查依赖及执行后端脚本使用 `.venv/bin/python`，本地文档命令同步，验证环境必须是声明的 Python3.13。项目测试运行时和模板工具链保持原入口。

旧测试处理遵循 TDD 约定：

- 保留仍有效的行为断言；修正 fake Session、作业结算签名、claim_revision 等基础设施适配。
- 旧协议语义已失效的测试整体替换，并说明删除理由；新增 v2 游标、异步正文、请求终态测试，不能仅把旧预期改成现有输出。
- `_ReplayPlan` 显式提供 cursor_seq，LISTEN 测试验证 v2 游标及 publication_seq；存储公共入口补齐四个遗漏模型，不缩小导出完整性断言。
- SSE 单测直接消费可控 body iterator，使用有界 asyncio 等待，finally 关闭 iterator 并验证 slot 归还。真实 HTTP 集成启动本地 ASGI 服务、逐帧读取并主动断开，不让 TestClient 的无限响应阻塞 pytest 收尾。
- 给 6 个原阻塞用例建立确定的结束条件，再恢复默认完整套件；删除为审阅临时使用的排除选择。

本机 rm 包装器问题独立于生产实现。拟让测试 fake python3 只识别确切的 pymap 探测及启动参数，其余参数转交测试已记录的真实 Python，从而不拦截其他工具的解释器；不修改全局包装器，也不将其失败计为生产回归。该测试适配仍需验证 passfile 内容、0600 权限、argv 无秘密及最终清理行为。

## 12. 迁移、执行顺序与恢复

实施顺序及验证屏障：

1. I 的解释器修复、G 的模型对齐、H 锁序修复 → 验证干净解释器导出、零 drift、真实锁竞争。
2. A 与 B → 验证真实会话、单账号请求、迟到结果，以及 claim/配额/初始化失败全部回归。
3. C → 验证去重、claimed 后继、分页、重试、删除、中断和 full generation 全链路；未通过前不把 D 的停转测试解释为后端已完成。
4. D 与 E → 验证浏览器断流/重载恢复及实际跨进程连接峰值。
5. F 与 G 的保留期切换 → 验证真实跨卷恢复、清理水位和多 API 重放。
6. I 的完整门禁 → 全部后端、前端 lint/type/build/schema、桌面及真实 E2E；结果按实际环境记录。

新增结构使用连续的新 Alembic revision，实际编号在实施时按唯一 head 分配。部署按一次维护窗口切换 API、Worker、SPA 到同一版本；本方案不执行发布。

迁移前验证 DB/Blob 备份可恢复并停止旧 Worker。历史邮件、正文、附件、checkpoint 不按猜测重写。已有 queued/running 请求因缺乏可靠执行绑定，迁移时明确标 failed(code=execution_tracking_unavailable)，保留原 ID 和历史；原后台同步作业保留可续跑，去除失效请求关联，不取消共享轮询。新状态不能伪造为历史同步成功。

WorkerJob execution_generation 对现有作业生成唯一 UUID；scan_generation 初始为空，下一次真正全量扫描时建立。新增绑定只服务新可跟踪执行；不从覆盖过的 payload 猜测历史请求所属代次。终结请求按 7 天分批清理，活跃请求不因 TTL 删除。

回退前先停止新进程，验证旧版本能否读取新增状态和字段。不能安全降级时，从验证过的备份恢复至独立目标并切换，禁止直接丢弃未知状态、覆盖原库或删除邮件数据。恢复和清理都必须确认目标身份及所有权。

## 13. 必须通过的验收矩阵

|领域|必须验证的故障/竞争|
|---|---|
|请求入口|Cookie、过期 CSRF、401、超长/省略 ID、并发相同 ID、所有角色及 scope|
|归档|旧执行成功/失败/暂停均不能覆盖新 claim；长下载续期；remote_id 变化；消息删除；配额及存储错误|
|请求进度|共享 pending、claimed 后继、可重试与耗尽、续批、无基线、目标删除、Worker kill，计数最终一致|
|全量|IMAP 旧 UID 被重读；Gmail/Graph 从合法起点重扫；中断续扫；半扫描不删除；全部阶段闭环|
|前端|queued 旋转、终态停转、错误可读、SSE 断流轮询、隐藏/恢复、重载、A→B→A|
|连接|多进程实际网络峰值≤8，后台≤6，前台可用保留槽；失败/取消/kill/DB 断连后资源释放|
|恢复|跨卷、非法 tar、错误密钥、目标身份不符、非空目标、各阶段中断、已发布文件保留和有条件续跑|
|Outbox|发布后广播；小缺口超过清理水位必重取；未发布事件不删；两个 API 都收到；零 schema drift|
|锁序|组合账号 PATCH、布局、OAuth、删除与 Worker 交错，无死锁或旧状态复活|
|门禁|原 6 个流式用例回归默认套件；21 项失败逐项分类解决；不依赖排除参数或主机假设|

## 14. 用户决策

当前没有必须新增的产品裁决。全量范围、正文独立归档、8/6 连接预算、7 天保留期、同账号在途 full 复用均有现有架构或既有技术设计依据；实施按上述规则收敛。

生产部署时间、恢复目标及生产操作授权在实际发布或恢复前核对，本次方案不提前代替这些授权。全局 rm 配置保持原样；测试自身的解释器替身适配纳入 I。
