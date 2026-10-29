# Task spec

## 背景

p063 根因 3：积攒的 5 条已读同步在一次远程写回推送中逐条执行，耗时 69 秒，期间串行 Worker 无法处理用户点击的正文拉取。核实（2026-10-30）：

- `push_remote_operations` 已按账号一次取出最多 `limit=20` 条 PENDING 操作，但对每条操作单独调用 `provider.apply_remote_operation`。
- IMAP 实现（`providers/imap.py` `apply_remote_operation`）每条操作独立完成：取连接槽（新建 PG 控制连接）→ TCP/TLS → LOGIN → ID → SELECT → STATUS（UIDVALIDITY）→ FETCH 确认存在 → STORE/MOVE → FETCH 回读 → LOGOUT，约 10 次往返，建连与登录占主要耗时，单条约 14 秒。
- Graph 实现每条操作一次独立 HTTP 请求。
- 入队侧已具备合并基础：同一邮件同类操作按 `entity_key` 合并为一行并递增 revision（`_coalesce_existing`），推送任务按 `remote-op-push:{account_id}` 去重，执行中到达的新操作登记后继执行。

参考实现（2026-10-30 源码核查）：

- Thunderbird：一次用户操作的选中邮件转为一个 UID 集合发一条 STORE，UID 串超过 950 字符分块（`nsImapUtils.cpp`）；离线回放时 `ProcessFlagOperation` 把目标 flag 相同的待处理操作合并为一条命令，移动按目标文件夹合并；操作复用已登录的缓存连接（每服务器默认最多 5 条）。
- Mailspring：每个任务按文件夹分组，每组一次 `storeFlagsByUID` / `moveMessages`，移动用 UIDPLUS uidmap 取得新 UID；前台会话常驻已登录。
- SnappyMail / Cypht：一次请求的选中 UID 一条 `UID STORE`，Cypht 每 1000 个 UID 分块。
- Delta Chat：待标已读队列表每次清空，按（folder, uid）排序压缩区间，UID 串 1000 字符分块。
- 以上均不对已读 / 星标设时间合并窗口。

## 契约区

### 范围

- provider 写回接口改为批量：一次调用接收一个账号的多条操作，返回与每条操作一一对应的结果；移除单条接口，所有 provider（IMAP、Graph、Memory）与 `remote_push` 调用方同步切换。
- IMAP 批量执行：
    - 一次推送只建立一个已登录连接（含连接槽 permit），全部分组复用。
    - 按（源文件夹，操作类型，目标值）分组；每个源文件夹只 SELECT 并校验 UIDVALIDITY 一次。
    - 标记类（已读 / 未读 / 星标 / 取消星标）每组发一条 UID 集合 STORE；以服务器返回的逐 UID FLAGS 作为存在性与生效校验，响应中缺失的 UID 再以一条 UID 集合 FETCH 补查；保持既有「UID 不存在或回读不符即该条失败」语义（A368）。
    - 移动 / 删除到废纸篓每组发一条 UID 集合 MOVE；按 COPYUID 响应的源 / 目标 UID 顺序映射为每条操作的新远端标识；无 COPYUID 时沿用既有降级状态。
    - IMAP 废纸篓文件夹解析每次推送至多一次。
    - UID 集合压缩为区间表示，单条命令的 UID 串超过 1000 字符时分块为多条命令。
- Graph 批量执行：使用 JSON batching，每个批请求至多 20 个子请求，逐子响应映射回操作结果；子请求限流按既有限流延后语义处理该条操作。
- `remote_push` 批量编排：
    - 一次推送取出该账号至多 500 条 PENDING 操作（原 20）；剩余部分由既有后继执行继续。
    - 网络调用前在一个短事务内校验 fencing 并将本批操作置为 IN_PROGRESS；网络调用后逐条按 revision CAS 结算（执行期间被合并出新 revision 的操作回到 PENDING 重推）。
    - 网络调用后 fencing 丢失时，本批操作保持 IN_PROGRESS 交由既有回收 / 对账处理，不写 DONE。
    - 连接槽容量不足时整批延后，操作回到 PENDING 且不消耗尝试次数（既有语义）。
    - 单组命令失败只影响该组操作，按既有瞬态 / 永久错误分类处理；连接已不可用导致未执行的分组保持可重试。
- 不设时间合并窗口与唤醒延迟：合并范围为推送执行时刻该账号全部待推送操作。

### 非范围

- 不改入队侧合并规则（`entity_key`、revision、推送任务去重键）与前端行为。
- 不引入跨推送的常驻 IMAP 连接池或连接保活。
- 不新增撤销窗口等产品功能。
- 不改 Worker 执行模型（属 t063）与唤醒机制（属 t062）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：同一 IMAP 账号同一文件夹有 N 条待推送「标为已读」操作时，一次推送只建立 1 个连接、执行 1 次登录、1 次 SELECT 与 1 条 STORE 命令，N 条操作全部完成且远端 `\Seen` 已设置。
- [ ] AC-002：同一账号待推送操作跨多个文件夹且混合已读、未读、星标、取消星标、移动、删除到废纸篓时，一次推送只建立 1 个连接；每个源文件夹只 SELECT 1 次；每个（源文件夹，操作类型，目标值）组只发 1 条变更命令（超长分块除外）。
- [ ] AC-003：一组中某个 UID 在远端已不存在时，仅该条操作按既有「UID 不存在」语义失败，同组其余操作正常完成。
- [ ] AC-004：服务器对 STORE 返回 OK 但某 UID 的标记实际未生效时，该条操作不被记为完成。
- [ ] AC-005：某源文件夹 UIDVALIDITY 与操作记录不符时，仅该文件夹的操作按既有错误失败，其余文件夹的操作正常完成。
- [ ] AC-006：批量移动 / 删除到废纸篓后，每条操作的远端结果包含按 COPYUID 映射得到的目标文件夹新 UID；服务器不返回 COPYUID 时结果与现有单条行为一致。
- [ ] AC-007：单条命令 UID 串超过 1000 字符时被拆为多条命令，全部操作仍正确完成。
- [ ] AC-008：网络调用期间某操作被用户再次修改（revision 递增）时，该操作推送后回到 PENDING 并在后续推送中按新意图执行，不被记为完成。
- [ ] AC-009：网络调用后账号租约 fencing 已丢失时，本批操作全部保持 IN_PROGRESS，不写入完成或失败。
- [ ] AC-010：连接槽容量不足时，本批操作全部回到 PENDING，不消耗尝试次数，推送按既有延后语义重排。
- [ ] AC-011：某组变更命令返回失败时，仅该组操作按既有瞬态 / 永久分类处理；其余分组照常执行或在连接失效时保持可重试。
- [ ] AC-012：待推送操作超过 500 条时，一次推送处理 500 条，剩余操作由后继推送继续处理直至全部完成。
- [ ] AC-013：Graph 账号的多条待推送操作以批请求提交，每个批请求至多 20 个子请求；每条操作结果与对应子响应一致；单个子请求被限流时仅该条操作按限流延后处理。
- [ ] [deploy] AC-014：真实 IMAP 账号上积攒 5 条同文件夹已读操作，一次推送仅出现 1 次登录，推送总耗时不超过同环境单条推送耗时的 2 倍。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- AC-014：需真实服务商账号的登录与网络时延，无法在 CI 复现；以部署环境人工实测记录替代（服务商、操作数、登录次数、单条与批量耗时）。

## 上下文区

- 来源：p063（2026-10-30 核实：根因 3 成立，逐条推送且每条独立建连登录；p063 修复方向 4「合并为单条 IMAP 批量指令」采纳并扩展到全部写回操作类型与 Graph；合并方式为执行时清空队列分组，不设时间窗口，依据五个参考项目源码核查）

### 有意不测

- 各真实服务商对超长 UID 集合与 MOVE 的个体差异：以 Dovecot 真实服务器与 fake IMAP 覆盖协议行为，真实服务商差异由 AC-014 与上线观测覆盖。

### 测试策略

- fake IMAP 客户端：记录登录、SELECT、STORE、MOVE、FETCH 调用次数与参数，覆盖分组、分块、缺失 UID、回读不符、UIDVALIDITY 不符、COPYUID 有无、单组失败、连接中断。
- Dovecot 集成测试（既有全栈 E2E 基础设施）：真实服务器验证批量 STORE 的逐 UID FLAGS 回应、批量 MOVE 的 COPYUID 映射。
- `remote_push` PostgreSQL 集成测试：批量 IN_PROGRESS、revision CAS、fencing 丢失、容量不足、500 条上限与后继推送。
- Graph：mock transport 验证批请求切分、子响应映射与子请求限流。
- 既有单条接口测试迁移为调用批量接口传入单条操作，断言预期保持不变；仅实现单条接口的测试替身改为实现批量接口。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 非 SILENT 的 UID STORE 逐 UID 回应：已核实（2026-10-30，RFC 3501 §6.4.6 原文）。`+FLAGS` / `-FLAGS` / `FLAGS` 规定「The new value of the flags is returned as if a FETCH of those flags was done」，`.SILENT` 后缀才抑制该未标记 FETCH；已不存在的 UID 不产生回应。个别服务商可能不完全遵守，设计对响应中缺失的 UID 一律以 UID 集合 FETCH 补查，正确性不依赖服务器是否回应，最坏情形多一次往返；Dovecot 集成测试固化标准行为。
- Graph JSON batching：已核实（2026-10-30，Microsoft Learn「Combine multiple HTTP requests using JSON batching」，文档日期 2025-02-21）。端点 `POST /v1.0/$batch`；单批至多 20 个子请求；子响应以 `id` 关联、顺序不保证、各带独立 `status` 与 `headers`；批响应 200 不代表子请求成功；子请求按各自限流规则独立评估，超限子请求以 `429` 失败。未声明 `dependsOn` 时子请求可并行执行，本 task 的子请求相互独立，无需排序。

### 风险与回退

- 风险：分组结果到操作的映射错误导致错标完成；部分服务器对大 UID 集合或 MOVE 的响应不规范；单连接中途断开使后续分组状态不清；批量改造遗漏单条路径中的既有防护（文件夹不一致拒绝、A368 存在性校验、废纸篓解析）。
- 防御：AC-003 至 AC-011 逐项覆盖既有防护；映射以 UID 为键而非响应顺序（COPYUID 除外，其顺序由 RFC 4315 规定）；未确认结果的操作一律不写 DONE。
- 回退：git revert 本 task commit 恢复逐条推送。

### 依赖与约束

- 无前置 task 依赖；可与 t063 并行实施。t063 仅在 `worker/handlers.py` 调整传入 owner，不改 `sync/remote_push.py` 内部。
- 必须保持既有写回约束：revision CAS、fencing 前置检查、容量延后不计失败、瞬态 / 限流分类。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：出站写回状态机章节补记批量推送（分组、单连接、逐条 CAS 结算、无时间窗口）。
- `docs/blueprint/decisions.md`：写回合并采用执行时清空分组、不设时间窗口的取舍及参考依据。
- `docs/specs/mail_sync_and_storage.md`：累积 spec 补记批量写回契约。
