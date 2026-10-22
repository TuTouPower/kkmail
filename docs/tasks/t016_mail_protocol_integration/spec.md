# Task spec

## 背景

现有 Dovecot 夹具和两个 live IMAP 测试未自动纳入完整门禁，端口未监听时跳过。Gmail/Graph 已有 transport fixture 合约测试，应复用并补关键失败路径；普通 CI 不应依赖真实个人邮箱或外部 OAuth 凭据。

## 契约区

### 范围

- 复用 tests/mail_core/fixtures/dovecot、start-mail-core-imap.sh 与现有 provider 测试，建立测试专用、可重置、无需业务 Compose 密钥的 IMAP 服务入口。
- 通过真实 ImapProvider、数据库及 Worker 路径验证首次同步、分页、增量、标志写回、现有安全 Trash 操作、断线重连和 UIDVALIDITY 失效恢复。
- 以字节/传输夹具补 Gmail/Graph 既有适配器的 token 刷新、分页、增量过期、429/5xx、超时与脱敏；无真实服务凭据作为合并前置。

### 非范围

- 不新增发信、任意跨文件夹移动或归档产品操作，不重复 t007 裸 GBK 修复及 t008 新文件夹导航。
- 不把模拟 transport 称为真实 Gmail/Graph 联网验证；外部真实账号探针只能显式 opt-in，不能作为默认 CI 条件。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [x] AC-001：协议测试入口从独立干净邮箱种子启动服务并等待就绪，显式选择协议套件时服务缺失、认证错误或就绪超时返回非零，不以缺端口 skip 或退回 MemoryProvider 冒充真实 IMAP 通过。
- [x] AC-002：真实生产 Worker 将包含中文、multipart HTML/text、附件、同 Message-ID 和多页邮件同步入库；逐项断言主题、正文、附件字节、身份和计数，重复同步不产生重复邮件。
- [x] AC-003：远端新增、读状态/旗标变化与删除后，后续增量反映至本地；本地单封状态更新经真实写回在服务端可观察，重连与 UIDVALIDITY 失效恢复后不丢不重。
- [x] AC-004：现有安全移入废纸篓路径在支持能力时仅影响目标邮件；缺失 MOVE/UIDPLUS 能力或 TLS 证书校验失败时拒绝不安全操作，不调用全目录 EXPUNGE，不吞失败。
- [x] AC-005：Gmail/Graph transport fixture 覆盖分页终止/重复页、过期 cursor、token 刷新失败、429 重试约束、5xx 和超时，断言游标不错误前进、错误脱敏与重放幂等；至少含异常响应结构。
- [x] AC-006：服务与邮箱状态可重复重置；协议日志及失败产物不含密码/token，默认执行不访问真实邮箱或修改用户账号。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试；执行阶段必须给出真实运行证据，外部环境不可用不得替代为模拟通过。

## 上下文区

- 来源：无外部条目；本会话测试评估、固定容器方案与用户批准（2026-10-22）。2026-10-22 核实已有 Dovecot Dockerfile、seed.eml、test_imap_provider_live.py、test_imap_sync_loop.py 和 test_gmail_graph_contracts.py；不新造第二套服务商适配器。

### 有意不测

- 不做 Gmail/Microsoft 外网服务可用性门禁，不依赖个人邮箱、真实收费配额或真实 OAuth secret。

### 测试策略

- 真实协议层使用 Dovecot 和可控网络中断；缺失能力、坏证书及异常服务商响应使用受控协议夹具并准确标注模拟边界。
- TLS 用本地测试证书和隔离 endpoint，验证信任正确与不受信拒绝两条路径，不关闭生产校验。
- 针对已知 p016 不增加手动二次 push 来伪造调度收敛；若现有缺陷阻断新链路，保留失败证据并引用t012 独立修复流程。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无尚未裁定的外部产品契约；执行环境、工具可用性与权限按实施入口核对，缺少前提须失败并报告，不能用 skip 代替本 task 验收。

### 风险与回退

- 风险：真实服务种子污染、端口探测假就绪、协议重试无界或误触业务邮箱。服务身份与凭据均来自本轮夹具，网络访问限制在测试 endpoint。
- 回退：回退本 task 单一执行 commit 恢复原入口与测试；仅回收本轮拥有测试资源，保留用户数据、其他 task 改动和失败证据。不更改生产 schema 或数据，迁移验证仅对一次性测试库操作。

### 依赖与约束

- 硬依赖 t014：复用其已交付的隔离后端测试状态并建立确定性数据夹具。
- 本批 task 与 t012 的 finalization 都更新 docs/blueprint/testing.md，已登记 conflicts_with，建议串行交付；冲突不冒充硬依赖，不修改旧 task 和 active worktree。
- 只按本 spec 修改生产代码/测试/脚本；发现超出范围产品缺陷按既有 bug-to-pending 流程记录，不放宽断言或静默扩大修复。

### Finalization 时更新的 blueprint

- `docs/blueprint/testing.md`：IMAP 服务生命周期、必跑协议分类、服务商夹具与真实验证边界。
