# p039 按需归档残留占用导致正文长期不可读，并伴随无限请求与闪烁

- 现象：用户打开所有收件箱第一封邮件后，“正在优先同步邮件正文…”与“立即拉取正文”交替出现，正文始终不显示。2026-10-24T13:38:31+08:00 在本机 Compose 服务 `http://127.0.0.1:37281` 复现；浏览器记录 112 次自动 POST，同一邮件连续响应均为 HTTP 200、`is_archived=false`、空正文、`parse_error=null`，相邻请求约 0.15 秒。预期自动拉取后进入成功、可观察等待或明确失败状态，禁止无间隔重试。
- 影响：所有未归档且按需尝试后仍未完成的邮件，不限第一封或单一 provider；高频 API 请求、重复入队及租约竞争，无法阅读正文。并发打开同账号邮件或多窗口请求时，共用按需归档 owner 会使先前请求失效，可能连带阻碍同账号后台同步。既有工作区账号配置改动不属于本条范围，排查未修改。
- 根因：产品缺陷，前后端状态契约与并发身份共同失配，详见下文。现场未发现该邮件 `parse_error` 或远端拉取错误，不能据此断言远端服务不可用。
- 测试缺口：前端 mock 覆盖已归档成功、HTTP 500、永久 pending，没有覆盖带真实异步间隔的 HTTP 200 未归档响应；立即 resolve 的 mock 还会因 React 状态批处理掩盖循环。后端 `test_ac005_sync_body_captures_provider_or_parse_error` 明确断言远端错误返回 200、`is_archived=false`，却未验证失败反馈能传到客户端。租约测试覆盖不同 owner 抢占，未覆盖多个 API 调用共享 `api-on-demand`。需补组件、API/归档并发和跨层验证，详见下文。
- 线索：`.scratch/body_sync_flicker/`；`browser_evidence.json` 为现场请求与 UI 证据（含本地邮件信息，不入库）；`reader_repro.test.tsx` 基于现有组件测试，模拟两次延迟 15ms 的未完成响应，第三次保持 pending 以有界证明重复 POST；`frontend_result.txt` 为复现通过结果；`lease_repro.py` 调用生产 lease 函数验证同 owner 重入使先前 fencing 失效，内存 session 替身、不写数据库；`lease_result.txt` 为结果。
- 处理：未开

## 可验证机制

1. `src/frontend/src/components/MessageReader.tsx:62` 将空正文、无 parse_error、`is_archived=false` 判为待归档；自动 effect 在 `!syncingBody && !syncError` 时发 POST。HTTP 200 后只更新详情，finally 立即清除 syncingBody。未完成响应仍满足自动 effect，且没有尝试次数、退避或单封自动触发守卫，于是重新发 POST；两种占位界面随状态反复切换。
2. `src/mail_core/api/mail.py:373` 忽略 `run_archive_batch` 返回状态；异常也只 warning，最终总是返回详情。`lease_busy`、`fencing_mismatch`、配额暂停、无可领取任务、fetch 失败等均可能得到同样的 HTTP 200 未完成详情。`MessageDetailOut` 无归档等待原因或 fetch 错误字段；必须与 MIME `parse_error` 保持分离，不能将网络错误伪装成解析错误。
3. 该 API 固定使用 `worker_id="api-on-demand"`。`sync/leases.py:36` 允许同 owner 重入并递增 fencing token；不同请求因此不能互斥，后请求使先请求 token 过期。归档在 renew 或落库 fencing 检查失败时直接返回；先前已领取邮件可能保留 `archive_in_progress` 与 claimed_by，直到 stale reclaim（默认 15 分钟）。首次排查时该邮件处于 `archive_in_progress`，`claimed_by=api-on-demand`、retry_count=0、last_error=null，账号租约 fencing token 已达 5669。独立内存复现确认租约机制；未追踪原始第一笔请求，不能断言最初卡住一定由此造成。

## 正文长期取不出来：现场补充验证

此处“归档”指从 provider 拉取原始 MIME、保存原文并解析正文与附件，不是将邮件移动到 Archive 文件夹。

- 2026-10-24T13:35:47.339078+08:00：该邮件被 `api-on-demand` 领取。首次快照中状态持续为 `archive_in_progress`，没有 MessageBody 可供详情接口返回。
- `claim_archive_batch` 仅选择 `metadata_synced/archive_pending`、`claimed_by IS NULL`、`retry_count < 5` 的邮件。残留 in-progress 占用不会被新的 POST 或 worker 重领。因此“不断请求”不代表“不断向 provider 拉取原文”；后续调用可以完全不调用 provider，直接得到 `ok, claimed=0, completed=0`，API 再返回空正文。
- 更严重的是，即使后请求无任务可领，它仍先以相同 owner 获取并在收尾释放账号租约，两步均使 token 递增。先请求若尚在网络阶段，其写回资格也会被无工作请求破坏；fencing 失败分支返回时未清理已持久化 claim，形成任务看似执行中、实际无人完成的状态。`.scratch/body_sync_flicker/no_work_repro.py` 调用真实 `run_archive_batch` 与 lease 函数，用隔离 session/claim 替身确认：后请求未创建 provider 即返回 claimed=0，同时原请求 fencing 检查失败；不是对真实数据库发起破坏性并发实验。
- Worker 现场日志记录 13:38:28、13:38:40 的 `ok, claimed=0, completed=0`，期间也有 `lease_busy`。后台任务同样不能完成该残留 claim。
- `worker/main.py::_reclaim_once` 对邮件归档 claim 写死 15 分钟过期阈值；账号租约 120 秒过期与邮件 claim 回收是两套条件，不能认为等两分钟即可重新拉正文。日志在 13:50:47 回收两条过期归档 claim；该邮件随后持久留下 `last_error=|reclaimed_stale_archive_claim`，确认确实经历过回收。回收只重置 claim 状态，本身没有安排该封即时归档 job。
- 2026-10-24T13:53:09.986255+08:00：该邮件再次领取；13:53:10.791287 完成归档。最新只读快照显示 `archive_complete`、claimed_by=null，正文存在（plain 724 字符、HTML 5807 字符），parse_error=null。重新领取到完成约 0.8 秒，说明这次长时间无正文直接卡在任务占用与恢复链路，不能解释为该邮件始终无法从远端取得。
- 原始第一笔请求为何最初失去执行资格，没有逐请求运行结果日志，仍需保留证据边界；同 owner fencing 竞态已有生产函数复现，残留占用、回收和最终成功已有运行态证据。API 忽略运行结果且不记录 fencing mismatch，正是现场无法完整还原起点的观测缺口。

新增证据：`.scratch/body_sync_flicker/recovered_archive.json`、`recovery_worker_logs.txt`、`no_work_repro.py`、`no_work_result.txt`。修复验收必须包含“正文在有界时间内成功，或明确错误并可恢复”，不能只消除闪烁与请求风暴。

## 同类扫描与修复范围

- 已确认：所有 `run_archive_batch` 非完成路径都通过同一 sync-body API 丢失结果，并触发同一前端循环，包括 lease busy、fencing mismatch、quota paused、fetch failure、已 in-progress/重试耗尽而 claim 为空。应统一明确等待、可重试失败和终态失败语义，客户端不得立即自动重发。
- 已确认：同邮件多窗口与同账号不同邮件按需请求均共用固定 owner；按请求隔离身份，并正确处理互斥、失效请求的 claim 与租约收尾。测试不能通过取消 fencing 检查实现成功。
- 已扫描：`postMailCoreSyncMessageBody` 只有 MessageReader 消费；`run_archive_batch` 另一入口为 worker handler，后者会读取返回值并交给 `_evaluate_result`，未发现同样忽略结果。GET detail 会提优先级并入队，但不执行固定 owner 就地归档。
- 待验证：快速切换邮件时旧请求 finally/catch 会改写组件共用同步状态，属于相邻竞态风险；本次未独立复现，不作为已确认缺陷。

## 必须补齐的日志与可诊断性

用户明确要求：以后再次出现正文长时间不可读，必须能从日志还原真实停点。本次只记录 worker 最终摘要、provider 异常和 API HTTP 200，不能区分仍在网络中、根本未 fetch、成功拉取但写回失效；缺失定位如下。

|位置|当前缺口|必需记录|
|---|---|---|
|api/mail.py::api_sync_message_body|run_archive_batch 结果被丢弃；无开始/结束、耗时与状态快照|request/trace ID、归档 attempt ID、account_id/message_id、入口来源、归档前后 state、run result、claimed/completed/failed、elapsed_ms；HTTP 200 不能代替业务结果|
|sync/leases.py 与 archive.py 租约分支|acquire/reentry、renew/release 与 fencing mismatch 无关联事件|owner、attempt、预期/current token、过期时间、失败阶段；同 owner 重入及冲突至少明确可查；复用现有 trace_scope，不能把共享 worker_id 当请求标识|
|archive.py::claim_archive_batch|领取到或跳过指定邮件不留原因|state、claimed_by、claimed_at、claim age、retry_count、pause_reason、目标是否领取；claimed=0 必须区分已完成、正在执行、暂停、重试耗尽或锁竞争；原因检查须避免竞态导致伪报|
|archive.py provider build/open_session/fetch_mime|open_session/fetch 仅异常 warning，无开始/成功/耗时、有效 timeout|phase start/end、provider 类型、实际 timeout 及来源、重试序号/退避、fetch 字节数、elapsed_ms、异常类别及脱敏原因；HTTP token 刷新、API 重试阶段可关联；socket timeout 不伪报成整体 deadline|
|archive.py 原文保存/解析/事务提交|parse error 有 warning，但无法确认 fetch 成功后停在哪|fetch_success、blob_store、parse、commit 各阶段结果及耗时，最终 archive state；fencing 拒绝明确标记 commit_rejected 与阶段，而非静默 return|
|archive.py 所有退出分支|lease_busy、fencing_mismatch、quota、provider_error、空 claim 与异常收尾缺少统一结束事件|每次 attempt 有结束或可追踪未结束记录；结果、失败阶段、claim 是否释放、lease 是否释放、后续恢复/重试安排；捕获异常也保留异常类别和受脱敏保护的堆栈定位|
|archive.py::reclaim_stale_archive_claims / worker/main.py|仅“回收 N 条”汇总，不能定位具体邮件及原执行者|每条 message/account、旧 owner/attempt、claimed_at、age、回收阈值、前后状态、是否安排后续 job、job ID；可保留聚合摘要，但不能只有计数|
|worker/handlers.py 与 enqueue_job 调用点|trace 为 job ID，但与 API 请求及归档 attempt 缺少关联；去重后实际任务不可查|request→enqueue/dedupe命中→job→attempt 关联；终态记录 account/message 与调度结果，便于判断 job done 是否只是 claimed=0|

字段复用现有 logging/trace/redact，不另造日志系统；不记录凭据、Authorization、邮件正文、原始 MIME 或完整敏感请求 URL。阶段耗时用单调时钟；关联事件时间应带时区。正常事件控制噪声，高频零工作/冲突可聚合计数，首次原因及 attempt 终态必须保留，不能采样掉失败因果。

验收：用 caplog/结构化记录断言成功、timeout、lease_busy、claim=0、fencing mismatch、异常退出、过期回收路径均可串联；复现“首请求 fetch 中、后请求无工作、首请求写回失效”，日志必须能直接回答是否已 fetch、耗时多少、被谁打断、claim 是否释放、如何恢复。另覆盖进程中断：存在 start 而无 end 时，能由 claim 与回收日志衔接，不能伪称单次拉取耗时 15 分钟。

超时设置另见 p040：当前服务端未保存该值，前端 120 为占位提示，且保存值尚未接入 provider。该配置缺陷与本条占用残留共同妨碍诊断。

## 功能补测要求

- 组件：延迟返回 HTTP 200 + 空正文 + `is_archived=false` 后，请求次数有界、界面稳定；等待与错误可区分，显式重试只发一次；最终成功、合法空正文与 parse_error 既有语义保持；切换邮件与旧请求完成不污染当前邮件。
- API/归档集成：覆盖 lease_busy、fencing_mismatch、配额暂停、provider timeout、retry_count 耗尽、claim 为空，断言可观察结果及错误分类，禁止返回模糊成功后让客户端自行猜测；真实 PostgreSQL 并发两次同账号按需调用，验证活跃归档 token 不被第二请求破坏、claim 可收尾、可重试后正文落库。特别覆盖“首请求已 claim 且正在 fetch，第二请求 claim=0”并发时序，验证首请求能够保存正文；失效或异常退出后的 claim 与 job 必须可恢复，不能等 15 分钟且还依赖重新打开邮件才恢复。增加脱敏执行结果与请求关联日志，能区分未发起 fetch、fetch 失败、写回被 fencing 拒绝。
- 跨层：实际打开未归档邮件，首个请求遇占用/远端失败，验证无高频 POST、状态不闪烁，明确重试或受控等待后可显示正文；覆盖同邮件多窗口、同账号不同邮件场景。

## 复现命令

```sh
src/frontend/node_modules/.bin/vitest run --config .scratch/body_sync_flicker/vitest.config.mjs -t 'reproduces repeated automatic'
PYTHONPATH=src .venv/bin/python .scratch/body_sync_flicker/lease_repro.py
PYTHONPATH=src .venv/bin/python .scratch/body_sync_flicker/no_work_repro.py
```

仅在 `.scratch/` 保存复现材料；未修改生产代码或正式测试，未手工修改运行数据、重启服务或执行 commit。打开邮件按现有业务逻辑触发详情读取、归档提优先级与按需同步。
