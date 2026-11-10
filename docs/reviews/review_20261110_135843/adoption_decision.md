# 审阅结果决策

## 目录

docs/reviews/review_20261110_135843

## 报告来源

- 已读：review_intensive.md
- 缺失：根目录无任何 `bundle_*.md`，以聚合 review_intensive 为准（该报告为单次穷尽模式产出，正文自带逐项证据）
- 合并说明：报告含 5 条闭环裁决（A–E）+ 24 条编号问题 → 21 个决策项。映射：
    - 裁决 A（已闭环）、D（实质闭环）：无需动作，不单列；其残留尾巴即问题 1–4、19–24
    - 裁决 B（未闭环）+ 问题 7、8、9 → A16（原 D3；同一根因：stamp/基线校验严格度）
    - 裁决 C（部分闭环）→ 拆分为问题 10–18 各自决策
    - 裁决 E（部分闭环）→ 拆分为问题 19–24 各自决策
    - 问题 2、3 → A14（原 D1；同一根因：两入口按分类执行的模式校验不对称）
    - 问题 11、12 → A17（原 D4；同一类：形状型整值豁免可被借用）
    - 问题 16 拆为 A7（关键词与 JSON 键形态）与 R2（门禁范围扩大与表格形态）
    - 其余问题一对一：1→A1、4→A2、5→A3、6→A15（原 D2）、10→A4、13→A18（原 R1）、14→A5、15→A6、17→A19（原 R3）、18→R4、19→A8、20→A9、21→A10、22→A11、23→A12、24→A13
- 优先级：原报告「不分级」，下列优先级为本决策按影响面自行评定
- 决策准则：用户指示按项目 AGENTS.md「核心架构铁律」（架构至上、拒绝妥协、零兼容性负担）决策。据此：D1–D4 全部取最彻底方案并转入采纳；原以误报/改动成本为由的 R1、R3 改判为根因修正并转入采纳；A3、A6 修复说明从「文案/记录」升级为结构性修正；R2、R4 理由与成本无关（属范围与语义判定），维持不采纳

## 统计

- 采纳：19 项
- 不采纳：2 项
- 待决定：0 项

## 待决定项（请先决策）

无（原 D1–D4 已按核心架构铁律决策，分别转为 A14–A17）

## 采纳项

### A1. 离线 RevisionContext 写死，新增 revision 后两入口分类分歧

- 来源：review_intensive（问题 1）
- 位置：src/mail_core/db/baseline.py:770-781（`offline_revision_context`）；src/mail_core/__main__.py:54-62
- 优先级：HIGH
- 详细判断理由：已核实。启动从 `ScriptDirectory.walk_revisions()` 动态取 known_revisions/heads，离线写死 `{UNIFIED_BASELINE_REVISION}`；当前仅一个迁移文件故恰好相等，新增 revision 即复发旧问题 A（报告探针已复现）。单源的是分类函数而非分类输入，属设计缺陷，须根因修正。
- 修复说明：在 baseline.py 新增唯一的 context 构造函数（如 `revision_context() -> RevisionContext`），内部按 `mail_core.db` 包路径定位 `alembic.ini` / `alembic` 目录、经 `ScriptDirectory` 取 known_revisions 与 heads；删除 `offline_revision_context`；`__main__.run_migrations` 与 `run_migration` 均调用之（`__main__` 中 cfg 构造复用同一路径解析）。新增非 PG 门控单测：临时迁移目录多一个 revision 时两入口取到的 context 相同

### A2. 启动入口手抄一份数据库状态读取逻辑

- 来源：review_intensive（问题 4）
- 位置：src/mail_core/__main__.py:69-85；src/mail_core/db/baseline.py:784-794（`read_database_state`）
- 优先级：MEDIUM
- 详细判断理由：已核实两份逐行等价，当前无活分歧，但违背「单一入口」，`read_database_state` 后续扩展时启动侧不会跟随。
- 修复说明：`__main__.py` 中 inspect + 查 version_num + 拼 `DatabaseState` 段替换为 `baseline.read_database_state(conn)`；删除因此无用的局部变量。与 A1、A14 合并考虑：两入口共享「读状态 → 分类 → 按分类校验」同一条 baseline.py 内路径，入口只保留各自支持的执行动作（启动 upgrade / 离线转换与 stamp）

### A3. 比基线更新的 revision 被提示为 legacy 并引导恢复旧备份

- 来源：review_intensive（问题 5）
- 位置：src/mail_core/db/baseline.py:876-884
- 优先级：MEDIUM
- 详细判断理由：已核实。日期型 revision 大于当前 head（库由更新版本写入）统一判 UNKNOWN_REVISION，文案 "unrecognized legacy revision ... restore a known-good backup"，会引导运维用旧备份覆盖较新数据，有数据丢失风险。按架构铁律，「库比程序新」是独立的真实状态，应在分类层建模，不靠同一动作换文案。
- 修复说明：MigrationAction 新增独立动作（如 `NEWER_THAN_CODE`）；plan_migration 在 UNKNOWN 分支前识别「日期型且大于所有 head」的 revision 返回该动作，文案说明「数据库由更新版本 kkmail 写入，请升级 kkmail；不要用旧备份覆盖」；两入口均列入拒绝集合。补纯函数单测（`20261201_0001` → `NEWER_THAN_CODE`）

### A4. 以 `$`、`(`、`{`、`<` 开头的值整类放行

- 来源：review_intensive（问题 10）
- 位置：scripts/check_doc_sensitive.py:162-165（CODE_EXPRESSION_RE 第一分支）；:147-150（SAFE_REFERENCE_RE 前三分支无 `\Z`）
- 优先级：HIGH
- 详细判断理由：已核实。`\A[{($<]` 命中即 safe，`$uperSecret99`、`(hiddenpass1)` 判 SAFE，与「根除字符集豁免」声称不符。合法模板形态已由 SAFE_REFERENCE_RE 的 `${...}`、`$(...)`、`{{...}}` 覆盖。
- 修复说明：删除 CODE_EXPRESSION_RE 的 `\A[{($<]` 分支（与 A17 合并后 CODE_EXPRESSION_RE 整体删除）；SAFE_REFERENCE_RE 的 `${...}`、`$(...)`、`{{...}}` 三分支补 `\Z` 整值锚定。补单测：`$uperSecret99`、`(hiddenpass1)`、`${X}tail` 判违规，`${X}`、`$(cmd)`、`{{ t }}` 判 safe。改后对已跟踪 docs 全量实跑，新增命中逐条判定：真泄漏修文档，合法写法加带理由 allow marker（见 A19）

### A5. SAFE_REFERENCE_RE 环境引用分支为子串 search，含 `os.environ` 字样即整值豁免

- 来源：review_intensive（问题 14）
- 位置：scripts/check_doc_sensitive.py:152-156
- 优先级：HIGH
- 详细判断理由：已核实。五个 API 引用分支无起始锚点且以 `.search()` 调用，`abc os.environ leak` 整值豁免，直接违背注释「never a contains-character exemption」。
- 修复说明：五分支改为整值锚定（值以 `os.environ`、`os.getenv(`、`getenv(`、`process.env`、`store.get_secret(` 开头且整值为该引用表达式，如 `\Aos\.environ(\[[^\]]+\]|\.get\([^)]*\))\Z`），`is_safe_credential` 对 SAFE_REFERENCE_RE 改用 `fullmatch`。补单测：`abc os.environ leak`、`os.environ leak` 判违规，`os.environ["X"]`、`os.getenv("X")`、`process.env.X` 判 safe

### A6. isolated-assignment gate 全有全无，同行多赋值整行出界

- 来源：review_intensive（问题 15）
- 位置：scripts/check_doc_sensitive.py:236-253（`_is_isolated_assignment`）、:452-456；docs/blueprint/testing.md 敏感文档门禁说明
- 优先级：MEDIUM
- 详细判断理由：已核实 gate 为整行前置门，同行第二个赋值使后缀不干净即整行跳过，未加引号多词口令亦同。按「拒绝妥协」，不能仅记录为已知取舍了事：同行多赋值是可结构化解决的召回缺口，应从 gate 设计上修正；未引号多词值与散文 `password = all power` 在形状上不可区分，属检测原理边界，如实记录。
- 修复说明：gate 改为按「赋值片段」判定——先按语句分隔符（`;`、`&&`、行内 `,` 后紧跟新 `key=` 等）把行切成片段，每个片段独立做前缀/后缀干净判定与 `is_safe_credential`，同行多个赋值各自检出；未引号多词值维持只取首词并在 testing.md 与 `is_safe_credential` docstring 写明 default-deny 的适用边界。补单测：`password=abc123; token=xyz789` 两处均检出

### A7. 凭据关键词缺 apikey / private_key，JSON 键形态无命中

- 来源：review_intensive（问题 16 第二、三点）
- 位置：scripts/check_doc_sensitive.py:90-99（CREDENTIAL_KEYWORDS）、:101-104（ASSIGN_RE）
- 优先级：MEDIUM
- 详细判断理由：已核实关键词表不含 `apikey`、`private_key`；`"password": "x"` 因 key 后紧跟引号不匹配 ASSIGN_RE。均为文档中常见泄漏形态，属门禁范围内的漏检。
- 修复说明：CREDENTIAL_KEYWORDS 增加 `apikey`、`private_key`；ASSIGN_RE 允许 key 前后可选同种引号（如 `[\"']?key[\"']?\s*[:=]`），isolated gate（A6 片段化后）同步接受 JSON 行（含行尾逗号）。补单测覆盖 `apikey=...`、`private_key: ...`、`"password": "x",`。改后对已跟踪 docs 全量实跑并逐条判定新增命中

### A8. handoff「已逐一核实」SQLite 残留清单不完整

- 来源：review_intensive（问题 19）
- 位置：docs/handoff.md:49
- 优先级：LOW
- 详细判断理由：已核实清单仅列 7 个文件，HEAD 另有 8 个含 sqlite 字样文件未列入；残留本身无害，但「逐一核实」与 grep 结果对不齐，属同型记录失实。
- 修复说明：按报告 D 节三类分类（legacy 输入契约 / 字符串注释退役说明 / 方言名 stub）补全为完整清单，并附可复现的 grep 命令

### A9. 「25 个」手写 DDL 测试计数无法复现

- 来源：review_intensive（问题 20）
- 位置：docs/handoff.md:29、:36
- 优先级：LOW
- 详细判断理由：报告按可复现口径得 24（迁移文件并集）/ 22（含手写 CREATE TABLE），与 25 均不符且无清单，与上轮被纠过度声称同型。
- 修复说明：落地时按 `1fff64c6`、`a029d639` 实际 diff 重新统计，写入可复现数字并附文件清单或统计命令

### A10. handoff head_commit 语义前后不一

- 来源：review_intensive（问题 21）
- 位置：docs/handoff.md:9
- 优先级：LOW
- 详细判断理由：已核实现行节 head_commit 写 c3c824f6，与 37f60d03 节立下的「本节所述代码状态」口径不一致，前一节又少报 3062626b。仅改现行节，不回改历史。
- 修复说明：现行节 head_commit 按「本节所述代码状态的最后一个代码提交」口径重写（落地后以届时实际 git log 复核），并在字段旁一次性写明口径定义

### A11. baseline.py 函数「已删除」表述不精确

- 来源：review_intensive（问题 22）
- 位置：docs/handoff.md:47
- 优先级：LOW
- 详细判断理由：已核实 `configure_read_only` 等三个函数仍存在，仅改为非 PG 抛 ValueError；`_migrate_patrol_status_data_generic` 确已删除。
- 修复说明：改为「删除 `_migrate_patrol_status_data_generic` 与 advisory lock 的 SQLite 分支；`configure_read_only`、`ensure_folder_patrol_status_table`、`_check_cursor_data` 保留但非 PG 一律 ValueError」（若 A16 落地改变这些函数存废，以落地后实际为准）

### A12. PG 侧手写历史 DDL 存续未主动澄清

- 来源：review_intensive（问题 23）
- 位置：docs/handoff.md:49
- 优先级：LOW
- 详细判断理由：test_startup_migrations.py（40 处）与 test_migration_validation.py（34 处）手写 CREATE TABLE 为 PG 语法历史 schema fixture，定性合理，但现行文本易被读成「手写 DDL 已彻底删除」。
- 修复说明：在清单中明确两文件保留 PG 语法手写历史 DDL 的数量与理由（0030 历史形态冻结转写，跑在 PG schema 上），与「SQLite DDL 复刻生产表已清零」区分

### A13. 全量门禁数字无留存证据，testing.md 结果表未登记

- 来源：review_intensive（问题 24）
- 位置：docs/blueprint/testing.md:307-314；docs/handoff.md:41、:50
- 优先级：MEDIUM
- 详细判断理由：已核实 testing.md 门禁结果表最新行停在 2026-10-27，2142/2 skip 等数字仓库内无日志或证据文件，前端/桌面/E2E「本轮实测」亦无证据。本机有 OrbStack，可在本机真实 PG 复跑补证。
- 修复说明：全部采纳项落地后，在本机真实 PG 环境复跑 `## test_cmd` 全量门禁（后端 + 前端 + tsc + 桌面，按 testing.md 定义），把结果与证据文件链接登记进 testing.md 门禁结果表；handoff 数字与之对齐，与原声称不一致处据实更正。证据文件存放位置按 testing.md 既有惯例；若须新建 review 目录，落地前先确认

### A14. AT_BASELINE 两入口模式校验不对称（启动 check 从不校验 schema）（原 D1）

- 来源：review_intensive（问题 2、3）
- 位置：src/mail_core/__main__.py:92-98；src/mail_core/db/baseline.py:925-930
- 优先级：HIGH
- 详细判断理由：已核实。启动入口对 EMPTY / AT_BASELINE 在 check_only 时直接 return、正常启动直接 `command.upgrade`，`verify_database_schema` 在 baseline.py 外零调用方；离线入口对 AT_BASELINE 调 `verify_database_schema`。部署 preflight 放行漂移基线库而离线工具拒绝，门禁结论可相反；且 LEGACY 验得比 AT_BASELINE 严。校验口径须与分类同样单源。
- 修复说明：在 baseline.py 抽出「按 plan 执行校验」单一函数（如 `verify_for_plan(conn, plan) -> list[str]`：AT_BASELINE→完整基线校验（A16），LEGACY→窄校验，EMPTY→无），两入口都调用；启动的 check_only 与正常启动均对 AT_BASELINE 执行校验，失败即拒绝启动。补 PG 门控测试：手工删列的基线库，启动 check、正常启动、离线工具三者均拒绝
- 选项：
    - A 抽出单一「按 plan 校验」函数，两入口共用，正常启动也校验
    - B 仅在启动 `--check-migrations` 路径加校验
    - C 保持现状，文档记录差异
- 推荐：A
- 推荐理由：校验口径单源，彻底消除同库两门禁结论相反；fail-closed
- 用户决策：A（按核心架构铁律决策：架构至上、拒绝妥协、零兼容性负担）

### A15. LEGACY 分类保留日期模式启发（原 D2）

- 来源：review_intensive（问题 6）
- 位置：src/mail_core/db/baseline.py:82-94（`is_legacy_revision`）、:858
- 优先级：LOW
- 详细判断理由：已核实。形如 `YYYYMMDD_NNNN` 且小于基线的任意 revision 即判 LEGACY，伪造 revision 分类标签错误，报错文案掩盖「非任何已知 revision」事实。启发式分类是设计缺陷，分类输入应显式可审计。
- 修复说明：删除 `is_legacy_revision` 的日期启发；从 Git 历史枚举旧迁移树全部 revision 写入显式集合，区分「窄转换支持的旧 revision」与「其余已知旧 revision」（后者在 plan 层给出「旧版本库，需先用对应历史版本升级」专门动作/文案），未列入的一律 UNKNOWN_REVISION；同步 upgrade.md。补纯函数单测：`20200101_0001` → UNKNOWN_REVISION，枚举集合内旧 revision 各自分类正确
- 选项：
    - A 删除日期启发，显式枚举全部旧 revision，同步 upgrade.md
    - B 保留启发，仅调整窄校验失败文案
    - C 保持现状
- 推荐：A
- 推荐理由：分类输入显式、可审计；旧迁移树已冻结，枚举一次即可
- 用户决策：A（按核心架构铁律决策：架构至上、拒绝妥协、零兼容性负担）

### A16. 基线/旧库 stamp 前 schema 校验严格度（旧问题 B 未闭环）（原 D3）

- 来源：review_intensive（裁决 B，问题 7、8、9）
- 位置：src/mail_core/db/baseline.py:131-190（REQUIRED_COLUMNS）、:294-325（`verify_database_schema`）、:331（`_column_affinity`）、:392（窄校验）
- 优先级：HIGH
- 详细判断理由：已核实。`verify_database_schema` 只验 32 表名 + 15 表关键列名；窄校验深度只覆盖转换触碰的 4 张表，类型判定用子串 affinity。带合法 revision 的漂移库可被当作合格基线接受。手写列清单是与基线 DDL 并行的第二份真相，属设计缺陷，须从根因收敛为单一真相源；零兼容性负担下，现存漂移库被拒绝是预期结果。
- 修复说明：以统一基线 ORM metadata 为唯一真相，用 Alembic 内置 `alembic.autogenerate.compare_metadata` 对全部 32 表做完整比对（列名、PG 精确类型、可空、PK/FK/唯一约束、索引）；AT_BASELINE 校验（A14 的 `verify_for_plan`）与 LEGACY 转换后（同一写事务内、stamp 前）均执行，任何差异即拒绝；删除 REQUIRED_COLUMNS 手写表与 `_column_affinity`，窄校验仅保留「转换前置条件」检查。先在真实 PG 上确认 compare_metadata 对新建基线库零差异（排除 server_default、类型渲染等假阳性），需要的忽略规则显式列出并附理由。补 PG 门控测试：改类型、删约束、删列的基线库各自被拒
- 选项：
    - A compare_metadata 全量比对，删除手写列清单与 affinity
    - B REQUIRED_COLUMNS 扩到全部 32 表（仍只验列名）
    - C 接受现行严格度
- 推荐：A
- 推荐理由：复用成熟库能力，校验源与基线 DDL 单源，一次根除 7/8/9
- 用户决策：A（按核心架构铁律决策：架构至上、拒绝妥协、零兼容性负担）

### A17. 函数调用形态与尖括号整值豁免可被真实口令借用（原 D4）

- 来源：review_intensive（问题 11、12）
- 位置：scripts/check_doc_sensitive.py:151（`\A<[^<>]+>\Z`）、:162-165（函数调用分支）
- 优先级：MEDIUM
- 详细判断理由：已核实。`Str0ng(Pass)`、`<realpass123>` 形态判 SAFE；handoff「带括号形态均检出」声称不完整。纯形状无法区分代码与口令，任何收窄都是启发式补丁；彻底方案是 default-deny 只保留显式白名单，合法例外由带理由的显式标注承担。
- 修复说明：删除 CODE_EXPRESSION_RE 整体与 SAFE_REFERENCE_RE 的 `\A<[^<>]+>\Z` 分支；尖括号占位词仅经 SAFE_CREDENTIAL_PLACEHOLDERS 显式列举放行（按需补充文档中实际使用的占位词，如 `<your-token>`）；文档中合法代码写法加带理由 allow marker（A19）。补单测：`Str0ng(Pass)`、`<realpass123>`、`loadSecret()` 判违规，白名单占位词判 safe。改后对已跟踪 docs 全量实跑并逐条处理新增命中
- 选项：
    - A 删除两条形状豁免，仅保留显式白名单 + 显式 allow marker
    - B 收窄两条形状豁免
    - C 保持现状，记录为已知盲区
- 推荐：B（初稿）
- 推荐理由：初稿按误报成本推荐 B；按核心架构铁律改取 A——B 仍是可被借用的启发式
- 用户决策：A（按核心架构铁律决策：架构至上、拒绝妥协、零兼容性负担）

### A18. 含任一非 ASCII 字符的值整类放行（原 R1）

- 来源：review_intensive（问题 13）
- 位置：scripts/check_doc_sensitive.py:267-268
- 优先级：MEDIUM
- 详细判断理由：已核实属保留豁免。初稿以误报成本不采纳；按核心架构铁律复判：豁免粒度错在「含任一非 ASCII 字符」，真实意图是放行纯中文说明值。根因修正是把豁免改成精确形状，而非保留宽豁免。
- 修复说明：删除 `not v.isascii()` 豁免，改为「值中不含任何 ASCII 字母数字」才视为散文说明放行（如 `见上文`、`（略）`）；ASCII 字母数字与非 ASCII 混合（`pässwort1`、`密码123`）一律判违规。补单测覆盖上述四例。改后对已跟踪 docs 全量实跑并逐条处理新增命中

### A19. 行内 allow marker 无需说明理由（原 R3）

- 来源：review_intensive（问题 17）
- 位置：scripts/check_doc_sensitive.py:182（ALLOW_MARKER_RE）、:325、:466-472；.sensitive_ignore
- 优先级：LOW
- 详细判断理由：初稿以「设计内逃生口、Git diff 可见」不采纳；按核心架构铁律复判：A4/A17/A18 收紧后 allow marker 成为合法例外的唯一通道，零成本无理由豁免与 default-deny 设计不一致。已跟踪 docs 中现仅 1 处使用，破坏性变更成本可忽略。.sensitive_ignore 现 3 条均为归档或 `_meta` 过程目录整树，合理，不动。
- 修复说明：ALLOW_MARKER_RE 改为必须携带非空理由（如 `<!-- sensitive-allow: <理由> -->`、`# noqa: sensitive <理由>`），无理由 marker 不生效并单独报违规；更新现存 1 处 marker 补理由。补单测：无理由 marker 不豁免、带理由 marker 豁免

## 不采纳项

### R2. 凭据门禁扩到源码/配置，以及 Markdown 表格行形态

- 来源：review_intensive（问题 16 第一、四点）
- 位置：scripts/check_doc_sensitive.py:477-490（collect_target_files）
- 优先级：LOW
- 详细判断理由：与改动成本无关，属范围与判定可行性问题。A22 的职责是敏感文档门禁，源码/配置凭据由「禁硬编码」规范与代码审查覆盖，扩范围是新需求而非本批缺陷，应单独立 task 设计（混入本门禁会把两类职责耦合进一个工具）；表格行 `| password | str | required |` 是字段说明表的标准写法，键值列语义不可从形状判定，纳入即系统性误判

### R4. 占位符白名单含 default / none / password 等字面量

- 来源：review_intensive（问题 18）
- 位置：scripts/check_doc_sensitive.py:108-137
- 优先级：LOW
- 详细判断理由：与改动成本无关，属语义判定。白名单是显式列举（default-deny 的正确形态），这些字面量在文档中表达字段语义（`password: required`、`token: none`）；本项目全局规范禁止默认口令，不存在「出厂默认口令写进文档」的场景
