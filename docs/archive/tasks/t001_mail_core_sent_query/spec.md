# Task spec

## 背景

前端需支持“所有已发邮件”及各账号已发邮件展示，当前 `mail_core` 的 `/api/mail/inbox` 仅查询 `role=inbox`，且 IMAP 缺少常见中文已发文件夹名称映射，导致已发邮件无法按角色或按账号检索。

## 契约区

### 范围

- `src/mail_core/providers/imap.py`：在 `_FOLDER_ROLE` 映射中增加中文名称映射（如 `"已发送"`、`"已发送邮件"`），并支持识别 IMAP 特殊用途标记 `\Sent`。
- `src/mail_core/mail/application/queries.py`：扩展邮件查询逻辑，支持按 `folder_role: str = "inbox"`（支持 `inbox`、`sent` 等有效角色）和可选的 `account_ids` 检索分页邮件列表。
- `src/mail_core/api/mail.py`：在 `/api/mail/inbox` 增加可选参数 `folder_role: str = Query("inbox")`，保持默认 `inbox` 向后兼容。
- 编写对应的单元/集成测试。

### 非范围

- 前端 UI 与视图修改（由 t002 负责）。
- 发信功能（不在产品范围）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [x] AC-001：调用 `/api/mail/inbox?folder_role=sent` 时，返回所有账号下 `role="sent"` 文件夹中的邮件列表，并支持 keyset 分页与 `account_id` 过滤。
- [x] AC-002：未传 `folder_role` 时，接口行为与原先一致，默认返回 `role="inbox"` 邮件。
- [x] AC-003：IMAP Provider 对名为 `"已发送"`、`"已发送邮件"` 或带有 `\Sent` 标志的目录，解析出 `role="sent"`。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：无

### 有意不测

- 无

### 测试策略

- 使用 pytest 编写 API 端点测试验证 `folder_role=sent` 与 `account_id` 联合过滤及默认值行为；编写 IMAP provider 单元测试验证目录角色解析。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：默认参数不当影响现有收件箱列表调用。
- 回退：默认值保持 `inbox`，若发现兼容问题回退新增参数。

### 依赖与约束

- 无

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录 `/api/mail/inbox` 支持 `folder_role` 查询已发邮件的契约说明。
