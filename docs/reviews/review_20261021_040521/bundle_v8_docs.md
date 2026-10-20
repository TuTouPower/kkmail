> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — 视角 8：文档规范

- 审阅目标：当前全库代码、文档、示例与注释；不是 HEAD diff。
- 基线：`daca631aec54c30ce02cdb5e6499ae196dc3a72d`。
- 时间：`2026-10-21T05:05:00+08:00`（报告记录时间；未执行运行验证）。
- 输入：`bundle.json`，168 文件、40 bundles；另读 `.env.example`、`frontend/.env.example`、`Dockerfile.mail-core`、`desktop/vendor/README.md`、`tests/mail_core/fixtures/README.md`、相关测试/包配置。
- Findings：Critical / High / Medium / Low / Info = **0 / 4 / 8 / 10 / 0**。结论：**REQUEST CHANGES**。
- 规范：`/Users/developer/kar/code/my_file/coding_agent/skills_mine/intensive-review/SKILL.md` §3 视角8；`/Users/developer/kar/code/my_file/coding_agent/docs/DOCUMENTATION_STANDARD.md`（下称 DS）§2、§3.2、§4、§8.1、§8.4；仓库 `AGENTS.md`。

## High

- [High][99] docs/upgrade.md:17 L17-L17 — Blob 轮换完成不足以退休旧密钥，会使账户凭据不可解密 — 文档要求保留旧 key「直到 `mail_core.blobs.rotate.run_rewrap()` 完成重新加密」，容易被作为删除旧 key 条件。反证：`mail_core/blobs/rotate.py:86-128` 只处理 `*.blob`、同步 `MessageBlob.key_version`；`mail_core/accounts/credentials.py:74-91` 按 `CredentialSecret.key_version` 从同一 blob keyring 派生凭据密钥，没有在 `run_rewrap` 中迁移。旧密钥下保存、且未再写入的 IMAP/OAuth 凭据会在删 key 后失效；旧备份同样可能依赖旧 blob key。修复：明确 blob 重封装、凭据重加密、保留备份可恢复性三项均通过后才允许退休旧 key；目前没有完整迁移流程时明确禁止退休，并要求 `errors=[]`、旧版本引用归零与读回验证。DS §3.2、§8.1。

- [High][98] docs/upgrade.md:5 L5-L9 — “密封备份”命令未加载实例配置，可成功生成明文且缺失真实 blob 的备份 — 同一命令还完整重复于 `docs/security.md:77-83`：`python -c "from mail_core.backup import run_backup; print(run_backup(output_dir='/path/to/backups'))"`。`--data-dir` 只在服务子进程调用 bootstrap，并不修改启动 shell 环境；该独立 Python 不调用 `bootstrap_data_dir`。反证：`mail_core/backup/package.py:242-245` 未配置 backup key 时自动选择明文，`blobs/archive.py:40-41` 默认读 `[REDACTED]mail-core-blobs`，`package.py:209-217` 根目录不存在仍生成空 blobs.tar；`run_backup:483-496` 可以返回 `status=ok`。采用文档推荐 `--data-dir` 的实例，仅有 DB URL 时即可得到“通过校验”的错误范围备份。Docker 镜像又未安装 `pg_dump`（`Dockerfile.mail-core` 仅装 curl），文档也未指定在哪个具备客户端/真实 blob 挂载的进程执行。修复：补齐匹配实例的 DB URL、blob 根、备份/解密密钥加载与 PG16 客户端前提；强制 `encrypt=True`，使用每次独立输出目录，检查状态后才允许升级；备份前停止写入/GC或声明受验证的一致性策略。DS §3.2、§8.1。

- [High][98] docs/upgrade.md:16 L14-L17 — 通用 downgrade 回滚步骤缺少破坏性检查点与可恢复性条件 — 文档直接给出 `alembic ... downgrade <旧 revision>`，只提示「基线迁移不可降级」。实际 `20261020_0001_baseline.py:21-22` 的 downgrade 为 `pass`，并非拒绝降级；`20261020_0002_mail_core_unified_schema.py:254-277` 会删除 messages/accounts 等核心表，`0007` 亦删除凭据表。旧 revision 未定义、不核对目标，不停止当前 API/worker，不验证恢复包或先在副本演练，可能在新代码运行中删表/丢凭据。修复：逐目标列出可逆范围、停止 API/worker 后迁移、先验证完整备份能恢复、遇不兼容/删表迁移停止并走副本恢复；恢复后验证行数/解密/`/ready`；纠正基线描述。DS §3.2、§8.1，AGENTS 工作区与数据保护要求。

- [High][100] RELEASE.md:8 L7-L8 — 当前发布说明仍声称推 tag 自动发布，但所有工作流已删除 — 文档写「推送标签 `vX.Y.Z` 触发发布工作流」，L19 要求 `main` 上 `tests`/`frontend` 检查，L27-L35 只推代码和 tag 后就要求 Release 附件与镜像齐全。反证：`git ls-tree -r --name-only HEAD .github` 为空；`CHANGELOG.md:37` 明确“不再跑远程测试、构建、发版”；`BRANCH_PROTECTION.md` 也明确无 Actions。按唯一发版指南执行不会产生镜像、安装包或 Release。修复：将旧自动发布流程标为过时，按当前实际支持范围写本地验证、构建、产物校验和明确授权后的手动上传/发布步骤；若尚无可用发布流程，明确待建立，不宣称 tag 会发布。DS §2.1-2.2、§3.2、§8.1。

## Medium

- [Medium][100] docs/upgrade.md:10 L10-L12 — Compose 升级未重建运行容器或重新执行 migrate，旧服务 `/ready=200` 会造成升级成功假象 — 唯一命令是 `docker compose ... build`；这只构建镜像，不替换 api/worker，也不运行已经结束的 migrate 服务。随后“compose 的 migrate 服务”和 `/ready` 检查未提供启动步骤。旧进程的 `_code_schema_head` 来自旧代码（`mail_core/api/app.py:83-93`），旧库与旧进程匹配仍返回200。修复：明确检查目标镜像/commit，停止写入，显式运行目标版本一次性迁移并检查退出状态，再替换 api/worker；核对 `/health.version` 与 schema head 均来自目标产物，失败则停止并按已验证回滚方案处理。DS §3.2、§8.1。

- [Medium][100] docs/upgrade.md:9 L9-L9 — “恢复演练”实际固定无效 DB，只测试加解密与校验和 — 同类宣称见 `docs/mail-core-status.md:16`、`docs/security.md:83`。`scripts/mail-core-backup-restore-drill.sh:50` 固定 `postgresql://nobody:...@127.0.0.1:1/none`，L59-L77 在 pg_dump 失败后允许 sql_stub 并输出 `DRILL_OK`；无 pg_restore、实例恢复或邮件可读性验证，也不接受待恢复真实备份。该结果不能作为升级/回滚前的可恢复证据。修复：把现有脚本准确命名/说明为 crypto-only 封包校验，并明确未验证恢复；另提供隔离临时 PostgreSQL、还原 dump/blob、加载原密钥、验证代表邮件与附件的恢复流程。DS §2.4、§3.2、§8.1。脚本自身 L2「no live pg_restore by default」也应纠正为始终不做 pg_restore。

- [Medium][99] docs/deployment.md:39 L35-L42 — 拆分 API/worker 示例丢失 data-dir 与共享密钥加载，不能替代上一行单进程部署 — 示例注释建议 `python -m mail_core --no-worker` 与 `python -m mail_core.worker.main`，没有沿用 `/var/lib/kkmail`；已配置 DB URL 也不会自动加载该目录密钥。API缺登录/blob key时失败；worker入口仅 `load_keyring_from_env`（`worker/main.py:133-139`），不调用 bootstrap，独立进程亦不继承 API bootstrap 后环境。修复：给出两进程共同配置来源、同一 blob root/keyring，以及 API 明确 `--data-dir`；为独立 worker 提供受支持的加载方式，或明确仅在所有共享变量已导出时可用。`mail_core/README.md:19` 同样需要链接该前提。DS §3.2、§8.1。

- [Medium][95] docs/deployment.md:29 L25-L31 — TLS 部署只说“设置 Secure Cookie 变量”，未说明 Compose 必须把变量传入 API — 本页前半段全部用 host `export` 配置 Compose，但 `docker-compose.mail-core.yml` 的 api.environment 没有 `MAIL_CORE_COOKIE_SECURE`，单纯 export 或写 .env 不会传入容器。`security/auth.py:68-74` 缺失时返回False，登录 Cookie 因而没有Secure属性。相邻 L30 对 FORWARDED_ALLOW_IPS明确要求“compose 中给 api 加环境变量”，Secure设置却缺相同条件。修复：给出实际 Compose override/environment项并重新创建API，随后检查真实登录响应 Set-Cookie包含Secure；把TLS要求与传参路径一起定义。DS §3.2、§8.1。

- [Medium][100] RELEASE.md:7 L7-L20 — 版本操作只更新 VERSION，桌面产物与 API版本不会跟随 — L28只 `echo X.Y.Z > VERSION`，但 `desktop/package.json:3` 单独写 `3.0.20`，electron-builder使用`${version}`命名产物；`mail_core/__init__.py:6`独立写`0.1.0`，API `/health`和OpenAPI均读取它。不存在发布工作流或同步脚本补齐这些来源。下一次按指南发布会产生新tag、旧安装包版本及旧API版本。修复：确定产品版本与后端组件版本关系，列出必须更新或生成的来源及lockfile/生成schema检查；发版核对以最终安装包metadata、`/health.version`、tag一致性为准。DS §3.2、§8.1、§9.1。

- [Medium][100] desktop/README.md:22 L19-L23 — 子进程环境隔离说明与实际前缀白名单相反 — 表格说 `MAIL_CORE_*`“not inherited from the parent shell”，L53又概括“parent secrets are not inherited”。`desktop/startup.js:62-74`却显式允许所有`MAIL_CORE_`与`KKMAIL_`前缀，`main.js:77-83`只覆盖四个运行项；父级`MAIL_CORE_LOGIN_PASSWORD`、API keys、blob/backup keys仍传入，bootstrap会优先采用它们。表格`PG*`也不是父级前缀白名单，只有extras中显式提供的PG变量才通过。修复：文档准确列出继承边界、覆盖项与parent环境优先级；每安装独立密钥需声明父环境没有这些覆盖项；若授权边界本来要求隔离，先修实现而不能把契约静默改写。DS §3.2、§8.4。

- [Medium][97] RELEASE.md:29 L26-L30 — 发版示例 `git commit -am` 可混入全部无关已跟踪改动 — 文档没有要求/验证干净工作树，直接 `git commit -am "chore(release): ..."` 然后push，会把当前全部tracked修改纳入发布提交，违反仓库“用户改动默认保留、不提交无关改动”要求。版本化与发布是高影响操作，应让读者能确定实际提交范围。修复：先只读检查status/diff、核对工作树归属；仅stage已审阅的版本/变更记录文件，检查cached diff后再commit和push；存在无关改动时停止发版步骤并隔离工作区。DS §8.1，用户AGENTS“工作区保护”。

- [Medium][99] docs/deployment.md:35 L33-L42 — 非 Docker 部署未构建或配置 SPA，按文档全新安装只能启动 API — 本节只安装Python依赖后启动mail-core，无Node/npm前提、`frontend npm ci/build`或预构建SPA路径。`mail_core/api/app.py:25-35,144-164`仅在已存在`frontend/dist/index.html`或有效`KKMAIL_FRONTEND_DIST`时注册首页。全新clone按此唯一部署入口操作，访问声明的同源SPA会404。修复：注明从仓库根执行，先生成/取得与后端版本匹配的frontend/dist并验证路径；或链接根README中已存在的构建步骤。将只启动API的方式明确区分。DS §3.2、§8.1、§8.4。

## Low

- [Low][100] docs/mail-core-status.md:7 L7-L7 — 当前实现状态仍把迁移 head写成0007 — 仓库已存在`20261021_0008_blob_gc_eligible_at.py`与`20261021_0009_inbox_keyset_indexes.py`，0009的`down_revision`为0008；`/health`按Alembic实际head计算。此状态页会误导schema核对。修复：更新为当前head或仅说明以`/health.schema_head`/迁移目录为准，避免第二份手写head。DS §2.1、§3.2、§4。

- [Low][100] docs/troubleshooting.md:34 L32-L35 — 忘记密码说明把初始密码文件写到错误子目录 — 写“生成新的 `secrets/initial-password.txt`”，而`runtime/bootstrap.py:77`用`root / INITIAL_PASSWORD_FILE`，即`<data-dir>/initial-password.txt`；security/README也写根目录。按排障文档会在错误位置寻找恢复密码。修复：改为相对data-dir根的正确路径，并注明同一data-dir与无环境密码覆盖前提。DS §3.2、§8.4。

- [Low][100] docs/api.md:44 L42-L46 — 连续执行漂移检查代码块会因工作目录变化失败 — L44 `cd frontend && npm run openapi:check`后留在frontend，L45的`tests/mail_core/...`相对路径不存在；L46再次`cd frontend`也不存在。相同错误在`frontend/src/api/generated/README.md:18-20`。修复：用`(cd frontend && npm run ...)`保持根目录，或各命令明确独立执行及工作目录；保留一份完整检查流程，生成类型README只链接。DS §4、§8.1。

- [Low][100] docs/api.md:51 L49-L53 — 认证约定的“所有路由”例外清单与本页公开schema/SPA表冲突 — 此处称“Every route except `/health`, `/ready` and login requires”认证，但L20-L21与`api/app.py:59-64,144-164`明确`/docs`、`/openapi.json`、`/redoc`、SPA无需认证。未认证访问公开schema返回200不是违约或安全故障。修复：把断言限定为business API，并直接引用同页Route surface，不另列不完整例外。`CHANGELOG.md:30`同样可用“business API”避免绝对化。DS §3.3、§4、§8.4。

- [Low][100] docs/mail-core-desktop.md:83 L78-L83 — `KKMAIL_PACK_STRICT=1`并不能让所有列出的打包失败变成硬失败 — 文档将未安装builder、下载失败、缺PG列为soft-ok，然后推荐strict用于硬失败。`desktop/scripts/pack-linux.js:38-41`在builder缺失时直接exit0，不检查strict；缺PG时L32-L35只提示，即使strict也可exit0。strict只处理builder进程非0退出（L68-L74）。修复：准确缩小strict覆盖说明，列出缺builder/PG/sidecar的独立前置检查；若意图提供可发版门禁，应修脚本后同步文档。DS §3.2、§8.1。

- [Low][99] docs/mail-core-architecture.md:145 L139-L151 — 部署拓扑保留旧`web`服务名与worker outbox职责，未标明与当前实现差异 — 架构写Compose服务`web/worker/postgres`，实际文件使用`api/worker/postgres/migrate`；L146说worker参与outbox投递，但`realtime/dispatcher.py:3-6`明确worker不得调用dispatch（会抢走API事件），`worker/handlers.py`只发送NOTIFY唤醒。本文件虽是供实现契约，当前已落地章节却混用旧命名；不能靠读者猜测这是未来要求还是过时。修复：按决策流程明确当前映射`web→api`、migrate职责与API拥有dispatcher，并标记原部署命名被替代；若保留目标拓扑，则显式列实现偏差。DS §2、§3.3。

- [Low][96] docs/security.md:77 L75-L83 — 备份流程有两份完整定义，安全页与升级页会独立漂移 — `docs/upgrade.md:5-9`与此处都完整给出相同run_backup命令、输出/密钥与演练说明；认证能力模型也在`security.md:13-17`、架构§11.4、known-limitations和AGENTS保留多份完整解释。此轮已出现同类漂移：api认证例外与security公开路由不同、初始密码路径与troubleshooting不同。修复：安全页仅保留保护要求与摘要，具体备份/恢复步骤统一在升级/恢复runbook；能力模型完整定义保留一处，其余摘要链接且不改语义。DS §4、§8.4。此项只报告重复权威，不要求删历史证据快照。

- [Low][100] mail_core/accounts/settings_store.py:10 L10-L10 — 配置写入注释仍声称忽略未知字段，实现已改为拒绝 — 注释写“Anything else is ignored on write”，实际L47-L50对未知或secret key抛ValueError，API `accounts.py`映射为400。维护者依注释可能把破坏性输入行为误当无害忽略。修复：描述当前reject语义；读侧仍omit，分别准确说明。另`mail_core/mail/storage/models.py:81`把credential_ref仅写成OS Keychain/KMS引用，实际默认DB加密store（`accounts/credentials.py:186-214`），应改成实际支持scheme或引用store契约。DS §8.4。

- [Low][100] mail_core/blobs/rotate.py:3 L3-L6 — crash-safety docstring未限定自建session，夸大“至多一个digest暂不一致”保证 — 文档声称每个文件后都commit，实际`rewrap_all_blobs(session=...)`分支L121-L123只flush，不逐文件commit；无DB配置分支L94-L95、L115-L116完全不更新DB。这些受支持参数路径可以积累多文件/DB版本不一致。修复：把逐文件提交与至多一个digest保证限定到默认自建session且DB可用路径；显式说明外部session由调用方事务控制、离线模式不更新DB。无需为文档准确性擅自改变调用方事务语义。DS §3.2、§8.4。

- [Low][100] CHANGELOG.md:1292 L1279-L1293 — 历史release条目被批量追加同一后来的修复，损害版本追溯 — `2.0.0`（2026-04-09）也记“重试失败改流式”，多处旧版同样重复“Token刷新管理移除运行中进度卡”。`git blame`及`git show 3d9dbbbe297ea8d8524ae3ea79f6f56e4a8e8169 -- CHANGELOG.md`直接显示2026-04-28同次修改向2.0.34及此前数十历史小节添加40行相同记录；修复代码亦在该commit引入。它不是单纯重复排版，而是把同一后续变更归入早期版本。修复：用明确勘误说明受影响历史条目及正确首发版本，保留原记录可追溯，不无声重写/批量删历史。DS §2.2、§9.2。

## 覆盖与证据

- 全量阅读当前文档：根目录`README/AGENTS/RELEASE/BRANCH_PROTECTION/CHANGELOG/DESIGN`；`docs`下9份人工Markdown；`mail_core/README`；`desktop/README`、`desktop/vendor/README`；`frontend/README`、`ARCHITECTURE`、生成API README；fixtures README。共22份非review Markdown。`CHANGELOG.md`历史小节按历史证据处理，没有把已删除的Flask/扩展功能当作当前需求。
- 代码视角覆盖：对bundle中Python/JS/TS/TSX/shell注释、docstring做全库检索，并用AST抽取多行Python docstring；对认证/CSRF、静态资源、schema head、bootstrap、备份加密与打包、轮换、credentials、worker启动、桌面env/进程与打包、Compose/Dockerfile、前端请求和token配置逐项核对调用点。代码实现缺陷与文档缺陷区分；例如Compose缺共享持久blob目录属于实现/部署配置根因，已向主任务提供证据，未在此重复计数。
- 相对Markdown目标做只读存在性检查：22份文档未发现不存在目标；未发现需要校验的显式`#anchor`链接。纯代码样式路径另与`rg --files`核对。没有请求公网或验证外链可访问性。
- 生成资料：读取`docs/openapi.json`、`frontend/src/api/generated/schema.ts`契约位置与生成器/调用链，确认生成源为FastAPI `app.openapi()`、`scripts/export_openapi.py`、`scripts/gen-openapi.sh`和openapi-typescript。未改生成物、未重生成。
- Agent指令：仓库根`AGENTS.md`在当前加载路径，已由任务上下文明确提供；没有把普通Markdown链接当自动加载。未发现必须通过嵌套指令导入才能生效的安全规则。
- 未报为问题：单用户UUID能力边界；无发信/联系人/系统通知/扩展；SPA仅首100条、无浏览器E2E；设计稿已明确其动作清单只是视觉参考；Keychain/KMS明确标为目标；Linux scaffold的soft-ok本身已明确标记；这些不是未实现功能漏报。

## 历史追溯

全库审阅按当前真实问题保留基线已存在项，不把“不是最后一次commit新增”当排除条件。

| 问题位置 | blame/history来源 | 结论 |
| --- | --- | --- |
| RELEASE标签发布、版本/提交步骤 | `b5edaa6a`，工作流删除见`af85b20` | 旧流程未随删除同步；当前仍有效入口 |
| upgrade备份/恢复/回滚文本 | `daca631a`，轮换条件`a875ce95` | 部分为基线HEAD最近改动，其他为预存 |
| deployment直跑/拆进程、Secure设置 | `b5edaa6a`；代理补充`a875ce95` | 预存流程缺口 |
| schema状态0007、密码恢复路径 | `b5edaa6a` | 预存文档漂移 |
| API drift命令/生成README | `3dc1e071` | 初始codegen说明引入cwd问题 |
| pack strict说明 | `daca631a` | 基线HEAD新增说明未覆盖全部分支 |
| 架构web/worker职责 | `8106e07c` | 初始方案语义与当前进程职责不再一致 |
| settings注释 / credential_ref注释 | `a4a5239a` / `ff2640b9` | 预存注释未随实现同步 |
| rotate crash-safety docstring | `1ce66644` | 新保证只适用部分调用路径 |
| CHANGELOG历史污染 | `3d9dbbbe297ea8d8524ae3ea79f6f56e4a8e8169` | 同一后续提交向数十旧版本插入相同条目，有直接patch证据 |

## 验证限制

- 只读静态审阅；仅写本报告。未运行tests、lint、tsc、build、迁移、备份脚本、打包脚本、Docker/桌面启动、发布或恢复；所有命令结论属于“写法/调用路径已核对”，不是“流程实测通过”。
- 没有读取其他agent报告或既往review正文；没有用旧review结论替代本轮取证。关联Git历史仅用于定位引入时间与核实历史记录。
- 未获取生产配置、真实密钥、部署产物、目标机器PG客户端及受控恢复结果，因此“目标环境可恢复、TLS参数已生效、安装包可启动”均不能在本报告中标Verified。
- 对进程环境、FS备份范围、数据迁移等安全/破坏性断言至少同时核对文档、实现与实际调用/配置入口；仍需修改后的隔离环境恢复/升级实测，才能消除运行风险。
