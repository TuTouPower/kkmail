---
tid: "t078"
slug: "quality_gate_root_cause_refactor"
title: "质量门禁从根因重构：统一扫描语义模型、归档分流与依赖锁离线校验"
status: "done"
branch: "t078_quality_gate_root_cause_refactor"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "b2050e33b7aa30ec21616936659002a4c77331f6"
spec_source_sha: "b2050e33b7aa30ec21616936659002a4c77331f6"
depends_on: ""
conflicts_with: ""
note: "来源 p077；按开发铁律修正门禁失效而非白名单补丁"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 根因：确认门禁失效不是配置缺陷。`scripts/check_doc_sensitive.py::scan_file` 同文件内两套不一致模型（凭据走赋值形态、邮箱/路径/口令长度对任意行全文扫描），把散文/表格/代码引用中的示例当泄漏；归档/历史产物与发布面混在同一 `docs` target；`.sensitive_ignore` 路径指向 `docs/archive/**` 而实际违规文件在 `docs/reviews/**` / `docs/tasks/**`。`scripts/check_dep_locks.py --check` 用 `uv pip compile` 联网重解析后与已提交 lock 逐字节比对，把「当下最新」当基线，`.txt` 全 `>=` 下界导致上游发版必然复发。
- 修复（拒绝妥协，未做白名单扩容 / 重生成 lock 的临时补丁）：新增 `_value_spans` 统一值形态判定（isolated assignment RHS 或孤立裸值行），邮箱/用户路径/口令长度只在值区间检测；TOKEN/PRIVATE_KEY 高危签名仍全文拦截；`collect_target_files` 按目录职责排除归档/历史产物，`.sensitive_ignore` 同步修正；allow marker 保留为发布面合法例外的逃生口。`check_dep_locks.py --check` 改为 `verify_lock_offline` 离线自洽校验（格式、直接依赖覆盖、`>=` 约束、hash 完整），不联网、不重解析、不升级生产依赖；生成模式保留。`requirements-mail-core.lock` 内容未变。
- TDD：先写 5 个失败测试再实现。11 个基于旧全文扫描模型的用例按铁律处理——7 个 true-positive 用例改输入为值形态（断言「真泄漏仍被拦截 + 脱敏输出」不变），4 个旧语义用例（散文 allow marker、归档 errata、注释路径）整体删除并在模块 docstring 写明理由；新增 4 个新语义用例（散文示例不报、发布面真泄漏仍拦、归档不扫、发布面 allow marker 生效）与 2 个 lock 离线用例。
- 文档：`docs/blueprint/testing.md` 的 `verification_notes`、`:82` 敏感扫描规范改为新模型；历史证据表明确标注为历史快照、当前状态以 verification_notes 为准，历史行按「历史由 Git 保存」不改写。
- 闭环：`p077` 由本 task 闭环（resolved / fix_ref=t078）；`docs/specs/testing_quality.md` 登记 `t078`。
- 结果：后端 unit **1658 passed、0 failed**（两个长期红灯 `test_repo_docs_gate_passes` / `test_check_dep_locks_script_passes` 均熄灭）；`## test_cmd` 四项全绿；全仓敏感扫描 0 违规；lock 离线校验通过。无「既存失败」需登记。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-12T15:30:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t078_code_f001|important|已修|`verify_lock_offline` 手搓整数元组比较改为 PEP 440 `SpecifierSet(spec).contains(version)`（`packaging` 显式声明于 requirements-dev.txt，缺失时 fail-closed），正确处理 `1.2 >=1.2.0`、拒绝 `2.0.0rc1 >=2.0.0`、未知/空约束报错|scripts/check_dep_locks.py|
|t078_code_f002|minor|已修|删除重构后无引用的 `strip_header_comments` 死函数|scripts/check_dep_locks.py|
|t078_code_f003|minor|已修|`_value_spans` 仅在无赋值片段时才回退整行裸值，消除 `key=value` 行重复计数|scripts/check_doc_sensitive.py|
|t078_test_f001|important|已修|`test_publish_face_true_positives_still_detected` 改为 5 类各自独立文件并精确断言命中数，删掉任一检测逻辑必红|tests/scripts/test_check_doc_sensitive.py|
|t078_test_f002|important|已修|缺 hash 用例改为从真实 lock 复制并删去某包全部 hash 续行（消除「未固定」噪声）+ 直接断言 `verify_lock_offline` 错误精确含 `has no sha256 hash`；新增 `test_lock_below_declared_floor_rejected` 版本下界负向|tests/scripts/test_check_dep_locks.py|
|t078_test_f003|minor|已修|`test_personal_email` 脱敏断言改查新邮箱并加 `@` 锚，避免恒真|tests/scripts/test_check_doc_sensitive.py|
|t078_test_f004|minor|已修|新增 `test_upstream_release_does_not_invalidate_older_lock`（老但满足下界的 lock 通过）显式模拟上游发版|tests/scripts/test_check_dep_locks.py|
|t078_test_f005|minor|已修|新增 `test_explicit_archived_file_target_is_still_scanned` 回归归档显式文件 target 仍扫描|tests/scripts/test_check_doc_sensitive.py|

Round 1 两轴 FAIL 共 8 条（2 important + 6 minor）全部从根因修复并有负向回归护航；Round 2 两轴 PASS，code 轴新增 1 条 minor 见下。

### Round 2 (2026-11-12T16:10:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t078_code_f004|minor|已修|`_REQ_RE` 原只捕获首个 specifier，逗号后的上界（如 `foo>=1.2,<2.0`）被静默丢弃；改为捕获完整约束串交 `SpecifierSet` 判定，并新增 `test_compound_constraint_upper_bound_enforced` 负向用例|scripts/check_dep_locks.py|

Round 2 两轴 PASS（code 6/6、test 5/6 AC `trust_prior`）；R1 八条处置经独立复核全部消除。Round 2 唯一 minor `t078_code_f004` 已修，按「review 后改交付内容必须重新 review」进入 Round 3。

### Round 3 (2026-11-12T16:40:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t078_test_f006|minor|已修|`test_check_dep_locks.py:24-29` 注释仍称 `--check` shell out 到 `uv`；改为反映离线实现，并删除冗余的 `env["PATH"]` 前置与 `os` import|tests/scripts/test_check_dep_locks.py|

Round 3 两轴 PASS（code 轴 0 新 finding），唯一 minor `t078_test_f006` 已修；按「review 后改交付内容必须重新 review」进入 Round 4 收尾轮。

### Round 4 (2026-11-12T17:10:00+08:00)

Round 4 零 finding（code / test 双轴 PASS，`reviewed_scope: 6c3de906163c1209`）；R1 8 条 + R2 1 条 + R3 1 条共 10 条 finding 全部已修并经独立复核，无 TICK-VOID、无遗留。`review-status overall=PASS / next_action=finalize`。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：后端 unit **1658 passed、0 failed、537 skipped**（两个长期红灯均熄灭）；`tests/scripts` 199 passed、42 skipped；模板契约 463 passed、1 skipped；前端 vitest 586 passed + `tsc -b` + build + `oxlint`；桌面单测通过；`python3 scripts/check_doc_sensitive.py docs --check` 报 32 文件 0 违规；`.venv/bin/python scripts/check_dep_locks.py --check` 通过。`## test_cmd` 四项全绿，不再有「既存失败」需登记。
- 黑盒：本 task 只改门禁脚本与测试，不改用户/调用方可观察行为；`blackbox_verify`（stubApi E2E 21 passed）在 t077 已验证、本次未触及前端生产代码，按相关门禁边界不重复执行。
- review：full 级 **5 轮**（`review_limit=5`），`review_code.md` / `review_test.md` 的 Round 5 双轴 PASS、0 新 finding、6/6 AC 全 TICK-VALID 且无 TICK-VOID；R1-R4 共 11 条 finding 全部已修并经独立复核。`review-status overall=PASS / next_action=finalize`。
- AC 判定：见 `task.md` 行内打勾（AC-001~AC-006 全部勾选）

### 结果摘要

- 质量门禁从根因重构：统一扫描语义模型（值形态才判泄漏）、归档按目录职责分流、lock 改离线自洽校验；补负向 true-positive 回归证明拦截能力未削弱；同步 `testing.md` 基线与规范。`## test_cmd` 首次实现全绿、后端 unit 首次 0 failed。来源 `p077` 已闭环，本 task 无新增遗留。

### 长期文档闭环

- specs_index：`docs/specs/testing_quality.md` front matter `tasks` 已登记 `t078`。
- blueprint：`docs/blueprint/testing.md` 的 `verification_notes`、敏感扫描规范（原 `:82`）与历史证据表说明已同步为新模型。
- 正式 spike：无（本 task 无未核实外部契约）。
