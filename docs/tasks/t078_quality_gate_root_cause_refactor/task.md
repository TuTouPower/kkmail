# Task spec

## 背景

t076/t077 收尾报告把 `## test_cmd` 的两项长期失败归为「配置缺陷 / 采纳前基线既存」并写「如实登记、不改动无关文件」，被用户指出是用分类当免责、以回避代替修复。经核查，这是**质量门禁失效**，不是配置缺陷：

1. `python3 scripts/check_doc_sensitive.py docs --check` 报 14 处违规，逐条核对全部是占位符 `[REDACTED_EMAIL]` / `[REDACTED_ID]`、RFC 示例 `foo@bar.com`、代码证据 `a@b@gmail.com`、以及「p027 曾含真实邮箱」的评审讨论文本，无一条真实凭据或个人邮箱。`tests/scripts/test_check_doc_sensitive.py::test_repo_docs_gate_passes` 因此长期红，真泄漏会被淹没在误报里。根因是 `scripts/check_doc_sensitive.py::scan_file` 同一文件内两套不一致判定模型：凭据检测走 `ASSIGN_RE` + `_split_assignment_fragments`（赋值形态，正确），而邮箱 `:423`、用户路径 `:442/:455`、口令长度 `:490` 对**任意行全文**扫描，把散文/表格/代码引用里的字符串形态等同于敏感事实。且 `main` 默认 `targets=["docs"]`，把已评审入库的归档产物与当前发布面同等扫描，规则又要求合法例外逐行加 `<!-- sensitive-allow -->`，与「归档记录只读」形成结构性矛盾。`.sensitive_ignore:5-6` 指向 `docs/archive/**`，实际违规文件在 `docs/reviews/**` / `docs/tasks/**`，路径不匹配。
2. `python3 scripts/check_dep_locks.py --check` 报 lock out of date，`test_check_dep_locks_script_passes` 长期红。根因是 `run_compile` 用 `uv pip compile --universal --python-version 3.13 --generate-hashes` 现场联网重解析，再与已提交 lock 逐字节文本比较（含缩进 `# via` 注释），把「当下最新解析结果」当门禁基线；`requirements-mail-core.txt` 全为 `>=` 下界，任何上游发版都会再次漂移。
3. `docs/blueprint/testing.md` 的基线声明（`:21` 2142 passed、`:318/325` 0 违规、`:323` 未修如实登记）与 `:82` 的规范描述均为历史时点快照，与当前 main 事实不符规范落点也错（敏感扫描规范实际在 testing.md 而非 conventions.md）。

依据开发铁律（架构至上、拒绝妥协、零兼容性负担），从根因重构门禁：统一扫描语义模型、按目录职责分离归档与发布面、把 lock 校验改为离线自洽判定、同步长期文档基线，并用负向 true-positive 测试证明门禁能力未被削弱。不做「白名单扩容 + 重生成 lock」这类临时补丁：前者继续叠在错误语义模型上，后者顺带升级生产依赖且上游发版后必然复发。

## 契约区

### 范围

- `scripts/check_doc_sensitive.py`：统一判定模型（邮箱 / 用户路径 / 口令长度只在值形态判定）；按目录职责排除归档/历史产物；保留 `TOKEN_RE` / `PRIVATE_KEY_RE` 高危签名全文拦截；保留 `ASSIGN_RE` 凭据赋值检测与带理由的 allow marker（发布面合法例外仍需逃生口）。
- `.sensitive_ignore`：修正为真实归档路径，与脚本内置分流一致。
- `scripts/check_dep_locks.py`：`--check` 改为离线自洽校验（不联网、不重解析、不与当下最新比对）；保留人工生成模式；不改 `requirements-mail-core.lock` 内容、不升级生产依赖。
- `tests/scripts/test_check_doc_sensitive.py`、`tests/scripts/test_check_dep_locks.py`：新增负向 true-positive 回归用例，证明真泄漏仍被拦截、散文示例不报、归档不扫、上游漂移不触发失败；旧测试按 TDD 规则处理（整体删除或保留并写明理由，禁止就地改预期）。
- `docs/blueprint/testing.md`：同步过期基线声明与敏感扫描规范描述。
- `docs/specs/testing_quality.md`：front matter `tasks` 登记 `t078`；闭环来源 pending `p077`。

### 非范围

- 不改动产品代码（`src/mail_core/`、`src/frontend/`、`src/desktop/`）。
- 不升级 `requirements-mail-core.txt` 的约束写法与任何生产依赖版本；不重构 `requirements-ci.lock` / dev 依赖链（属独立缺口，若需处理另立 pending）。
- 不改写 `docs/reviews/**`、`docs/archive/**`、`docs/tasks/**` 等已入库归档文档的内容。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：`check_doc_sensitive.py` 扫描 `docs/` 时按目录职责排除归档/历史产物（`docs/reviews/**`、`docs/archive/**`、`docs/tasks/**`、`docs/pending/**`、`docs/findings/**`、`docs/spikes/**`、`docs/handoff.md`）；当前发布面（`docs/guides/**`、`docs/blueprint/*.md`、`docs/specs/*.md`、根 README）仍全量扫描。`.sensitive_ignore` 路径修正为真实位置。全仓 `python3 scripts/check_doc_sensitive.py docs --check` 报 **0 违规**，且 `test_repo_docs_gate_passes` 通过。
- [ ] AC-002：扫描语义模型统一：邮箱 / 用户路径 / 口令长度只在「值形态」（isolated assignment 的 RHS 或孤立值行）判定；散文、markdown 表格、代码引用中的示例字符串不再报违规。`TOKEN_RE` / `PRIVATE_KEY_RE` 高危签名仍全文拦截，`ASSIGN_RE` 凭据赋值仍按 default-deny 判定。
- [ ] AC-003：`check_dep_locks.py --check` 改为**离线自洽校验**：不调用 `uv pip compile`、不联网、不重解析；验证 lock 每行 `pkg==version --hash=sha256:...` 格式完整、覆盖 `.txt` 的直接依赖且版本满足其约束。`requirements-mail-core.lock` 内容不变（不升级生产依赖）；`test_check_dep_locks_script_passes` 与 `scripts/build-sidecar.sh` 的门禁调用字面量保持有效；模拟上游版本发版不触发漂移。人工生成模式仍可用。
- [ ] AC-004：新增负向 true-positive 回归用例并全部通过：发布面里独立个人邮箱 / 真实口令赋值 / `ghp_` token / `-----BEGIN PRIVATE KEY-----` / 真实用户路径仍被拦截；散文中的 `foo@bar.com` / `[REDACTED_EMAIL]` / 代码引用不报；归档目录文件不被扫描；上游版本变化不影响 `--check` 结果。
- [ ] AC-005：`docs/blueprint/testing.md` 的过期基线（`:21` 2142 passed、`:318/325` 0 违规、`:323` 未修如实登记）与 `:82` 敏感扫描规范描述同步为新模型；`## test_cmd` 四项（模板契约、前端全链、桌面单测、敏感扫描）全部通过，不再有「既存失败」需要登记。
- [ ] AC-006：`docs/pending/p077_quality_gate_false_positives_and_lock_drift.md` 闭环为 `status=closed` / `resolution=resolved` / `fix_ref=t078`；`docs/specs/testing_quality.md` front matter `tasks` 登记 `t078`；本 task 不新增遗留项。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试（AC-003 的「离线」通过 monkeypatch 阻断 `subprocess`/网络调用并断言 `--check` 仍通过；AC-005 的 `## test_cmd` 由命令实际执行结果验证）。

## 上下文区

- 关联 spec：docs/specs/testing_quality.md
- 来源：p077（2026-11-12 核实：门禁误报与 lock 漂移的根因，非配置缺陷；t076/t077 收尾报告的「既存/如实登记」处理被用户指出是妥协）

### 有意不测

- 无：所有扫描分支、归档分流、离线校验与文档基线均有自动化测试覆盖

### 测试策略

- `tests/scripts/test_check_doc_sensitive.py`：值形态 vs 散文的判定边界、归档目录排除、发布面 true-positive 回归（邮箱/路径/口令/token/私钥）、allow marker 仅对发布面生效。
- `tests/scripts/test_check_dep_locks.py`：离线自洽校验（格式、约束覆盖、hash 完整）、上游版本变化不影响结果、生成模式仍可用。
- 门禁：`## test_cmd` 四项全量执行；`python3 scripts/check_doc_sensitive.py docs --check` 与 `check_dep_locks.py --check` 直接复跑。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：改动安全门禁可能被误认为「弱化断言」；故 AC-004 的负向 true-positive 回归是硬门禁，必须证明拦截能力不降。
- 回退：本 task 独立分支；失败时整体丢弃，主仓门禁恢复原状（仍是既存失败，不产生数据损失）。

### 依赖与约束

- 遵循开发铁律：零兼容性负担，直接重构判定模型，不保留「白名单扩容 + 重生成 lock」的兼容补丁。
- 按 TDD 规则：实现让旧测试语义失效时，整体删除/重写并写明理由，禁止就地改预期制造假绿。
- `scripts/build-sidecar.sh:20` 与 `tests/scripts/test_check_dep_locks.py:55` 硬编码 `check_dep_locks.py --check` 字面量，脚本 CLI 必须保持兼容。

### Finalization 时更新的 blueprint

- `docs/blueprint/testing.md`：过期基线声明、敏感扫描规范描述、迁移校验约定（若本 task 触及）。
- `docs/specs/testing_quality.md`：front matter `tasks` 登记 `t078`。
