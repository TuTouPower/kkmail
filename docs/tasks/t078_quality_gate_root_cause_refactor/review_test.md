# Task review t078（reviewer_focus: 测试）

- task：`t078_quality_gate_root_cause_refactor`
- spec：`docs/tasks/t078_quality_gate_root_cause_refactor/task.md`
- diff_anchor：`b2050e33b7aa30ec21616936659002a4c77331f6`
- target：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`
- round：1
- reviewed_at：2026-11-12T16:35:02+08:00

reviewed_scope: 6bcaa2fd7152a3b9

## Findings

### t078_test_f001 - 发布面 true-positive 硬门禁用聚合存在性断言，无法证明 ghp\_ token / 私钥 / 口令逐类拦截未削弱

- 严重度：important
- 锚点：AC-004（「负向 true-positive 回归是硬门禁，必须证明拦截能力不降」）；spec「风险与回退」节
- 位置：`tests/scripts/test_check_doc_sensitive.py:769`（`test_publish_face_true_positives_still_detected`），断言 `:785-787`
- 问题：fixture 含 5 类真泄漏（个人邮箱 / DB_PASSWORD 赋值 / 用户路径 / 私钥头 / `ghp_` token），但断言仅 `assert proc.returncode != 0` 加 `for category in ("EMAIL","CREDENTIAL","PATH"): assert category in proc.stderr`。口令赋值、私钥头、`ghp_` token 三者全部只产出 `CREDENTIAL` 类，任意一条存活即满足该循环；`stderr.count` / 行号 / 逐类 `matched_text` 均未断言。独立探针复现：把 fixture 中私钥头与 `ghp_` token 两行删去（仅留邮箱/口令/路径），同一断言仍 `returncode=1` 且 EMAIL/CREDENTIAL/PATH 全命中 → 测试照常 PASS。即 `TOKEN_RE` 的 `ghp_` 分支或 `PRIVATE_KEY_RE` 整行拦截被删除时本用例无法报警；`ghp_` 在其余用例中无覆盖（`test_credential_signatures_detected_with_redacted_output` 用的是 `sk-proj-` 分支）。AC-004 点名的「`ghp_` token 仍被拦截」因此缺少有效断言。另 `assert proc.returncode != 0` 把误判为「无文件/参数错误」的 returncode 2 也算通过，弱于 `== 1`。
- 建议：改为逐类/逐行断言，例如 `assert proc.stderr.count("[CREDENTIAL]") == 3` 并核对 3 条 CREDENTIAL 的行号（口令/私钥/token 各一行），或像 `test_credential_signatures_detected_with_redacted_output` 那样拆成每类独立 case；`!= 0` 收紧为 `== 1`。

### t078_test_f002 - 缺 hash 用例被「直接依赖未固定」噪声污染，无法证明 hash 完整性校验生效

- 严重度：important
- 锚点：AC-003（「验证 lock 每行 `pkg==version --hash=sha256:...` 格式完整、覆盖 .txt 的直接依赖且版本满足其约束」）、AC-004（「能力不削弱」）
- 位置：`tests/scripts/test_check_dep_locks.py:93-101`（`test_check_rejects_lock_missing_hash`），断言 `:101`
- 问题：`broken.write_text("fastapi==0.162.2\n")` 只固定了 `.txt` 9 个直接依赖中的 1 个；`verify_lock_offline` 对该 fixture 返回 9 条错误：1 条 `has no sha256 hash` + 8 条 `is not pinned`。断言仅 `assert module.main() != 0`，不区分错误来源。独立探针复现：即使删去 `verify_lock_offline` 的 hash 校验分支（`scripts/check_dep_locks.py:117-119`），剩余 8 条「未固定」错误仍使 `main()` 返回 1，本用例照样 PASS → hash 完整性校验是否被实现/保留，本用例无法证明。此外 AC-003 声明的第三类校验「版本满足 `>=` 约束」完全没有负向用例（无低于 `fastapi>=0.115.0` 下界的 lock fixture），直接依赖覆盖也仅被噪声间接带过。三类校验只有 1 个负向用例且归因混淆。
- 建议：让 fixture 覆盖全部 9 个直接依赖且均带 hash，仅人为去掉其中一行的 `--hash=`，使 `main()!=0` 只能由 hash 分支产生；或断言 stderr 含 `has no sha256 hash` 且 `main() == 1`。另补一个版本下界 fixture（如 `fastapi==0.100.0`）断言被拒，覆盖 AC-003 的约束校验分支。

### t078_test_f003 - 改输入后 `test_personal_email_detected_with_redacted_output` 的脱敏断言失效（恒真）

- 严重度：minor
- 锚点：行为缺陷（改输入疏漏）；TDD 铁律「7 个改输入用例断言不变且有效」之自述
- 位置：`tests/scripts/test_check_doc_sensitive.py:324-334`，fixture `:328`、断言 `:334`
- 问题：输入由 `alice_developer@gmail.com` 改为 `CONTACT=alice_developer@personal-mail.com`，但断言仍是 `assert "alice_developer@gmail.com" not in proc.stderr`。独立探针：该文档 stderr 只有 `文件名:3 [EMAIL]`（redact 不回显任何值），`alice_developer@gmail.com` 从未出现在输入或输出中，断言恒为真、不提供任何证据。其余 6 个改输入用例的脱敏断言都与新输入值一致（邮箱、macOS/Linux/Windows 用户路径、口令长度），仅此一例脱节。拦截断言（`returncode == 1`、`[EMAIL]` 存在）仍有效，脱敏契约另有 `test_redact_output_is_only_category_file_line` 等覆盖，故不阻断；但「7 个改输入用例断言（真泄漏仍被拦截 + 脱敏输出）不变且有效」的自述不成立 1 例。非「就地改预期制造假绿」（断言文本未改、且非 AC 唯一证据），按测试结构清理定 minor。
- 建议：把 `:334` 改为 `assert "alice_developer@personal-mail.com" not in proc.stderr`，使脱敏断言重新指向实际泄漏值。

### t078_test_f004 - 「模拟上游版本发版不触发漂移 / --check 不联网」缺显式用例，离线证明口径偏窄

- 严重度：minor
- 锚点：AC-003（「模拟上游版本发版不触发漂移」「不联网」）、AC-004（「上游版本变化不影响 --check 结果」）
- 位置：`tests/scripts/test_check_dep_locks.py:80-90`（`test_check_is_offline_no_recompile`）
- 问题：该用例只把模块内部函数 `run_compile` monkeypatch 成抛错并断言 `main() == 0`。这能证明 `--check` 未走 `uv pip compile` 生成分支（生产 `verify_lock_offline` 经查为纯 `read_text` + 正则，本身不联网，离线结论成立），但 tripwire 只覆盖 `run_compile` 这一个内部函数，未下沉到 `subprocess.run` / socket 系统边界；若 `verify_lock_offline` 内另增直连网络调用，用例不会失败。AC-003/AC-004 明文要求的「模拟上游版本发版」同样没有任何 mock 上游索引/版本变化的用例，仅靠上述结构性推断。属可选覆盖扩展，不阻断。
- 建议：补一个显式上游漂移用例（monkeypatch 解析结果为更高版本，断言 `--check` 仍 0），并将 tripwire 改为对 `subprocess.run` 抛错，使「不联网」由系统边界证据支撑。

### t078_test_f005 - 归档显式文件 target 仍扫描的行为随旧用例删除后无回归覆盖

- 严重度：minor
- 锚点：AC-001 相邻行为；`docs/blueprint/testing.md:83` 明确保留「显式指定单个归档文件作为 target 时仍扫描，供人工核查」
- 位置：`tests/scripts/test_check_doc_sensitive.py:790-803`（`test_archive_directories_excluded_from_docs_scan`）；删除的 `test_archived_errata_cannot_hide_sensitive_line` / `test_archived_errata_precision_line_exemption`
- 问题：归档分流只改 `collect_target_files` 的 `elif target.is_dir()` 分支（`scripts/check_doc_sensitive.py:619-622`），`if target.is_file(): collected.append(target)`（`:617-618`）未加归档判断 → 既有显式文件 target 用例不受误伤，46 passed 中全部保留用例仍通过，本项确认无误伤。但被删的两个 errata 用例原先是唯一以 `docs/archive/**` 下单个文件作 target 并断言扫描生效的用例；新语义下没有任何用例对归档路径下的显式文件 target 断言「值形态真泄漏仍被拦截」。blueprint 保留该行为却无回归测试，未来若在 file 分支误加归档排除将无用例报警。属可选覆盖扩展，不阻断。
- 建议：补一例，将 `docs/reviews/**` 或 `docs/archive/**` 下含值形态泄漏的单文件作为显式 target，断言 `returncode == 1` 且对应 `[EMAIL]` / `[PATH]` 命中。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 改测方向复核：无「迁就实现」的就地改预期。7 处改输入均为规格变更（散文/表格/代码引用 → 值形态）驱动，断言文本未改；4 个旧语义用例（`test_inline_allow_exempts_only_nearest_match`、`test_archived_errata_cannot_hide_sensitive_line`、`test_archived_errata_precision_line_exemption`、`test_comment_start_does_not_exempt_real_path`）整体删除，理由已写入模块 docstring（`tests/scripts/test_check_doc_sensitive.py:8-15`：整体删除而非把预期迁就新输出），符合 TDD 铁律。但新增的 `test_publish_face_true_positives_still_detected` 采用聚合存在性断言，强度不足以承担 AC-004 硬门禁（f001），另 1 例改输入遗留恒真脱敏断言（f003）。
- 本轮新发现：5 条（important 2 / minor 3）。
- 危险模式扫描：4 个删除用例经调查为合法（spec 语义变更 + 写明理由），不按「语法命中」出 finding；无 `.skip` / `.only` / `xfail` / `type: ignore` / 注释掉断言 / 反转 expect / mock 掉被测逻辑（两个新 lock 用例均真实调用 `main()` / `verify_lock_offline`）。命中项：f001（聚合存在性断言、弱化 `!= 0`）、f002（`!= 0` 弱化 + 噪声污染）、f003（恒真断言，但非 AC 唯一证据，按结构清理定 minor）。
- 测试可信与现有覆盖：两个新 lock 用例与 4 个 `test_publish_face_*` 均经 `run_checker` 子进程或真实 `main()` 触达生产脚本，非 mock 凑数；独立复跑 `tests/scripts` 共 46 passed（39 + 7），无失败/跳过；`check_doc_sensitive.py docs --check` 报 32 文件 0 违规（rc=0）、`check_dep_locks.py --check` rc=0；`requirements-mail-core.lock` 与 `scripts/build-sidecar.sh` 不在 diff 内（内容/调用字面量未变）。归档分流未误伤既有显式文件 target 用例（见 f005）。
- 未进表的提示：①`## test_cmd` 四项中，敏感扫描一项已由 reviewer 复跑，模板契约 / 前端全链 / 桌面单测三项依赖用户提供的门禁证据与 progress.md 自述，未独立复跑（见 AC-005 的 trust_prior）。②AC-002「PRIVATE_KEY_RE 全文拦截」缺「私钥头出现在散文行」的专门用例（token 的全文拦截已由 `test_credential_signatures_detected_with_redacted_output` 的 `sk-proj-` 散文行覆盖），属可选扩展。③范围外（code reviewer 职责）：`_value_spans` 对无空格赋值行同时把 RHS 与整行计入值区间，单行 `CONTACT=...` 会产出 2 条 `[EMAIL]`；本轮相关断言均为存在性检查，不受影响。④`tests/scripts/test_check_dep_locks.py:23-28` 注释仍称 `--check` 会 shell out 到 `uv`，与新离线实现不符，属注释清理。
- 总体判断：FAIL。AC-004 硬门禁的核心负向回归用例（f001）与 AC-003 的 hash 完整性负向用例（f002）均为聚合/被污染的弱断言，删除 `ghp_` / 私钥检测或删去 hash 校验分支都能让用例继续全绿；两项打勾缺少可信测试支撑，须修复并重验后再审。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_archive_directories_excluded_from_docs_scan` 实证归档目录不进 docs 目标（且 guides 文件仍在目标内，否则会 returncode 2）；复跑 `check_doc_sensitive.py docs --check` 报 32 文件 0 违规（rc=0）、46 passed 中 `test_repo_docs_gate_passes` 通过；`.sensitive_ignore` diff 修正为真实归档路径。
- AC-002：TICK-VALID，re_verified。`test_publish_face_prose_examples_are_not_values` + `test_normal_document_passes` / `test_prose_assignments_not_flagged_via_cli` 证散文/表格/代码引用不报；7 个值形态改输入用例与 `test_credential_signatures_detected_with_redacted_output`（`sk-proj-` 散文行、私钥头）证值形态与高危签名仍拦；ASSIGN_RE default-deny 由 A17/A19/A22 系列用例覆盖。
- AC-003：TICK-VOID，re_verified。`test_check_is_offline_no_recompile` 与复跑 `check_dep_locks.py --check`（rc=0）证实离线、生成分支未入、lock 内容未变、sidecar 字面量有效；但 AC 声明的三类校验（hash 完整 / 直接依赖覆盖 / `>=` 版本约束）唯一负向用例 `test_check_rejects_lock_missing_hash` 被 8 条「未固定」噪声污染，探针证明删去 hash 校验分支后仍 PASS，版本下界分支完全无负向用例 → 打勾证据不足。
- AC-004：TICK-VOID，re_verified。散文不报、归档排除、上游漂移经离线结构推断均有覆盖；但点名的 `ghp_` token / 私钥 / 口令「仍被拦截」只由 `test_publish_face_true_positives_still_detected` 的聚合类别断言支撑，探针证明删去 token 与私钥两行后该断言仍 PASS，`ghp_` 在别处无有效断言 → 硬门禁证据不足。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的 `verification_notes` / 敏感扫描规范 / 历史快照标注经 diff 复验；`## test_cmd` 四项中敏感扫描已复跑通过，模板契约、前端全链、桌面单测三项依赖用户提供的「四项全绿」门禁证据与实施侧结果，未独立复跑。
- AC-006：TICK-VALID，re_verified。diff 中 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 为 `status=closed / resolution=resolved / fix_ref=t078`，`docs/specs/testing_quality.md` front matter `tasks` 含 `t078`，未见新增遗留项。

coverage = 5/6

verdict: FAIL

## Round 2 (2026-11-12T17:05:12+08:00)

reviewed_scope: 4e9c7b3e39a3b9ce

- 落点仓库校验：通过（不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于目标 worktree 根）。
- 指纹核对：本小节按重新渲染的 Round 2 模板整行照抄本轮指纹；独立复算 `monitoring.review_scope_fingerprint`（相对 `diff_anchor` 的完整 worktree 变化，排除 review 流程文件）当前值 = `4e9c7b3e39a3b9ce`，与本轮声明一致，本报告 PASS 有效性锚点成立。`task.py review-status` 的 `review_scope=stale` 来自另一轴 `review_code.md` 仍为 R1 指纹（`6bcaa2fd7152a3b9`）/ `verdict: FAIL`，非本报告问题（本报告 `test_verdict=PASS`、`ac_review=ok`、`privacy_review=ok`、`round=2`）；code 轴 Round 2 由 code reviewer 独立完成后该 stale 才消除。读 prompt / 读 R1 报告 / 读 diff / 定点单测后 `git status --short` 无新增未跟踪交付文件（仅 11 个 `M` 交付文件 + 2 份 review 报告），未引入指纹漂移。
- 审查对象：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（完整 diff，非 `...HEAD`）。
- 独立复跑：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/scripts/test_check_doc_sensitive.py tests/scripts/test_check_dep_locks.py -q` → **49 passed**；`python3 scripts/check_doc_sensitive.py docs --check` → `PASSED: Checked 32 file(s)` rc=0；`.venv/bin/python scripts/check_dep_locks.py --check` → `OK: ... is synchronized` rc=0。

### Findings（本轮新发现：0 条）

本轮无新 finding，编号 `t078_test_f006` 起预留未使用。clean review，不凑数。

### 前轮 finding 复核（Round 1，5 条，以 diff 为准，不采信处置表自称「已修」）

#### t078_test_f001 - important｜AC-004 — 已消除（真修，非换形式弱化）

- 现状 `tests/scripts/test_check_doc_sensitive.py:770-789`：`test_publish_face_true_positives_still_detected` 改为 5 类各自独立文件（email / password / path / private_key / token），每类单独跑 `run_checker`（真实 CLI 子进程），断言 `proc.returncode != 0` 且 `proc.stderr.count(f"[{category}]") == 1` 精确计数。
- 独立探针（脚本副本置于系统临时目录、内存改模块，不改 worktree）：逐类禁用 `EMAIL_RE` / `CREDENTIAL_KEYWORDS` / `USER_PATH_RE` / `PRIVATE_KEY_RE` / `TOKEN_RE`，5 类 `[CATEGORY]` 命中数全部由 `1 → 0`，对应子断言必红。逐类基线均 `rc=1, count=1`。
- 题目点名的形态差异经 `_value_spans` 探针确认：`private_key.md`（`-----BEGIN RSA PRIVATE KEY-----`）`_value_spans=[]`，纯靠 `PRIVATE_KEY_RE.search(line)` 全文拦截（`scripts/check_doc_sensitive.py:510`）；`token.md`（`ghp_` + 36 字符）靠 `TOKEN_RE.search(line)` 全文拦截（`:520`）；`path.md` / `email.md` 的 `_value_spans` 非空（分别为宿主用户路径裸值行、个人邮箱赋值 RHS，`alice@personal-mail.com`），靠值形态分支（`:460-505`）。R1 指出「`ghp_` 在其余用例无有效断言」，现由独立文件 + 精确计数覆盖，删 `TOKEN_RE` 必红。
- R1 附带建议「`!= 0` 收紧为 `== 1`」未字面采纳（仍 `!= 0`，`:788`），但每类 `count == 1` 兜底：returncode=2（参数/无文件错误）时 stderr 不含 `[CATEGORY]`，`count == 1` 必失败，不构成假绿路径。判「已消除」而非「修不彻底」；`!= 0` 收紧列入可选清理（未进表提示 5）。

#### t078_test_f002 - important｜AC-003 / AC-004 — 已消除

- 现状 `tests/scripts/test_check_dep_locks.py:93-120`：从真实 lock 复制，`pin_idx` 定位首包 `alembic==1.20.1 \`，`while` 删去其**全部** `--hash=` 续行，其余 9 个直接依赖仍固定且带 hash；断言 `any("has no sha256 hash" in e for e in errors)` 精确归因，另有 `main() != 0` 端到端（monkeypatch `LOCK_FILE` / `sys.argv`）。
- 独立探针：删续行数为 2；`verify_lock_offline(broken, TXT_FILE)` 返回且**仅**返回 `['broken.lock: alembic==1.20.1 has no sha256 hash']`（R1 的 8 条 `is not pinned` 噪声已消除）。移除生产 `verify_lock_offline` 的 hash 校验分支（`scripts/check_dep_locks.py:120-122`）后 errors=`[]`，`has no sha256 hash` 不可断言 → 用例必红。证明触达生产逻辑、归因唯一、非恒真。
- 新增 `test_lock_below_declared_floor_rejected`（`:133`）：`fastapi==0.100.0 < >=0.115.0`（`requirements-mail-core.txt:2`）→ 探针确认 `['below.lock: fastapi==0.100.0 does not satisfy >=0.115.0']`，精确覆盖版本约束分支。三类校验现有 2 个精确负向 + 1 个正向（older lock）+ 1 个离线 tripwire，R1 的假绿根因已消除。

#### t078_test_f003 - minor — 已消除

- 现状 `tests/scripts/test_check_doc_sensitive.py:324-335`：脱敏断言改为 `"alice_developer@personal-mail.com" not in proc.stderr` 并新增 `assert "@" not in proc.stderr`；输入同为 `CONTACT=alice_developer@personal-mail.com`（`:328`），新邮箱真实出现在输入中，`@` 锚使任何邮箱形态回显都失败。`redact()`（`scripts/check_doc_sensitive.py:202-207`）输出仅 `leak_email.md:3 [EMAIL]` 不含 `@`，49 passed 中该用例通过 → 恒真已消除，且方向为增强断言。

#### t078_test_f004 - minor — 已消除（核心），可选扩展未采纳

- 新增 `test_upstream_release_does_not_invalidate_older_lock`（`:122-130`）：真实 lock `fastapi==0.162.2` 经 `re.sub` 降为 `0.115.0`（满足 `>=0.115.0` 下界），断言 `verify_lock_offline(older_lock, TXT_FILE) == []`；探针确认返回 `[]`。旧实现（与当下最新 compile 结果逐字节比对）下任何非最新 lock 必失败，故该用例能区分新旧实现、非恒真，显式覆盖 AC-003 / AC-004「上游版本变化不影响 `--check`」。
- R1 建议第二半「把 tripwire 从 `run_compile` 下沉到 `subprocess.run` / socket 系统边界」未采纳（`test_check_is_offline_no_recompile` `:81` 仍 monkeypatch `run_compile`）。核查 `verify_lock_offline`（`scripts/check_dep_locks.py:75-141`）为纯 `read_text` + 正则 + `SpecifierSet`，`main()` 的 `--check` 分支（`:176-186`）只调它，离线结论有代码证据 + `--check` rc=0 支撑。属 R1 已认定的非阻断可选扩展，不另出 finding。

#### t078_test_f005 - minor — 已消除

- 新增 `test_explicit_archived_file_target_is_still_scanned`（`:822-830`）：`docs/reviews/review_x/leak.md` 含值形态 `CONTACT=alice@personal-mail.com`，显式文件 target + `--root tmp_path`，断言 `returncode == 1` 且 `[EMAIL]` 命中。`collect_target_files`（`scripts/check_doc_sensitive.py:621-626`）的 `if target.is_file(): collected.append(target)` 分支不做归档判断（排除仅在 `elif target.is_dir()` 分支），故扫描生效；若未来在 file 分支误加归档排除，`target_files` 为空 → `main()` 返回 2 → `returncode == 1` 断言失败 → 必红。R1 指出的回归缺口已补。

### 改测方向复核与 TDD 铁律（独立复核，不采信自述）

- 删除的 4 个旧用例（`test_inline_allow_exempts_only_nearest_match`、`test_archived_errata_cannot_hide_sensitive_line`、`test_archived_errata_precision_line_exemption`、`test_comment_start_does_not_exempt_real_path`）在 diff 中为整体删除（全 `-` 行），理由写入 `tests/scripts/test_check_doc_sensitive.py:8-15` 模块 docstring（"removed wholesale rather than having their expectations nudged to the new output"）；语义变更由 spec（散文 → 值形态）驱动，属合法删除，不按语法命中出 finding。
- 7 个改输入用例的断言**语义**（真泄漏仍被拦截 + 脱敏不回显）全部未变。独立核对后不照收 progress.md「7 个断言不变」字面自述：其中 5 处断言文本完全未动，2 处脱敏断言字符串随输入同步更新——`test_personal_email...`（f003 修恒真断言，旧值 → 新值 + `@` 锚）与 `test_credential_signatures...` 的 pwdlen case（`secret` 随 content 从 `口令长 16 位` 改 `口令长16位`）。两处方向均为「让断言指向实际输入值以增强有效性」，非「迁就当前实现输出」，不违反 TDD 铁律。
- 无就地把旧测试预期改成新实现输出（无「应报」改「不报」的反转、无删 expect、无注释掉断言）；新增用例均为新增断言；`test_publish_face_true_positives_still_detected` 由聚合存在性改为逐类精确计数，是**增强**而非弱化。
- 无 mock 掉被测逻辑：doc 侧 `run_checker`（`:29-31`）跑真实 CLI 子进程；lock 侧 `_load_dep_module`（`:68-78`）从真实脚本路径 importlib 加载，真实调用 `verify_lock_offline` / `main()`；仅 monkeypatch `run_compile`（生成分支 tripwire）、`LOCK_FILE` / `sys.argv`（fixture 注入），均在系统边界，不 mock 被测实现本身。

### 危险模式扫描（逐条调查后判定，非语法命中）

全量 grep 两个测试文件：命中 4 处 `# noqa: sensitive` 均为 allow-marker **fixture 输入文本**（用于测合法例外），非 `# type: ignore` / `eslint-disable` / `@SuppressWarnings`。无 `.skip` / `.only` / `xfail` / `pytest.mark.skip` / 恒真 `assert True` / 纯存在性断言作 AC 证据 / 删除或反转 expect / 注释掉断言 / 弱化断言（本轮方向为增强）/ 条件跳过弱化 / 阈值（timeout / 重试 / 容差）增大 / 静默错误 / mock 关键副作用或被测逻辑 / 存在即通过。R1 的 f001（聚合 + `!= 0`）、f002（`!= 0` + 噪声污染）、f003（恒真）三类命中均已按上述复核消除。

### 结论

- 前轮 finding 复核：f001 已消除、f002 已消除、f003 已消除、f004 已消除（核心）且可选扩展未采纳、f005 已消除；无「换形式弱化」——f001 由聚合存在性改为逐类精确计数（增强并附探针证据），f003 由恒真改为有效且更严断言，f002 由噪声污染改为唯一归因 + 精确错误串。两条 important（f001 / f002）以 diff + 独立探针核实真修，不采信处置表自称。
- 改测方向复核：无「迁就实现」的就地改预期。7 处改输入为规格变更驱动；2 处脱敏断言值同步更新与 4 个旧用例整体删除均为合法配套处理，已写明理由。
- 本轮新发现：0 条（critical 0 / important 0 / minor 0）。
- 危险模式扫描：无新增命中；4 个删除用例经调查合法，不按语法命中出 finding。
- 测试可信与覆盖：两个脚本的测试均经真实 CLI 子进程或真实 `verify_lock_offline` / `main()` 触达生产实现；49 相关测试全绿；两条 CLI 门禁独立复跑 rc=0；`requirements-mail-core.lock` 与 `scripts/build-sidecar.sh` 不在 diff；生成模式 `if not args.check:`（`scripts/check_dep_locks.py:153-170`）完整保留；负向 true-positive 充分（逐类删检测必红 + 缺 hash / 低于下界两个精确负向）。门禁证据中 `tests/scripts` 202 passed、后端 unit 1661 passed 0 failed、`## test_cmd` 四项全绿，除上述定点复跑外依赖用户提供证据，按任务约束未运行 PG 门禁与前端 / 桌面 / 模板全链。
- 未进表的提示（覆盖缺口 / 可选扩展，均 minor 级、不阻断，按 prompt「可以再加 case」不进 finding 表）：
    1. AC-005 `## test_cmd` 四项中，敏感扫描已复跑；模板契约、前端全链、桌面单测三项依赖用户门禁证据与 progress.md 自述，未独立复跑（trust_prior）。
    2. 三类校验中「直接依赖覆盖（`is not pinned` 分支）」仍无独立负向用例（f002 修复聚焦 hash 完整 + 版本约束），属「可再加一个 case」。
    3. `test_check_is_offline_no_recompile` 的 tripwire 仍锁定 `run_compile`，未下沉 `subprocess.run` / socket 系统边界（R1 f004 第二半建议未采纳）；离线结论由代码结构 + rc=0 支撑。
    4. AC-002「`PRIVATE_KEY_RE` 全文拦截」缺「私钥头内嵌于散文行」专门用例（R1 未进表提示②沿用）；`TOKEN_RE` 全文拦截已由 `test_credential_signatures_detected_with_redacted_output` 的 `api token: sk-proj-...` 散文行覆盖。
    5. `test_publish_face_true_positives_still_detected` 的 `!= 0` 未收紧为 `== 1`（R1 f001 附带建议），已由逐类 `count == 1` 兜底，属可选清理。
    6. `tests/scripts/test_check_dep_locks.py:24-29` 注释仍称 `--check` 会 shell out 到 `uv`，与新离线实现不符（R1 未进表提示④沿用），属注释清理。
    7. 范围外（code reviewer 轴）：`_value_spans` / `SpecifierSet` 等实现层质量由 `review_code.md` 独立判定，本报告不评；本报告 verdict 仅判定测试轴（「verdict 判定（仅本报告）」）。
- 总体判断：PASS。R1 两条 important 假绿根因（发布面聚合断言、缺 hash 噪声污染）经本轮 diff + 独立探针核实已真修，3 条 minor 均落地；本轮无未解决 critical / important；6 条 AC 全部 TICK-VALID；49 相关测试全绿、负向 true-positive 充分。「PASS/FAIL/INCOMPLETE」结论：PASS（测试轴）。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`.sensitive_ignore` diff 修正为 6 类真实归档路径 + `docs/handoff.md`；`test_archive_directories_excluded_from_docs_scan`（`:792`）与 `test_explicit_archived_file_target_is_still_scanned`（`:822`）分别覆盖目录排除与显式文件仍扫；复跑 `check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；49 passed 含 `test_repo_docs_gate_passes`（`:164`）。
- AC-002：TICK-VALID，re_verified。`test_publish_face_prose_examples_are_not_values`（`:752`）证散文 / 表格 / 代码引用 / `[REDACTED_EMAIL]` 不报（`returncode == 0`）；7 个值形态改输入用例 + `test_credential_signatures_detected_with_redacted_output`（含 `api token: sk-proj-...` 散文行、私钥头、口令长、凭据）证值形态与 `TOKEN_RE` / `PRIVATE_KEY_RE` 全文拦截仍拦；ASSIGN_RE default-deny 由 A7 / A19 / A22 系列用例覆盖。
- AC-003：TICK-VALID，re_verified。`test_check_is_offline_no_recompile`（`:81`，`run_compile` tripwire）+ `test_check_rejects_lock_missing_hash`（`:93`，探针证删 hash 校验分支必红、唯一 `has no sha256 hash` 错误、无 `is not pinned` 噪声）+ `test_lock_below_declared_floor_rejected`（`:133`）+ `test_upstream_release_does_not_invalidate_older_lock`（`:122`，探针 `[]`）覆盖三类校验与上游漂移；复跑 `--check` rc=0；`requirements-mail-core.lock` / `scripts/build-sidecar.sh` 不在 diff；生成模式 `main():153` 保留；`requirements-dev.txt` 显式声明 `packaging>=23.0`。
- AC-004：TICK-VALID，re_verified。`test_publish_face_true_positives_still_detected`（`:770`）5 类逐类独立文件 + `count == 1`，本轮探针逐类禁用 5 个检测逻辑命中数 `1 → 0` 全部必红（private_key / token 全文拦截、path / email 值形态）；散文不报、归档不扫（`test_archive_directories_excluded_from_docs_scan`）、上游漂移（`test_upstream_release...`）均有独立用例；`ghp_` token 现由独立文件 + 精确计数覆盖。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的 `verification_notes` 当前基线、`:82` 敏感扫描规范改写、历史证据表「历史时点快照」标注经 diff 复验；敏感扫描一项已复跑 rc=0；模板契约、前端全链、桌面单测三项及 `## test_cmd` 四项全绿依赖用户提供的门禁证据与 progress.md 自述，按任务约束未独立复跑（不运行 PG 门禁 / 前端全链 / 桌面单测 / 模板契约）。
- AC-006：TICK-VALID，re_verified。diff 中 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 为 `status=closed / resolution=resolved / fix_ref=t078`；`docs/specs/testing_quality.md` front matter `tasks: [t013, t014, t078]`；progress 处置表 8 条全部「已修」、收尾报告无新增遗留项。

coverage = 5/6

verdict: PASS

## Round 3 (2026-11-12T17:24:17+08:00)

reviewed_scope: 0e1bd51a2b18e0fb

- 落点仓库校验：通过（不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于目标 worktree 根）。
- 指纹核对：本小节整行照抄重新渲染的 Round 3 模板指纹；独立复算 `monitoring.review_scope_fingerprint`（相对 `diff_anchor` 的完整 worktree 变化，排除 review 流程文件）当前值 = `0e1bd51a2b18e0fb`，与本轮声明一致，且与 R2 的 `4e9c7b3e39a3b9ce` 不同（R2→R3 交付新增 `_REQ_RE` 修复与 `test_compound_constraint_upper_bound_enforced`），本轮 PASS 有效性锚点成立。读 prompt / 读 R1·R2 报告 / 读完整 diff / 定点单测 / 独立探针后 `git status --short` 仍为 11 个 `M` 交付文件 + 2 份未跟踪 review 报告，无新增未跟踪交付文件，未引入指纹漂移。
- 审查对象：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（完整 diff，非 `...HEAD`）。本轮交付相对 R2 的增量：`scripts/check_dep_locks.py` 的 `_REQ_RE` 改为捕获完整约束串（`\A(...)(...)?\s*(.*?)\s*\Z`，`:37`），`tests/scripts/test_check_dep_locks.py` 新增 `test_compound_constraint_upper_bound_enforced`（`:145-158`），其余交付文件未变。
- 独立复跑：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/scripts/test_check_doc_sensitive.py tests/scripts/test_check_dep_locks.py -q` → **50 passed**（R2 为 49，新增 1 例），0 failed / 0 skipped。未运行 PG 门禁。

### Findings（本轮新发现：1 条）

#### t078_test_f006 - `test_check_dep_locks.py:24-29` 注释仍称 `--check` shell out 到 `uv`，与离线实现不符

- 严重度：minor
- 锚点：行为缺陷（测试注释过时）；AC-003「`--check` 改为离线自洽校验、不联网、不重解析」相邻
- 位置：`tests/scripts/test_check_dep_locks.py:24-29`（`test_check_dep_locks_script_passes`），配套 `env["PATH"]` 前置 `:30-32`
- 问题：注释称 "The script shells out to a bare `uv`... the script dies with FileNotFoundError('uv') before checking anything"，据此把运行解释器目录前置到 `env["PATH"]`。但当前 `main()` 的 `--check` 分支（`scripts/check_dep_locks.py:172-186`）只调 `verify_lock_offline`（纯 `read_text` + 正则 + `SpecifierSet`）；`uv` / `subprocess` / `run_compile` 仅存在于生成模式分支（`if not args.check`，`:153-170`）。独立复跑 `env PATH=/usr/bin:/bin .venv/bin/python scripts/check_dep_locks.py --check` → `OK: ... is synchronized`，rc=0，证明注释描述的 `FileNotFoundError('uv')` 失败场景已不存在，PATH 前置沦为冗余（无害，该用例仍通过）。R1 未进表提示④、R2 未进表提示 6 已两次记录，本轮按任务要求正式提出。属注释清理，不影响测试可信（该用例仍经真实 CLI 子进程、`--check` rc=0、断言 `synchronized` 在 stdout），按「注释 → minor」定级，不阻断。
- 建议：改写/删除 `:24-29` 注释并移除配套的 `env["PATH"]` 前置（`:30-32`），或改注为「离线 `--check` 不依赖 `uv`，保留显式 PATH 仅为测试环境一致性」。

### 本轮核实项（任务指定，独立复验）

#### 1. `test_compound_constraint_upper_bound_enforced` 恒真/触达验证（独立探针，纯内存 + 系统临时目录，不改 worktree）

- 用例现状（`tests/scripts/test_check_dep_locks.py:145-158`）：`.txt` = `foo>=1.2,<2.0`，lock = `foo==2.5 \` + 合法 `--hash=sha256:` + 64 位 hex，直接调生产 `module.verify_lock_offline(lock, txt)`，断言 `any("does not satisfy" in e for e in errors)`。无平行实现、无 mock 被测逻辑、无 skip。
- 探针 A（当前 R3 正则）：`_REQ_RE` 解析 group(2) = `'>=1.2,<2.0'`，`verify_lock_offline` 返回且仅返回 `['requirements.lock: foo==2.5 does not satisfy >=1.2,<2.0']`，断言 True → 用例绿。hash 被 `_HASH_RE` 正确识别（否则会混入 `has no sha256 hash` 噪声），`foo==2.5` 被 `_PIN_RE` 正确解析，错误唯一归因于约束满足判定（`:132-135` 是全文唯一产生 `does not satisfy` 的分支）。
- 探针 B（把 `_REQ_RE` 改回「截断逗号、只捕获首个 specifier」的旧正则，复刻 code f004 的 bug）：解析 group(2) = `'>=1.2'`，`SpecifierSet(">=1.2").contains("2.5")` = True，`verify_lock_offline` 返回 `[]`，断言 `any("does not satisfy")` = False → **用例必红**。
- 结论：非恒真（绿只能由完整约束判定产生、旧实现必红），确实触达生产逻辑（直接调用 `verify_lock_offline`，探针改生产正则即翻红），能抓住 code f004 的「上界被静默丢弃」缺陷。该用例是 R2 code f004 的有效测试护航。

#### 2. R1/R2 全部处置维持有效 + TDD 铁律 + 50 passed

- 以完整 diff 复核，不采信处置表自称：R1 的 f001（`test_publish_face_true_positives_still_detected` 5 类独立文件 + 逐类 `count == 1`，`tests/scripts/test_check_doc_sensitive.py:770-789`）、f002（`test_check_rejects_lock_missing_hash` 从真实 lock 删全部 hash 续行 + 唯一 `has no sha256 hash` 归因，另 `test_lock_below_declared_floor_rejected`：`:93-142`）、f003（脱敏断言改新邮箱 + `@` 锚，`:334-335`）、f004（`test_upstream_release_does_not_invalidate_older_lock`，`:122-130`）、f005（`test_explicit_archived_file_target_is_still_scanned`，`:822-830`）在 R3 diff 中均维持 R2 修复形态，无回退、无「换形式弱化」。R2 零新 finding。
- TDD 铁律：R3 唯一测试改动 `test_compound_constraint_upper_bound_enforced` 为纯新增（diff 全 `+` 行），无就地把旧测试预期改成新实现输出；4 个旧语义用例仍为整体删除、理由写入 `tests/scripts/test_check_doc_sensitive.py:8-15` docstring；7 个改输入用例断言语义（真泄漏仍拦 + 脱敏不回显）未变。无 mock 掉被测逻辑：doc 侧 `run_checker` 真实 CLI 子进程，lock 侧 `_load_dep_module`（`:69-78`）importlib 加载真实脚本、真实调 `verify_lock_offline`/`main()`，仅 monkeypatch `run_compile`（生成分支 tripwire）、`LOCK_FILE`/`sys.argv`（fixture 注入），均在系统边界。
- 50 passed 已独立复跑（见上）。本轮未改任何生产代码/测试/其它文件、未 git add/commit。

#### 3. `test_check_dep_locks.py:24-29` 注释

- 已过时，正式提出 `t078_test_f006`（minor，见上）。

### 改测方向复核与危险模式扫描

- 改测方向：无「迁就实现」的就地改预期；本轮无既有测试被修改，仅新增 1 例。
- 危险模式逐条扫描（全量 grep 两个测试文件）：无恒真 `assert True` / 纯存在性断言作 AC 证据 / 删除或反转 expect / 注释掉断言 / 弱化断言 / `.skip` / `.only` / `xfail` / `pytest.mark.skip` / `# type: ignore` / `eslint-disable` / 静默错误 / mock 被测逻辑 / 条件跳过弱化断言 / 阈值增大 / 存在即通过。4 处 `# noqa: sensitive` 仍为 allow-marker fixture 输入文本。新增用例断言 `any("does not satisfy" in e for e in errors)` 与 R2 已认可的 `test_lock_below_declared_floor_rejected` 同构，子串精确指向唯一错误类型，探针 B 证其能区分实现，非「`toBe`→`toContain`」式弱化。

### 结论

- 前轮 finding 复核：R1 5 条（f001/f002/f003/f004/f005）在 R3 完整 diff 中全部维持「已消除」形态，无回退、无换形式弱化；R2 零新 finding、其对 R1 的复核结论维持。R2 code 轴 f004 的测试护航经本轮探针核实有效。
- 改测方向复核：无「迁就实现」的就地改预期；本轮纯新增 1 例。
- 本轮新发现：1 条（critical 0 / important 0 / minor 1 = `t078_test_f006` 注释过时）。
- 覆盖缺口（未进表提示 / 剩余，均 minor 级、不阻断，按 prompt「可以再加 case」不进 finding 表）：①AC-005 `## test_cmd` 四项中模板契约、前端全链、桌面单测依赖用户门禁证据与 progress.md 自述，按任务约束未独立复跑（trust_prior）；②「直接依赖覆盖（`is not pinned` 分支）」仍无独立负向用例；③`test_check_is_offline_no_recompile` 的 tripwire 仍锁定 `run_compile`，未下沉 `subprocess.run`/socket 系统边界（离线结论由代码结构 + `--check` rc=0 支撑）；④AC-002「`PRIVATE_KEY_RE` 全文拦截」缺「私钥头内嵌散文行」专门用例（`TOKEN_RE` 全文拦截已由 `test_credential_signatures_detected_with_redacted_output` 的 `sk-proj-` 散文行覆盖）；⑤`test_publish_face_true_positives_still_detected` 的 `!= 0` 未收紧为 `== 1`（已由逐类 `count == 1` 兜底）；⑥范围外（code reviewer 轴）：`_value_spans` / `SpecifierSet` 实现层质量由 `review_code.md` 独立判定，本报告不评。原 R2 未进表提示 6（注释过时）本轮已提升为 `t078_test_f006` 正式 finding，不再列为缺口。
- 总体判断：PASS（测试轴）。R3 新增的 `test_compound_constraint_upper_bound_enforced` 经独立探针证实非恒真、触达生产逻辑、改回旧正则必红；R1/R2 全部处置维持；TDD 铁律成立；50 相关测试全绿；指纹 `0e1bd51a2b18e0fb` 与当前一致。本轮唯一新 finding 为 minor（注释过时），不阻断；6 条 AC 全部 TICK-VALID。「PASS/FAIL/INCOMPLETE」结论：**PASS**。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_archive_directories_excluded_from_docs_scan`（`tests/scripts/test_check_doc_sensitive.py:792`）与 `test_explicit_archived_file_target_is_still_scanned`（`:822`）在 R3 diff 维持；`.sensitive_ignore` diff 仍为 6 类真实归档路径 + `docs/handoff.md`；50 passed 含 `test_repo_docs_gate_passes`；R3 未回退归档分流。
- AC-002：TICK-VALID，re_verified。`test_publish_face_prose_examples_are_not_values`（`:752`）证散文/表格/代码引用/`[REDACTED_EMAIL]` 不报；7 个值形态改输入用例 + `test_credential_signatures_detected_with_redacted_output`（`sk-proj-` 散文行、私钥头、口令长）证值形态与 `TOKEN_RE`/`PRIVATE_KEY_RE` 全文拦截仍拦；ASSIGN_RE default-deny 由 A7/A19/A22 系列覆盖；R3 未回退。
- AC-003：TICK-VALID，re_verified。`test_check_is_offline_no_recompile`（`:81`，`run_compile` tripwire）+ `test_check_rejects_lock_missing_hash`（`:93`，唯一 `has no sha256 hash`）+ `test_lock_below_declared_floor_rejected`（`:133`）+ `test_upstream_release_does_not_invalidate_older_lock`（`:122`）覆盖三类校验与上游漂移；R3 新增 `_REQ_RE` 完整约束捕获（`scripts/check_dep_locks.py:37`）与 `test_compound_constraint_upper_bound_enforced`（`:145`），本轮探针 A/B 证实复合约束上界生效、改回旧正则必红；`env PATH=/usr/bin:/bin ... --check` rc=0 证离线；`requirements-mail-core.lock`/`scripts/build-sidecar.sh` 不在 diff；生成模式 `main():153` 保留。
- AC-004：TICK-VALID，re_verified。`test_publish_face_true_positives_still_detected`（`tests/scripts/test_check_doc_sensitive.py:770`）5 类逐类独立文件 + `count == 1` 维持（R2 探针逐类禁用检测必红），`ghp_` token / 私钥 / 口令逐类有精确断言；散文不报、归档不扫、上游漂移均有独立用例；R3 新增约束上界负向进一步证明拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的 `verification_notes` 当前基线、`:82` 敏感扫描规范改写、历史证据表「历史时点快照」标注经 R3 diff 复验无回退；`## test_cmd` 四项全绿、后端 unit 1661 passed 0 failed、相关 50 passed 依赖用户提供的门禁证据与 progress.md 自述，按任务约束未独立复跑模板契约/前端全链/桌面单测/PG 门禁。
- AC-006：TICK-VALID，re_verified。diff 中 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 仍为 `status=closed / resolution=resolved / fix_ref=t078`；`docs/specs/testing_quality.md` front matter `tasks: [t013, t014, t078]`；progress 处置表 R1 八条、R2 一条全部「已修」，收尾报告无新增遗留项，R3 未新增遗留。

coverage = 5/6

verdict: PASS

## Round 4 (2026-11-12T17:39:03+08:00)

reviewed_scope: 6c3de906163c1209

- 落点仓库校验：通过（不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于目标 worktree 根）。
- 指纹核对：本小节整行照抄重新渲染的 Round 4 模板指纹；独立复算 `repo_task.monitoring.review_scope_fingerprint('b2050e33b7aa30ec21616936659002a4c77331f6', 'docs/tasks/t078_quality_gate_root_cause_refactor')` = `6c3de906163c1209`，与注入值一致，且与 R3 的 `0e1bd51a2b18e0fb` 不同（R3→R4 交付仅 `tests/scripts/test_check_dep_locks.py` 的注释 / `import os`→`import re` / `env["PATH"]` 清理），本轮 PASS 有效性锚点成立。`task.py review-status` 当前 `code_verdict=PASS / test_verdict=PASS / review_scope=stale / round=3 / overall=INCOMPLETE / next_action=rerender_review`：stale 与 INCOMPLETE 系两份报告末条 reviewed_scope 仍为 R3 指纹、而 worktree 已变为 R4 指纹所致（审查后交付改动触发），且 code 轴 `review_code.md` 仍停在 Round 3（`0e1bd51a2b18e0fb`）；本报告写入 R4 行后 test 轴 stale 消除，code 轴由 code reviewer 独立追加 R4 后消解，非本报告问题（verdict 判定「仅本报告」）。读 prompt / 读 R1·R2·R3 报告 / 读完整 diff / 定点单测 / CLI 门禁 / 指纹复算后 `git status --short` 仍为 11 个 `M` 交付文件 + 2 份未跟踪 review 报告，无 reviewer 不可见的新增未跟踪交付文件，未引入指纹漂移。
- 审查对象：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（完整 diff，非 `...HEAD`）。本轮交付相对 R3 的增量：`tests/scripts/test_check_dep_locks.py` 的 f006 修复（注释改离线实现、删 `os` import、删 `env["PATH"]` 前置与 `env=env`），其余 10 个交付文件未变。
- 独立复跑：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/scripts/test_check_doc_sensitive.py tests/scripts/test_check_dep_locks.py -q` → **50 passed**（0 failed / 0 skipped）；`python3 scripts/check_doc_sensitive.py docs --check` → `PASSED: Checked 32 file(s), no sensitive data violations found.` rc=0；`.venv/bin/python scripts/check_dep_locks.py --check` → `OK: ... is synchronized` rc=0。未运行 PG 门禁。

### Findings（本轮新发现：0 条）

本轮无新 finding，编号 `t078_test_f007` 起预留未使用。clean review，不凑数。

### 前轮 finding 复核

#### t078_test_f006 - minor｜AC-003 相邻（注释过时）— 已消除（真修，非换形式弱化）

- R3 指出的 `tests/scripts/test_check_dep_locks.py:24-29` 过时注释（称 `--check` shell out 到 `uv`、据此把运行解释器目录前置到 `env["PATH"]`）已改为 `:23-25`："`--check` is an offline self-consistency check; it does not shell out to `uv` or touch the network. The running interpreter is passed by absolute path, so no PATH manipulation is needed."，与 `scripts/check_dep_locks.py` 的 `verify_lock_offline` 离线实现一致。
- `import os` → `import re`（`:3`，`re` 为 R2/R3 新增用例所需），冗余的 `env = dict(os.environ)` / `venv_bin` / `env["PATH"]` 构造与 `subprocess.run(..., env=env)` 参数全部删除（diff `@@ -20,21 +20,14 @@` 净 -7 行）；当前文件无 `os.` 引用，50 passed 证无 NameError。
- **任务核实项 1（关键）**：`test_check_dep_locks_script_passes`（`:21-33`）的两条断言 `assert proc.returncode == 0`（`:32`）与 `assert "synchronized" in proc.stdout`（`:33`）原样保留，未弱化、未删除、未反转；subprocess 仍以 `[sys.executable, str(script), "--check"]` 真实 CLI 子进程触达生产 `--check`，`cwd=ROOT` / `capture_output` / `text` 不变。删除的是测试环境搭建代码（冗余 PATH 前置），不是断言；离线 `--check` 本就不依赖 `uv`/PATH（R3 探针 `env PATH=/usr/bin:/bin ... --check` rc=0 已证），清理后断言更贴近真实调用。50 passed 中该用例通过，`--check` 门禁独立复跑 rc=0。
- 结论：f006 已真修。方向为「改注释 + 删死代码」，非「迁就实现」的就地改预期，非「换形式弱化」——R2 反复提示的弱化风险点（两条断言）一字未动。

#### R1/R2/R3 全部处置维持有效（任务核实项 2，以完整 diff 为准，不采信处置表自称）

- R1 f001：`test_publish_face_true_positives_still_detected`（`tests/scripts/test_check_doc_sensitive.py:770` 起）5 类独立文件 + 逐类 `proc.stderr.count(f"[{category}]") == 1` + `returncode != 0`，R4 diff 维持；R2 探针逐类禁用 5 个检测逻辑命中数 `1 → 0` 必红。
- R1 f002：`test_check_rejects_lock_missing_hash`（`test_check_dep_locks.py:86-111`）从真实 lock 删某包全部 hash 续行 + `any("has no sha256 hash")` 唯一归因 + `main() != 0`；`test_lock_below_declared_floor_rejected`（`:125`）。R4 diff 维持。
- R1 f003：脱敏断言 `assert "alice_developer@personal-mail.com" not in proc.stderr` + `assert "@" not in proc.stderr`（`test_check_doc_sensitive.py:334-335`）。R4 diff 维持。
- R1 f004：`test_upstream_release_does_not_invalidate_older_lock`（`test_check_dep_locks.py:114`）。R4 diff 维持。
- R1 f005：`test_explicit_archived_file_target_is_still_scanned`（`test_check_doc_sensitive.py` 末尾，`returncode == 1` + `[EMAIL]`）。R4 diff 维持。
- R2 code f004 护航：`test_compound_constraint_upper_bound_enforced`（`test_check_dep_locks.py:137`），R3 探针 A/B 证非恒真、改回旧正则必红。R4 diff 维持。
- R2 零新 finding；R3 唯一新 finding f006 本轮已消除。
- TDD 铁律：4 个旧语义用例在 `test_check_doc_sensitive.py` diff 中为整体删除（全 `-` 行），理由写入模块 docstring `:8-15`；7 个改输入用例断言语义（真泄漏仍拦 + 脱敏不回显）未变，2 处脱敏断言值随输入同步更新方向为增强；无就地把旧测试预期改成新实现输出。R4 唯一改动是注释 / import / 冗余环境代码清理，无既有测试断言被修改。无 mock 掉被测逻辑：doc 侧 `run_checker` 真实 CLI 子进程，lock 侧 `_load_dep_module`（`:61`）importlib 加载真实脚本、真实调 `verify_lock_offline` / `main()`，仅 monkeypatch `run_compile`（生成分支 tripwire）、`LOCK_FILE` / `sys.argv`（fixture 注入），均在系统边界。
- 50 passed 已独立复跑，与门禁证据「相关测试 50 passed」一致；后端 unit 1661 passed 0 failed、`## test_cmd` 四项全绿按任务约束不运行 PG 门禁，依赖用户提供证据。

### 改测方向复核与危险模式扫描

- 改测方向：无「迁就实现」的就地改预期；本轮仅注释 / import / 冗余环境代码清理，两条断言一字未动。
- 危险模式逐条扫描（全量核对两个测试文件与 R3→R4 增量 diff）：无恒真 `assert True` / 纯存在性断言作 AC 证据 / 删除或反转 expect / 注释掉断言 / 弱化断言 / `.skip` / `.only` / `xfail` / `pytest.mark.skip` / `# type: ignore` / `eslint-disable` / 静默错误 / mock 被测逻辑 / 条件跳过弱化断言 / 阈值（timeout / 重试 / 容差）增大 / 存在即通过 / 程序赋值替代真实交互。4 处 `# noqa: sensitive` 仍为 allow-marker fixture 输入文本。本轮删除的 `env=env` 是测试环境搭建代码，非断言、非测试块，不构成「删测试 / 删断言」；R3 唯一 minor f006 为注释清理，修复方向正确。

### 结论

- 前轮 finding 复核：R3 唯一新 finding `t078_test_f006`（minor）经 R4 完整 diff 核实已真修，非换形式弱化；R1 五条 / R2 零条 / R3 对处置的复核结论在 R4 diff 中全部维持，无回退。
- 改测方向复核：无「迁就实现」的就地改预期；本轮仅注释 / import / 冗余环境代码清理，`test_check_dep_locks_script_passes` 的 `returncode == 0` 与 `"synchronized"` 断言一字未动。
- 本轮新发现：0 条（critical 0 / important 0 / minor 0）。
- 危险模式扫描：无新增命中。
- 测试可信与覆盖：`test_check_dep_locks_script_passes` 仍经真实 CLI 子进程触达生产 `--check`，断言完整、仍通过；50 相关测试全绿、两条 CLI 门禁独立复跑 rc=0；`requirements-mail-core.lock` / `scripts/build-sidecar.sh` 不在 diff；生成模式 `scripts/check_dep_locks.py:153-170` 保留；负向 true-positive（5 类逐类 `count == 1`、缺 hash、低于下界、复合约束上界）维持；指纹 `6c3de906163c1209` 与当前一致。
- 覆盖缺口（未进表提示 / 剩余，均 minor 级、不阻断，按 prompt「可以再加 case」不进 finding 表）：①AC-005 `## test_cmd` 四项中模板契约、前端全链、桌面单测依赖用户门禁证据与 progress.md 自述，按任务约束未独立复跑（trust_prior）；②「直接依赖覆盖（`is not pinned` 分支）」仍无独立负向用例；③`test_check_is_offline_no_recompile` 的 tripwire 仍锁定 `run_compile`，未下沉 `subprocess.run` / socket 系统边界（离线结论由代码结构 + `--check` rc=0 支撑）；④AC-002「`PRIVATE_KEY_RE` 全文拦截」缺「私钥头内嵌散文行」专门用例（`TOKEN_RE` 全文拦截已由 `test_credential_signatures_detected_with_redacted_output` 的 `sk-proj-` 散文行覆盖）；⑤`test_publish_face_true_positives_still_detected` 的 `!= 0` 未收紧为 `== 1`（已由逐类 `count == 1` 兜底）；⑥范围外（code reviewer 轴）：`_value_spans` / `SpecifierSet` 实现层质量由 `review_code.md` 独立判定，本报告不评。R3 未进表提示 6（注释过时）已提升为 f006 并本轮修复，不再列为缺口。
- 总体判断：PASS（测试轴）。R3 唯一 minor f006 经 diff 核实真修，`test_check_dep_locks_script_passes` 断言未弱化、仍通过；R1/R2/R3 全部处置维持；TDD 铁律成立；50 相关测试全绿；本轮 0 新 finding，6 条 AC 全部 TICK-VALID，PASS 有效性锚点成立。「PASS/FAIL/INCOMPLETE」结论：**PASS**。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_archive_directories_excluded_from_docs_scan` / `test_explicit_archived_file_target_is_still_scanned`（`tests/scripts/test_check_doc_sensitive.py`）在 R4 diff 维持；`.sensitive_ignore` 仍为 6 类真实归档路径 + `docs/handoff.md`；复跑 `check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；50 passed 含 `test_repo_docs_gate_passes`。
- AC-002：TICK-VALID，re_verified。`test_publish_face_prose_examples_are_not_values` 证散文 / 表格 / 代码引用 / `[REDACTED_EMAIL]` 不报；7 个值形态改输入用例 + `test_credential_signatures_detected_with_redacted_output`（`sk-proj-` 散文行、私钥头、口令长）证值形态与 `TOKEN_RE` / `PRIVATE_KEY_RE` 全文拦截仍拦；ASSIGN_RE default-deny 由 A7 / A19 / A22 系列覆盖；R4 diff 未回退。
- AC-003：TICK-VALID，re_verified。`test_check_is_offline_no_recompile`（`run_compile` tripwire）+ 缺 hash / 低于下界 / 上游漂移 / 复合约束上界 4 个负向用例覆盖三类校验；`test_check_dep_locks_script_passes` 注释清理后断言 `returncode == 0` + `"synchronized"` 仍通过（R4 核实项 1）；复跑 `--check` rc=0；`verify_lock_offline` 纯离线、生成模式 `scripts/check_dep_locks.py:153-170` 保留；`requirements-mail-core.lock` / `scripts/build-sidecar.sh` 不在 diff；`requirements-dev.txt` 显式声明 `packaging>=23.0`。
- AC-004：TICK-VALID，re_verified。`test_publish_face_true_positives_still_detected` 5 类逐类独立文件 + `count == 1` 维持（R2 探针逐类禁用检测必红），`ghp_` token / 私钥 / 口令逐类精确断言；散文不报、归档不扫、上游漂移均有独立用例；R4 未回退，拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的 `verification_notes` 当前基线、敏感扫描规范改写、历史证据表「历史时点快照」标注经 R4 diff 复验无回退；敏感扫描一项已复跑 rc=0；`## test_cmd` 四项全绿、后端 unit 1661 passed 0 failed、相关 50 passed 中除定点复跑外依赖用户提供的门禁证据与 progress.md 自述，按任务约束未独立复跑模板契约 / 前端全链 / 桌面单测 / PG 门禁。
- AC-006：TICK-VALID，re_verified。diff 中 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 仍为 `status=closed / resolution=resolved / fix_ref=t078`；`docs/specs/testing_quality.md` front matter `tasks: [t013, t014, t078]`；`task.md` AC-001~006 全部 `[x]` 无未勾遗留；progress 处置表 R1 八条、R2 一条、R3 一条全部「已修」，收尾报告无新增遗留项。

coverage = 5/6

verdict: PASS

## Round 5 (2026-11-12T18:04:35+08:00)

reviewed_scope: e8cc9501ce3231ae

- 落点仓库校验：通过（不带 `-C` 的 `git rev-parse --show-toplevel` 输出精确等于目标 worktree 根）。
- 指纹核对：本小节整行照抄重新渲染的 Round 5 模板指纹；独立复算 `repo_task.monitoring.review_scope_fingerprint(diff_anchor, task_dir)` = `e8cc9501ce3231ae`，与注入值一致，且与 R4 的 `6c3de906163c1209` 不同（R4→R5 交付增量仅 `tests/scripts/test_check_doc_sensitive.py`），本轮 PASS 有效性锚点成立。`task.py review-status` 当前 `code_verdict=PASS / test_verdict=PASS / review_scope=stale / round=4 / overall=INCOMPLETE / next_action=rerender_review`：stale 与 INCOMPLETE 系两份报告末条 reviewed_scope 仍为 R4 指纹、而 worktree 已变为 R5 指纹所致；本小节写入 R5 行后 test 轴 stale 消除，code 轴由 code reviewer 独立追加 R5 后消解（verdict 判定「仅本报告」）。`git status --short` 为 11 个 `M` 交付文件 + 2 个 `A` review 报告，共 13 行全部 staged，无 reviewer 不可见的新增未跟踪交付文件；读 prompt / 读 R1-R4 报告 / 完整 diff / 定点单测 / 独立探针 / 指纹复算 / 隐私扫描后 status 未变，未引入指纹漂移。
- 审查对象：`git diff b2050e33b7aa30ec21616936659002a4c77331f6`（完整 diff，非 `...HEAD`）。R4→R5 增量：`tests/scripts/test_check_doc_sensitive.py` 把 7 个改输入用例与 `test_publish_face_true_positives_still_detected` 的 path case 中家目录路径字面量改为 `_home()` / `_linux_home()` / `_win_home()` 三个 helper 运行时拼接，新增 3 个 helper 定义（`:325-342`）与模块 docstring 说明；其余交付文件（两个生产脚本、`tests/scripts/test_check_dep_locks.py`、`.sensitive_ignore`、文档基线、spec/pending）在 R5 完整 diff 中维持 R4 形态。
- 独立复跑：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/scripts/test_check_doc_sensitive.py tests/scripts/test_check_dep_locks.py -q` → **50 passed**（0 failed / 0 skipped）；`python3 scripts/check_doc_sensitive.py docs --check` → `PASSED: Checked 32 file(s)` rc=0；`.venv/bin/python scripts/check_dep_locks.py --check` → `OK: ... is synchronized` rc=0。未运行 PG 门禁。

### Findings（本轮新发现：0 条）

本轮无新 finding，编号 `t078_test_f007` 起预留未使用。clean review，不凑数。

### 前轮 finding 复核（以完整 diff + 当前两测试文件为准，不采信处置表自称「已修」）

test 轴前轮 6 条（R1 f001-f005、R3 f006）在 R5 完整 diff 中全部维持 R2/R3/R4 已复核的「已消除」形态，无回退、无换形式弱化：

- f001：`test_publish_face_true_positives_still_detected`（`tests/scripts/test_check_doc_sensitive.py:791-810`）5 类各自独立文件 + 逐类 `proc.stderr.count(f"[{category}]") == 1` + `returncode != 0` 维持；path case 改用 `_home("realuser")` 拼接，本轮探针证其仍 `rc=1`、`[PATH]=1`（见核实项 1）。
- f002：`test_check_rejects_lock_missing_hash`（`tests/scripts/test_check_dep_locks.py:86-111`）从真实 lock 删某包全部 hash 续行 + `any("has no sha256 hash")` 唯一归因 + `main() != 0`；`test_lock_below_declared_floor_rejected`（`:125`）。维持。
- f003：脱敏断言 `assert "alice_developer@personal-mail.com" not in proc.stderr` + `assert "@" not in proc.stderr`（`tests/scripts/test_check_doc_sensitive.py:355-356`）。维持。
- f004：`test_upstream_release_does_not_invalidate_older_lock`（`tests/scripts/test_check_dep_locks.py:114`）。维持。
- f005：`test_explicit_archived_file_target_is_still_scanned`（`tests/scripts/test_check_doc_sensitive.py:843-851`，`returncode == 1` + `[EMAIL]`）。维持。
- f006：`test_check_dep_locks_script_passes`（`tests/scripts/test_check_dep_locks.py:21-33`）注释改离线实现、`import re`、删 `os` / `env["PATH"]` 前置与 `env=env`；两条断言 `returncode == 0`（`:32`）与 `"synchronized"`（`:33`）一字未动。维持。
- R2 零新 finding；R2 code f004 护航 `test_compound_constraint_upper_bound_enforced`（`:137-150`）维持。R4 零新 finding。

### 本轮核实项（任务指定，独立复验）

#### 1. helper 拼接路径仍触发生产正则、50 测试全绿、非弱化断言、非 mock 掉被测逻辑

- 探针（系统临时目录副本，纯内存 importlib 加载生产脚本与测试模块，不改 worktree）：三个 helper 运行时返回 macOS / Linux / Windows 家目录形态完整前缀；`_home("john_doe")`、`_linux_home("developer")`、`_win_home("john_doe")`、`_home("example.user")`、`_home("realuser")` 拼接出的 6 组完整路径，直接 `USER_PATH_RE` / `WIN_USER_PATH_RE`.finditer 全部命中，且经生产 `_value_spans` 判定为 isolated assignment RHS 后再次命中，命中文本为完整路径本身。
- 端到端：对这 6 组拼接路径各写临时文档，用测试自身的 `run_checker`（`tests/scripts/test_check_doc_sensitive.py:29-31`，`[sys.executable, SCRIPT, ...]` 真实 CLI 子进程，非 mock）跑 `--check`，全部 `returncode == 1`、`[PATH]` 命中 1 次；`test_publish_face_true_positives_still_detected` 的 path.md 以裸值形态复跑同样 `rc=1`、`[PATH]=1`，与逐类 `count == 1` 断言一致。
- 反证：把拼接结果换成去掉家目录形态前缀的弱化路径，6 组全部 `finditer` 空、`rc=0`、`[PATH]=0`。证明测试确实依赖真实路径形态触发生产正则，若 helper 拼接出的不是家目录形态，拦截断言 `returncode == 1` / `[PATH]` 命中必红——不是弱化断言、不是 mock 掉被测逻辑。
- 脱敏断言等价：探针比对 `_home("john_doe")` 返回值与 R4 旧断言里的字面量字符串逐字相等、`_win_home("john_doe")` 同理；R5 把 5 处脱敏断言的字面量替换为同值 helper 调用（`:277`、`:296`、`:309`、`:321`、`:369`），断言语义与强度不变（redact() 输出仍仅 `file:line [PATH]`，不回显完整值），拦截断言（`returncode == 1` + `[PATH]` 命中 + 文件名行号）一字未动。50 passed 证 6 个改输入用例与 publish face 用例全部通过。

#### 2. R1-R4 全部处置维持有效 + TDD 铁律

- 以 R5 完整 diff + 当前两测试文件逐条核对（见「前轮 finding 复核」），f001-f006 与 code f004 护航用例均维持，无回退、无「换形式弱化」。
- TDD 铁律：4 个旧语义用例（`test_inline_allow_exempts_only_nearest_match`、`test_archived_errata_cannot_hide_sensitive_line`、`test_archived_errata_precision_line_exemption`、`test_comment_start_does_not_exempt_real_path`）在 diff 中仍为整体删除（全 `-` 行），理由写入模块 docstring `tests/scripts/test_check_doc_sensitive.py:8-15`；7 个改输入用例断言语义（真泄漏仍拦 + 脱敏不回显）未变，R5 仅做字面量→同值 helper 的等价替换，方向为保持等价、非迁就实现；无就地改旧测试预期、无反转/删/注释掉断言、无 `.skip` / `.only` / `xfail` / `# type: ignore`、无阈值放大、无 mock 被测逻辑（doc 侧真实 CLI 子进程，lock 侧 `_load_dep_module` importlib 加载真实脚本、真实调 `verify_lock_offline` / `main()`，仅 monkeypatch `run_compile` 生成分支 tripwire 与 `LOCK_FILE` / `sys.argv` fixture 注入，均在系统边界）。
- 50 passed 已独立复跑；`requirements-mail-core.lock` / `scripts/build-sidecar.sh` 不在 diff；生成模式 `scripts/check_dep_locks.py:153-170` 保留。

#### 3. 隐私门禁工具链缺陷与 R5 改动边界（范围外观察，不进 finding 表）

- R5 改动起因：finish 的隐私门禁 `scan_privacy_changes` / `_scan_text_change`（`.repo_template/scripts/repo_task/privacy.py:483-503,506-563`）只对相对 base 的新增/修改行调用 `find_developer_path_leaks`，无法区分合成 fixture 与真实开发者家目录路径；R4 时变化行里的家目录路径字面量被误判为泄漏，阻断收尾。按 CLAUDE.md「先自行绕过、任务结束后报告工具链缺陷」，实施侧把变化行里的字面量改为运行时拼接，未改 `.repo_template`。
- 本轮只读复算 `privacy.scan_privacy_changes(root, base=diff_anchor)` → `[]`（0 发现），证实绕行有效、当前交付变化行干净。
- `tests/scripts/test_check_doc_sensitive.py:67`、`:90`、`:50`、`:154` 仍含家目录路径字面量，经 `git show diff_anchor` 与 R5 完整 diff 核对为**基线原有且逐字未改动**的行（属 ignore 机制 / 散文示例 fixture，带 allow marker），`scan_privacy_changes` docstring 明确「未修改的历史行不阻断」；这些行不进入扫描，R5 不动它们是正确的最小改动，非「改动不彻底」，不构成 finding。
- 该缺陷属模板工具链语义边界，按 read-only 边界不在本 task 修复、不改 `.repo_template`；由主任务在收尾后报告用户 / 走模板 issue 流程（见「系统性 follow-up」）。

### 改测方向复核与危险模式扫描

- 改测方向：无「迁就实现」的就地改预期。R5 唯一既有测试改动是 5 处脱敏断言的字面量→同值 helper 等价替换（探针证字符串相等）与输入侧字面量→同值拼接，断言语义与强度不变；3 个 helper 为纯新增模块级函数，50 passed 证无 NameError（helper 定义在 `:325-342`，被 `:269` 等更早定义的用例在运行时调用，模块加载期已绑定）。
- 危险模式逐条扫描（全量核对两个测试文件与 R4→R5 增量 diff）：无恒真 `assert True` / 纯存在性断言作 AC 证据 / 删除或反转 expect / 注释掉断言 / 弱化断言 / `.skip` / `.only` / `xfail` / `pytest.mark.skip` / `# type: ignore` / `eslint-disable` / 静默错误 / mock 被测逻辑 / 条件跳过弱化断言 / 阈值（timeout / 重试 / 容差）增大 / 存在即通过 / 程序赋值替代真实交互。4 处 `# noqa: sensitive` 仍为 allow-marker fixture 输入文本。R5 未删除任何测试块或断言。

### 结论

- 前轮 finding 复核：test 轴 R1 五条、R3 一条共 6 条在 R5 完整 diff 中全部维持「已消除」形态，无回退、无换形式弱化；R2 / R4 零新 finding 及其对处置的复核结论维持。
- 改测方向复核：无「迁就实现」的就地改预期；R5 仅字面量→同值 helper 的等价替换与纯新增 helper。
- 本轮新发现：0 条（critical 0 / important 0 / minor 0）。
- 危险模式扫描：无新增命中。
- 测试可信与覆盖：50 相关测试全绿、两条 CLI 门禁独立复跑 rc=0；探针证 6 组 helper 拼接完整路径命中 `USER_PATH_RE` / `WIN_USER_PATH_RE`、端到端真实 CLI `rc=1 PATH=1`、弱化形态 `rc=0`、脱敏断言等价；`test_publish_face_true_positives_still_detected` 5 类逐类 `count == 1` 维持；指纹 `e8cc9501ce3231ae` 与当前一致；隐私扫描 0 发现。门禁证据「相关测试 50 passed、后端 unit 1661 passed 0 failed、`## test_cmd` 四项全绿」中，定点单测与敏感扫描已独立复跑，模板契约 / 前端全链 / 桌面单测按任务约束未运行 PG 门禁与全链，依赖用户提供证据与 progress.md 自述。
- 未进表的提示（覆盖缺口 / 范围外观察，均 minor 级、不阻断，按 prompt「可以再加 case」不进 finding 表）：①AC-005 `## test_cmd` 四项中模板契约、前端全链、桌面单测及后端 unit 1661 passed 依赖用户门禁证据与 progress.md 自述，按任务约束未独立复跑（trust_prior）；②「直接依赖覆盖（`is not pinned` 分支）」仍无独立负向用例；③`test_check_is_offline_no_recompile` 的 tripwire 仍锁定 `run_compile`，未下沉 `subprocess.run` / socket 系统边界（离线结论由代码结构 + `--check` rc=0 支撑）；④AC-002「`PRIVATE_KEY_RE` 全文拦截」缺「私钥头内嵌散文行」专门用例（`TOKEN_RE` 全文拦截已由 `test_credential_signatures_detected_with_redacted_output` 的 `sk-proj-` 散文行覆盖）；⑤`test_publish_face_true_positives_still_detected` 的 `!= 0` 未收紧为 `== 1`（已由逐类 `count == 1` 兜底）；⑥范围外（code reviewer 轴）：`_value_spans` / `SpecifierSet` 实现层质量由 `review_code.md` 独立判定，本报告不评；⑦工具链缺陷（见核实项 3）：finish 隐私门禁把合成测试路径误判为真实家目录泄漏，属 `.repo_template` 语义边界，本 task 只读绕过、不改模板，须收尾后报告用户。
- 总体判断：PASS（测试轴）。R5 唯一改动经独立探针证实未弱化断言、未 mock 掉被测逻辑、拼接路径仍触发生产正则，50 相关测试全绿；R1-R4 全部处置维持、TDD 铁律成立；本轮 0 新 finding，6 条 AC 全部 TICK-VALID，指纹一致、隐私扫描 0 发现，PASS 有效性锚点成立。「PASS/FAIL/INCOMPLETE」结论：**PASS**。
- 系统性 follow-up：建议标题「finish 隐私门禁无法区分合成测试路径与真实开发者家目录」，slug `privacy_gate_synthetic_path_false_positive`，阻断性：非阻断（模板工具链缺陷，消费仓不自行修 `.repo_template`）。经 `task.py list` 只读查证无等价 follow-up；按 CLAUDE.md 与 read-only 边界，本 task 不改模板、不建 task，由主任务收尾后报告用户 / 走 template-issue-report 流程。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_archive_directories_excluded_from_docs_scan`（`tests/scripts/test_check_doc_sensitive.py:813`）与 `test_explicit_archived_file_target_is_still_scanned`（`:843`）在 R5 diff 维持；`.sensitive_ignore` diff 仍为 6 类真实归档路径 + `docs/handoff.md`；复跑 `check_doc_sensitive.py docs --check` 报 32 文件 0 违规 rc=0；50 passed 含 `test_repo_docs_gate_passes`（`:164`）。
- AC-002：TICK-VALID，re_verified。`test_publish_face_prose_examples_are_not_values`（`:773`）证散文 / 表格 / 代码引用 / `[REDACTED_EMAIL]` 不报（`returncode == 0`）；7 个值形态改输入用例（R5 路径输入改 helper 拼接，探针证仍命中 `USER_PATH_RE` / `WIN_USER_PATH_RE`）+ `test_credential_signatures_detected_with_redacted_output`（`sk-proj-` 散文行、私钥头、口令长）证值形态与 `TOKEN_RE` / `PRIVATE_KEY_RE` 全文拦截仍拦；ASSIGN_RE default-deny 由 A7 / A19 / A22 系列覆盖；`docs/blueprint/testing.md` 敏感扫描规范改写经 R5 diff 复验无回退。
- AC-003：TICK-VALID，re_verified。`test_check_is_offline_no_recompile`（`tests/scripts/test_check_dep_locks.py:73`，`run_compile` tripwire）+ 缺 hash / 低于下界 / 上游漂移 / 复合约束上界 4 个负向用例覆盖三类校验；`test_check_dep_locks_script_passes`（`:21`）注释清理后 `returncode == 0` + `"synchronized"` 仍通过；复跑 `--check` rc=0；`requirements-mail-core.lock` / `scripts/build-sidecar.sh` 不在 diff；生成模式 `scripts/check_dep_locks.py:153-170` 保留；`requirements-dev.txt` 显式声明 `packaging>=23.0`。
- AC-004：TICK-VALID，re_verified。`test_publish_face_true_positives_still_detected`（`tests/scripts/test_check_doc_sensitive.py:791`）5 类逐类独立文件 + `count == 1` 维持，本轮探针证 path case 改用 `_home("realuser")` 拼接后仍 `rc=1 [PATH]=1`、删除该类检测必红；`ghp_` token / 私钥 / 口令逐类精确断言不变；散文不报、归档不扫、上游漂移均有独立用例；R5 未回退，拦截能力未削弱。
- AC-005：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的 `verification_notes` 当前基线、敏感扫描规范改写、历史证据表「历史时点快照」标注经 R5 diff 复验无回退；敏感扫描一项已复跑 rc=0；`## test_cmd` 四项全绿、后端 unit 1661 passed 0 failed、相关 50 passed 中除定点复跑外依赖用户提供的门禁证据与 progress.md 自述，按任务约束未独立复跑模板契约 / 前端全链 / 桌面单测 / PG 门禁。
- AC-006：TICK-VALID，re_verified。diff 中 `docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 仍为 `status=closed / resolution=resolved / fix_ref=t078`；`docs/specs/testing_quality.md` front matter `tasks: [t013, t014, t078]`；`task.md` AC-001~006 全部 `[x]` 无未勾遗留；progress 处置表 R1 八条、R2 一条、R3 一条全部「已修」，收尾报告无新增遗留项；R5 引入的工具链缺陷属 `.repo_template` 既有缺陷、按 CLAUDE.md 报告用户而非本 task 遗留，不计为新增遗留项。

coverage = 5/6

verdict: PASS
