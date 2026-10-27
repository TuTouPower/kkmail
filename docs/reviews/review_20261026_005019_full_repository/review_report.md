# kkmail 全仓审阅报告

> 状态变更注记（2026-10-27）：本文所称「未修复」为报告基准时点的状态；本包计划已实施完毕，最终状态见同目录 [repair_results.md](repair_results.md)。历史正文不改写。

- 报告时间：`2026-10-26T00:53:50+08:00`。
- 全仓初轮基准：`e825147f`；后端全量验证基于该提交。
- 补审终点：`6f6605b6ab08eb26eb1c375d0e76db3482a66811`。补审包括 `3e142b97` 的剪贴板回退与 `6f6605b6` 的文档归档；前端单元测试已在该终点重跑。
- 文档性质：版本化审阅证据。结论只适用于上述基准，不作为后续版本已经修复或仍未修复的证明。
- 处理状态：未修复、未创建 pending/task，修复方案均为建议；本次仅新增审阅文档。
- 读者：维护者、后续 task 实现者及代码/测试 reviewer。

## 结论与范围

本轮记录 **16 条审阅项：6 条 P1、10 条 P2**。其中 15 条具有实现、配置或运行证据；P2-10 已确认原生 modal 外 textarea 无法获得焦点，**实际系统剪贴板复制结果仍待端到端验证**。静态证据项不标为“目标环境运行通过”。

P1 表示优先处理的数据破坏风险、安全缺口、可靠性缺陷或确定性门禁阻断；不等同于所有条目均可被匿名远程利用。P2 表示条件性功能错误、可观测性偏差或其他质量门禁问题。排序属于审阅建议，不表示已经批准立项。

覆盖后端 API/鉴权、账户与 OAuth、同步/写回/任务、Outbox/SSE、Blob 与备份恢复、模型与迁移；前端缓存、阅读器、导航及新增剪贴板路径；Electron 生命周期与权限、容器/CI、测试及现行文档约定。未审计第三方依赖源码，未执行生产操作、跨平台人工验证、真实供应商 OAuth、严格桌面打包或真实全栈 E2E。

本报告不是逐行无缺陷证明。通过的测试证明各自断言在运行快照成立，不能替代本文列出的缺失边界。完整执行记录、失败分类、复现步骤与剩余验证范围见 [验证与复现证据](review_evidence.md)。

## 问题总览

|编号|级别|问题|主要证据|状态|
|---|---|---|---|---|
|P1-01|P1|备份恢复允许越过 Blob 目标目录覆盖文件|reproduce.py::restore_escape；真实文件校验/解包，pg_restore 替身|已取得相应复现/运行证据|
|P1-02|P1|“禁止覆盖源库”检查被数据库用户名变化绕过|reproduce.py 中 \_restore_database_identity 对比；仅验证保护判定|已取得相应复现/运行证据|
|P1-03|P1|去重任务完成与新唤醒并发时会丢任务|test_review_probe_lost_job_wakeup；真实 PostgreSQL 两会话|已取得相应复现/运行证据|
|P1-04|P1|SSE 将序列 ID 当提交顺序，丢失较晚提交事件|test_review_probe_outbox_commit_order；真实 PostgreSQL 两事务|已取得相应复现/运行证据|
|P1-05|P1|provider 异常 traceback 泄露通用 token 值|reproduce.py 中真实 LogRecord / RedactingTraceFormatter 探针|已取得相应复现/运行证据|
|P1-06|P1|desktop CI 在没有生产前端资产时执行严格打包冒烟|独立 job 配置、Git 跟踪清单与打包冒烟断言交叉核对；未跑远端 CI|静态核对；目标环境未实测|
|P2-01|P2|续跑丢失新 payload/priority，周期对账计数无法推进|reproduce.py::followup_payload；真实调度函数、Session 替身|已取得相应复现/运行证据|
|P2-02|P2|远端已读变更只刷新当前文件夹统计|test_review_probe_multilocation_flags；真实 PostgreSQL|已取得相应复现/运行证据|
|P2-03|P2|移除一个标签/位置时未刷新统计和事件|test_review_probe_multilocation_delete；真实 PostgreSQL|已取得相应复现/运行证据|
|P2-04|P2|IMAP 删除硬编码 Trash，忽略已发现废纸篓身份|test_review_probe_trash_destination；真实数据库任务载荷，未连接远端 IMAP|已取得相应复现/运行证据|
|P2-05|P2|业务健康指标绕过实例鉴权|reproduce.py::public_metrics；真实 HTTP 路由、指标服务替身|已取得相应复现/运行证据|
|P2-06|P2|长任务阻断 Worker 健康心跳|主循环、任务锁续期线程与健康阈值静态交叉核对；未等待长任务|静态核对；目标环境未实测|
|P2-07|P2|同步健康指标查询不存在的 success 状态|test_review_probe_sync_success_metrics；真实 PostgreSQL|已取得相应复现/运行证据|
|P2-08|P2|提交的前端 OpenAPI 类型落后于契约|npm test 的 OpenAPI 失败 + 生成类型 diff + 后端 schema check|已取得相应复现/运行证据|
|P2-09|P2|App 新增 effect 违反现有 lint 门禁|npm run lint 实际退出 1，定位 App.tsx:109|已取得相应复现/运行证据|
|P2-10|P2|新增 Clipboard 回退把 textarea 放在原生 dialog 外，无法取得复制焦点|真实 Chromium 焦点观察；execCommand 为观察替身，系统复制结果待验证|焦点已证实；实际复制待验证|

## P1：优先处理

以下条目分别涉及恢复安全、任务与事件可靠性、日志保密及 CI 资产依赖。风险前提写在各条“触发条件”，不能把维护入口缺陷解释成未鉴权远程漏洞。

### P1-01 备份恢复允许越过 Blob 目标目录覆盖文件

**代码入口**：

- [src/mail_core/backup/package.py](../../../src/mail_core/backup/package.py)：restore_backup_package，946–962 行；目标路径预处理见 894–898 行。

**触发条件**：恢复包含异常成员名的 blobs.tar，或恢复目标下已有可越界的链接。操作者对目标文件具有写权限；该问题发生在维护恢复入口，不是匿名 HTTP 上传入口。

**实现机制与影响**：blobs.tar 成员只检查 blobs/ 前缀和 ..，没有拒绝去掉前缀后得到的绝对路径。成员 blobs//absolute/path 经 target_blobs / rel_path 直接跳到绝对路径，replace 覆盖目标目录外文件。现有目录中的符号链接也未进行最终 containment 检查；target_blobs 在 resolve 后再 is_symlink 无法识别原始末端链接。绝对路径覆盖已有文件已实测；链接相关判断来自源码，未对竞态链接替换做系统级实验。

**证据与边界**：reproduce.py 的 restore_escape 使用真实 manifest 校验和真实 Blob 解包，确认目标目录外预先存在的文件被覆盖；仅 pg_restore 被替身替换，没有接触真实数据库。所有测试文件限制在 .scratch。

**修复方向（建议，未实施）**：校验成员类型与规范化相对路径；拒绝绝对路径、链接与越界解析结果；在创建父目录及替换文件前维持目标根边界。

**建议回归与验收条件**：

- 使用绝对路径、重复分隔符、..、链接等成员构造恢复包；全部应在写出任何目标根外文件前失败。
- 预置目标根外哨兵文件；失败后内容和权限保持原样。合法内容寻址 Blob 仍能恢复。

### P1-02 “禁止覆盖源库”检查被数据库用户名变化绕过

**代码入口**：

- [src/mail_core/backup/package.py](../../../src/mail_core/backup/package.py)：\_restore_database_identity，134–167 行；同源检查 890–892 行；pg_restore 参数 990 行附近。

**触发条件**：源、目标 URL 指向同一 PostgreSQL 实例和同一 database，仅使用不同数据库角色。恢复角色还需具备相应清理/恢复权限，才可能造成实际数据破坏。

**实现机制与影响**：数据库身份元组包含 username。同一 host/port/database 换成 restore_role 后，被视为另一个数据库，随后 pg_restore --clean --if-exists 可以对源库执行破坏性恢复。主机别名同样不能靠字符串比较证明目标隔离。

**证据与边界**：reproduce.py 对相同 host/port/database、不同用户名调用生产 \_restore_database_identity，得到不相等结果。未执行真实破坏性恢复。

**修复方向（建议，未实施）**：用户名不能作为数据库区分依据；针对破坏性恢复验证实际实例及数据库身份，默认要求独立、明确授权的恢复目标。

**建议回归与验收条件**：

- 相同实例/database、不同用户名的源目标必须拒绝，断言 pg_restore 未被调用。
- 增加 localhost/loopback/实例别名等目标身份案例；独立临时目标库恢复成功，并保留可回退恢复策略。

### P1-03 去重任务完成与新唤醒并发时会丢任务

**代码入口**：

- [src/mail_core/sync/jobs.py](../../../src/mail_core/sync/jobs.py)：enqueue_job，61–74 行；唯一约束竞争回退分支亦需检查。
- [src/mail_core/worker/handlers.py](../../../src/mail_core/worker/handlers.py)：\_evaluate_result，125–155 行。

**触发条件**：同一 dedupe_key 已有 CLAIMED 任务；新请求读取该行后，另一事务完成旧任务；随后新请求才 flush 唤醒标记。两个事务的交错即可触发，不要求进程崩溃。

**实现机制与影响**：读取命中 CLAIMED 任务时未锁行。另一事务可在该 SELECT 后完成任务，当前事务随后只把 \_followup_needed 写到已 DONE 行；没有 PENDING 后继，Worker 不会继续消费该行上的唤醒标记；其他补偿机制是否能重新发现业务余量需另行验证。

**证据与边界**：test_review_probes.py::test_review_probe_lost_job_wakeup，用两个真实 PostgreSQL Session 在 SELECT 与 UPDATE 间完成原任务，最终只剩带唤醒标记的 DONE 行。

**修复方向（建议，未实施）**：把去重读取、完成判定和后继生成放进同一并发协议；锁定并重新检查状态，确保唤醒最终落在可执行任务。

**建议回归与验收条件**：

- 使用真实 PostgreSQL 两会话，在 SELECT 与唤醒 UPDATE 间完成原任务；新请求结束后必须有可执行后继或等价可靠唤醒。
- 覆盖原任务先完成、唤醒先提交、唯一约束竞争回退，以及多次相同唤醒去重。

### P1-04 SSE 将序列 ID 当提交顺序，丢失较晚提交事件

**代码入口**：

- [src/mail_core/api/sse.py](../../../src/mail_core/api/sse.py)：stream_events，282–287 行；\_build_replay。
- [src/mail_core/realtime/outbox.py](../../../src/mail_core/realtime/outbox.py)：fetch_since。
- [src/mail_core/realtime/dispatcher.py](../../../src/mail_core/realtime/dispatcher.py)：dispatch_once。

**触发条件**：两个可独立提交的事务生成 Outbox 事件，并出现小 ID 晚提交、大 ID 先提交。浏览器在小 ID 提交前已经收到较大 ID 或以其作为回放游标。

**实现机制与影响**：PostgreSQL 序列分配顺序不等于事务提交顺序。事务 A 取得较小 ID 尚未提交，事务 B 取得较大 ID 并先提交；客户端推进到 B 后，A 的事件被 eid \<= cursor_local 丢弃。重连也只查 id > cursor，无法补回 A。事件仍保存在数据库中；缺陷是该订阅/游标链无法交付事件，不代表业务数据或 Outbox 行已被删除。后续列表全量刷新可能恢复视图，但不补足当前实时交付保证。

**证据与边界**：test_review_probes.py::test_review_probe_outbox_commit_order，通过两个真实事务复现较大 ID 先回放、较小 ID 后提交且重连回放为空。

**修复方向（建议，未实施）**：采用可证明不会跨越未提交事件的投递/游标设计；不能只用序列高水位判定所有更早事件已经交付。

**建议回归与验收条件**：

- 用两个真实事务强制小 ID 晚提交，覆盖在线流与断线重连两条路径；两次业务变更都必须可观察。
- 覆盖订阅前后提交、重放截断及队列溢出，允许契约定义的重复/全量刷新，但不能静默丢失有效变更。

### P1-05 provider 异常 traceback 泄露通用 token 值

**代码入口**：

- [src/mail_core/security/redact.py](../../../src/mail_core/security/redact.py)：\_PATTERNS，14–31 行。
- [src/mail_core/logging_config.py](../../../src/mail_core/logging_config.py)：RedactingTraceFormatter.format。
- [src/mail_core/sync/delta.py](../../../src/mail_core/sync/delta.py)：sync_folder_delta，401 行。
- [src/mail_core/sync/reconcile.py](../../../src/mail_core/sync/reconcile.py)：provider 异常处理中的 log.exception。
- [src/mail_core/sync/remote_push.py](../../../src/mail_core/sync/remote_push.py)：写回异常处理中的 log.exception。

**触发条件**：provider 异常消息包含 token=...，调用路径使用 log.exception，或其他方式把原始异常附加到日志；最终通过当前生产 formatter 输出。

**实现机制与影响**：调用处虽然生成 safe_provider_summary，但 log.exception 仍附带原始异常文本。RedactingTraceFormatter 最终依赖 redact，规则列表缺少通用 token 键，因此 token=... 原样进入日志；异常 body 也不会因为安全摘要而自动从 traceback 删除。

**证据与边界**：reproduce.py 使用真实 ProviderHttpError、LogRecord 和 RedactingTraceFormatter，验证合成 token 标记仍在格式化结果中。后端全量失败捕获也显示该路径；没有使用真实令牌。

**修复方向（建议，未实施）**：provider 错误日志不能附带原始响应异常文本；统一处理 traceback 和凭据字段，增加覆盖生产 formatter 的回归验证。

**建议回归与验收条件**：

- 通过真实 RedactingTraceFormatter 和实际 log.exception 调用验证异常链、消息、已知凭据字段与响应体处理。
- 覆盖 token=、带引号 JSON、URL query 和异常 cause；日志中不得出现输入标记，仍保留受控错误类型、状态码和 trace_id。

### P1-06 desktop CI 在没有生产前端资产时执行严格打包冒烟

**代码入口**：

- [.github/workflows/ci.yml](../../../.github/workflows/ci.yml)：desktop-quality，99–129 行。
- [src/desktop/scripts/packaged-smoke.js](../../../src/desktop/scripts/packaged-smoke.js)：建包与真实 SPA 断言，44–77 行。
- [src/desktop/package.json](../../../src/desktop/package.json)：build.extraResources。

**触发条件**：从干净 checkout 启动 GitHub Actions desktop-quality job，执行现有 npm run test:packaged。不能依赖开发机现存 dist 或另一个 job 的本地文件。

**实现机制与影响**：desktop-quality 是独立的新 checkout，只安装 desktop 依赖和下载 PG，没有安装/构建 frontend，也没有下载其他 job 产物。frontend/dist 不入库；test:packaged 却要求真实 SPA。其他 job 的构建不会自动出现在此 runner，干净 CI 无法满足门禁。

**证据与边界**：静态核对 job 步骤、git ls-files 和 packaged-smoke 的断言；未触发远端 CI 或重新下载打包依赖。

**修复方向（建议，未实施）**：该 job 构建或取得同一提交的生产资产，再运行严格打包冒烟。

**建议回归与验收条件**：

- 从干净工作目录重放 desktop job；不存在预先生成的 frontend/dist 也能取得同提交真实 SPA 后完成冒烟。
- 保留对 stub SPA 的拒绝，并验证包内资产与预期提交一致。

## P2：功能、观测与验证缺口

### P2-01 续跑丢失新 payload/priority，周期对账计数无法推进

**代码入口**：

- [src/mail_core/sync/jobs.py](../../../src/mail_core/sync/jobs.py)：enqueue_job，67–75 行。
- [src/mail_core/worker/handlers.py](../../../src/mail_core/worker/handlers.py)：\_evaluate_result，146–154 行。
- [src/mail_core/sync/delta.py](../../../src/mail_core/sync/delta.py)：下轮轮询与周期对账，486–506 行。

**触发条件**：delta Worker 在执行自身 CLAIMED 任务时，以相同 dedupe_key 请求后继；后继需要新的 poll_round 或优先级。PENDING 去重场景同样不保存新请求载荷。

**实现机制与影响**：命中 PENDING 直接返回，命中 CLAIMED 只记录唤醒/时间。新 payload 和 priority 被丢弃；Worker 复制旧任务。delta 请求 poll_round=1、priority=75，后继仍为 poll_round=0、priority=60，在该正常 CLAIMED 自调度链内无法达到每 20 轮 reconcile 条件。其他去重入队新载荷（包括错误 detail）也可能丢失。

**证据与边界**：reproduce.py 调用真实 enqueue_job/\_evaluate_result，打印请求值与后继实际值。后端 test_a27_sync_folder_delta_sanitizes_errors 同时暴露去重后 detail 丢失。

**修复方向（建议，未实施）**：明确并保存后继业务载荷、优先级及执行时间，完成时使用该后继请求。

**建议回归与验收条件**：

- 首次 payload.poll_round=0，完成后下一轮为 1；连续 20 轮按契约产生 reconcile 并复位计数。
- 验证后继 priority=75、run_after 延迟，以及 claimed/pending 命中时业务载荷的合并/替换语义。

### P2-02 远端已读变更只刷新当前文件夹统计

**代码入口**：

- [src/mail_core/sync/delta.py](../../../src/mail_core/sync/delta.py)：\_apply_flag_patches；apply_delta_page，195–198、236–237 行。
- [src/mail_core/sync/metadata.py](../../../src/mail_core/sync/metadata.py)：apply_metadata_page 的统计刷新。

**触发条件**：同一 Message 具有至少两个 MessageLocation。远端把邮件改为已读/未读，先在一个位置同步到共享状态，再在另一位置同步同一最终状态。

**实现机制与影响**：Message.is_read 在多位置间共享，更新一个文件夹时却只重算该目录。随后同步另一个目录，状态已经相同，不再产生 touched，该目录未读统计持续陈旧。

**证据与边界**：真实 PostgreSQL 同一邮件位于 INBOX/ALL，两个文件夹依次同步 read=True，统计仍为 [0, 1]。见 test_review_probe_multilocation_flags。

**修复方向（建议，未实施）**：共享状态变化时，重算并通知该邮件全部受影响位置。

**建议回归与验收条件**：

- 同一邮件位于 INBOX/ALL，两边均同步 read=True 后，未读数必须为 [0, 0]；反向未读变化同样正确。
- 覆盖 metadata upsert、delta flag、未知读状态、重复页和所有受影响文件夹的失效事件。

### P2-03 移除一个标签/位置时未刷新统计和事件

**代码入口**：

- [src/mail_core/sync/delta.py](../../../src/mail_core/sync/delta.py)：位置移除、孤儿判定与统计刷新，214–243 行。

**触发条件**：provider delta 删除当前文件夹位置，但邮件在其他文件夹仍有位置；当前页没有其他字段变更或整个 Message 删除可以碰巧触发统计刷新。

**实现机制与影响**：删除 MessageLocation 后，只有邮件彻底成为孤儿才增加 deleted。如果邮件仍在其他文件夹，touched/deleted 都为空，不重算被移出目录，也不发相关失效事件。

**证据与边界**：test_review_probe_multilocation_delete，真实 PostgreSQL 中目录已无 MessageLocation，FolderStats.total_count 仍为 1。

**修复方向（建议，未实施）**：单独追踪位置删除，不能用整个 Message 删除数作为目录变化判据。

**建议回归与验收条件**：

- 移除一个位置且保留其他位置，原目录 total/unread 立即更新，邮件及其他目录仍存在。
- 确认目录统计事件足以刷新列表；重复删除保持幂等，孤儿邮件原有删除语义不退化。

### P2-04 IMAP 删除硬编码 Trash，忽略已发现废纸篓身份

**代码入口**：

- [src/mail_core/mail/application/mutations.py](../../../src/mail_core/mail/application/mutations.py)：trash_message，216–219 行。
- [src/mail_core/providers/imap.py](../../../src/mail_core/providers/imap.py)：apply_remote_operation，1002、1059 行。

**触发条件**：IMAP 账号已发现 role=trash 的真实目录，但 remote_id 不为 Trash，例如 INBOX.Deleted。用户从本地界面发起移到废纸篓。

**实现机制与影响**：账号实际 role=trash 文件夹可以是 INBOX.Deleted、Trash 以外名称或编码路径，但出站任务统一传 Trash，provider 原样 UID MOVE。真实目标不存在时远端删除失败，而本地邮件已经被移除。

**证据与边界**：test_review_probe_trash_destination，数据库已有 INBOX.Deleted/role=trash，实际任务目标仍为 Trash。

**修复方向（建议，未实施）**：按账号查询 role=trash 的真实 remote_id，并显式处理无目标或目标歧义。

**建议回归与验收条件**：

- 真实或协议契约夹具提供非 Trash 的特殊用途目录，断言 UID MOVE 的目标使用真实 remote_id。
- 覆盖空格/编码路径、缺少废纸篓、多个候选以及远端失败；界面不得把未送达操作误认为远端已成功。

### P2-05 业务健康指标绕过实例鉴权

**代码入口**：

- [src/mail_core/api/app.py](../../../src/mail_core/api/app.py)：system_health，239–248 行。
- [src/mail_core/system_metrics.py](../../../src/mail_core/system_metrics.py)：SystemHealthReport 与聚合实现。
- [docs/guides/security.md](../../../docs/guides/security.md)：公开探针与实例鉴权边界。

**触发条件**：部署入口可访问且没有额外反向代理鉴权。请求既不带 Cookie Session，也不带 Bearer API Key。实例网络是否公开取决于部署，匿名路由行为不随此改变。

**实现机制与影响**：/api/system/health 和 /health/metrics 直接注册在 app，没有 require_auth。匿名请求可以读取账号数、任务/写回数量、Worker 标识、磁盘容量与备份状态；超出 security.md 声明的公开探针范围。

**证据与边界**：reproduce.py 用无 Cookie、无 Bearer 的真实 TestClient 路由访问，两个路径均返回 200；仅指标服务和 Session 工厂替换为无 DB 探针。

**修复方向（建议，未实施）**：两条别名同时绑定实例鉴权，公开健康探针保留最小信息。

**建议回归与验收条件**：

- 对两个路径分别测试匿名 401、有效 Session/Bearer 成功；保留 /health、/ready 的公开探针契约。
- 确认反向代理、Web 与桌面模式不会通过别名绕过鉴权。

### P2-06 长任务阻断 Worker 健康心跳

**代码入口**：

- [src/mail_core/worker/main.py](../../../src/mail_core/worker/main.py)：run，288–316 行；\_tick；\_heartbeat_claims。
- [src/mail_core/worker/healthcheck.py](../../../src/mail_core/worker/healthcheck.py)：默认 60 秒陈旧阈值。
- [src/mail_core/worker/heartbeat.py](../../../src/mail_core/worker/heartbeat.py)：record_heartbeat / get_worker_heartbeats。

**触发条件**：一次 \_tick 内的串行任务处理超过健康心跳陈旧阈值。归档批次、网络慢请求或多任务累计都可满足该条件；任务锁续期线程并未更新同一健康记录。

**实现机制与影响**：业务健康心跳只在主循环 \_tick 前更新；\_tick 串行执行一批网络/归档任务，期间只续 WorkerJob.locked_at。合法任务累计超过默认 60 秒时，容器 healthcheck 把仍在工作的 Worker 判为 stale；严格 readiness 同样受影响。Docker 的 unhealthy 标记本身不等于自动重启；是否进一步重启取决于外部编排/运维策略，本轮未验证该策略。

**证据与边界**：静态核对 run、\_tick、\_heartbeat_claims、healthcheck；未以墙钟等待长任务复现。

**修复方向（建议，未实施）**：把进程存活心跳独立于任务执行续期，区分存活与任务进展。

**建议回归与验收条件**：

- 用可控慢任务跨过 60 秒阈值，同时验证进程健康记录仍续期、任务锁续期保持独立。
- 停止/崩溃后健康记录按阈值变旧；不把任务失败、处理延迟与进程死亡混为一类。

### P2-07 同步健康指标查询不存在的 success 状态

**代码入口**：

- [src/mail_core/system_metrics.py](../../../src/mail_core/system_metrics.py)：SyncRun 查询，138–140 行。
- [src/mail_core/mail/domain/enums.py](../../../src/mail_core/mail/domain/enums.py)：SyncRunStatus，33–35 行。
- [src/mail_core/sync/engine.py](../../../src/mail_core/sync/engine.py)：完成状态写入，193 行。

**触发条件**：数据库存在按生产枚举记录的 done SyncRun，且没有非生产代码人为写入 success 状态；随后读取业务健康指标。

**实现机制与影响**：实际成功状态为 done，查询却限定 status == success，last_sync_success_at 和同步延迟长期为空。

**证据与边界**：test_review_probe_sync_success_metrics，在真实数据库插入生产合法 DONE SyncRun 后返回 last_sync_success_at=None。

**修复方向（建议，未实施）**：使用领域枚举及真实成功记录，避免测试只 mock scalar 值而不验证查询条件。

**建议回归与验收条件**：

- 真实 PostgreSQL 写入合法 done SyncRun 后，指标返回该完成时间；无成功记录时仍为 null。
- 如果指标名 max_sync_lag_seconds 需要表达最慢账号延迟，应另行确认聚合定义；本条只修复错误状态筛选。

### P2-08 提交的前端 OpenAPI 类型落后于契约

**代码入口**：

- [src/frontend/src/api/generated/schema.ts](../../../src/frontend/src/api/generated/schema.ts)：已提交生成类型，600 行附近。
- [schemas/openapi.json](../../../schemas/openapi.json)：/api/system/health 与 ReadyOut.worker。
- [src/frontend/scripts/check_openapi.mjs](../../../src/frontend/scripts/check_openapi.mjs)：生成与校验入口。

**触发条件**：执行 frontend 的 npm test 或 npm run openapi:check。无需真实邮箱或 PostgreSQL 即可到达当前失败。

**实现机制与影响**：schemas/openapi.json 已包含 /api/system/health 与 ReadyOut.worker，生成 TypeScript 未更新。npm test 在 初轮 378 项、补审终点 386 项单元/组件测试通过后被 openapi:check 阻断。

**证据与边界**：.scratch/review_all/schema_fresh.ts 与已提交类型 diff；后端 export_openapi.py --check 通过，表明当前漂移位于前端生成类型。

**修复方向（建议，未实施）**：从契约重新生成类型，连同源契约改动完成门禁。

**建议回归与验收条件**：

- 由现有生成器重新导出后，前端类型应含新路径和 ReadyOut.worker，npm run openapi:check 退出 0。
- 后端 export_openapi.py --check 同时通过，避免手工修改生成类型制造第二次漂移。

### P2-09 App 新增 effect 违反现有 lint 门禁

**代码入口**：

- [src/frontend/src/App.tsx](../../../src/frontend/src/App.tsx)：OAuth 返回 effect，106–111 行。
- [src/frontend/.oxlintrc.json](../../../src/frontend/.oxlintrc.json)：react/set-state-in-effect 门禁。

**触发条件**：使用项目声明的 oxlint 配置执行 npm run lint。失败与 OAuth 返回页面是否在浏览器中被实际访问无关。

**实现机制与影响**：OAuth 返回 effect 同步调用 setOAuthReturnPending(true)，触发 react/set-state-in-effect。npm run lint 退出 1，CI frontend-quality 在该步骤停止；类型检查和生产构建通过不能替代 lint。

**证据与边界**：实际运行 npm run lint 的定位为 App.tsx:109。

**修复方向（建议，未实施）**：按现有 React 状态规则调整该初始化/事件路径并重新执行 lint，不放宽全局规则。

**建议回归与验收条件**：

- 保留 OAuth 返回时打开设置和消费返回状态的行为，npm run lint 退出 0。
- 补充首次会话检查、登录后返回、重复进入与普通登录路径，避免仅删除 effect 造成行为缺失。

### P2-10 新增 Clipboard 回退把 textarea 放在原生 dialog 外，无法取得复制焦点

**代码入口**：

- [src/frontend/src/lib/clipboard.ts](../../../src/frontend/src/lib/clipboard.ts)：fallbackCopy，25–46 行。
- [src/frontend/src/components/settings_account_form.tsx](../../../src/frontend/src/components/settings_account_form.tsx)：showModal，94 行；回调地址/设备码复制，346、361 行。
- [src/frontend/src/lib/clipboard.test.ts](../../../src/frontend/src/lib/clipboard.test.ts)：jsdom 与 execCommand 替身覆盖。

**触发条件**：原生 showModal 对话框打开，现代 Clipboard API 缺失或拒绝，复制逻辑进入 fallbackCopy。关注 AccountDialog 内的回调地址与设备码按钮。

**实现机制与影响**：AccountDialog 以 showModal 打开。fallbackCopy 把 textarea 追加到 document.body，使其位于活动 modal 外部。真实 Chromium 中调用 ta.focus 后，焦点仍留在对话框按钮。该事实暴露回退选区与原生 modal 约束之间的冲突；当前证据没有执行真实系统剪贴板读写，因此不能把“复制必定失败”写成已经完成的端到端结论。jsdom 中 execCommand=true 的替身也无法证明该原生路径成功。

**证据与边界**：真实 Chromium 载入当前生产 clipboard.ts 转译结果，建立原生 dialog 并禁用 navigator.clipboard 后执行 helper。execCommand 被替换为观察 DOM 的函数并返回 false，以免改写用户系统剪贴板。观察到 textareaFocused=false、activeElement=probe-button；helper 拒绝由替身返回 false 导致，不能用该拒绝本身证明原生命令返回值。证据摘要保存在验证文档。

**修复方向（建议，未实施）**：优先验证活动 modal 内放置复制目标、恢复焦点/选择的方案；是否采用该方案以真实点击、真实复制结果的回归为准。该条保留 P2 风险评级，功能失败结论待补证据。

**建议回归与验收条件**：

- 在真实浏览器原生 dialog 中，模拟缺少 Clipboard API，以用户点击触发回退；核对实际粘贴内容等于目标文本。
- 覆盖 API 拒绝、选区/焦点恢复、非 modal 复制和用户失败反馈；测试须保持系统剪贴板或使用隔离环境。

## 处理顺序与关联

1. 优先收紧备份恢复边界（P1-01、P1-02），再修复日志保密（P1-05）。修复和验证全部使用隔离目标，不能用生产恢复证明保护是否有效。
2. 将任务竞争（P1-03）与后继载荷（P2-01）一并设计，但分别保留回归；前者是并发唤醒丢失，后者是不发生竞争也会丢失业务参数。
3. 处理 SSE 提交顺序（P1-04），再验证多位置同步统计（P2-02、P2-03）。视图刷新只能缓解展示延迟，不能代替数据库统计和可靠交付修复。
4. 修复 CI 资产依赖（P1-06）、OpenAPI 漂移（P2-08）、lint（P2-09），恢复可重复的质量门禁。
5. 其余功能/观测项按影响处理。P2-10 先补真实剪贴板结果证据，再确定最终实现。

此顺序是依赖与风险分析，不写入 task 调度状态。本文不批准接口变更、数据库迁移或生产操作，也不替代项目 task/spec 流程。

## 审阅边界与证据维护

- 初轮工作区干净。补审只涉及后来进入 HEAD 的剪贴板与归档变更，后端实现未随之改变。
- 审阅使用本机 Python `3.14.7`、Node.js `v24.21.0`；CI 声明的 Python `3.13`、Node.js `22` 并非此次完整运行环境。跨版本结论需在修复门禁补验。
- 主报告保留每项影响与建议，验证文档保留运行结果和复现边界。历史测试计数不写回 blueprint 的当前基线，也不声称现有全量门禁已经通过。
- `.scratch/` 中原始日志与探针属于本机附加证据，可被清理且不会随 Git 克隆；下列验证文档已内嵌关键结果，不以这些临时文件作为唯一可读依据。
- 未归档旧 review、未创建 pending/task、未修改生产实现；本轮发现尚无修复 commit。后续修复应追加状态或指向完成 task，不静默改写本轮历史结论。
