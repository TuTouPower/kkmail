# 合并 Diff 目的符合性复审（修复批）

- 范围：合并 diff `c5cb8905..f0e6c72b`（22 个提交，整体审，不逐 commit 拆）
- 对象：针对 2026-11-10 凌晨审阅（`2d175202..c5cb8905`）所列折扣项的修复批：迁移分类单一入口、baseline 工具链 PG-only 化、凭据检测 default-deny 重写、A18 测试迁真 PG、handoff 失实更正
- 方法：通读 handoff 本批段落与各提交 diff、HEAD 代码实读、AST 逐函数比对新旧 baseline.py、纯函数探针实测 plan_migration 与凭据检测器判定、grep 全仓对照、可离线子集实跑
- 环境限定：本机无 Docker、无 PG，PG 门控用例本机只能 skip；全量门禁数字未在本机复跑，下文逐项标注

## 逐项闭环裁决

### A 两入口分歧（无标记但表齐全的库，启动拒绝、离线 stamp）——分类层已闭环，执行层有残留

分类逻辑真单源：唯一分类函数是 `src/mail_core/db/baseline.py:797 plan_migration(state, context)`，输出六类 MigrationAction。旧启动侧自有的三个分类 helper 已全部删除，AST 与 grep 均确认 HEAD 无残留。启动入口（`src/mail_core/__main__.py:58-93`）与离线入口（`scripts/migrate_to_unified_baseline.py` 63 行薄包装 → `baseline.run_migration`，baseline.py:903-918）都调同一 plan_migration，对 NO_VERSION_WITH_BUSINESS_TABLES / UNKNOWN_REVISION / MULTIPLE_VERSIONS 一律拒绝。探针实测 10 个状态 × 2 套 context 全部一致：空库→EMPTY；无标记+32 表齐全→NO_VERSION（两入口都拒绝，判定条件是任一必需表出现即拦，比旧离线更严）；旧链尾 0030/0031→LEGACY；更早旧库 0029→LEGACY（随后在窄校验阶段因缺表被拒，口径与 upgrade.md 一致）；未知 revision→UNKNOWN；多行 version→MULTIPLE。全仓无第二处分类实现：health.py 只读版本号做展示，部署 preflight gate 走同一 run_migrations。

### B stamp 放行过宽（仅验表名+关键列名，漂移库静默 stamp）——未闭环

AST 逐函数比对 c5cb8905 与 f0e6c72b 的 baseline.py：`verify_database_schema`、`verify_narrow_legacy_schema`、`stamp_unified_baseline`、`_stamp_targets` 四个函数一字未改。957acb90 及本批对校验面的改动只有删 SQLite 分支（非 PG 一律 ValueError、删 SQLite 的 Python 侧 JSON 回退）。现行严格度：AT_BASELINE 走离线校验时仍只有「32 表名 + 15 表关键列名存在性」（baseline.py:294-325）；LEGACY 窄校验确实更深（sync_checkpoints 的 cursor 列 JSON 类型/复合主键/两条外键、folders 主键与唯一约束、accounts 主键、已存在的 folder_patrol_status 全部列定义、cursor 数据对象性），但只覆盖转换触碰的 4 张表，其余 28 张仍只过表名+列名层。文档口径已同步如实披露：testing.md 与 upgrade.md 均明写实际校验范围，「自述与实现不符」在 B 这条上不存在了——现在是文档明说只验这么多。缓解事实：NO_VERSION 库现一律拒绝，「无标记漂移库被 stamp」这条最危险的子路径已不存在；LEGACY 的 stamp 在 apply_narrow_legacy_conversion 的单一写事务内从头复验，无 TOCTOU。现行暴露面是「带合法旧/基线 revision 的漂移库被当作合格基线接受」。是否接受这个严格度属于裁决问题，但按 B 的原始标准不能记为已修复。

### C A22 凭据检测放行面过大——部分闭环

旧 CODE_PROSE_CHARS 字符集豁免与纯字母豁免已删除（HEAD 无残留）。新 is_safe_credential（scripts/check_doc_sensitive.py:256-283）结构为 default-deny：只有空值、非 ASCII、占位符白名单、全标点值、模板/环境引用、代码表达式、与 key 同名自赋值这些显式形状才 safe。内存探针实测：上轮点名形态全部检出——带点号的 my.passw0rd 形态、supersecret、correcthorsebatterystaple、纯数字、带逗号形态、引号内带空格的短语形态、冒号形态、列表项反引号形态均判 VIOLATION，与 handoff 声称一致（带括号形态要区分写法，见问题 11）。实跑：tests/scripts/test_check_doc_sensitive.py 本机 30 passed / 1 failed，唯一 failed 的 7 条违规全部位于未跟踪的本地残留目录（review_20261021_011607 与 review_20261021_064335），非本批跟踪内容；以 git ls-files 对已跟踪 docs 全量实跑检测器，701 个文件 0 违规，与 handoff「581 文件 0 违规」方向一致（文件数差异是统计范围不同）。

### D A18 未清零且过度声称——实质已闭环

基线对照：基线 38 个测试文件出现 sqlite 字样、其中 32 个真正打开 SQLite 数据库。HEAD 只剩 15 个文件出现字样，逐个分类：legacy 输入契约 6 个（test_legacy_migration.py 用 sqlite3 构造/回读上游遗留库文件、导入目标走真 PG；三个 tests/scripts/test_migrate_* 的被测生产函数签名本身就是 sqlite3.Connection；另两个只把 .sqlite 当路径参数，从不打开连接）；字符串/注释/退役说明 5 个（拒绝用例字符串常量、文件头退役文字、注释，实际用例走 PG schema 隔离）；方言名 stub 4 个（SimpleNamespace(dialect name 为 sqlite)，用假 Session 断言非 PG 方言不得发 advisory lock，不打开任何 SQLite 数据库）。「测试基础设施仍用 SQLite 跑生产行为」为零。publication_patrol 竞态测试：基线手写四组 DDL 与 sqlite 引擎已全部消失，改走真 PG schema、竞态手法（stale 首读）保留、断言未翻转；全仓含 CREATE TABLE 的测试文件 31→9，剩余全是 PG 历史-schema fixture 或 legacy 输入表，「手写 SQLite DDL 复刻生产表」清零。A13 双进程：test_a13_session_revocation_multiprocess.py（378 行）真 spawn 两个 OS 子进程打真 PG、子进程走生产 auth 路径、只共享数据库环境变量，覆盖 NOTIFY 被 patch 成 no-op 仍拒绝旧 cookie、重复/乱序 NOTIFY、DB 故障 fail-closed 且不回退进程内缓存 epoch、B 进程断言自己从未启动 listener；FakeSession 在 auth 范围整体退役且留退役理由，死代码三 helper 已删（本机无 PG 未实跑，代码证据充分）。3386977f FK seed 修复：只动 3 个测试文件、零生产代码；生产 FK（job_id → worker_jobs.id, ondelete SET NULL）与统一基线定义一致且有意，旧 seed 在 SQLite 上因不强制 FK 一直假绿、迁 PG 后才暴露顺序问题，修复是让测试数据满足生产约束，未给生产约束加 deferrable、未删 FK、未放宽任何生产校验——是修测试数据，未掩盖生产问题。任务未点名的 b64733a6 / 06bbd217 / 957acb90 把 auth、startup、deploy-gate、离线工具与 baseline.py 生产侧一并 PG-only 化，超出原声称范围；3062626b 给 test_microsoft_oauth.py 加的 seed 走生产模型、未放宽 A13 校验，定性为测试侧修复属实。生产侧旁证：src/ 只剩两处提及 SQLite 历史行为的注释；baseline.py 中被上轮点名的四个函数本体仍在，但已改为非 PG 一律 raise ValueError（见问题 22）。

### E 记录失实（handoff 过度声称、时间戳与 head_commit 自相矛盾）——部分闭环

已核实属实的部分：git log 确认 707c49b2 的提交时间是 2026-11-09 05:52:16 +0800，与旧 handoff 节标注确实矛盾，三份 docs 提交都明写勘误且未回改历史；37f60d03 的自我更正与其所述代码状态基本对应；c3c824f6 / f0e6c72b 声称的 A18 清零与代码侧现状对应；testing.md 的过时声明已同步修正。「2142」总数获得独立旁证：本机 collect-only 得 2144 个用例，恰等于 2142 passed + 2 skipped，收集总数口径对得上，不是编造的数字。残留问题见问题 19–24。

## 全部问题逐项（24 项，不分级、不合并省略）

### 迁移线

1. **离线 RevisionContext 写死，与启动动态来源不一致（潜伏分歧，已实测复现）**：启动的 known_revisions 来自 ScriptDirectory.walk_revisions() 动态读迁移树（__main__.py:58-62），离线是写死常量 frozenset({UNIFIED_BASELINE_REVISION})（baseline.py:770-781）。当前 versions 目录只有一个文件、两者恰好相等；探针模拟新增 head revision 20261115_0002 后，同一数据库状态启动判 AT_BASELINE、离线判 UNKNOWN_REVISION，分歧复现。单源的是分类函数、不是分类输入；下次新增迁移 revision 时若忘了同步改 offline_revision_context，旧问题 A 原样复发。能抓到它的 two-entries-agree 测试是 PG 门控测试，本机跑不了。
2. **AT_BASELINE 两入口模式校验严格度仍不一致（方向反转）**：离线 run_migration 对 AT_BASELINE 调 verify_database_schema（baseline.py:930 附近），缺表缺列直接报错；启动 run_migrations 对 AT_BASELINE / EMPTY 在 check_only 时直接 return、正常启动时直接 command.upgrade，从不调用 verify_database_schema——全仓 grep 确认该函数在 baseline.py 之外零调用方。后果：已在基线 revision 但被人手工删掉必需列的漂移库，`--check-migrations`（部署 preflight gate 的判定）会放行、应用照常启动，离线工具却报错。分类标签一致，但「这个库能不能过门禁」的实际结论仍能相反；旧问题 A 的原始形态（离线比启动宽松）方向反了过来。
3. **LEGACY 的 check_only 语义两入口不对称**：启动 --check-migrations 对 LEGACY 跑 verify_narrow_legacy_schema 后 return（__main__.py:103），离线 --dry-run 同样跑窄校验（一致）；但对 AT_BASELINE 如第 2 项所述启动 check 不跑任何模式校验。即同一个门禁对 legacy 库验得比对基线库还严，校验覆盖随分类变化，不是统一口径。
4. **启动入口手抄了一份状态读取逻辑**：离线走 baseline.read_database_state（baseline.py:784-794）；启动在 __main__.py:69-85 内联重写同一套「inspect 表名 + 查 version_num」逻辑再手工拼 DatabaseState。当前两份逐行等价，不是活分歧；但「单一入口」在状态读取层不成立，将来 read_database_state 扩展（如把 alembic_version 表本身的列形纳入状态）时启动侧不会跟随，分歧会从这里重新长出来。
5. **UNKNOWN_REVISION 文案把「比基线更新的 revision」也称作 legacy，旧启动的区分性提示丢失**：旧 _legacy_revision_error 对 dated revision 大于当前 head 单独提示「数据库由更新版本写入、应升级 kkmail，不要拿旧备份覆盖」。新 plan_migration 对这类状态（如探针中的 20261201_0001）统一判 UNKNOWN_REVISION，文案是 "unrecognized legacy revision ... restore a known-good backup"（baseline.py:876-884）。动作仍是 fail-closed 拒绝，安全方向没问题；但对「库比程序新」这一真实场景，文案会引导运维去恢复旧备份，与旧提示明确警告的恰好相反。属提示层面的回退。
6. **LEGACY 分类的日期模式启发仍在**：plan_migration 的 legacy 判定含 is_legacy_revision 的日期模式启发（baseline.py:88-100、858：形如 YYYYMMDD_NNNN 且小于基线即认 legacy）。从未存在过的伪造 revision（如 20200101_0001）会被分类为 LEGACY 而非 UNKNOWN，随后靠窄校验缺表才被拒绝。最终结论仍是拒绝，但分类标签与事实不符，且窄校验的报错文案（automatic upgrade not supported）会掩盖「这根本不是任何已知 revision」的真相。
7. **REQUIRED_COLUMNS 只覆盖 32 张表中的 15 张**：verify_database_schema 的列名校验只及 15 张表（baseline.py:137-190），其余 17 张表连列名都不验、只验表名存在。这是旧问题 B 的具体构成之一，本批未动。
8. **窄校验的深校验范围由「转换触碰什么」决定、覆盖不均匀**：深校验只及 sync_checkpoints / folders / accounts / folder_patrol_status 四张表，其余 28 张在窄路径仍只过表名+列名层；folder_patrol_status 不存在时被 exempt（baseline.py:392 调用处），其列定义深校验只在表已存在时执行——不存在时由转换按固定 DDL 新建，这是合理的；但意味着「0031 库里已有一张列形错误的 folder_patrol_status」能被抓、「同库其他表的列形错误」抓不到。文档已披露此点。
9. **_column_affinity 是字符串包含式的类型归类**：窄校验里 patrol 列的类型判定用 baseline.py:328 的 affinity（含 INT 子串即 integer 等）而非 PG catalog 精确类型，例如 last_probe_failures 若被建成 BIGINT，affinity 同为 integer、判定通过，而统一基线 DDL 是 INTEGER。此为既有设计（旧版相同，AST 未变），列在这里是因为它决定了「深校验」实际有多深。

### 凭据检测线（均为探针实测或代码直读）

10. **以 $、(、{、< 开头的值整类放行**：CODE_EXPRESSION_RE（check_doc_sensitive.py:162-165）第一分支 `\A[{($<]` 命中即 safe；探针实测美元符开头的 $uperSecret99 形态与括号开头的 (hiddenpass1) 形态均判 SAFE。以 $ 开头的口令在真实凭据里并不罕见，这类值现在不是「含某字符被豁免」，而是「首字符即被豁免」；此项是旧 startswith 豁免的保留并扩大到了左括号。与 handoff「根除字符集豁免反模式」的表述不完全相符。
11. **函数调用形态放行可被借用**：CODE_EXPRESSION_RE 第二分支 `\A[A-Za-z_][A-Za-z0-9_.]*\([^)]*\)?\Z` 只看形状不看语义；探针实测 Str0ng(Pass) 形态判 SAFE（被当成函数调用），loadSecret() 这类真代码形态判 SAFE 是设计意图内。问题是真实口令只要写成「词(词)」形态即整体豁免。handoff 声称「带括号形态均检出」，此写法是反例——handoff 的用例大概是括号在中间或带尾随标点的形态，两种写法结论相反，声称的覆盖不完整。
12. **尖括号包裹整类放行可被借用**：SAFE_REFERENCE_RE 第三分支 `\A<[^<>]+>\Z` 不区分尖括号里是不是占位词；探针实测尖括号包裹的 realpass123 形态判 SAFE。占位符白名单里尖括号占位词本已单列，整类尖括号放行是额外的、更宽的一层。
13. **含任一非 ASCII 字符的值整类放行**：is_safe_credential 第 265-266 行对非 ASCII 直接返回 True；探针实测含变音字母的口令形态判 SAFE。设计意图是放行中文文档散文，但判定粒度是值级不是行级：真实口令只要含一个非 ASCII 字符（变音字母、全角符号、一个汉字）即整体豁免。旧版同样有此豁免、属保留未改，但与「default-deny」的声称并列时应点名。
14. **SAFE_REFERENCE_RE 后半分支是子串 search 而非整值匹配**：第 147-160 行中 os.environ、os.getenv(、getenv(、process.env、store.get_secret( 五个分支无起始锚点，且 is_safe_credential 用 .search() 调用；探针实测引号值里只要出现 os.environ 字样（如 abc os.environ leak 的构造值）整值即豁免，与注释自述的「never a contains-character exemption」直接矛盾（注释只对前四个整值分支成立）。
15. **isolated-assignment gate 是全有全无的前置门，非孤立行连判定都不进**：scan_file（第 452-456 行）先过 _is_isolated_assignment（第 236-253 行，前缀只允许列表标记/HTML 注释/export 等声明词、后缀只允许单个标点加行尾注释），不过即整行跳过。探针实测漏检形态：同一行有第二个赋值时整行 SKIPPED（值捕获成带分号的残段、后缀不干净）；未加引号的多词口令只捕获首词、剩余文本使后缀不干净，同样 SKIPPED。设计理由是压制散文误报（docstring 明说），代价是召回：凭据只要和别的内容同行出现就整体出界。对防泄漏门禁这是用召回换精度，应作为已知取舍记录，而不是「default-deny」一句带过。
16. **检测范围的结构边界（本批未变，但决定 gate 的实际覆盖面）**：其一，collect_target_files（第 477-490 行）对目录只递归 Markdown，门禁实际调用也只有 docs 一处，源码、配置、脚本里的赋值型凭据不在这个门禁范围内（A22 定位「敏感文档门禁」的既定范围，不是本批回退，但 default-deny 只在此范围内成立）；其二，ASSIGN_RE 的 key 关键词表（第 90-99 行）不含 apikey、private_key，探针实测这两类键名无任何 ASSIGN 命中；其三，JSON 形态（key 后紧跟引号）因 ASSIGN_RE 要求 key 后直接是冒号/等号，同样无命中；其四，Markdown 表格行形态无命中。这三类是上一轮就存在的形状盲区，本批的 gate 改造没有触及，引用「凭据检测已 default-deny」时不能默认覆盖这些形态。
17. **行内 allow marker 与 .sensitive_ignore 是两条可借用的豁免通道（既有机制，gate 未收紧）**：行内 sensitive-allow 注释或 noqa 标记即豁免该行 marker 之前最近的一条违规（scan_file 第 466-471 行），对 email/path/credential 所有类别通用、无需说明理由；.sensitive_ignore 现有 3 条模式，其中 reviews 的 _meta 子树与两个 archive 目录整树豁免。把真实凭据写进被忽略目录、或在泄漏行尾加 marker，都能让门禁变绿，豁免不产生任何审计输出，借用成本为零。这是设计内的逃生口，但应列明。
18. **占位符白名单混着可作真实口令的字面量**：SAFE_CREDENTIAL_PLACEHOLDERS（第 108-137 行）含 default、none、null、true、false、required、example、password、dummy12345、testpassword 等，均判 safe；探针实测 passwd 取 default 字面量、password 取 none 字面量均判 SAFE。白名单语义是「这些字面量视为非凭据」，对文档门禁大体合理，但 default 作真实出厂默认口令写进文档时正是泄漏场景本身，属已知盲区。

### 记录更正线

19. **handoff「已逐一核实」清单不完整**：现行 handoff 声称「全仓剩余 SQLite 使用点已逐一核实并显式标注」，列举只覆盖 7 个文件；实际 HEAD 还有 8 个含 sqlite 字样的文件未被列入：方言名 stub 4 个（test_blob_crypto_gc.py、test_r4adopt_p23_gc.py、test_archive_adoption_p15.py、test_archive_claim_ownership.py）、test_migrate_from_legacy_db_cli.py、test_migrate_blob_key_validation.py、test_session_engine_thread_safety.py、test_startup_migrations.py（后者在别处被提及为已 PG 化，但未进入这份「剩余使用点」清单）。这些残留全部无害（见 D 的分类），但「逐一核实」的清单与全仓 grep 结果对不齐，属列举不完整。
20. **「25 个」计数无法复现**：37f60d03 与 c3c824f6 两处都写「25 个手写 SQLite DDL 复刻生产表的业务测试」。按仓库可复现口径：1fff64c6 与 a029d639 两提交实际迁移文件并集为 24 个；这 24 个中在基线真正含手写 CREATE TABLE 的是 22 个（test_rotate_credential_locking.py 用 Base.metadata.create_all 于 SQLite 引擎、test_session_engine_thread_safety.py 只是 SQLite smoke engine，均无手写 DDL）。24 与 22 都不是 25，且 handoff 未附清单，该数字无从对账——与上轮被纠的过度声称同型，量级小但性质同。
21. **head_commit 口径在更正后仍前后不一**：37f60d03 节时间戳 2026-11-10T04:52:52、head_commit 写 40685283 并注明文档提交另计，自洽；c3c824f6 节时间戳 10:24:22、head_commit 写 048446c4（08:40:52 的 merge），但该节正文新增的 microsoft_oauth seed 修复描述的是 3062626b 的改动，而 3062626b 位于 048446c4 之后、是 c3c824f6 的直接父提交（父链 c3c824f6 ← 3062626b ← 048446c4，两者提交时间同为 10:26:45）——该节所述代码状态实际包含 3062626b，head_commit 却少报一个提交，与被勘误的旧问题同型、只是方向相反；f0e6c72b 节又把 head_commit 改写为上一个 docs 提交 c3c824f6，与 37f 节立下的「本节所述代码状态」口径不一致。三节之间 head_commit 的语义不统一。
22. **baseline.py 的函数存废表述不精确**：现行 handoff 写「baseline.py 已删除全部 SQLite 方言分支（configure_read_only、ensure_folder_patrol_status_table、_migrate_patrol_status_data_generic、_check_cursor_data、advisory lock 分支）」。实际 _migrate_patrol_status_data_generic 确已删除；但 configure_read_only（:257）、ensure_folder_patrol_status_table（:626）、_check_cursor_data（:520）三个函数仍存在，只是改为非 PG 抛 ValueError。把「函数改为 PG-only 拒绝」与「已删除函数」并列表述，容易让读者以为这些函数已不存在。行为层面无虚假，文字层面不精确。
23. **PG 侧手写历史 DDL 的存续未主动澄清**：现行 handoff 字面无误，但 test_startup_migrations.py 仍含 40 处手写 CREATE TABLE（文件头自述是 0030 历史形态的冻结字面转写，PG 语法、跑在 PG schema 上）、test_migration_validation.py 仍含 34 处（handoff 只以「手写 DDL 是 PG 语法的历史 schema 校验 fixture」一句带过）。这两批定性合理，但读者按「手写 DDL 已彻底删除」的旧印象理解现行文本会与仓库实际不符，现行文本没有主动澄清这一区分。
24. **全量门禁数字在本机不可复现、且无仓库内留存证据**：handoff 的核心数字「2142 passed, 2 skipped, 0 failed」及分批数字（迁移/policy 99、竞态/outbox 56、sync/patrol 56、A13/双进程 105、合并态 137、microsoft_oauth 63+1 skip、敏感扫描 581 文件 0 违规、检测器 31、模板契约 257+1 skip）——仓库内没有附带任何一次运行的日志/报告文件可供对账；docs/blueprint/testing.md 的门禁结果表最新一行仍停在 2026-10-27，未登记这批 2026-11-10 结果，f0e6c72b 只改了 testing.md 的一段文字说明、未补结果表。本机因无 Docker/PG 无法复跑（门禁脚本无 PG 时按其策略直接失败退出、不降级）。可旁证的只有收集总数 2144 与总数吻合；passed/failed/skip 拆分、2 个 skip 的归因、以及前端/桌面/E2E「本轮实测全通过」的声称（f0e6c72b 将 c3c824f6 的「沿用上一节记录」升级为「本轮实测」），在本机与仓库证据范围内均无法独立验证，只能记为「与仓库结构不矛盾、无反证、亦无留存证据」。

## 总评

三项旧问题里，A 的核心修复是真的：分类函数单源、旧双套判断删净、点名状态两入口一致拒绝（探针逐项复实）；尾巴是 context 构造的潜伏分歧（问题 1，新增 revision 时复发）、AT_BASELINE 校验严格度两入口仍不对称（问题 2、3）、状态读取留了一份手抄副本（问题 4）。B 按原始标准未闭环：校验函数 AST 层面一字未改，PG-only 只删了 SQLite 放行面；变化在文档，从「自述不符」变成「如实披露」。C 是实打实的进步与实打实的新洞并存：旧字符集豁免删净、上轮点名形态全数检出（实测），但五类整值放行（问题 10–14）仍可被真实口令借用、isolated gate 又把同行多赋值与未引号多词口令整体排除在检测外——「default-deny」准确的说法是「在孤立赋值行、ASCII、非特殊形状的值上 default-deny」。D 实质闭环且超出原声称范围。E 的勘误方向与主要事实属实且未回改历史，但更正后的记录自身仍留下问题 19–24 六处毛边，都落在上轮被纠的同一类病灶（数字与清单未经对账即落笔）上。PG 门控关键证据本机全部 skip，本报告涉及 PG 行为的裁决均为代码实读与探针（纯函数层）证据，不含真实 PG 运行证据。
