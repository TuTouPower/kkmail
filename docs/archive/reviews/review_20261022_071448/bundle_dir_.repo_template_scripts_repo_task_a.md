# Bundle Review — dir:.repo_template/scripts/repo_task_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][96] .repo_template/scripts/repo_task/documents.py:11-L72 — task title/note 含换行可破坏权威 front matter — 证据：输入仅转义引号与反斜线，多行值被写入按行解析的 front matter，后续 task parser 可能无法读取。 — 依据：task.md 是 task 状态权威文件。 — 修复：拒绝换行和控制字符，或正确编码并验证 YAML 往返解析。
- [Low][86] .repo_template/scripts/repo_task/documents.py:370-L380 — AC 提取器会把 fenced code 中的示例误识别为验收条件 — 证据：解析器只按 AC 标记提取，没有跳过 Markdown fenced code；示例 ID 可能进入真实 handoff 清单。 — 依据：handoff 证据应对应正文中的真实 AC。 — 修复：跳过 fenced code，并统一使用结构化 AC 解析。

## Files examined

- .repo_template/scripts/repo_task/__init__.py
- .repo_template/scripts/repo_task/attempts.py
- .repo_template/scripts/repo_task/cli.py
- .repo_template/scripts/repo_task/context.py
- .repo_template/scripts/repo_task/control.py
- .repo_template/scripts/repo_task/documents.py
- .repo_template/scripts/repo_task/git_ops.py
- .repo_template/scripts/repo_task/goal.py
