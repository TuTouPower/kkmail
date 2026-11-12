---
pid: "p077"
slug: "quality_gate_false_positives_and_lock_drift"
status: "todo"
---
# p077 质量门禁误报与依赖锁漂移：扫描语义模型不一致、归档被扫、lock 校验拿当下最新当基线

- 现象：
    1. `python3 scripts/check_doc_sensitive.py docs --check` 报 14 处违规，逐条核对全部是占位符 `[REDACTED_EMAIL]` / `[REDACTED_ID]`、RFC 示例 `foo@bar.com`、代码证据 `a@b@gmail.com`、以及「p027 曾含真实邮箱」的评审讨论文本，无一条真实凭据或个人邮箱；`tests/scripts/test_check_doc_sensitive.py::test_repo_docs_gate_passes` 因此长期红，`## test_cmd` 这一项永远失败，真泄漏会被淹没在误报里（门禁失效）。
    2. `python3 scripts/check_dep_locks.py --check` 报 lock out of date，`tests/scripts/test_check_dep_locks.py::test_check_dep_locks_script_passes` 长期红；`requirements-mail-core.txt` 全为 `>=` 下界，任何上游发版都会再次漂移（2026-11-11 记载 fastapi 0.162.4，现已 0.162.5）。
    3. `docs/blueprint/testing.md:318/325` 声明「0 违规」、`:323` 声明「未修、如实登记」、`:21` 声明「2142 passed」均与当前 main 事实不符。
- 影响：`## test_cmd` 两项长期红，门禁失去区分力；每个 task 被迫重复「既存、非本 task 引入、如实登记」的免责声明并照常合并，违反开发铁律「拒绝妥协、从根因修正」。
- 根因：
    1. `scripts/check_doc_sensitive.py::scan_file` 同一文件内两套不一致判定模型：凭据检测走 `ASSIGN_RE` + `_split_assignment_fragments`（赋值形态，正确），但邮箱 `:423`、用户路径 `:442`、口令长度 `:490` 对**任意行全文**扫描，把散文/表格/代码引用里的字符串形态等同于敏感事实。
    2. 扫描边界无职责分离：`main` 默认 `targets=["docs"]`，把已评审入库的归档产物（`docs/reviews/**`、`docs/tasks/**`、`docs/archive/**`）与当前发布面同等扫描；规则又要求合法例外每行加 `<!-- sensitive-allow -->`，与「归档记录只读」形成结构性矛盾。`.sensitive_ignore:5-6` 指向 `docs/archive/**`，实际违规文件在 `docs/reviews/**` / `docs/tasks/**`，路径不匹配。
    3. `scripts/check_dep_locks.py::run_compile` 用 `uv pip compile --universal --python-version 3.13 --generate-hashes` 现场联网重解析，再与已提交 lock 逐字节文本比较（含缩进 `# via` 注释），把「当下最新解析结果」当门禁基线；`--check` 跨机器/时间不确定。
    4. `docs/blueprint/testing.md` 基线声明是历史时点快照，未随归档文档入库与门禁模型演进同步。
- 测试缺口：缺「发布面真泄漏仍被拦截」的负向回归用例（防止为绿而弱化断言）；`test_repo_docs_gate_passes` 长期红，掩盖了误报与真违规不可区分；`test_check_dep_locks_script_passes` 依赖联网重解析，无法稳定验证离线一致性。
- 线索：`scripts/check_doc_sensitive.py:393-542`、`scripts/check_dep_locks.py:17-107`、`docs/blueprint/testing.md:21/82/318/323/325`、`.sensitive_ignore`
- 处理：转 t078 立项（门禁属安全/质量契约，超出 `pending-fix` 准入：`docs/blueprint/` 长期行为 + 安全规则重写）。
