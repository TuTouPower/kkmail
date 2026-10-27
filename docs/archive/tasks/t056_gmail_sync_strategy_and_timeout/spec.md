# Task spec

## 背景

Gmail IMAP 采用标签（Label）多重映射机制，其特有的虚拟全量文件夹（`[Gmail]/所有邮件` 对应 `\All`，`[Gmail]/重要` 对应 `\Important`）包含了账户下的全量邮件。当前同步引擎将它们作为普通独立文件夹全量拉取，导致同一封邮件被重复多次下载，本地邮件数成倍膨胀（如 3,700 封实际收件膨胀至 7,290 封；该数字据用户 2026-10 反馈日志，未入库，仅作量级示意），引发巨量无效 IO 与存储浪费。
同时，IMAP Provider 默认 Socket 读超时过短（30s），且单任务循环 20 页（1000 封），跨国访问 Gmail IMAP 时极易偶发 `TimeoutError`。且任务发生瞬时超时时，账号状态被立即打上 `failed` 红色告警，缺乏网络抖动容错。此外，RFC 6154 属性解析遗漏 `\All` 与 `\Flagged`，导致 Gmail 核心文件夹降级为 `role = "other"`。

## 契约区

### 范围

- 在 IMAP 文件夹发现阶段识别 Gmail 提供商：默认将 `\All`（所有邮件）及 `\Important`（重要邮件）虚拟文件夹标记为 `sync_status = "paused"`，不排入常规自动抓取队列。
- 补齐 `src/mail_core/providers/imap.py` 中的 RFC 6154 属性解析：支持 `\All` $\\rightarrow$ `role = "all"`，`\Flagged` $\\rightarrow$ `role = "flagged"`。
- 放宽 IMAP Provider 默认超时至 60.0 秒。
- 调整 `sync_folder_metadata` 默认单次任务 `max_pages` 为 10，平滑单次网络占用。
- 优化 Worker 同步异常处理：瞬态网络超时（`TimeoutError`、`SSLEOFError`）进入常规重试并退避，不立即将账号状态置为 `failed`。

### 非范围

- 不修改现有数据库历史已下载的重复邮件（避免破坏用户本地缓存）。
- 不引入客户端本地标签（Labels）的多对多交互重构。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：在 IMAP 文件夹发现中，Gmail 账号的 `\All`（所有邮件）与 `\Important`（重要）文件夹默认初始同步状态为 `sync_status = "paused"`，常规同步不自动为其拉取邮件。
- [ ] AC-002：`ImapProvider.discover_folders` 解析到 `\All` 标志时赋予 `role = "all"`，解析到 `\Flagged` 标志时赋予 `role = "flagged"`。
- [ ] AC-003：`ImapProvider` 默认 Socket 读取超时放宽为 60.0 秒。
- [ ] AC-004：`sync_folder_metadata` 默认单次最大拉取页数 `max_pages` 调整为 10 页。
- [ ] AC-005：Worker 执行同步任务遇到 `TimeoutError` 或 `SSLEOFError` 等瞬时网络错误进行重新排期时，账号的 `sync_status` 保持原有状态或维持 `running`，不被置为 `failed`。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：用户日志反馈排查发现

### 有意不测

- 真实跨国连接 Google IMAP 服务器的网络抖动：使用 mock/本地 IMAP stub 验证超时配置与异常拦截。

### 测试策略

- 单元测试：`tests/mail_core/` 下针对 `ImapProvider` 的标志位解析、超时默认值进行断言。
- 同步与 Worker 测试：针对 Gmail 文件夹发现的 paused 策略和 Worker 瞬态网络超时的错误恢复机制编写测试用例。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：若用户依赖在“所有邮件”文件夹中查看被跳过收件箱直接归档的邮件，默认 paused 需手动点进该文件夹触发同步。主流客户端（如 Outlook/Apple Mail）对 Gmail 均默认排除 All Mail 同步。
- 回退：git revert 对应 commit。

### 依赖与约束

- 依赖现有的 alembic 迁移机制（本变更不改动数据表 DDL，仅涉及业务逻辑与默认值）。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录 Gmail 虚拟标签文件夹默认 paused 策略与 IMAP 超时规范。
