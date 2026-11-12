# Task review t078（reviewer_focus: 代码）

- task：`t078_quality_gate_root_cause_refactor`
- spec：`docs/tasks/t078_quality_gate_root_cause_refactor/task.md`
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`
- round：1
- reviewed_at：2026-11-12T16:37:22+08:00

reviewed_scope: 6bcaa2fd7152a3b9

## Findings

### t078_code_f001 - `verify_lock_offline` 版本约束解析用脆弱整数元组比较，实测误判合法 lock、放行违反约束的 lock

- 严重度：important
- 锚点：AC-003（「版本满足其约束」）；行为缺陷：合法 lock 被判不一致、违反约束的 lock 被放行
- 位置：`scripts/check_dep_locks.py:125-133`（约束解析见 `:28-29`）
- 问题：独立动态调用 `verify_lock_offline`（构造临时 `.txt`/`.lock`）得到三类可复现坏结果。① `foo>=1.2.0` + lock `foo==1.2` → 返回 `['r.lock: foo==1.2 does not satisfy >=1.2.0']`；`have=(1,2) < floor=(1,2,0)` 是长度不等元组的字典序比较，而 `1.2` 按 PEP 440 等于 `1.2.0`、本应满足下界——合法 lock 被误判不一致，`scripts/build-sidecar.sh:20` 会据此拒绝构建。② `foo>=2.0.0` + lock `foo==2.0.0rc1` → 返回 `[]` 放行；`re.findall(r"\d+","2.0.0rc1")[:3]=(2,0,0)` 把预发布后缀数字截断后误判满足，但 PEP 440 下 `2.0.0rc1 < 2.0.0`，属「放行违反约束的 lock」，与本 task「不弱化断言」红线相悖。③ `_GE_FLOOR_RE.match(spec)` 只识别以 `>=` 开头的约束，其余 `==`/`~=`/`<`/`<=`/复合约束一律 `continue` 跳过；实测 `foo==9.9.9` + lock `foo==1.0.0` 返回 `[]`，AC-003「版本满足其约束」未覆盖非 `>=` 约束。现状说明：当前 `requirements-mail-core.txt` 9 行全为 `>=` 三段下界、lock 全为三段标准版本，故 `--check` 实测 rc=0 通过，以上为潜在缺陷、未在当前交付物触发；但门禁脚本用 `re.findall(r"\d+", ...)[:len(floor)]` 手搓版本比较属权宜实现，与项目「架构至上、拒绝妥协」相悖，且是用户点名核查的「RC/预发布稳健性」所在。
- 建议：按 PEP 440 规范化版本与约束——优先用 `packaging.version.Version` + `packaging.specifiers.SpecifierSet.contains`（若 build 运行环境可用），否则至少解析 release 段、忽略 pre/post/dev 后缀、补齐段数后再比较，删除位置敏感的 `re.findall(r"\d+")` 比较；对无法解析的约束显式报错而非静默跳过。

### t078_code_f002 - `strip_header_comments` 重构后成为死函数

- 严重度：minor
- 锚点：行为缺陷（死代码，无对应 AC）
- 位置：`scripts/check_dep_locks.py:55`
- 问题：`--check` 路径删除了基于 `strip_header_comments` 的逐字节内容比较后，全仓 grep 仅余定义处一处命中，无任何调用方；生成模式只调 `canonicalize_header`（`:60`）。属本 task 重构直接产生、未随改动清理的死代码。
- 建议：删除该函数。

### t078_code_f003 - `_value_spans` 对无空格 `key=value` 行重复返回 RHS 与整行裸值，同一泄漏被重复计数

- 严重度：minor
- 锚点：行为缺陷：同一行同一值产生重复违规；关联 AC-002 / AC-004 实现
- 位置：`scripts/check_doc_sensitive.py:312-314`
- 问题：独立动态调用 `_value_spans("PWD_NOTE=口令长16位")` 返回 `['口令长16位', 'PWD_NOTE=口令长16位']`——ASSIGN_RE 分支已把 RHS 加入，bare 分支（整行无空格、不以 `|` `#` 反引号开头）又把整行作为裸值加入。`scan_file` 随后对每个 span 跑 `PWD_LEN_RE` / `EMAIL_RE` / 路径正则，同一值在同一行被报 2 条违规（无空格写法 `KEY=ops@corp.example` 同样重复）。不改变 `--check` 的 rc，但违规计数虚高、stderr 出现重复行，且使 `ALLOW_MARKER` 的「nearest match 仅豁免一条」语义在重复违规下更脆弱。
- 建议：bare 分支排除「整行本身已是孤立赋值」的情形（ASSIGN_RE 分支已产出 span 时不再追加整行），或对 `value_spans` 返回值去重。

## 结论

- 前轮 finding 复核：不适用（Round 1，无前轮 finding）。
- 本轮新发现：3 条（1 important / 2 minor）。
- 未进表的提示：
    - 残留双套归档判定：`scripts/check_doc_sensitive.py:427/435/449/651-656/685` 仍保留旧 `--ignore-archived-errata` 机制与 `is_archived = "docs/archive" in rel_path`（仅认单一子串），与新 `ARCHIVE_DIR_PREFIXES`（6 前缀 + handoff，`:591-607`）形成同文件内两套不一致归档判定；目录扫描下归档已被 `collect_target_files` 整体排除，该分支仅「显式单文件归档 target」可达，属重构后未清理的残留/一致性观察，不改变门禁结果，按 prompt 不进表。
    - 文件过大（按降级规则仅列路径与行数，不进表）：`scripts/check_doc_sensitive.py` 702 行（手写脚本阈值 400/800，本 task 净增约 65 行）、`tests/scripts/test_check_doc_sensitive.py` 817 行（测试源码阈值 600/1200，本 task 净增约 12 行），均命中 minor 未达 important；`scripts/check_dep_locks.py` 184 行、`tests/scripts/test_check_dep_locks.py` 101 行未超阈值。
    - 圈复杂度：`scan_file`（`scripts/check_doc_sensitive.py:425`）本就多分支，本 task 把 email/path/pwd 检测改为嵌套 `for value in value_spans`，手算 CC ≥10，按规则不进表、仅提示可简化。
    - 安全/语义边界（spec 已批准，非 finding）：散文、表格、代码引用中的邮箱按新模型不报（「讨论值不算泄漏」），`docs/blueprint/testing.md` 与 spec 明示该边界；`PRIVATE_KEY_RE`/`TOKEN_RE` 仍对整行无条件拦截（`:506`/`:516`），`ASSIGN_RE` 凭据 default-deny 门控（`:540-559`）逐行未削弱；归档目录整体不收集，故其中真 token 也不扫，属 spec 授权的职责分流。
    - 剩余风险：`docs/handoff.md` 是持续维护的当前交接文档，却被 `ARCHIVE_FILES`（`:599`）与 `.sensitive_ignore` 排除，目录扫描不覆盖；若其中出现真凭据（含高危签名）不会被发现。此为 AC-001 明确授权的排除项，非 finding，仅作风险提示。
    - 从根因修复核：`_value_spans` 语义边界经动态验证合理（散文/表格/代码引用返回空、赋值 RHS 与裸值行返回值）；`verify_lock_offline`（`:72-135`）纯文件读取 + 正则、无 `subprocess`/网络调用，`--check` 分支（`:166-180`）不调 `run_compile`，确为离线；对缺 hash / 缺直接依赖 / 低于下界均能拒绝（动态验证 A/E/F），拦截能力未被削弱；归档分流不漏发布面（`docs/guides`/`docs/blueprint`/`docs/specs` 不排除）。
    - CLI 兼容复核：`--check` flag、`OK: ... is synchronized ...` 输出（`scripts/check_dep_locks.py:179`）、`scripts/build-sidecar.sh:20` 与 `tests/scripts/test_check_dep_locks.py:55` 字面量均保持；`test_check_dep_locks_script_passes` 断言 `"synchronized" in proc.stdout` 通过。
    - 不偏航复核：diff 仅触及 `.sensitive_ignore`、`docs/blueprint/testing.md`、`docs/pending/p077_quality_gate_false_positives_and_lock_drift.md`、`docs/specs/testing_quality.md`、本 task 工作区 `progress.md`/`task.md`、`scripts/check_dep_locks.py`、`scripts/check_doc_sensitive.py`、两个 `tests/scripts` 测试；未改产品代码（`src/mail_core/`、`src/frontend/`、`src/desktop/`）、`requirements-mail-core.lock`、`requirements-mail-core.txt`；`git diff --check` 无空白错误；`git status --short` 无未跟踪交付文件。
    - 独立复跑：`check_doc_sensitive.py docs --check` 报 0 违规/32 文件 rc=0；`check_dep_locks.py --check` 输出 `OK: ... is synchronized ...` rc=0；`tests/scripts` 定点单测 46 passed。`## test_cmd` 的模板契约 463 / 前端 586+ 全链 / 桌面单测三项采用门禁证据，未由本 reviewer 重跑（用户指示不跑 PG 门禁、前端全链成本高）。
    - 指纹：`reviewed_scope: 6bcaa2fd7152a3b9` 与独立重算的当前 worktree 指纹一致；`review_code.md` 在 `REVIEW_PROCESS_FILES` 排除表内，写报告不扰动该值。
- 总体判断：AC-001~AC-006 打勾均成立（全 TICK-VALID，从根因重构且未弱化高危签名/凭据门控），但 `verify_lock_offline` 版本约束解析存在 1 条未解决 important（实测误判合法 lock 不一致、放行违反约束的 RC/非 `>=` 约束 lock），按判定式 verdict=FAIL。
- 系统性 follow-up：建议「用 PEP 440 (`packaging`) 规范化 lock 版本约束校验」，slug `dep_lock_pep440_version_check`（并入本 task 修复或另立 pending 由用户定）；另建议同 task 收尾清理 f002 死代码与「残留双套归档判定」提示项。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`collect_target_files`/`_is_archived_doc`（`scripts/check_doc_sensitive.py:591-623`）排除 6 前缀 + `docs/handoff.md`、发布面不排除；复跑 `python3 scripts/check_doc_sensitive.py docs --check` 报 0 违规/32 文件 rc=0，`test_repo_docs_gate_passes`（`tests/scripts/test_check_doc_sensitive.py:164`）与归档排除用例在 46 passed 内；`.sensitive_ignore` 已改真实路径。
- AC-002：TICK-VALID，re_verified。动态调用 `_value_spans` 实测散文/表格/代码引用返回空、赋值 RHS 与裸值行返回对应值；`PRIVATE_KEY_RE`/`TOKEN_RE` 仍整行检测（`scripts/check_doc_sensitive.py:506`/`:516`），`ASSIGN_RE` default-deny 分支（`:540-559`）逐行未改，PWD_LEN 改为仅值区间检测（`:527-538`）。
- AC-003：TICK-VALID，re_verified。`verify_lock_offline`（`scripts/check_dep_locks.py:72-135`）无 `subprocess`/网络，`--check` 分支（`:166-180`）不调 `run_compile`；复跑输出 `OK: ... is synchronized ...` rc=0；`git diff` 未含 `requirements-mail-core.lock`/`.txt`；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:55` 字面量有效；生成模式（`:147-164`）保留。注：版本解析稳健性另见 f001，不改变本 AC 对当前交付物成立的判定。
- AC-004：TICK-VALID，re_verified。46 passed 含新增 `test_publish_face_true_positives_still_detected` / `test_publish_face_prose_examples_are_not_values` / `test_archive_directories_excluded_from_docs_scan` / `test_check_is_offline_no_recompile` / `test_check_rejects_lock_missing_hash`；动态验证 `verify_lock_offline` 对缺 hash、缺直接依赖、低于下界均拒绝，真泄漏拦截分支（高危签名全文、凭据 default-deny）逐行确认。
- AC-005：TICK-VALID，re_verified。核对 `docs/blueprint/testing.md` diff：`:21` 删除过期「2142 passed / 既存失败」并新增「当前基线（t078 之后）」段、`:82` 敏感扫描规范重写为新模型 + 归档分流段、`:313` 历史证据表加注「历史时点快照 / 当前以 verification_notes 为准」且历史行按约定不改写；复跑敏感扫描 0 违规；`## test_cmd` 其余三项采用门禁证据（见未进表提示）。
- AC-006：TICK-VALID，re_verified。核对 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` front matter `status=closed` / `resolution=resolved` / `fix_ref=t078`、`docs/specs/testing_quality.md` `tasks: [t013, t014, t078]`；diff 未新增其它遗留项。

coverage = 6 / 6

verdict: FAIL

## Round 2 (2026-11-12T17:09:05+08:00)

- reviewer_focus：代码
- round：2
- reviewed_at：2026-11-12T17:09:05+08:00
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（11 个已跟踪修改文件；无未跟踪交付文件，两份 `review_*.md` 属 REVIEW_PROCESS_FILES 排除项）
- review_level：full
- 独立复跑：`KKMAIL_TEST_MODE=unit` 定点 `tests/scripts` 49 passed；`python3 scripts/check_doc_sensitive.py docs --check` 32 文件 0 违规 rc=0；`.venv/bin/python scripts/check_dep_locks.py --check` rc=0；PEP 440 / `verify_lock_offline` / `_value_spans` 动态探针。未跑 PG 门禁 / 前端全链 / 桌面单测（按用户指示与成本，采用门禁证据）。

reviewed_scope: 4e9c7b3e39a3b9ce

### 前轮 finding 复核（R1 处置）

说明：R1 本轴 `review_code.md` 实为 3 条 finding（f001/f002/f003）；用户消息称「4 条」与报告原文不符，test 轴另有 5 条不属本轴。连同 R1 结论段系统性项，共 4 项逐条复核；以 diff / 代码 / 独立复跑为准，不采信处置表自称「已修」。

**① t078_code_f001（important，版本比较手搓）— 已消除，从根因修复。**

- 根因修复：`verify_lock_offline`（`scripts/check_dep_locks.py:75-141`）改用 `from packaging.specifiers import SpecifierSet, InvalidSpecifier`（`:22-29`）+ `SpecifierSet(spec).contains(pins[name])`（`:132`），删除整数元组 `re.findall(r"\d+")` 比较；`requirements-dev.txt` 显式 `packaging>=23.0`；import 失败 `SystemExit(2)` fail-closed（`:24-29`）。
- PEP 440 边界独立复跑（`.venv/bin/python`，packaging 26.3）：`SpecifierSet(">=1.2.0").contains("1.2")`=True（合法 lock 不再误判不一致）、`SpecifierSet(">=2.0.0").contains("2.0.0rc1")`=False（预发布被拒）；动态调用 `verify_lock_offline`：`>=1.2.0`/lock `1.2`→`[]`、`>=2.0.0`/lock `2.0.0rc1`→`does not satisfy`。
- 非 `>=` 约束不再静默跳过：`==9.9.9` / `~=2.0` / `<=1.0` 各返回 `does not satisfy`；空约束 `foo`→`has no version constraint`、非法 `foo>=>>`→`invalid constraint ... InvalidSpecifier`，均显式报错。
- 生成模式保留：`main()` 非 `--check` 分支（`:153-170`）仍调 `run_compile` + `canonicalize_header`（`:164`），后者非死代码。
- CLI 兼容：`--check` flag、`OK: requirements-mail-core.lock is synchronized with requirements-mail-core.txt`（`:185`）保持，`.venv/bin/python ... --check` rc=0；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:55` 字面量 grep 仍在。
- packaging 解释器核实（用户特别关注）：见「结论」剩余风险①。canonical 门禁入口全部落在 `.venv/bin/python`（含 packaging）；裸 `python3`（无 venv）确为 rc=2，属 fail-closed 正确行为。
- 未引入 regression：真实 `verify_lock_offline(LOCK_FILE, TXT_FILE)` 返回 `[]`（`--check` rc=0）；`git diff` 未含 `requirements-mail-core.lock` / `.txt`。

**② t078_code_f002（minor，死函数）— 已消除。** `strip_header_comments` 定义与全部引用从 `scripts/check_dep_locks.py` 删除（全仓 grep 零命中）；生成模式改依赖 `canonicalize_header`（`:164` 仍调用），无新增死代码。

**③ t078_code_f003（minor，重复计数）— 已消除，且孤立值行未漏检。**

- `_value_spans`（`scripts/check_doc_sensitive.py:290-319`）改为「仅当 `values` 为空才回退整行裸值」（`:315-318`）。动态复跑：`PWD_NOTE=口令长16位`→`['口令长16位']`、`CONTACT=ops@corp.example`→`['ops@corp.example']`，与 R1 的 `['RHS','整行']` 不同，重复计数消除。
- 孤立值行未漏检（用户关注）：单段宿主绝对路径值、`alice@personal-mail.com` 单值经 `_value_spans` 均返回对应值，markdown 列表/引用前缀（`_MD_LEAD_RE`）剥离后仍返回；`scan_file` 对 `iso_path.md` / `iso_email.md` 各报 1 条 PATH/EMAIL；散文、表格、代码引用→`[]`。
- 注：`PWD_NOTE=口令长16位` 在 `scan_file` 仍产出 2 条 `[CREDENTIAL]`（`PWD_LEN_RE` 值区间 `:533` + `ASSIGN_RE` default-deny `:545` 各命中一次）；此为 t078 之前即存在的两套检测叠加（`ASSIGN_RE` 循环在 diff 中为未改上下文），非本轮 f003 修复引入、不改变 rc，按观察记录。

**④ R1 结论段系统性项（非 finding：PEP440 follow-up / 残留双套归档判定 / 文件过大 / 复杂度 / 不偏航）— 已处置或状态延续。**

- PEP 440 规范化 follow-up 已并入本 task（即 f001 修复），无悬空。
- 「残留双套归档判定」仍在（`scripts/check_doc_sensitive.py:431` `ignore_archived_errata`、`:439` `is_archived = "docs/archive" in rel_path`、`:453` errata 分支、`:656` CLI flag）：t078 之前既有、R1 已列未进表；R1 修复未触及这些行，非 regression；目录扫描下由 `ARCHIVE_DIR_PREFIXES`（`:595`）整体排除，仅显式单文件归档 target 可达，不改变门禁结果。
- 不偏航复核：diff 仅 11 文件，`git diff --name-only b2050e33 -- src/` 为空（未改产品代码）、`requirements-mail-core.lock` / `.txt` `git diff` 为空；`requirements-dev.txt` 仅加 dev 依赖；`git diff --check` rc=0；`git status --short` 无未跟踪交付文件。

### Findings

#### t078_code_f004 - `_REQ_RE` 逗号截断复合约束、静默忽略上界，违反约束的 lock 仍被放行（潜在）

- 严重度：minor
- 锚点：AC-003「验证…版本满足其约束」；行为缺陷：复合约束上界被丢弃 → 放行违反约束的 lock（潜在，当前交付物不触发）
- 位置：`scripts/check_dep_locks.py:37`（`_REQ_RE`），消费见 `:99`、`:132`
- 问题：`_REQ_RE` 约束组 `([><=!~]{1,2}\s*[^\s,;]+)?` 在逗号/分号处截断，只取首个 specifier。独立动态复跑：txt `foo>=1.2,<2.0` + lock `foo==2.5`（带合法 sha256）→ `verify_lock_offline` 返回 `[]`（rc=0 放行）；而 `SpecifierSet(">=1.2,<2.0").contains("2.5")`=False，声明约束本应拒绝。`SpecifierSet` 原生支持逗号复合集，截断发生在传入前的正则解析。现状：当前 `requirements-mail-core.txt` 9 行全为单段 `>=`（`uvicorn[standard]` / `psycopg[binary]` 的 extras 由 `(?:\[[^\]]+\])?` 正确处理），无复合约束；且 spec 非范围明确「不升级 requirements-mail-core.txt 的约束写法」，故坏结果不落在当前交付物，仅未来引入 `,<2.0` / `!=` 等复合约束才触发，不削弱当前门禁拦截能力。此为 R1 f001 之外的另一层面（需求解析正则，非版本比较逻辑本身），f001 三类坏结果已全部消失。
- 建议：把约束组扩到 `;`（环境标记分隔）或行尾，保留完整 specifier 集整体传给 `SpecifierSet`；或维持现状并在处置表说明「当前 `.txt` 约束形态单一，复合约束不在范围」。属 minor，须由 implementer 写入 `progress.md` 处置表（已修 / 遗留 / 撤回）。

### 结论

- 前轮 finding 复核：f001（important）从根因消除、f002/f003（minor）已修；R1 结论段系统性项状态延续、无悬空。详见上方四条处置。
- 本轮新发现：1 条（minor `t078_code_f004`），0 critical / 0 important。
- 未进表的提示：
    - 文件过大（降级规则，仅列路径与行数）：`scripts/check_doc_sensitive.py` 706 行、`tests/scripts/test_check_doc_sensitive.py` 830 行（手写脚本 400/800、测试源码 600/1200，均命中 minor 未达 important，本 task 净增）；`scripts/check_dep_locks.py` 190 行、`tests/scripts/test_check_dep_locks.py` 142 行未超阈值。
    - 圈复杂度：`scan_file`（`scripts/check_doc_sensitive.py:429`）本就多分支，值形态改造后嵌套 `for value in value_spans`，手算 CC ≥10，按规则不进表、仅提示可简化。
    - 代码/文档一致性：生产脚本模块 docstring、`verify_lock_offline` docstring、`--check` help、`OK: ...` 输出与新离线模型一致；`tests/scripts/test_check_dep_locks.py:24-28` 注释仍称 `--check` 会 shell out 到 `uv`（与新离线实现不符），该观察 R1 test 轴已记录、属测试层注释清理，本轴不重复出 finding，仅提示。
    - 死代码：`strip_header_comments` 已删；`canonicalize_header` / `run_compile` / `tempfile` 生成模式仍引用，无新增未用 import/函数。
    - 安全/语义边界（spec 已批准）：散文/表格/代码引用示例不报、归档目录整体不收集、`TOKEN_RE`（`:520`）/`PRIVATE_KEY_RE`（`:510`）整行无条件拦截、`ASSIGN_RE` default-deny（`:545`）未削弱，动态复跑确认。
    - `docs/handoff.md` 被 `ARCHIVE_FILES`（`:603`）与 `.sensitive_ignore`（`:15`）排除，其中真凭据目录扫描不覆盖，属 AC-001 授权排除项。
- 剩余风险（重点核实项）：
    - ① packaging 解释器（用户特别关注）：系统 `python3`（无 venv、无 packaging）直接 `python3 scripts/check_dep_locks.py --check` 实测 `rc=2`、`SystemExit(2)` fail-closed。逐一核实所有 `--check` 入口——`## test_cmd` / `## doctor_cmd` 仅以 `python3` 调 `check_doc_sensitive.py`（不 import packaging，`docs/blueprint/testing.md:12/37`）；`test_check_dep_locks_script_passes` 用 `sys.executable`（`tests/scripts/test_check_dep_locks.py:34`），独立复跑确认 pytest 的 `sys.executable`=`.venv/bin/python`、49 passed；`scripts/build-sidecar.sh` 的 PY 选择（`:11-17`）在本工作树解析为 `.venv/bin/python`（packaging 26.3）；`_load_dep_module` 系列用例在 pytest 解释器内 import 模块，同样落在 `.venv`。`requirements-dev.txt` 声明 `packaging>=23.0`，`.venv` 由其安装（`docs/blueprint/testing.md:90-95`）；全仓 grep 无 CI/工作流以裸 `python3` 调 `--check`。结论：canonical 门禁全部落在有 packaging 的解释器，fail-closed 为正确设计，不构成当前交付门禁缺陷。残留：无 venv 的 ad-hoc 裸 `python3` 复跑（如 testing strategy「直接复跑」）与 `build-sidecar.sh` 的 `PY=python3` 兜底分支确会 rc=2 并在 `:20` 以「Dependency lock mismatch」误导性报错中止；但该兜底路径同样缺 PyInstaller（`:25`）构建本就无法成功，且非项目文档声明的环境。可按处置表登记为已知约束或改用懒加载/强制 venv。
    - ② f004 复合约束截断：潜在、当前 `.txt` 不触发，见 finding。
    - ③ 跨轴状态：本轮仅代码轴；写报告后 `review-status` 读到 `code_verdict=PASS` / `test_verdict=PASS` / `review_scope=ok` / `ac_review=ok` / `privacy_review=ok`（两轴 R2 均已 PASS、指纹与题干一致）。当前 `overall=INCOMPLETE` 仅因 `missing_disposition=t078_code_f004`：新增 minor 未入 `progress.md` 处置表，属 implementer 正常收尾动作（补一行 已修/遗留/撤回），非审查结论翻转。
- 总体判断：AC-001~AC-006 实现层打勾均成立（全 TICK-VALID），R1 唯一 important 已从根因修复、未引入 regression，无未解决 critical / important；仅 1 条潜在 minor（f004，当前交付物不触发）。按判定式 verdict=PASS。
- 系统性 follow-up：无（`task.py list` 无等价 dep-lock / PEP440 follow-up；f004 属本 task 内 minor，由处置表闭环，不构成跨 task 缺口）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`ARCHIVE_DIR_PREFIXES`（`:595`）/ `ARCHIVE_FILES`（`:603`）/ `_is_archived_doc`（`:606-611`）排除 6 前缀 + `docs/handoff.md`，`collect_target_files`（`:614`）目录排除、发布面不排除；`.sensitive_ignore`（`:8-15`）已改真实路径；复跑 `python3 scripts/check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0，`test_repo_docs_gate_passes` 在 49 passed 内。
- AC-002：TICK-VALID，re_verified。动态复跑 `_value_spans`：散文/表格/代码引用→`[]`、赋值 RHS 与孤立裸值行→对应值；`PRIVATE_KEY_RE`（`:510`）/`TOKEN_RE`（`:520`）整行检测、`ASSIGN_RE` default-deny（`:545`）逐行未改，PWD_LEN 改值区间（`:533`）。
- AC-003：TICK-VALID，re_verified。`verify_lock_offline`（`:75-141`）无 `subprocess`/网络、`--check` 分支（`:172-186`）不调 `run_compile`（`test_check_is_offline_no_recompile` 在 49 passed 内）；`.venv/bin/python ... --check` 输出 `OK: ... is synchronized ...` rc=0；`git diff` 未含 lock/txt；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:55` 字面量有效；生成模式（`:153-170`）保留；PEP 440 边界与非 `>=` 约束动态复跑通过。f004 为潜在解析边界，不改变本 AC 对当前交付物成立。
- AC-004：TICK-VALID，re_verified。49 passed 含新增负向用例；动态复跑 `verify_lock_offline` 对缺 hash、低于下界、非 `>=` 约束均拒绝，`scan_file` 对孤立 PATH/EMAIL 值仍拦截、高危签名整行拦截；真泄漏拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。核对 `docs/blueprint/testing.md` diff：`:21` 删除过期「2142 passed / 既存失败」、`:23` 新增「当前基线（t078 之后）」、`:84` 敏感扫描规范重写为新模型 + `:86` 归档分流段、`:313` 历史证据表标注「历史时点快照 / 当前以 verification_notes 为准」且历史行不改写；复跑敏感扫描 0 违规；`## test_cmd` 其余三项（模板契约 463 / 前端 586+ 全链 / 桌面单测）依赖用户提供的门禁证据，本 reviewer 未独立重跑（按用户指示不跑 PG 门禁、前端全链成本高），如实披露。
- AC-006：TICK-VALID，re_verified。核对 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` front matter `status=closed` / `resolution=resolved` / `fix_ref=t078`、`docs/specs/testing_quality.md` `tasks: [t013, t014, t078]`；diff 未新增 pending/finding/spike 等遗留项（`requirements-dev.txt` 仅加 dev 依赖）。

coverage = 5 / 6

verdict: PASS

## Round 3 (2026-11-12T17:24:18+08:00)

- reviewer_focus：代码
- round：3
- reviewed_at：2026-11-12T17:24:18+08:00
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（11 个已跟踪修改文件；`git status --short` 未跟踪仅两份 `review_*.md`，属 REVIEW_PROCESS_FILES 排除项，无未跟踪交付文件）
- review_level：full
- 落点仓库校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过。
- 独立复跑：`.venv/bin/python` 动态探针（`_REQ_RE` 8 类输入、`verify_lock_offline` 12 类边界、`main --check`、生成模式代码路径、PEP 440 回归探针）；`KKMAIL_TEST_MODE=unit` 定点 `tests/scripts/test_check_dep_locks.py` + `test_check_doc_sensitive.py` **50 passed**；`python3 scripts/check_doc_sensitive.py docs --check` 32 文件 0 违规 rc=0；裸 `python3 ... --check` rc=2 fail-closed；`git diff --check` rc=0。未跑 PG 门禁 / 前端全链 / 桌面单测 / 模板契约（按用户指示与成本，采用门禁证据）。

reviewed_scope: 0e1bd51a2b18e0fb

### 前轮 finding 复核（R1/R2 全部，以 diff / 代码 / 独立复跑为准）

说明：本轮为 f004 修复后的定点重审。逐条核实 R1 三条 + R2 一条 + 两轮结论段系统性项 + test 轴 R1 五条，结论均为「维持有效、未因本轮改动回退」。本轮 diff 增量仅落 `scripts/check_dep_locks.py:37`（`_REQ_RE` 一行替换）与 `tests/scripts/test_check_dep_locks.py:145-158`（新增 `test_compound_constraint_upper_bound_enforced`）两处；`scripts/check_doc_sensitive.py`、`tests/scripts/test_check_doc_sensitive.py` 本轮未改（R2 描述的关键实现逐行对照当前内容一致）。

**① t078_code_f004（minor，复合约束逗号截断）— 已消除，从根因修复，处置结论：CLOSED。**

- 修复：`_REQ_RE`（`scripts/check_dep_locks.py:37`）由 `\A([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*([><=!~]{1,2}\s*[^\s,;]+)?` 改为 `\A([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*?)\s*\Z`，约束组改为捕获整行剩余串；`:99` 取值后交 `SpecifierSet(spec)`（`:132`）整体判定。新增负向用例 `test_compound_constraint_upper_bound_enforced`（`tests/scripts/test_check_dep_locks.py:145-158`）：构造 `foo>=1.2,<2.0` + lock `foo==2.5`（带合法 sha256）断言 `does not satisfy`。断言非恒真（errors 为空即失败），锁的 hash 合法故失败原因唯一，触达生产 `verify_lock_offline`。
- 独立动态复跑：`foo>=1.2,<2.0` / `foo==2.5` → `['r.lock: foo==2.5 does not satisfy >=1.2,<2.0']`，上界不再被静默放行；满足上界的 `foo==1.5` → `[]`。R2 报告的坏结果消失。
- 用户点名边界逐项复核：
    - 无约束行 `foo`：`_REQ_RE` → group(2)=`''`，`:128-129` 报 `has no version constraint` 拒绝，解析**不异常**；与 R2「空约束→has no version constraint」一致。
    - 带 extras 行 `uvicorn[standard]>=0.30.0` / `psycopg[binary]>=3.2.0`：group(1) 正确截在 `[` 前、extras 由 `(?:\[[^\]]+\])?` 吸收、group(2)=`>=0.30.0` / `>=3.2.0`；动态复跑 `uvicorn==0.31.0`→`[]`、`uvicorn==0.20.0`→`does not satisfy >=0.30.0`，**解析与判定均正常**。
    - `verify_lock_offline` 仍 fail-closed：缺 txt / 缺 lock / 无直接依赖声明 / 无 pins / 缺 hash / 缺直接依赖 pin / 无约束 / 非法约束 `>=>>` / 低于下界 / 违反上界共 10 类均返回非空 errors；`packaging` import 失败 `SystemExit(2)`（`:22-29`，裸 `python3 --check` 实测 rc=2）；未见「静默放行违反约束 lock」路径。
    - 当前 `requirements-mail-core.txt`（9 行，含 2 个 extras）`verify_lock_offline(LOCK_FILE, TXT_FILE)` 返回 `[]`，`main --check` rc=0。
    - 生成模式：`main` 非 `--check` 分支（`:153-170`）仍 `run_compile`（`:161`）+ `canonicalize_header`（`:164`），后者非死代码；只读审查下以 `inspect.getsource` 核实路径存在，未实际执行（避免改写 lock）。
    - CLI / 输出：`--check` flag（`:146`）、`OK: requirements-mail-core.lock is synchronized with requirements-mail-core.txt`（`:185`，`main --check` 实测输出 rc=0）、`assert "synchronized"`（`tests/scripts/test_check_dep_locks.py:41`）均保持。
    - 字面量：`scripts/build-sidecar.sh:20` = `if ! "$PY" scripts/check_dep_locks.py --check; then`；`tests/scripts/test_check_dep_locks.py:56` = `assert "check_dep_locks.py --check" in sidecar_script`（R1/R2 记 `:55`，实为 `:56`，另 `:40` 同含字面量），`test_build_sidecar_script_includes_gate`（`:54`）在 50 passed 内。均仍有效。
    - 不偏航：`git diff --name-only b2050e33 -- src/ requirements-mail-core.lock requirements-mail-core.txt` 为空；11 个修改文件全在 spec 范围；`git diff --check` rc=0；未改产品代码 / lock / txt 之外不该动的文件。
- 结论：f004 从根因修复、负向回归护航、无 regression，处置 **CLOSED（已消除）**。

**② t078_code_f001（important，PEP 440 版本比较）— 维持已消除，未回退。** `SpecifierSet(spec).contains(pins[name])`（`:132`）与 `InvalidSpecifier/ValueError` 捕获（`:136`）在位；`packaging>=23.0` 仍在 `requirements-dev.txt:5`；import guard（`:22-29`）fail-closed。PEP 440 回归探针：`>=1.2.0` contains `1.2`=True、`>=2.0.0` contains `2.0.0rc1`=False、`!=1.5` / `==9.9.9` 均正确；R1 三类坏结果不复现。

**③ t078_code_f002（minor，死函数）— 维持已消除。** 全仓 grep `strip_header_comments` 零命中；生成模式依赖 `canonicalize_header`（`:164`）。

**④ t078_code_f003（minor，重复计数）— 维持已消除，本轮未触及。** `_value_spans`（`scripts/check_doc_sensitive.py:290-319`）`:315-318` 仍为「仅当 `values` 为空才回退整行裸值」，与 `:312-314` 注释一致；本轮 diff 未含该文件。

**⑤ R1/R2 结论段系统性项 + test 轴 R1 五条 — 状态延续、无悬空。** PEP 440 follow-up 已并入 f001；「残留双套归档判定」、文件过大、`scan_file` 复杂度、`docs/handoff.md` 排除项、`tests/scripts/test_check_dep_locks.py:24-28` 过时注释（仍称 `--check` shell out 到 uv）均为 t078 前既有或 R1/R2 已记录、本轮未触及、非 regression。`test_check_doc_sensitive.py` 本轮未改，10 个负向 true-positive 用例全在（50 passed 内）；`test_check_dep_locks.py` 1-142 行旧用例未删改，新增用例仅追加于末尾。

### Findings

本轮新发现：0 条（`t078_code_f005` 起无编号）。f004 修复未引入新的 critical / important / minor 缺陷。零发现合法：唯一新观察「环境标记约束被拒」属范围外、当前交付物不触发、方向为拒绝而非放行违规，按 prompt「范围外问题仅结论段提示」不进表，详见结论「剩余风险①」。

### 结论

- 前轮 finding 复核：f004（minor）从根因消除、处置 CLOSED；f001（important）/ f002 / f003（minor）维持已消除、未回退；R1/R2 系统性项与 test 轴 R1 五条状态延续、无悬空。详见上方五条。
- 本轮新发现：0 条（0 critical / 0 important / 0 minor）。
- f004 处置结论：**已消除（CLOSED）**。
- 本轮判定（PASS / FAIL / INCOMPLETE）：**PASS**（code 轴 verdict）。写报告后实测 `review-status`：`code_verdict=PASS` / `test_verdict=PASS` / `review_scope=ok` / `ac_review=ok` / `privacy_review=ok` / `round=3`，本轴 `reviewed_scope=0e1bd51a2b18e0fb` 与当前 worktree 一致；`overall=INCOMPLETE` 仅因 `missing_disposition=t078_test_f006`（test 轴 R3 并行追加的 1 条 minor：`tests/scripts/test_check_dep_locks.py:24-29` 过时注释，属测试层、与本报告 ⑤ 记录一致，非本轴 finding），由 implementer 在 `progress.md` 处置表补一行「已修 / 遗留 / 撤回」即闭环，非 code 轴结论翻转。
- 未进表的提示：
    - 文件过大（降级规则，仅列路径与行数）：`scripts/check_doc_sensitive.py` 706 行、`tests/scripts/test_check_doc_sensitive.py` 约 830 行（手写脚本 400/800、测试源码 600/1200，命中 minor 未达 important）；`scripts/check_dep_locks.py` 190 行（本轮净增 0）、`tests/scripts/test_check_dep_locks.py` 158 行（本轮净增约 16 行、新增 1 用例）未超阈值，未使任何文件越过新档。
    - 圈复杂度：`scan_file`（`scripts/check_doc_sensitive.py`）本就多分支，按规则不进表。
    - 代码/文档一致性：模块 docstring、`verify_lock_offline` docstring、`--check` help、`OK:` 输出与离线模型一致；`tests/scripts/test_check_dep_locks.py:24-28` 过时注释见 ⑤。
    - 安全/语义边界（spec 已批准）：散文/表格/代码引用示例不报、归档整体排除、`TOKEN_RE` / `PRIVATE_KEY_RE` 整行拦截、`ASSIGN_RE` default-deny 未削弱（敏感扫描 32 文件 0 违规）。
    - `docs/handoff.md` 被 `ARCHIVE_FILES` 与 `.sensitive_ignore` 排除，其中真凭据目录扫描不覆盖，属 AC-001 授权排除项。
    - 行号漂移：spec「依赖与约束」记 `tests/scripts/test_check_dep_locks.py:55` 硬编码字面量，当前实际在 `:56`（另 `:40` 亦有）；字面量与测试均有效，非行为偏差，不进表。
- 剩余风险（如实披露，均不阻断）：
    - ① 环境标记（`;`）需求：新 `(.*?)` + `\Z` 把 marker 一并捕获交 `SpecifierSet`，动态复跑 `foo>=1.2; python_version < '3.12'` → `invalid constraint ... InvalidSpecifier` 并被 `main` 拒绝（rc=1）。相对旧实现（在 `;` 处截断、静默忽略 marker）属行为变化，但方向为「拒绝」而非「放行违规」，不削弱门禁；当前 `requirements-mail-core.txt` 9 行无环境标记、spec 非范围明确「不升级约束写法」，故不触发；R2 f004 建议本就给「扩到 `;` 或行尾」二选一，实施选行尾属合规选项。按「范围外问题仅结论段提示」不进表。若未来引入带 marker 的生产依赖，需先在 `;` 处剥离 marker 再交 `SpecifierSet`。
    - ② 裸 `python3`（无 venv / 无 packaging）`--check` 实测 rc=2 fail-closed（R2 剩余风险①状态延续）：canonical 门禁入口全落 `.venv/bin/python`（含 packaging 26.3），`scripts/build-sidecar.sh:11-17` PY 选择在本树解析为 `.venv/bin/python`；`test_check_dep_locks_script_passes` 用 `sys.executable`（50 passed 内）。残留：ad-hoc 裸 `python3` 复跑与 `PY=python3` 兜底分支会 rc=2 并在 `:20` 以「Dependency lock mismatch」误导性报错中止；该兜底路径同样缺 PyInstaller、构建本就无法成功，且非项目声明环境。状态延续、非本轮引入。
    - ③ 跨轴 rollup（非本轴结论）：test 轴 R3 已由并行会话追加（PASS、`reviewed_scope=0e1bd51a2b18e0fb`，与本轴一致），提出 1 条 minor `t078_test_f006`（`tests/scripts/test_check_dep_locks.py:24-29` 过时注释，即本报告 ⑤ 记录、按职责归测试层）。`review-status` 实测 `review_scope=ok` / `round=3` / 两轴 verdict 均 PASS，`overall=INCOMPLETE` 唯一原因是该 minor 未入 `progress.md` 处置表（`missing_disposition`），属 implementer 正常收尾，非审查结论翻转。
- 总体判断：唯一 minor（f004）已从根因修复，经独立动态复跑与 50 passed 定点单测验证，无未解决 critical / important，前轮全部处置维持有效、无回退，AC-001~AC-006 实现层打勾全部成立。按判定式 **verdict: PASS**。
- 系统性 follow-up：无（沿用 R2 只读 `task.py list` 结论：无等价 dep-lock / PEP440 follow-up；f004 已闭环，环境标记 / 裸 python3 两项属本 task 已知约束，由处置表或未来需求承接，不构成跨 task 缺口）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`.sensitive_ignore` diff 修正为 7 条真实归档路径，`ARCHIVE_DIR_PREFIXES` / `ARCHIVE_FILES` / `collect_target_files`（`scripts/check_doc_sensitive.py`）排除 6 前缀 + `docs/handoff.md`、发布面不排除；复跑 `python3 scripts/check_doc_sensitive.py docs --check` 32 文件 0 违规 rc=0，`test_repo_docs_gate_passes`（`tests/scripts/test_check_doc_sensitive.py:164`）在 50 passed 内。
- AC-002：TICK-VALID，re_verified。`_value_spans`（`scripts/check_doc_sensitive.py:290-319`）值形态模型 + `:315-318` 仅空回退在位；动态复跑散文/表格/代码引用→`[]`、赋值 RHS 与孤立裸值行→对应值；`PRIVATE_KEY_RE` / `TOKEN_RE` 整行检测、`ASSIGN_RE` default-deny 未改；敏感扫描 0 违规。
- AC-003：TICK-VALID，re_verified。`verify_lock_offline`（`scripts/check_dep_locks.py:75-141`）无 subprocess / 网络，`main --check`（`:172-186`）不调 `run_compile`（`test_check_is_offline_no_recompile` 在 50 passed 内）；`.venv/bin/python ... --check` 输出 `OK: ... is synchronized ...` rc=0；`git diff` 未含 lock/txt；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:56` / `:40` 字面量有效；生成模式（`:153-170`）保留；f004 复合约束上界动态复跑已拒绝 `foo==2.5`。
- AC-004：TICK-VALID，re_verified。50 passed 含 `test_publish_face_true_positives_still_detected`（`:770`）、`test_publish_face_prose_examples_are_not_values`（`:752`）、`test_archive_directories_excluded_from_docs_scan`（`:792`）、`test_explicit_archived_file_target_is_still_scanned`（`:822`）、`test_check_rejects_lock_missing_hash`（`:94`）、`test_lock_below_declared_floor_rejected`（`:133`）、`test_upstream_release_does_not_invalidate_older_lock`（`:122`）及新增 `test_compound_constraint_upper_bound_enforced`（`:145`）；动态复跑 `verify_lock_offline` 对缺 hash、缺直接依赖、低于下界、违反上界、无约束、非法约束均拒绝，拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。核对 `docs/blueprint/testing.md` diff：`:21` 删除过期「2142 passed / 既存失败」、`:23` 新增「当前基线（t078 之后）」、`:84` 敏感扫描规范重写为新模型 + `:86` 归档分流段、`:313` 历史证据表标注「历史时点快照 / 当前以 verification_notes 为准」且历史行不改写；`## test_cmd`（`:29-38`）四项定义（模板契约 / 前端 npm test+tsc+build / 桌面 npm test / 敏感扫描）在位，其中第 4 项 `python3 ... docs --check` 本 reviewer 已独立复跑 0 违规；其余三项（模板契约 463、前端 586+ 全链、桌面单测）依用户门禁证据、本 reviewer 未独立重跑（按指示不跑 PG 门禁、前端全链成本高），如实披露 trust_prior。
- AC-006：TICK-VALID，re_verified。核对 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` front matter `status=closed` / `resolution=resolved` / `fix_ref=t078`、`docs/specs/testing_quality.md` `tasks: [t013, t014, t078]`；diff 未新增 pending / finding / spike 等遗留项（`requirements-dev.txt` 仅加 `packaging>=23.0` dev 依赖）。

coverage = 5 / 6

verdict: PASS

## Round 4 (2026-11-12T17:46:02+08:00)

- reviewer_focus：代码
- round：4
- reviewed_at：2026-11-12T17:46:02+08:00
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（11 个已跟踪修改文件；`git status --short` 未跟踪仅两份 `review_*.md`，属 REVIEW_PROCESS_FILES 排除项，无 reviewer 不可见的未跟踪交付文件）
- review_level：full
- 落点仓库校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过。HEAD 即 `diff_anchor` 本身（无中间 commit），全部 t078 改动为未提交工作树修改，各轮共用同一 diff。
- 独立复跑：`KKMAIL_TEST_MODE=unit` 定点 `tests/scripts/test_check_dep_locks.py` + `test_check_doc_sensitive.py` **50 passed**；单列 `::test_check_dep_locks_script_passes` **1 passed**；`.venv/bin/python scripts/check_dep_locks.py --check` 输出 `OK: ... is synchronized ...` rc=0；裸 `python3 ... --check` rc=2 fail-closed；`python3 scripts/check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；权威指纹复算 + R3 指纹反演（见下）；`git diff --check` rc=0。未跑 PG 门禁 / 前端全链 / 桌面单测 / 模板契约（按用户指示与成本，采用门禁证据）。

reviewed_scope: 6c3de906163c1209

### R3→R4 增量核实（指纹反演，收尾轮核心）

- 权威复算 `repo_task.monitoring.review_scope_fingerprint('b2050e33b7aa30ec21616936659002a4c77331f6', 'docs/tasks/t078_quality_gate_root_cause_refactor')` = `6c3de906163c1209`，与注入值一致；指纹覆盖 9 条交付路径（`.sensitive_ignore`、`docs/blueprint/testing.md`、`docs/specs/testing_quality.md`、`task.md`、`requirements-dev.txt`、`scripts/check_dep_locks.py`、`scripts/check_doc_sensitive.py`、两份 `tests/scripts/test_check_*.py`），`docs/pending/**` 等由 SCOPE_FINGERPRINT_EXCLUDES 排除，`review_*.md` / `progress.md` 由 REVIEW_PROCESS_FILES 排除（故写本报告不扰动该值）。
- **反演证明**：取当前 `tests/scripts/test_check_dep_locks.py`（150 行，blob `6153a1ff...`），把 `t078_test_f006` 清理反向还原（注释改回旧 uv/PATH 文案、恢复 3 行 `env = dict(os.environ)` / `venv_bin` / `env["PATH"]` 与 `env=env`、`import os` 恢复且 `import re` 保留），得候选 R3 内容 blob `35b347ed...`；以该 blob 替换 `after` 树该路径、其余 8 路径沿用当前 oid，重算指纹 = **`0e1bd51a2b18e0fb`**，与 R3 记录精确一致（另一 import 顺序候选得 `5ce4e7460129736b` 不匹配，排除歧义）。结论：R3→R4 交付变化**有且仅有** `tests/scripts/test_check_dep_locks.py` 这一处注释/冗余清理；`scripts/check_dep_locks.py`、`scripts/check_doc_sensitive.py` 及其余 6 条交付路径 R3↔R4 **逐字节一致，生产脚本无回退**。
- 生产脚本逐行对照 R3 描述一致（行号逐一吻合）：`_REQ_RE`（`scripts/check_dep_locks.py:37`）= `(.*?)\s*\Z`、`SpecifierSet(spec).contains(pins[name])`（`:132`）、`verify_lock_offline`（`:75-141`）、`main --check`（`:172-186`）、`OK:`（`:185`）、生成模式（`:153-170`）；`_value_spans`（`scripts/check_doc_sensitive.py:290-319`）与 `:315-318` 仅空回退、`ARCHIVE_DIR_PREFIXES`（`:595`）/ `ARCHIVE_FILES`（`:603`）/ `_is_archived_doc`（`:606-611`）/ `collect_target_files`（`:614-626`）；`scan_file`（`:458-583`）email/path/PWD_LEN 仅值区间、`PRIVATE_KEY_RE`（`:510`）/`TOKEN_RE`（`:520`）整行、`ASSIGN_RE` default-deny（`:544-563`）。
- 不偏航：`git diff --name-only b2050e33 -- src/ requirements-mail-core.lock requirements-mail-core.txt` 为空；`git diff --name-only b2050e33` 恰 11 文件全在 spec 范围；`scripts/build-sidecar.sh:20` 字面量 `if ! "$PY" scripts/check_dep_locks.py --check; then` 仍在（该文件不在 diff 内、未改）。

### 前轮 finding 复核（R1/R2/R3 全部，以 diff / 代码 / 独立复跑为准）

**① t078_code_f001（important，PEP 440 版本比较）— 维持已消除。** `SpecifierSet(spec).contains(pins[name])`（`:132`）+ `InvalidSpecifier/ValueError` 捕获（`:136`）在位；import guard（`:22-29`）fail-closed，本轮裸 `python3 --check` 实测 rc=2 复现；`packaging>=23.0` 在 `requirements-dev.txt:5`，`.venv` packaging 26.3。R1 三类坏结果不复现。

**② t078_code_f002（minor，死函数）— 维持已消除。** 全仓 grep `strip_header_comments` 仅命中 `progress.md` / `review_code.md` 叙述，代码零命中；生成模式依赖 `canonicalize_header`（`:63-72`，`:164` 调用）与 `run_compile`，无新增死代码。

**③ t078_code_f003（minor，重复计数）— 维持已消除。** `_value_spans`（`scripts/check_doc_sensitive.py:315-318`）仍为「仅当 `values` 为空才回退整行裸值」，与 `:312-314` 注释一致；本轮未触及该文件。

**④ t078_code_f004（minor，复合约束逗号截断）— 维持已消除。** `_REQ_RE`（`:37`）捕获整行剩余串交 `SpecifierSet`；`test_compound_constraint_upper_bound_enforced`（`tests/scripts/test_check_dep_locks.py:137-150`）在 50 passed 内，断言非恒真。

**⑤ R1/R2 结论段系统性项 + test 轴 R1 五条 — 状态延续、无悬空。** PEP 440 follow-up 已并入 f001；「残留双套归档判定」、文件过大、`scan_file` 复杂度、`docs/handoff.md` 排除项均为 t078 前既有或已记录、本轮未触及、非 regression；`test_check_doc_sensitive.py` 本轮未改，10 个负向 true-positive 用例全在（50 passed 内）。

**⑥ t078_test_f006（test 轴 R3 minor，即本轮唯一 R3→R4 交付变化）— 已修且本轮独立复验通过。** 清理后 `test_check_dep_locks_script_passes`（`:21-33`）以 `sys.executable` 绝对路径调用 `--check`，无 `env` 参数、无 `import os`，注释改述离线语义，与 `verify_lock_offline` 纯离线实现一致。见「Findings」与 AC-003 复验证据。

### Findings

本轮新发现：**0 条**（0 critical / 0 important / 0 minor）；`t078_code_f005` 起无编号（连续第二轮零发现）。`t078_test_f006` 清理未引入任何新缺陷：`import re` 仍被 `re.match` / `re.sub` 用例使用、无悬空 `os` 引用、无死代码、注释与实现一致；50 passed + 单测 1 passed + `.venv --check` rc=0 共同佐证。零发现合法，不为凑数制造 finding。

### 结论

- 前轮 finding 复核：f001（important）/ f002 / f003 / f004（minor）维持已消除、未回退；R1/R2 系统性项与 test 轴 R1 五条状态延续、无悬空；`t078_test_f006` 已修并独立复验通过。详见上方六条。
- R3→R4 增量：**仅 `tests/scripts/test_check_dep_locks.py` 注释/冗余清理，生产脚本逐字节未变**（指纹反演证明），R1/R2/R3 全部 finding 处置维持有效。
- 本轮新发现：0 条（`t078_code_f005` 起无编号）。
- 本轮判定（PASS / FAIL / INCOMPLETE）：**PASS**（code 轴 verdict）。`reviewed_scope=6c3de906163c1209` 与权威复算的当前 worktree 指纹一致；写报告不改指纹。
- 未进表的提示：
    - 文件过大（降级规则，仅列路径与行数）：`scripts/check_doc_sensitive.py` 706 行、`tests/scripts/test_check_doc_sensitive.py` 830 行（手写脚本 400/800、测试源码 600/1200，命中 minor 未达 important，均为本 task 净增）；`scripts/check_dep_locks.py` 190 行、`tests/scripts/test_check_dep_locks.py` 150 行（本轮净减 8 行）未超阈值，未使任何文件越过新档。
    - 圈复杂度：`scan_file`（`scripts/check_doc_sensitive.py`）本就多分支，按规则不进表。
    - 代码/文档一致性：模块 docstring、`verify_lock_offline` docstring、`--check` help、`OK:` 输出与离线模型一致；R4 新注释准确反映离线实现，无过时注释残留。
    - 安全/语义边界（spec 已批准）：散文/表格/代码引用示例不报、归档整体排除、`TOKEN_RE` / `PRIVATE_KEY_RE` 整行拦截、`ASSIGN_RE` default-deny 未削弱（敏感扫描 32 文件 0 违规）。
    - `docs/handoff.md` 被 `ARCHIVE_FILES` 与 `.sensitive_ignore` 排除，其中真凭据目录扫描不覆盖，属 AC-001 授权排除项。
    - 行号漂移：spec「依赖与约束」记 `tests/scripts/test_check_dep_locks.py:55` 硬编码字面量；本轮清理净减 8 行后实际在 `:48`（`assert "check_dep_locks.py --check" in sidecar_script`）与 `:32`（`assert ... --check failed:`），R3 记 `:56`/`:40`。字面量与 `test_build_sidecar_script_includes_gate`（`:46`）均有效，非行为偏差，不进表。
    - 残留双套归档判定（`--ignore-archived-errata` 旧机制）：t078 前既有、R1 已列未进表、本轮未触及、非 regression。
- 剩余风险（如实披露，均不阻断）：
    - ① 环境标记（`;`）需求：`(.*?)` + `\Z` 把 marker 一并交 `SpecifierSet`，动态复跑为 `invalid constraint ... InvalidSpecifier` 并被 `main` 拒绝（方向为「拒绝」而非「放行违规」，不削弱门禁）；当前 `requirements-mail-core.txt` 9 行无 marker、spec 非范围明确「不升级约束写法」，不触发；R2 f004 建议本就给「扩到 `;` 或行尾」二选一，实施选行尾属合规选项。状态延续、不进表；若未来引入带 marker 生产依赖，需先在 `;` 处剥离。
    - ② 裸 `python3`（无 venv / 无 packaging）`--check` 本轮实测 rc=2 fail-closed（R2/R3 剩余风险①状态延续）：canonical 门禁入口全落 `.venv/bin/python`（packaging 26.3），`scripts/build-sidecar.sh:11-17` PY 选择在本树解析为 `.venv/bin/python`，`test_check_dep_locks_script_passes` 用 `sys.executable`（50 passed 内）。残留：ad-hoc 裸 `python3` 复跑与 `PY=python3` 兜底分支会 rc=2 并在 `:20` 以「Dependency lock mismatch」误导性报错中止；该兜底路径同样缺 PyInstaller、构建本就无法成功，且非项目声明环境。
    - ③ 跨轴 rollup（非本轴结论）：test 轴 R4 已由并行会话追加（`## Round 4 (2026-11-12T17:39:03+08:00)`、`reviewed_scope=6c3de906163c1209`、`verdict: PASS`），与本轴指纹一致；本轴写入 R4 后两轴指纹一致。`overall` 仍取决于 `progress.md` 处置表补齐 R4 条目与轮次上限，属 implementer 收尾，非 code 轴 verdict 翻转。
    - ④ 用户门禁证据中模板契约 463 / 前端 586+ 全链 / 桌面单测三项未由本 reviewer 独立重跑，按 trust_prior 披露（见 AC-005）。
- 总体判断：收尾轮核实 R3→R4 交付变化仅测试文件注释/冗余清理、生产脚本无回退（指纹反演精确复现 R3 指纹），前轮全部 finding 处置维持有效、无回退，`test_check_dep_locks_script_passes` 去掉 `env` 后仍通过（50 passed + 单测 1 passed + `--check` rc=0），AC-001~AC-006 实现层打勾全部成立，无未解决 critical / important。按判定式 **verdict: PASS**。
- 系统性 follow-up：无（沿用 R2/R3 只读 `task.py list` 结论：无等价 dep-lock / PEP440 follow-up；环境标记 / 裸 python3 两项属本 task 已知约束，不构成跨 task 缺口）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`.sensitive_ignore` diff 修正为 7 条真实归档路径，`ARCHIVE_DIR_PREFIXES`（`:595`）/ `ARCHIVE_FILES`（`:603`）/ `_is_archived_doc`（`:606-611`）/ `collect_target_files`（`:614-626`）排除 6 前缀 + `docs/handoff.md`、发布面不排除；`python3 scripts/check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；`test_archive_directories_excluded_from_docs_scan`（`:792`）、`test_explicit_archived_file_target_is_still_scanned`（`:822`）、`test_repo_docs_gate_passes` 在 50 passed 内。
- AC-002：TICK-VALID，re_verified。`scan_file`（`:458-563`）email/path/PWD_LEN 仅值区间、`PRIVATE_KEY_RE`（`:510`）/`TOKEN_RE`（`:520`）整行无条件拦截、`ASSIGN_RE` default-deny（`:544-563`）逐行未改；`_value_spans`（`:290-319`）`:315-318` 仅空回退在位；`test_publish_face_prose_examples_are_not_values`（`:752`）在 50 passed 内；全仓敏感扫描 0 违规。
- AC-003：TICK-VALID，re_verified。`verify_lock_offline`（`scripts/check_dep_locks.py:75-141`）无 subprocess / 网络，`main --check`（`:176-185`）不调 `run_compile`（`test_check_is_offline_no_recompile` 在 50 passed 内）；`.venv/bin/python ... --check` 输出 `OK: ... is synchronized ...` rc=0；`git diff` 未含 lock/txt；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:48`/`:32` 字面量有效；生成模式（`:153-170`）保留；`test_upstream_release_does_not_invalidate_older_lock`（`:114`）、`test_compound_constraint_upper_bound_enforced`（`:137`）在 50 passed 内；`test_check_dep_locks_script_passes` 去 `env` 后单测 1 passed（离线 `--check` 不依赖 PATH 找 uv）。
- AC-004：TICK-VALID，re_verified。50 passed 含 `test_publish_face_true_positives_still_detected`（`:770`）、`test_publish_face_prose_examples_are_not_values`（`:752`）、`test_archive_directories_excluded_from_docs_scan`（`:792`）、`test_explicit_archived_file_target_is_still_scanned`（`:822`）、`test_check_rejects_lock_missing_hash`（`:86`）、`test_lock_below_declared_floor_rejected`（`:125`）、`test_compound_constraint_upper_bound_enforced`（`:137`）；动态确认高危签名整行拦截、缺 hash / 低于下界 / 违反上界均拒绝，真泄漏拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。核对 `docs/blueprint/testing.md` diff：`:21` 删除过期「2142 passed / 既存失败」并新增「当前基线（t078 之后）」段、`:84` 敏感扫描规范重写为新模型 + `:86` 归档分流段、`:313` 历史证据表标注「历史时点快照 / 当前以 verification_notes 为准」且历史行不改写；`## test_cmd`（`:29-38`）四项定义（模板契约 / 前端 npm test+tsc+build / 桌面 npm test / 敏感扫描）在位，其中第 4 项 `python3 ... docs --check` 本 reviewer 已独立复跑 0 违规；其余三项（模板契约 463、前端 586+ 全链、桌面单测）依用户门禁证据、本 reviewer 未独立重跑（按指示不跑 PG 门禁、前端全链成本高），如实披露 trust_prior。
- AC-006：TICK-VALID，re_verified。核对 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` front matter `status=closed` / `resolution=resolved` / `fix_ref=t078`、`docs/specs/testing_quality.md` `tasks: [t013, t014, t078]`；diff 未新增 pending / finding / spike 等遗留项（`requirements-dev.txt` 仅加 `packaging>=23.0` dev 依赖）。

coverage = 5 / 6

verdict: PASS

## Round 5 (2026-11-12T18:15:45+08:00)

- reviewer_focus：代码
- round：5（最后一轮，只读审查）
- reviewed_at：2026-11-12T18:15:45+08:00
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（13 个已跟踪文件；`git status --short` 无 reviewer 不可见的未跟踪交付文件，两份 `review_*.md` 属 REVIEW_PROCESS_FILES 排除项）
- review_level：full
- 落点仓库校验：不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于本 worktree 根，通过。HEAD 即 `diff_anchor`（无中间 commit），全部 t078 改动为工作树修改，各轮共用同一 diff。
- 独立复跑：`KKMAIL_TEST_MODE=unit` 定点 `tests/scripts/test_check_doc_sensitive.py` + `test_check_dep_locks.py` **50 passed**；6 个 helper 相关用例单列 **6 passed**；`python3 scripts/check_doc_sensitive.py docs --check` 32 文件 0 违规 rc=0；`.venv/bin/python scripts/check_dep_locks.py --check` rc=0；裸 `python3 ... --check` rc=2 fail-closed；权威指纹复算 + R4→R5 指纹反演；`scan_privacy_changes(base=anchor)` **0 findings**；helper 运行时产物静态求值 + 隐私正则比对；`git diff --check` rc=0；不偏航检查。未跑 PG 门禁 / 前端全链 / 桌面单测 / 模板契约（按用户指示与成本，采用门禁证据）。

reviewed_scope: e8cc9501ce3231ae

### R4→R5 增量核实（指纹反演，收尾轮核心）

- 权威复算 `repo_task.monitoring.review_scope_fingerprint('b2050e33b7aa30ec21616936659002a4c77331f6', 'docs/tasks/t078_quality_gate_root_cause_refactor')` = `e8cc9501ce3231ae`，与 Round 5 prompt 注入值一致；R4 记录 `6c3de906163c1209`。指纹覆盖相对 anchor 变化的 9 条交付路径（`.sensitive_ignore`、`docs/blueprint/testing.md`、`docs/specs/testing_quality.md`、`task.md`、`requirements-dev.txt`、两份 `scripts/check_*.py`、两份 `tests/scripts/test_check_*.py`），`docs/pending/**` 等由 SCOPE_FINGERPRINT_EXCLUDES、两份 `review_*.md` / `progress.md` 由 REVIEW_PROCESS_FILES 排除（故写本报告不扰动该值）。
- **反演证明**：把当前 `tests/scripts/test_check_doc_sensitive.py`（851 行，blob `81546ef7...`）的 R5 改动机械反向还原——helper 调用改回对应路径字面量、把拆分出的字符串拼接合并回单一字面量、删除 3 个 helper 定义块并保留 2 空行分隔——得 830 行 R4 候选（blob `e7a791f0...`）；以该 oid 替换 after 树该路径、其余 8 路径沿用当前 oid，重算指纹 = **`6c3de906163c1209`**，与 R4 记录精确一致（另 3 个变体：保留拼接写法 / 保留 3 空行，分别得 `e1177bd7...`、`896fd854...`、`117263ab...`，均不匹配，排除歧义）。结论：R4→R5 交付变化**有且仅有** `tests/scripts/test_check_doc_sensitive.py` 的家目录路径字面量→helper 运行时拼接替换；其余 8 条交付路径 R4↔R5 **逐字节一致，生产脚本无回退**。
- 佐证：helper 定义块插在 `tests/scripts/test_check_doc_sensitive.py:325-342` 前，`test_repo_docs_gate_passes` 当前 `:164`（R4 同为 `:164`，不变），其后 `test_publish_face_prose_examples_are_not_values` `:773` / `test_publish_face_true_positives_still_detected` `:791` / `test_archive_directories_excluded_from_docs_scan` `:813` / `test_explicit_archived_file_target_is_still_scanned` `:843`，相对 R4 `:752/:770/:792/:822` 全部 +21，与 851−830=21 行净增吻合；`tests/scripts/test_check_dep_locks.py` 当前 oid `6153a1ff...` 与 R4 报告记录逐字节一致（150 行未变）。
- 生产脚本逐行对照 R4 描述一致：`scripts/check_doc_sensitive.py` 706 行、`scripts/check_dep_locks.py` 190 行（均与 R4 记录一致）；`_REQ_RE`（`:37`）= `(.*?)\s*\Z`、`SpecifierSet(spec).contains(pins[name])`（`:132`）、`verify_lock_offline`（`:75`）、`OK:`（`:185`）、`_value_spans`（`:290`）、`ARCHIVE_DIR_PREFIXES`（`:595`）、`collect_target_files`（`:614`）、`USER_PATH_RE`（`:71`）/ `WIN_USER_PATH_RE`（`:75`）、`scan_file`（`:458-563`）email/path/PWD_LEN 仅值区间（`:481`/`:494`）、`PRIVATE_KEY_RE`（`:510`）/ `TOKEN_RE`（`:520`）整行、`ASSIGN_RE` default-deny（`:544-563`）。
- 不偏航：`git diff --name-only b2050e33 -- src/ requirements-mail-core.lock requirements-mail-core.txt` 为空；13 文件全在 spec 范围（含流程文件）；`scripts/build-sidecar.sh:20` 字面量未改；`git diff --check` rc=0；`git status --short` 无 reviewer 不可见的未跟踪交付文件。

### 前轮 finding 复核（R1/R2/R3/R4 全部，以 diff / 代码 / 独立复跑为准）

R5 未触及任何生产脚本或修复点（反演证明 8 路径逐字节一致），逐条复核结论均为「维持有效、未回退」。

- **① t078_code_f001（important，PEP 440 版本比较）— 维持已消除。** `SpecifierSet(spec).contains(pins[name])`（`scripts/check_dep_locks.py:132`）与 `InvalidSpecifier/ValueError` 捕获在位；import guard（`:22-29`）fail-closed，本轮裸 `python3 --check` 实测 rc=2 复现；`packaging>=23.0` 在 `requirements-dev.txt:5`。R1 三类坏结果不复现。
- **② t078_code_f002（minor，死函数）— 维持已消除。** `strip_header_comments` 代码零命中（仅叙述残留于 `progress.md` / `review_code.md`）；生成模式依赖 `canonicalize_header`（`:164` 调用），无新增死代码。
- **③ t078_code_f003（minor，重复计数）— 维持已消除。** `_value_spans`（`scripts/check_doc_sensitive.py:315-318`）仍为「仅当 `values` 为空才回退整行裸值」；本轮未触及该文件。
- **④ t078_code_f004（minor，复合约束逗号截断）— 维持已消除。** `_REQ_RE`（`:37`）捕获整行剩余串交 `SpecifierSet`；`test_compound_constraint_upper_bound_enforced` 在 50 passed 内，断言非恒真。
- **⑤ t078_test_f006（test 轴 R3 minor）— 维持已修。** `test_check_dep_locks_script_passes` 以 `sys.executable` 绝对路径调用 `--check`、无 `env`/`os` 冗余，与离线实现一致（R4 已独立复验，本轮该文件 oid 逐字节未变）。
- **⑥ R1/R2 结论段系统性项 + test 轴 R1 五条 — 状态延续、无悬空。** PEP 440 follow-up 已并入 f001；「残留双套归档判定」、文件过大、`scan_file` 复杂度、`docs/handoff.md` 排除项均为 t078 前既有或已记录、本轮未触及、非 regression；test 轴 10 个负向 true-positive 用例全在（50 passed 内）。

### 隐私门禁核实（核实点 3）

- 权威入口 `scan_privacy_changes(root, base=anchor)` 返回 **0 findings**；`tests/scripts/test_check_doc_sensitive.py` 相对 anchor 的 126 条新增/修改行逐行调 `find_developer_path_leaks` **0 命中**。
- 机制：`_POSIX_HOME`（`.repo_template/scripts/repo_task/privacy.py:49-52`）/`_WIN_PATH`（`:57-60`）要求家目录前缀后紧跟 `[\w.%-]+` 用户名 token；helper 源码行 `return "/Users/" + user` 的前缀后紧跟引号、模块 docstring 的占位写法 `` `/Users/<user>` `` 前缀后紧跟 `<`，均不构成完整家目录 token；6 个测试函数里的调用文本亦不含完整家目录字面量。家目录形态仅存在于**运行时拼接产物**（内存中的测试输入），不落盘为源码文本。
- 运行时产物仍是真实被测形态（核实点 2，见下），且这些产物本身经 `find_developer_path_leaks` 会返回对应 token——正是 `USER_PATH_RE` 拦截的前提，两者不矛盾；关键是源码新增行零命中。
- `task.py review-status` 实测 `privacy_review=ok` / `review_scope=stale` / `ac_review=ok` / `code_verdict=PASS` / `test_verdict=PASS` / `round=4` / `next_action=rerender_review`：finish 已从「家目录泄漏」转为仅 review stale，隐私门禁已过；stale 仅因 R5 改交付后报告内最后一轮 reviewed_scope 仍是 R4 值，本轮追加写入当前指纹即闭环。

### helper 真实被测形态与断言强度（核实点 2）

- `USER_PATH_RE`（`scripts/check_doc_sensitive.py:71-73`）/ `WIN_USER_PATH_RE`（`:75-77`）字符类 `[a-zA-Z0-9._-]+` 覆盖 5 类 helper 拼接用户名（含点号形态）；静态求值 5 类 helper 拼接产物全部匹配对应正则，并以 isolated assignment RHS（`TARGET=` / `path=` / `HOST_REPO=`）或孤立值行进入 `_value_spans`（`:290`），经 `USER_PATH_RE.finditer(value)`（`:481`）/ `WIN_USER_PATH_RE.finditer(value)`（`:494`）触发 PATH 违规。非弱化断言。
- 断言未放宽：`test_macos_user_path_detected_with_redacted_output`（`:286`）仍 `assert "leak_path.md:3 [PATH]" in proc.stderr` + 脱敏断言；`test_publish_face_true_positives_still_detected`（`:791`）按 5 类各自独立文件 + `assert proc.stderr.count(f"[{category}]") == 1`（精确命中数，删任一检测逻辑必红）。无 `>=` / 正则替换 / `toBeTruthy` / `.skip` / 恒真断言 / mock 被测逻辑。
- `KKMAIL_TEST_MODE=unit`：两文件 **50 passed**；6 个 helper 相关用例（`test_stderr_never_echoes_full_values`、`test_macos/linux/windows_user_path_detected_with_redacted_output`、`test_path_equals_form_detected_with_fake_user`、`test_publish_face_true_positives_still_detected`）单列 **6 passed**。

### Findings

本轮新发现：**0 条**（0 critical / 0 important / 0 minor）；`t078_code_f005` 起无编号（连续第三轮零发现）。R5 仅字面量→helper 替换，未引入新缺陷；零发现合法，不为凑数制造 finding。

### 结论

- 前轮 finding 复核：f001（important）/ f002 / f003 / f004（minor）维持已消除、未回退；`t078_test_f006` 维持已修；R1/R2 系统性项与 test 轴 R1 五条状态延续、无悬空。详见上方六条。
- R4→R5 增量：**仅 `tests/scripts/test_check_doc_sensitive.py` 字面量→helper 替换，其余 8 条交付路径逐字节一致、生产脚本无回退**（指纹反演精确复现 R4 指纹）。
- 本轮新发现：0 条（`t078_code_f005` 起无编号）。
- 本轮判定（PASS / FAIL / INCOMPLETE）：**PASS**（code 轴 verdict）。`reviewed_scope=e8cc9501ce3231ae` 与权威复算的当前 worktree 指纹一致；写报告不改指纹。
- 未进表的提示：
    - 文件过大（降级规则，仅列路径与行数）：`scripts/check_doc_sensitive.py` 706 行、`tests/scripts/test_check_doc_sensitive.py` 851 行（手写脚本 400/800、测试源码 600/1200，命中 minor 未达 important，本轮净增 21 行 helper 块）；`scripts/check_dep_locks.py` 190 行、`tests/scripts/test_check_dep_locks.py` 150 行未超阈值，未使任何文件越过新档。
    - 圈复杂度：`scan_file`（`scripts/check_doc_sensitive.py`）本就多分支，按规则不进表。
    - 代码/文档一致性：helper docstring 明确说明「运行时拼接出的完整路径仍是真实被测形态」并解释隐私门禁误判背景，与实现一致；无过时注释残留。
    - 安全/语义边界（spec 已批准）：散文/表格/代码引用示例不报、归档整体排除、`TOKEN_RE` / `PRIVATE_KEY_RE` 整行拦截、`ASSIGN_RE` default-deny 未削弱（敏感扫描 32 文件 0 违规）。
    - `docs/handoff.md` 被 `ARCHIVE_FILES` 与 `.sensitive_ignore` 排除，其中真凭据目录扫描不覆盖，属 AC-001 授权排除项。
    - 行号漂移：spec「依赖与约束」记 `tests/scripts/test_check_dep_locks.py:55` 硬编码字面量；实际在 `:48`/`:32`（R4 已记），`test_build_sidecar_script_includes_gate`（`:46`）有效，非行为偏差，不进表。
    - 残留双套归档判定（`--ignore-archived-errata` 旧机制）：t078 前既有、R1 已列未进表、本轮未触及、非 regression。
- 剩余风险（如实披露，均不阻断）：
    - ① 工具链配置缺陷（按 CLAUDE.md「先自行绕过、任务结束后将配置 bug 和任务结果一同报告」）：`repo_task/privacy.py::find_developer_path_leaks` 无法区分测试 fixture 里故意构造的合成用户路径与真实开发者家目录泄漏，R4 交付被 finish 误判为家目录泄漏；本轮以 helper 运行时拼接绕过、未改 `.repo_template`。**须在任务结束后报告用户决定，不静默处理**；不改模板工具链、不作本轴 finding（范围外工具链缺陷）。
    - ② 环境标记（`;`）需求：状态延续（R2/R3/R4 剩余风险①），当前 `requirements-mail-core.txt` 9 行无 marker、spec 非范围明确「不升级约束写法」，不触发；方向为「拒绝」而非放行违规。若未来引入带 marker 生产依赖，需先在 `;` 处剥离。
    - ③ 裸 `python3`（无 venv/无 packaging）`--check` 本轮实测 rc=2 fail-closed（R2/R3/R4 状态延续）：canonical 门禁入口全落 `.venv/bin/python`（packaging 26.3）；ad-hoc 裸 `python3` 复跑与 `PY=python3` 兜底分支会 rc=2 并在 `:20` 以「Dependency lock mismatch」误导性报错中止，该兜底路径同样缺 PyInstaller、构建本就无法成功。
    - ④ 门禁证据中模板契约 463 / 前端 586+ 全链 / 桌面单测 / 后端 unit 1661 passed 0 failed 四项未由本 reviewer 独立重跑，按 trust_prior 披露（见 AC-005；未跑 PG 门禁按用户指示）。
    - ⑤ 跨轴 rollup（非本轴结论）：`review-status` 当前 `overall=INCOMPLETE` / `next_action=rerender_review` / `round=4`，唯一原因是 R5 改交付后指纹 stale、两轴 R5 报告与处置表/轮次上限待收尾；本轴写入 R5 后 `reviewed_scope` 与当前一致。属 implementer 收尾，非 code 轴 verdict 翻转。
- 总体判断：R5 唯一改动经指纹反演证明仅测试文件字面量→helper 替换、生产脚本逐字节未变；helper 拼接产物仍是 `USER_PATH_RE` / `WIN_USER_PATH_RE` 的真实被测形态、断言未弱化、50 passed 与 6 passed 佐证；隐私门禁 0 findings 已过；R1-R4 全部 finding 处置维持有效、无回退；AC-001~AC-006 实现层打勾全部成立、无未解决 critical / important。按判定式 **verdict: PASS**。
- 系统性 follow-up：无等价 dep-lock / PEP440 follow-up（沿用 R2-R4 只读 `task.py list` 结论）；工具链缺陷（privacy 误判合成测试路径）按 ① 报告用户、不改模板、不作本轴 finding。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。归档排除（`ARCHIVE_DIR_PREFIXES`:595 / `ARCHIVE_FILES`:603 / `collect_target_files`:614）与 `.sensitive_ignore` 修正自 R4 起逐字节未变（反演证明）；`python3 scripts/check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；`test_repo_docs_gate_passes`（`:164`）、`test_archive_directories_excluded_from_docs_scan`（`:813`）、`test_explicit_archived_file_target_is_still_scanned`（`:843`）在 50 passed 内。
- AC-002：TICK-VALID，re_verified。值形态模型 `_value_spans`（`:290`）+ `:315-318` 仅空回退、`USER_PATH_RE`（`:71`）/ `WIN_USER_PATH_RE`（`:75`）仅值区间（`:481`/`:494`）、高危签名全文（`:510`/`:520`）、`ASSIGN_RE` default-deny（`:544-563`）逐行未改；helper 运行时拼接产物仍以值形态触发 PATH 拦截（6 passed）；`test_publish_face_prose_examples_are_not_values`（`:773`）在 50 passed 内；全仓敏感扫描 0 违规。
- AC-003：TICK-VALID，re_verified。`verify_lock_offline`（`scripts/check_dep_locks.py:75`）无 subprocess / 网络、`main --check`（`:176-185`）不调 `run_compile`；`.venv/bin/python ... --check` 输出 `OK: ... is synchronized ...` rc=0、裸 `python3 --check` rc=2 fail-closed；`git diff` 未含 lock/txt；`scripts/build-sidecar.sh:20`、`tests/scripts/test_check_dep_locks.py:48`/`:32` 字面量有效；生成模式保留。生产脚本自 R3 起逐字节未变（反演证明）。
- AC-004：TICK-VALID，re_verified。50 passed 含 `test_publish_face_true_positives_still_detected`（`:791`，5 类各自独立文件 + `count == 1`）、`test_publish_face_prose_examples_are_not_values`（`:773`）、`test_archive_directories_excluded_from_docs_scan`（`:813`）、`test_explicit_archived_file_target_is_still_scanned`（`:843`）、`test_check_rejects_lock_missing_hash`、`test_lock_below_declared_floor_rejected`、`test_compound_constraint_upper_bound_enforced`；6 个 helper 相关用例单列 6 passed；真泄漏拦截能力未削弱、断言未弱化。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 基线/规范/历史快照 diff 在 R1-R4 已逐行核对、本轮反演证明该路径逐字节未变；`## test_cmd` 第 4 项 `python3 ... docs --check` 本 reviewer 已独立复跑 0 违规；其余三项（模板契约 463、前端 586+ 全链、桌面单测）与后端 unit 1661 passed 0 failed 依用户门禁证据、本 reviewer 未独立重跑（按指示不跑 PG 门禁、前端全链成本高），如实披露 trust_prior。
- AC-006：TICK-VALID，re_verified。`docs/pending/p077_...` front matter `status=closed` / `resolution=resolved` / `fix_ref=t078`、`docs/specs/testing_quality.md` `tasks: [t013, t014, t078]` 在 R1-R4 已核对、本轮未触及；diff 未新增 pending / finding / spike 等遗留项。

coverage = 5 / 6

verdict: PASS
