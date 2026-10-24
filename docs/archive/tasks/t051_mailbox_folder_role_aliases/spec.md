# Task spec

## 背景

侧栏把同账号所有同角色文件夹显示成同一标准名称。25 个 Graph 账号各有两条 `role=inbox` 记录，导致两个“收件箱”无法区分。3 个 QQ IMAP 账号的远端 `Deleted Messages` 当前归为 `other`。远端文件夹可能是别名或独立目录，不能按角色删并。

## 契约区

### 范围

- 同账号同角色有多个远端文件夹时，侧栏名称必须区分原始名称或完整父路径；每个文件夹仍按自己的 `folder_id` 导航。
- IMAP 文件夹名 `Deleted Messages` 识别为废纸篓角色。
- 保留 `Outbox` 与 `Conversation History` 的独立身份；缺少权威 special-use / well-known 标记时不得将其并入“已发送”。

### 非范围

- 不删除或合并远端文件夹、邮件或邮件位置。
- 不改变 `发件箱`、`Outbox`、`Conversation History` 的角色，仅凭显示名称不推断它们等同于已发送。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：同账号存在多个 `role=inbox` 或多个其他标准角色时，侧栏为每个远端文件夹显示可区分名称，并能分别打开对应 `folder_id`。
- [ ] AC-002：IMAP `Deleted Messages` 文件夹返回 `trash` 角色并显示废纸篓分类。
- [ ] AC-003：没有权威 special-use / well-known 标记的 `Outbox` 与 `Conversation History` 保持独立 `other` 文件夹，不被重命名为已发送或与 sent folder 合并。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：p037（2026-10-24 核实：25 个 Graph 账号各有两个 inbox-role 目录；三个 QQ 账号的 `Deleted Messages` 均为 `other`；重复 inbox 目录间未发现同一邮件位置）。

### 有意不测

- Graph 重复目录是否是远端别名：不据此删除或合并目录；本 task 保证 UI 可辨认和独立访问。

### 测试策略

- Provider 单测覆盖 IMAP `Deleted Messages` 与 Graph inbox 角色边界。
- Sidebar 组件测试注入多个同角色文件夹，断言显示名不同、点击仍选各自 `folder_id`。
- 断言 `Outbox` / `Conversation History` 不因英文名或本地化显示名被错误归成 sent。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。未知的远端别名关系不影响本 task 的保守呈现策略。

### 风险与回退

- 风险：角色重复时名称更长；保留原始名称可避免用户误选。
- 回退：恢复原侧栏标准名和 IMAP 映射；不需要回滚数据。

### 依赖与约束

- 保留每个不同 `remote_id` / `folder_id`；禁止仅按 role 去重。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：说明特殊角色只用于筛选，不是远端文件夹身份；侧栏同角色文件夹需区分名称。
