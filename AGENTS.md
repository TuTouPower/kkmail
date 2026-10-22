# kkmail

kkmail 是基于 mail-core 的现代化自托管多账号邮件客户端（FastAPI + PostgreSQL + React SPA + Electron 桌面端）。产品范围不含发信、联系人与系统通知，浏览器扩展永久 out of scope (wontfix)。

本项目最初 fork 自上游开源项目 [`assast/outlookEmail`](https://github.com/assast/outlookEmail)，分叉基线为上游 3.0.20 版本（上游 Commit `498cd35358d687600b5dd7fd9cb79ff59cd18296`，本地历史对应 Commit `a8cf0ff82f36c53a75022c4ade5fb3b46f60b9b0`：`release: prepare 3.0.20 — 邮件转发收件人与关键词筛选`）。自该基线之后，项目已彻底推倒重构为 mail-core + React SPA + Electron 架构，与原项目完全脱钩并独立演进。

本项目使用模板仓 repo_template。此声明必须保留，消费仓不得删除。

## 目录与读写规则

|路径|用途|写权归属|
|---|---|---|
|`src/mail_core/`|后端唯一实现（FastAPI + PostgreSQL + Worker）；分层见 `src/mail_core/README.md`|仅在 task 执行期按 spec 修改|
|`src/mail_core/db/alembic/`|数据库迁移；数据模型改动必须附带迁移|仅在 task 执行期修改|
|`src/frontend/`|前端唯一实现（React SPA，由 mail-core 同源提供）|仅在 task 执行期按 spec 修改|
|`src/desktop/`|Electron 桌面端主进程与 PostgreSQL 管理器|仅在 task 执行期按 spec 修改|
|`tests/`|测试套件（后端单测/集成测试与 E2E）|仅在 task 执行期修改|
|`scripts/`|项目构建、迁移与开发脚本|仅在 task 执行期修改|
|`docs/specs_index.md`|当前生效 spec 清单（在表即生效）|task 收尾时更新；废弃删除行|
|`docs/specs/<slug>.md`|需求级 spec（按已完成 task 累积）|task 收尾时累积更新；废弃移入`docs/archive/specs/`|
|`docs/tasks/{tid}_{slug}/`|task 工作区兼**状态权威**（backlog 起即存在）|`spec.md` / `task.md` 正文由实现侧写；`task.md` front matter 只经 `.repo_template/scripts/task.py`；reviewer 写 `review_code.md` / `review_test.md`（`single` 级写 `review_general.md`）；`finish`/`drop` 由脚本移入 `docs/archive/tasks/{tid}_{slug}/`|
|`docs/handoff.md`|项目级交接（仅最新一节）|记录须含 branch 与交出时 head_commit；过时段落迁`docs/archive/handoff.md`|
|`docs/pending/{todo,parked}/pNNN_{slug}.md`|待办与不办总账（一条目一文件，统一`pNNN`；`parked/`=用户确认暂搁，不迁 archive）|条目创建与迁移只经`.repo_template/scripts/pending.py`；skill 流程见`.repo_template/docs/usage.md`「skill 调用」|
|`docs/findings/dNNN_{slug}.md`|已验证的技术发现（一条目一文件，跨 task 复用，`dNNN`）|条目创建只经`.repo_template/scripts/findings.py`；只新增与就地修订，不迁 archive；spike 收尾或日常验证出的事实写入|
|`docs/archive/pending/pNNN_{slug}.md`|已闭环待办|仅由`.repo_template/scripts/pending.py archive` 迁入；只准新增|
|`docs/blueprint/`|当前长期真相：架构、领域、约定、决策、测试|finalization 时更新；写代码或文档前读`conventions.md`，改跨模块行为前读 `architecture.md`，历史取舍读 `decisions.md`。门禁命令在 `testing.md` 的 `## doctor_cmd` / `## test_cmd` / `## blackbox_verify` 章节。|
|`docs/reviews/review_*/`|多路 review 会话产物（内部或外部评审生成）|报告`review_*.md` 入库；确认过时由 `repo-hygiene` 迁 `docs/archive/reviews/`|
|`docs/spikes/{sid}_{slug}/`|当前 spike（`report.md` 必需；有实验代码建 `code/`）|目录创建只经`.repo_template/scripts/spikes.py new`；结论入 `docs/findings/`；完结由 `repo-hygiene` 迁 `docs/archive/spikes/`|
|`docs/guides/`|给人看的使用指南|给人读，不写 agent 行为规则|
|`docs/archive/`|完结或终止的历史|镜像原路径；内部文件只准新增|
|`schemas/`|跨服务接口契约|改契约走 task 流程|
|`config/`|配置（默认 + 环境覆盖 +`.env.example`）|仅`.env.example` 入库；真值写本地 `.env`|
|`assets/`|静态资产源文件|仅在 task 执行期按 spec 修改|
|`.repo_template/`|模板工具链（skills、scripts、docs、hooks）|仅模板演进时修改；细目与写权见`.repo_template/docs/usage.md`|
|`artifacts/` `data/` `.scratch/`|产物、运行数据、一次性草稿|运行与草稿；debug 复现和临时实验只写`.scratch/`（已 gitignore）；需保留的 spike 验证材料写 `docs/spikes/{sid}_{slug}/code/`|

## 开发原则

- specs driven：需求拆分为可独立验证的 task，填写 `spec.md`（契约区行为 AC 须非空）；版本号、底层库选型、目录结构不写进行为 AC，需要长期约束的写 `docs/blueprint/decisions.md`。
- TDD：可测部分先红后绿；测试须触达生产逻辑。实现变更让旧测试语义失效时，新增覆盖新语义的测试；旧测试原样保留或整体删除并写明理由，**禁止就地把旧测试的预期改成当前实现的输出**。
- 用户未明确要求修改，且当前任务不在获准写入的 skill 流程中时，禁止修改未被 gitignore 的代码文件。
- task 状态读取优先级：登记 worktree → 未合并 task 分支 ref → 主干。进行中 task 的状态在其合并前不进主干；`list/show/preflight --ref` 用于只读分支快照，不能据主干旧 backlog 重复 start 或维护。
- task 执行期一个实现 commit；创建期和状态维护 commit 分开；派生 index 在集成时进入同一个 merge commit。每个 commit 必须独立可验证，有工程意义。
- 发现 commit 混入不属于当前工作的改动时，立即停止工作并向用户汇报；未经用户确认，不继续提交、合并或修正。
- 使用 `.repo_template` 提供的工具链、skills、hooks、模板文件时发现缺陷，不静默处理、不自行绕过或修改，报告用户决定。
- task 状态：`backlog` / `active` / `done` / `dropped`。
- 开发工作流的设计见 `.repo_template/docs/architecture.md`，使用见 `.repo_template/docs/usage.md`。
