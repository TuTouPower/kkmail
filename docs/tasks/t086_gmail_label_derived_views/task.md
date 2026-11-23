# Task spec

## 背景

用户新加 Gmail 账号后「重要邮件」「所有邮件」长期显示蓝色 `-`，被理解为仍在同步。根因不在 UI：`messages` 已按 `(account_id, remote_id)` 唯一、`message_locations` 已多对多承载标签位置（`models.py:162-206`），但 IMAP 适配器常规 FETCH 只取 `UID FLAGS INTERNALDATE HEADER.FIELDS`（`imap.py:1041`），全仓无 `X-GM-LABELS`，虚拟标签的成员关系无法从常规同步中推导。于是只能单独 SELECT 整个虚拟目录重抓一遍，造成同一封邮件重复下载（`t056` 记录 3,700 封膨胀至 7,290 封）。

`t056` 以 `paused` 回避重复 IO，却把两个一等导航视图变成永久空壳；其非范围还明确排除 Labels 多对多重构。`p060` 进而使显式 `folder_id` 指向 paused 目录解析为空目标集，删掉了 `t056` 承诺的手动兜底。空壳无 `FolderStats` → `queries.py:220` 返回 `unread_count=null` → `Sidebar.tsx:342` 渲染蓝色 `-`，形成 p086。这是同一架构缺陷上的连续三层补丁。

按开发铁律，废除"虚拟标签作为被暂停的同步单元"模型，改为从常规同步摄取的标签成员关系派生只读视图，从根因同时消除重复下载、空壳导航、错误码与未知角标。

## 契约区

### 范围

- IMAP 适配器对 Gmail 账号在常规 metadata/delta FETCH 中增补 `X-GM-LABELS`，解析标签到远端目录标识的映射；不支持该扩展的账号按 capability 降级，不写标签行。
- 落库阶段把标签成员关系写为 `message_locations` 行，复用 `(message_id, folder_id)` 唯一约束；同一封邮件命中多个物理目录与虚拟标签时只保留一条 `messages` 记录。
- `folders` 引入 `kind` 区分物理 mailbox（`container`，同步单元）与派生视图（`view`，非同步单元）；`sync_status` 仅对 `container` 有意义，view 不入任何同步作业队列、不再被赋 `paused`。
- `folder-stats` 与邮件列表查询对 view 走基于 `message_locations` 的聚合与去重，返回真实总数、真实未读数与真实列表；空账号返回真实 `0`，不返回 `null`。
- 一次性迁移：回填历史目录的 `kind`；重建 All Mail 视图的本地成员行；从 Gmail `\Important` 标签回填 Important 视图成员行，完成后不再重拉。
- 前端移除 paused 虚拟目录特判：侧栏显示真实计数（含 `0`），视图内显示真实邮件列表与真空态。
- 更正 `t056` 风险段、`p060` 相关表述与 blueprint，清除"手动点进触发同步"的失效兜底描述。

### 非范围

- 不恢复"手动点进虚拟目录触发全量同步"路径；view 永久只读。
- 不保留 `paused` 虚拟目录兼容分支；迁移完成后旧语义整体删除，不留双读路径。
- 不改动 Microsoft Graph provider，不引入客户端可编辑标签系统（多对多写操作）。
- 不改账号健康状态机、认证、部署与生产 Compose；不 push。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：Gmail 账号的「所有邮件」「重要邮件」在 `folder-stats` 响应中返回真实 `total_count` 与 `unread_count`（空账号为 `0`，含未读时为真实未读数），不再为 `null`。
- [x] AC-002：选中「所有邮件」「重要邮件」返回按邮件身份去重的真实列表，每封邮件单次呈现；同步队列中不产生以这两个目录为目标的 SELECT/FETCH 作业。
- [x] AC-003：常规目录 metadata/delta 同步把 `X-GM-LABELS` 成员写为 `message_locations` 行；同一封邮件命中两个物理目录与一个虚拟标签后，库内仍只有一条 `messages` 记录和三条 `message_locations` 行。
- [x] AC-004：虚拟标签 Folder 不再被赋 `sync_status=paused`，也不进入任何同步作业队列；`folders.kind` 可区分 `view` 与 `container`，历史虚拟目录已完成迁移且无残留 paused 标记。
- [x] AC-005：对 view 提交同步请求返回成功且目标数为 `0`，不再抛 `folder_not_selectable`；view 列表与计数走只读查询，不依赖该请求。
- [x] AC-006：迁移可重复执行且不产生重复 `message_locations` 行；迁移前后 `messages` 总数不增加，All Mail 视图成员在迁移后即可查询，Important 成员在完成一次标签回填后即可查询。
- [x] AC-007：前端侧栏「重要邮件」「所有邮件」显示真实计数（含 `0`），不再渲染蓝色未读未知角标 `-`；视图为空时显示真实空态，非 Gmail 目录及含 `is_read: null` 邮件目录的既有 `-` 语义不变。
- [x] AC-008：`p060` 描述与 blueprint/决策文档不再包含失效的"手动点进触发同步"兜底表述；`t056` 历史 task 文档因工具写权边界不在本 task 修改，其风险段更正记录在本 task 进度报告与 `docs/blueprint/decisions/20261123_gmail_label_derived_views.md`。
- [x] AC-009：后端完整 PostgreSQL 套件、前端测试与项目门禁全量通过。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- AC-001~008：由 IMAP stub（支持 `X-GM-LABELS`）、PG 集成测试、应用层单元测试与前端组件测试覆盖；stub 不提供扩展时验证 capability 降级。
- AC-009：由门禁命令实际执行结果验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p086（2026-11-23 核实并转办；supersede t084。根因链：无 label 摄取 → t056 `paused` → p060 空目标 → p086 未知角标）

### 有意不测

- 真实 Gmail 账号的标签回填与网页端计数对照：需用户账号与外网，本 task 不在该环境验证；以 IMAP stub 的 `X-GM-LABELS` FETCH、PG 落库与视图投影测试覆盖同一机制（AC-010 于实施期撤销，避免不可验证的打勾）。
- 不支持 `X-GM-LABELS` 的 IMAP 服务商：只验证降级后 view 计数为 `0` 且无错误，不为其生成伪标签。
- 客户端编辑标签/打标回写：非范围，不测。

### 测试策略

- Provider 层：IMAP stub 在 FETCH 响应中返回 `X-GM-LABELS`，断言解析结果与 capability 降级。
- 存储/应用层：断言标签→`message_locations` 映射、跨目录去重、view 聚合计数与列表去重。
- Worker/队列：断言 view Folder 不产生作业，显式 view 同步请求返回目标数 `0`。
- 迁移：在真实 PG 上执行两次，断言幂等、`messages` 总数不增、视图可查。
- 前端：侧栏真实计数渲染、空态、不回归 `is_read: null` 的 `-` 语义。
- 门禁：`doctor_cmd` / `test_cmd` / 后端完整 PG 套件全量通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。`X-GM-LABELS` 为 Gmail 私有 IMAP 扩展，采用 capability 探测：不支持时不写标签行、view 返回 `0` 与空态，不引入阻塞性未知。

### 风险与回退

- 风险：标签回填与常规同步并发写 `message_locations`；历史重复 location 行导致视图计数虚高；删除 paused 后旧作业重入队。
- 回退：迁移前备份 `folders` 与 `message_locations`；以 `(message_id, folder_id)` 唯一约束与事务保证幂等；回退 git revert 后按备份恢复，不保留双读兼容层。

### 依赖与约束

- 依赖：现有 `Message` / `MessageLocation` 唯一约束与 `recompute_folder_stats` 聚合；alembic 迁移机制。
- 约束：涉及数据迁移与 IMAP 协议解析，`review_level=full`；零兼容负担，迁移后旧 paused 视图语义整体移除。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录 IMAP 标签摄取与 view/container 二分。
- `docs/blueprint/domain.md`：`Folder.kind` 与派生视图语义。
- `docs/blueprint/decisions/20261123_gmail_label_derived_views.md`：记录废除 paused 虚拟同步单元、以派生视图根治重复拉取的决策。
