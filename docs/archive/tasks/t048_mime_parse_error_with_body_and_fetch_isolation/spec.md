# Task spec

## 背景

当前 MIME 归档与阅读器渲染存在三处缺陷：

1. 当邮件存在局部 MIME 编码瑕疵（如企业微信 `<meta name="viewport" content="width=device-width">` 中未转义 `=de` 触发 `strict` 解码失败）或已修复阅读副本带有 `parse_error` 时，后端 `run_archive_batch` 直接丢弃全部正文（`text_plain=None, text_html=None`），前端 `MessageReader` 与列表 `_hydrate_body_previews` 将 `parse_error` 与正文完全互斥，导致用户虽看到报错却完全无法阅读可用正文，阻碍正常工作；
2. `run_archive_batch` 在 `provider.fetch_mime` 发生网络/限流失败（如 IMAP `Too many login attempts`）时，将拉取异常写入 `MessageBody.parse_error`，导致阅读器误报「邮件解析失败」并锁死按需同步与手动重试入口；
3. `run_archive_batch` 每批逐封调用 `provider.fetch_mime` 时每封邮件均新建 IMAP 连接并重复 `LOGIN`/`LOGOUT`，高频触发网易 163/126 登录频控。

## 契约区

### 范围

- 严格报错且保留可读正文：当 `parse_mime_content` 检测到报头、附件名或正文编码缺陷（含未转义 QP、字符集局部非法字节等）时，严格记录 `MessageBody.parse_error`（绝不吞错），同时通过安全解码回退保留尽最大努力提取出的 `text_plain` / `text_html` 可读正文，不在异常分支将已提取的正文清空为 `None`。
- 阅读器告警与正文并存展示：当 `detail.parse_error` 非空时，阅读器始终醒目渲染 `data-ui="MR-PARSE-ERROR"`「邮件解析失败」告警框；若同时存在非空 `detail.body`，在告警框下方继续正常渲染邮件正文（HTML 沙箱或纯文本），不阻断用户阅读；列表 `_hydrate_body_previews` 只要存在非空正文即可生成只读 `body_preview`。
- 远端拉取失败与 MIME 解析错误严格分离：`provider.fetch_mime` 抛出的网络、连接、认证或限流异常仅记入 `MessageArchiveState.last_error` 并按重试次数流转 `ARCHIVE_PENDING` / `ARCHIVE_FAILED`，严禁写入 `MessageBody.parse_error`；拉取失败后阅读器与详情接口仍允许触发按需同步与「立即重试同步」。
- 同批归档复用 IMAP 连接：`run_archive_batch` 在处理同一账号批次内的多封邮件时复用同一个 IMAP 连接会话（按文件夹切换 `SELECT`），避免每封邮件重复建立 TCP/SSL 连接与 `LOGIN`/`LOGOUT`。

### 非范围

- 不放宽前端 HTML 沙箱（DOMPurify + CSP `iframe`）的安全过滤规则。
- 不静默吞掉任何真实的 MIME 解析缺陷（所有解析缺陷仍须写入 `parse_error` 并在 UI 提示）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：当 MIME 邮件存在编码或结构缺陷（如未转义 QP `=de`、局部非法字节或报头缺陷）但包含可提取正文时，归档后 `MessageBody.parse_error` 非空且准确记录脱敏错误原因，同时 `MessageBody.text_html` 或 `text_plain` 保存回退提取出的可读正文，不被清空为 `None`。
- [ ] AC-002：当邮件详情同时具有非空 `parse_error` 与非空 `body` 时，阅读器同时渲染 `data-ui="MR-PARSE-ERROR"`「邮件解析失败」提示框与邮件正文内容（HTML `iframe` 或纯文本），且列表接口能为该邮件返回非空 `body_preview`；当 `parse_error` 非空且 `body` 为空时，阅读器仅渲染解析失败提示框，不渲染空正文占位。
- [ ] AC-003：当 `provider.fetch_mime` 发生网络超时或服务端限流等拉取异常时，`MessageArchiveState.last_error` 记录该错误，`MessageBody.parse_error` 保持 `None`（不创建或覆盖 `parse_error`）；阅读器打开该未归档邮件时不会误报「邮件解析失败」，且按需同步与「立即重试同步」入口正常工作。
- [ ] AC-004：`run_archive_batch` 对同一 IMAP 账号同一批次内的多封待归档邮件复用单次 IMAP 登录连接完成 `fetch_mime`，不再对每封邮件重复执行 `LOGIN` 与 `LOGOUT`。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p031`（2026-10-23 核实：`archive.py:167-187, 613-646, 776-789`、`queries.py:121`、`api/mail.py:317-323`、`MessageReader.tsx:59-61, 194-213`、`imap.py:500-537` 均已核实；用户确认“有错误就严格报错提示用户，但能显示正文时同时展示正文，不干扰用户工作”）

### 有意不测

- 真实公网网易服务器限流阈值压测：由单元测试断言同批次 IMAP `login` 调用次数为 1 次代替。

### 测试策略

- 后端测试（`tests/mail_core/test_archive_decode_failure.py`、`tests/mail_core/test_on_demand_body_sync.py`）：验证局部损坏 MIME 同时产出 `parse_error` 与可读正文、`fetch_mime` 异常只写 `MessageArchiveState.last_error` 不写 `MessageBody.parse_error`、以及同批多封 IMAP 邮件归档仅建立一次连接登录。
- 前端组件测试（`src/frontend/src/components/MessageReader.test.tsx`）：验证 `parse_error` + 非空 `body` 同时展示错误告警与正文、`parse_error` + 空 `body` 仅展示错误告警、以及远端拉取失败可重试同步。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：既有测试 `test_ac005_sync_body_captures_provider_or_parse_error` 和 `MessageReader.test.tsx` 中曾断言“拉取超时写 `parse_error`”及“`parse_error` 与正文互斥”。
- 回退：遵照 TDD 原则，新增覆盖新契约（拉取错误与解析错误分离、解析告警与可读正文并存）的测试，移除或显式说明替代已失效的旧互斥断言。

### 依赖与约束

- 须同步更新 `docs/blueprint/conventions.md` §九「MIME 解析与错误可见性规范」中关于 `parse_error` 与正文渲染关系的表述。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：更新 §九.1–§九.3，明确 `fetch_mime` 拉取失败不写 `parse_error`，以及 `parse_error` 严格告警同时不屏蔽已提取可读正文。
