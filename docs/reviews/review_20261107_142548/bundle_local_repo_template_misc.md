# bundle_local_repo_template_misc

## responsibilities

- 提供 Git 提交前门禁钩子（pre-commit），自动对暂存的 Markdown 进行 md_kx 规范化格式化并重新暂存
- 实现模板同步与演进工具集（template_sync 与 repo_sync.py），处理上游模板到消费仓的代码、配置、skills 与 hooks 机械对齐
- 维护待办（pending.py）与已验证技术发现（findings.py）的总账分配、列举与三态生命周期流转
- 提供任务评审门禁检查（check_review_status.py），比对 diff 指纹并严格验收 AC 复验状态（TICK-VALID / TICK-VOID）
- 提供 OpenCode CLI 扩展命令层（.opencode/commands/\*.md）及模板自带自动化测试套件

## interfaces

- .repo_template/hooks/pre-commit 钩子入口
- repo_sync.py CLI（init, status, plan, apply, install-hooks, link-skills 等）
- pending.py CLI（new, list, archive, park, revive, rename）
- findings.py CLI（new, list, rename）
- check_review_status.py CLI（--task-dir, --max-review-round）
- skills/registry.json 技能注册清单契约

## dependencies

- md_format / md_kx（Markdown 格式化工具）
- pytest（模板契约与功能测试套件）
- Git CLI（diff, add, ls-tree, merge-base）

## flows

- Pre-commit 执行流：获取暂存 .md 文件 -> 检查工作区与 index 一致性（有差异直接拒绝，避免意外打包） -> 运行 md_format -> 重新 git add 格式化后的文件 -> 放行 commit
- 模板同步流：校验来源合法性与 dirty 状态 -> 扫描排除非分发文件 -> 开启文件事务 -> 同步硬同步目录/文件 -> 执行 schema 与 conventions 迁移 -> 运行测试门禁 -> 提交/更新 sync_state.json
- 编号互斥分配流：跨本地全部分支与登记 worktree 收集已用编号 -> 锁内取下一个可用正整数 -> 原子创建模板条目文件 -> 格式化落盘

## constraints

- pre-commit 遇到工作区未暂存改动时坚决拒绝执行，防止工作区未经验证的代码被 git add 卷入 commit
- 禁止将含有私有凭据或测试草稿的不可分发文件同步至下游消费仓
- pending 与 findings 的编号全局单调递增，即使被 archive 或分支尚未合并也不得复用

## decisions

- OpenCode 命令全部设计为薄代理层，正文仅包含引导至对应 skill 执行的指令，实际业务逻辑完全收敛在 scripts 与 skills 目录下
- 评审门禁（check_review_status.py）以 task 实际完成时的 diff 指纹为准，代码一旦发生变动自动判定 review_scope 失效

## evidence

- .repo_template/hooks/pre-commit:24-85（-z NUL 分隔处理非 ASCII 文件名、dirty 检查与重新暂存）
- .repo_template/scripts/template_sync/apply.py:35-80（不可分发文件拦截、目录硬同步与工作流迁移）
- .repo_template/scripts/\_id_scan.py:43-85（跨分支与 worktree 扫描、git common 锁内分配）
- .repo_template/scripts/check_review_status.py:26-72（AC 门禁、reviewed_scope 指纹比对）
- .repo_template/scripts/track_worktree.py:62-95（逆序读取账本快速定位当前 active 任务）

## uncertainties

## Findings

No findings.

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_ops"
  }
}
```

## files_reviewed

```json
[
  ".opencode/commands/bug-to-pending.md",
  ".opencode/commands/pending-fix.md",
  ".opencode/commands/pending-record.md",
  ".opencode/commands/repo-cleanup.md",
  ".opencode/commands/repo-hygiene.md",
  ".opencode/commands/repo-template-sync.md",
  ".opencode/commands/task-create.md",
  ".opencode/commands/task-from-pending.md",
  ".opencode/commands/task-merge.md",
  ".opencode/commands/task-preflight.md",
  ".opencode/commands/task-run.md",
  ".opencode/commands/task-schedule.md",
  ".opencode/commands/template-issue-report.md",
  ".repo_template/docs/architecture.md",
  ".repo_template/docs/recovery.md",
  ".repo_template/docs/review_prompts/code_prompt.txt",
  ".repo_template/docs/review_prompts/general_prompt.txt",
  ".repo_template/docs/review_prompts/share_prompt.txt",
  ".repo_template/docs/review_prompts/test_prompt.txt",
  ".repo_template/docs/spike_report_template.md",
  ".repo_template/docs/sync.md",
  ".repo_template/docs/task_template/progress.md",
  ".repo_template/docs/task_template/task.md",
  ".repo_template/docs/usage.md",
  ".repo_template/hooks/pre-commit",
  ".repo_template/scripts/_id_scan.py",
  ".repo_template/scripts/check_review_status.py",
  ".repo_template/scripts/export_template.py",
  ".repo_template/scripts/findings.py",
  ".repo_template/scripts/md_format.py",
  ".repo_template/scripts/package.json",
  ".repo_template/scripts/pending.py",
  ".repo_template/scripts/render_review_prompts.py",
  ".repo_template/scripts/repo_cleanup.py",
  ".repo_template/scripts/repo_hygiene.py",
  ".repo_template/scripts/repo_state.py",
  ".repo_template/scripts/repo_sync.py",
  ".repo_template/scripts/skill_registry.py",
  ".repo_template/scripts/spikes.py",
  ".repo_template/scripts/task.py",
  ".repo_template/scripts/template_sync/__init__.py",
  ".repo_template/scripts/template_sync/agents_merge.py",
  ".repo_template/scripts/template_sync/apply.py",
  ".repo_template/scripts/template_sync/assets.py",
  ".repo_template/scripts/template_sync/cli.py",
  ".repo_template/scripts/template_sync/common.py",
  ".repo_template/scripts/template_sync/context.py",
  ".repo_template/scripts/template_sync/conventions_migration.py",
  ".repo_template/scripts/template_sync/gates.py",
  ".repo_template/scripts/template_sync/hooks.py",
  ".repo_template/scripts/template_sync/shared_files.py",
  ".repo_template/scripts/template_sync/skills_links.py",
  ".repo_template/scripts/template_sync/source.py",
  ".repo_template/scripts/template_sync/specs_index_migration.py",
  ".repo_template/scripts/template_sync/state.py",
  ".repo_template/scripts/template_sync/status_plan.py",
  ".repo_template/scripts/template_sync/transaction.py",
  ".repo_template/scripts/template_sync/workflow_migration.py",
  ".repo_template/scripts/track_worktree.py",
  ".repo_template/skills/bug-to-pending/SKILL.md",
  ".repo_template/skills/pending-fix/SKILL.md",
  ".repo_template/skills/pending-record/SKILL.md",
  ".repo_template/skills/registry.json",
  ".repo_template/skills/repo-cleanup/SKILL.md",
  ".repo_template/skills/repo-hygiene/SKILL.md",
  ".repo_template/skills/repo-template-sync-core/SKILL.md",
  ".repo_template/skills/repo-template-sync/SKILL.md",
  ".repo_template/skills/task-create/SKILL.md",
  ".repo_template/skills/task-from-pending/SKILL.md",
  ".repo_template/skills/task-integrate/SKILL.md",
  ".repo_template/skills/task-merge/SKILL.md",
  ".repo_template/skills/task-preflight/SKILL.md",
  ".repo_template/skills/task-run/SKILL.md",
  ".repo_template/skills/task-schedule/SKILL.md",
  ".repo_template/skills/task-work/SKILL.md",
  ".repo_template/skills/template-issue-report/SKILL.md",
  ".repo_template/sync_manifest.json",
  ".repo_template/tests/pytest.ini",
  ".repo_template/tests/review_support.py",
  ".repo_template/tests/test_check_review_status.py",
  ".repo_template/tests/test_contract_suite.py",
  ".repo_template/tests/test_plan.py",
  ".repo_template/tests/test_repo_cleanup.py",
  ".repo_template/tests/test_specs_index.py",
  ".repo_template/tests/test_task_archive_dir.py",
  ".repo_template/tests/test_task_document_validation.py",
  ".repo_template/tests/test_task_save.py",
  ".repo_template/tests/test_task_unverified.py",
  ".repo_template/tests/test_validation_policy.py",
  ".repo_template/tests/test_view_server.py"
]
```
