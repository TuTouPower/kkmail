# Task spec

## 背景

生产 Gmail 账号 `6a47fef4` 在目录发现时发生服务商展示语言切换（2026-10-26 返回中文 modified UTF-7 `[Gmail]/...`，2026-11-25 起至今实时 `IMAP LIST` 返回英文 `[Gmail]/...`，且两套对应系统目录共享完全相同的 `UIDVALIDITY`），导致前端侧栏同时呈现 7 组 14 行中英双份 `[Gmail]/...` 目录；同时全部 Gmail 账号的 `\Important` 视图目录在 `folder-stats` 中均因 `role='other'` 被错投影为 `All Mail` 全量集合（实测 `6a47fef4` 的重要邮件与所有邮件同时误返 228）。

按开发铁律（架构至上、拒绝妥协、零兼容性负担），根因在于 `Folder` 的「身份与本地化路径」未解耦、「协议可选性 / 远端存活性 / 视图形态」三类正交状态长期坍缩在过载的 `folders.sync_status` 与前后端特判中（`t086` 拆分 `kind='view'` 后仍遗留 `sync_status` 且发现阶段只判 `container` 漏判 `view`），以及 IMAP `\Important` 解析与 `FolderRole` 枚举长期缺失迫使前端靠字符串启发式猜角色。必须执行彻底的正交状态重构、系统目录重绑定合并、协议角色收口、OpenAPI/前端契约同步升级及一次性存量洗净迁移。

## 契约区

### 范围

- **Folder 正交状态模型与破坏性迁移**：
    - 废除过载的 `Folder.sync_status` 与相关多义状态枚举，拆分为相互正交的 `kind`（`container` / `view`）、协议可选性标记（`selectable` 布尔列）与远端存活性（`remote_state`：`active` / `missing`）。
    - 完善 `FolderRole` 枚举补齐 `flagged` 与 `important`。
    - 新增 Alembic 迁移并同步更新数据库基线校验：除结构迁移与可逆回滚外，一次性幂等修正全库 Gmail Important 视图的 `role='other'` 为 `'important'`，并对同账号内历史已并存的同身份多语言重复系统目录执行原子合并与去重重算，确保不丢失已有 `MessageLocation` 归属与 `SyncCheckpoint` 增量水位。
- **IMAP 角色解析与派生视图判定统一**：
    - 修复 IMAP 目录发现中的 RFC 6154 `\Important` SPECIAL-USE 识别，并在按名称回退查角色表前剥离 `[Gmail]/` 命名空间前缀，大小写不敏感映射到权威 `FolderRole`。
    - 统一 `folder_views`、Important 视图统计与列表查询作用域、`metadata` 标签落库与 `label_backfill` 选视图逻辑均严格依据权威角色与激活态运作，杜绝 Important 视图误跌入 All Mail 全量分支。
- **目录发现重绑定合并与全形态消失收敛**：
    - `sync_account_folders` 统一对 `container` 与 `view` 执行发现收敛。
    - 当远端出现唯一系统角色新路径（如语言切换换名）且库内存在对应已消失系统旧行时，在同事务执行原地重绑定与原子合并（保留消息位置与同 `UIDVALIDITY` 游标、更新远端路径与名称、消除冗余旧行）。
    - 对于确从服务端删除的非重绑定目录（同时覆盖物理容器与派生视图），统一置为 `remote_state='missing'` 并收敛开放中的同步请求目标（`folder_deleted`）；服务端若重新出现则恢复为 `active`。
- **下游作用域、OpenAPI 契约与前端侧栏收敛**：
    - 目录统计列表、全账号/分组聚合未读统计、按角色收件箱查询与远端写回（单封/批量已读、移入废纸篓）全部按远端存活态与可选容器约束过滤。
    - `folder-stats` 响应与 OpenAPI / TypeScript 生成类型移除旧 `sync_status`，公开清晰的目录形态与可选属性；重构前端 `Sidebar` 移除字符串启发式猜角色与双义 `paused` 猜测，仅在真正存在多个活跃目录时消歧。
- **全量既有测试与契约/文档更新**：
    - 按 TDD 原则补齐端到端测试覆盖；因 `Folder.sync_status` 废除与 `AccountFolderStatsItemOut` 破坏性变更而语义失效的旧测试按规范整体重写并注记理由（不保留兼容双读层），并同步更新 `mail_sync_and_storage.md` 与相关 blueprint/决策文档。

### 非范围

- 不更改 Account 级三维健康状态机（`credential_state` / `connectivity_state` / `sync_activity`）或 Worker 任务执行血缘模型（`execution_origin`）。
- 不新增前端可编辑 Gmail 自定义标签或文件夹 CRUD 管理界面。
- 不在本 task 执行生产环境推代码或线上部署。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：数据库 `Folder` 模型及新增可逆 Alembic 迁移移除 `sync_status`，建立正交的 `kind`（`container` / `view`）、`selectable`（布尔）与 `remote_state`（`active` / `missing`），保持数据库 Schema 校验零漂移；迁移幂等将全库历史 Gmail Important 视图误存的 `role='other'` 修正为 `'important'`，并将同账号因换名并存的多语种系统目录（覆盖历史视图与物理容器）原子合并去重为单行活跃记录且完整保留既有消息位置归属与未失效增量检查点。
- [ ] AC-002：目录角色域枚举包含 `flagged` 与 `important`；IMAP 目录发现优先识别 RFC 6154 `\Important` 等 SPECIAL-USE 属性，名称回退匹配在剥离厂商命名空间前缀后统一映射标准角色，确保中英文 Gmail 的重要邮件目录与全部系统角色在入库阶段即携带准确 `role`。
- [ ] AC-003：目录发现阶段遇到同一账号下系统目录在服务端更换显示语言或路径（`remote_id` 变更，且对应物理容器未更改 `UIDVALIDITY` 或属同一系统视图角色）时，原地重绑定并原子合并既有消息位置、检查点与巡检基线，不产生双份重复系统目录也不触发全量重扫；对确认不再存在于服务端的目录统一覆盖 `container` 与 `view` 将其收敛为 `remote_state='missing'` 并失败收敛开放同步目标（`folder_deleted`），后续服务端重新出现时恢复为 `active` 并按需恢复调度。
- [ ] AC-004：Gmail `\Important` 派生视图的统计计数、邮件列表投影、日常标签写入与历史标签回填严格限定仅作用域指向自身 `Important` 视图行，绝不退化回落为 `All Mail` 全量容器；`folder-stats`、全局与分组聚合未读统计、按角色收件箱查询及出站写回主位置解析严格仅纳入 `remote_state='active'`（写回/同步且要求 `kind='container'` 与 `selectable=true`），不因失效历史目录存在而暴露重名条目、毒化聚合计数或向已消失远端目录发起写回。
- [ ] AC-005：目录统计接口契约与 OpenAPI / 前端生成类型移除旧 `sync_status`，准确输出目录 `kind` 与 `selectable` 语义并通过前后端契约一致校验；前端侧栏移除依赖目录名关键词猜角色与猜暂停状态的兜底分支，准确对 `selectable=false` 结构节点禁点且不显示未知 `-`，对活跃 Gmail `[Gmail]` 包装节点按规范扁平化呈现唯一清晰的标准化目录树。
- [ ] AC-006：更新 `docs/specs/mail_sync_and_storage.md` 与对应 `docs/blueprint/` 及决策记录；项目完整后端 PostgreSQL 测试套件、前端构建与单测、桌面端测试、E2E 冒烟及模板门禁全部通过。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 通过真实 PostgreSQL 上迁移升降级循环、ORM 零漂移校验与双语存量种子合并测试验证；AC-002 至 AC-004 通过 IMAP stub（含 `\Important` 标志与双语切换目录列表）及真实 PostgreSQL 发现、统计、列表、标签写入与出站写回集成测试验证；AC-005 通过 OpenAPI/TypeScript 契约校验、Vitest 侧栏组件测试与 Playwright E2E 验证；AC-006 通过全量门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p100（2026-11-26 核实并转办；生产 Gmail 账号 `6a47fef4` 实证中英双份 `[Gmail]/...` 与全部 Gmail 账号 `\Important` 视图 `role='other'` 误投影为 All Mail，最小复现 `.scratch/repro_p100.py`）

### 有意不测

- 真实生产账号线上语言切换：出于外网与账户隐私约束不作为 CI 用例，由线上 `IMAP LIST` 实测数据构造确定性 IMAP stub 与 PostgreSQL 种子合并用例替代覆盖同一机制。

### 测试策略

- 数据库迁移与存量合并：真实 PostgreSQL 验证新 revision `upgrade head -> downgrade -> upgrade head`、与基线升级路径对齐，以及 seed 类似 `6a47fef4` 的中英双份物理/视图目录与 `role='other'` Important 行后迁移结果的计数、消息位置去重与检查点留存。
- 发现与协议测试：IMAP stub 携带 RFC 6154 `\Important` 及中英前后两次 `LIST`（同 `UIDVALIDITY`），端到端验证原地重绑定、`view`/`container` 消失收敛、复活恢复以及 `view_scope_folder_ids` / `folder-stats` / `mutations` / `label_backfill` 行为。
- 契约与前端测试：执行 `export_openapi.py --check`、`openapi:check`、Vitest `Sidebar.test.tsx` 与 Playwright E2E，覆盖唯一系统目录不误拼消歧、真实多活跃同名目录消歧、`selectable=false` 父节点不可点与 Gmail `[Gmail]` 扁平化。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。Gmail IMAP `LIST` 的 `\Important` 标志、modified UTF-7 与英文路径、`UIDVALIDITY` 不变性及行为表现已在生产账号 `6a47fef4` 实时 `IMAP LIST` 与数据库核实完毕。

### 风险与回退

- 风险：废除 `folders.sync_status` 与调整 `AccountFolderStatsItemOut` 涉及前后端与较多历史测试夹具改动；数据迁移合并同角色重复目录时若同账号历史上非 Gmail 用户自建了多个同名同角色自定义目录，合并谓词必须严格限定目标范围并保持可校验性，避免误合并非系统自定义目录；未完成 `reconcile`/同步的新迁移行在合并 `MessageLocation` 冲突（`(message_id, folder_id)` 唯一约束）时需 `ON CONFLICT DO NOTHING` 去重后再更新 `FolderStats`。
- 回退：通过新增 Alembic revision 的 `downgrade` 回退表结构并在实施分支/提交前保持全量可逆；生产部署需依赖标准封存备份后按 revision 回退或 commit 回退。

### 依赖与约束

- 依赖：无前置未合并 task，基于当前 `main`（含 `t086`/`t091`/`p099`）直接立项；`review_level: full`。
- 约束：遵循开发铁律直接破坏性移除 `folders.sync_status`，不保留双读兼容层；遵守 `docs/blueprint/testing.md` 单一迁移入口与 TDD 规则（因旧 `sync_status='paused'` 契约废除而失效的测试须重写并注明原因或退役，不得篡改既有正确语义断言掩盖缺陷）。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新目录发现同实体重绑定合并与正交状态调度边界描述。
- `docs/blueprint/domain.md`：更新 `Folder` 实体的 `kind`、`selectable`、`remote_state` 与完备 `role` 定义。
- `docs/blueprint/conventions.md`：废除 `folders.sync_status` 混用表述，确立目录三正交状态、`\Important` 权威映射与侧栏活跃目录呈现契约。
- `docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md`：记录废除 `folders.sync_status` 及建立重绑定合并机制的架构决策。
- `docs/blueprint/testing.md`：记录新 Alembic revision 线性链路及门禁覆盖要求。
