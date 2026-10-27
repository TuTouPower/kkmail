# Bundle Review — dir:.repo_template/scripts_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [High][96] .repo_template/scripts/repo_cleanup.py:124-L213 — 清理目标根目录为软链时会扫描并删除仓外数据 — 证据：点名 .scratch、artifacts 或 data 后，扫描其后代并对匹配项执行 unlink/rmtree；若根本身指向仓外目录，apply 会作用于仓外路径。 — 依据：cleanup 目录边界与 repo-cleanup/SKILL.md:15-16 的确认约定。 — 修复：扫描和 apply 均拒绝根软链，并在删除前解析确认目标仍位于仓根内。
- [High][99] .repo_template/scripts/md_format.py:117-L193 — Markdown 格式化器接受绝对路径和路径遍历并可改写仓外文件 — 证据：调用参数未经仓根 containment 校验；REPO_ROOT / rel 可接收绝对路径或 ../../，随后传给 md_kx。 — 依据：脚本说明要求仓内路径，但当前没有对应运行时验证（md_format.py:7-10,117-145）。 — 修复：解析 realpath 并验证仓根包含关系；拒绝逃逸软链及仓外路径。
- [Medium][95] .repo_template/scripts/repo_cleanup.py:284-L290 — 清理 apply 重扫后会删除未展示给用户的新命中项 — 证据：apply 阶段重扫目录后直接删除新出现的匹配项，没有核对与用户先前审阅的 scan 清单是否一致。 — 依据：违反 repo-cleanup/SKILL.md:15-16 的变化后重新确认约定。 — 修复：apply 比较 scan 清单摘要；期间变化时停止并重新展示清单。
- [Medium][91] .repo_template/scripts/md_format.py:122-L151 — 批量格式化遇到 IO/超时异常会留下部分已格式化文件 — 证据：恢复逻辑只捕获 MdFormatError；子进程 TimeoutExpired、OSError 或读写错误可逃出，前面完成的文件不回滚。 — 依据：批量命令应保证失败后状态可解释且一致。 — 修复：捕获预期 IO/子进程异常并统一恢复，报告恢复失败路径。
- [Medium][84] .repo_template/scripts/pending.py:176-L224 — 批量 pending 迁移在 IO 或 Git 异常时可能半迁移 — 证据：回滚只针对 IdScanError；OSError 或 git 超时等异常可让部分文件已迁移后直接退出。 — 依据：pending 状态仅允许经脚本迁移，失败应保留一致状态。 — 修复：捕获预期文件和 Git 异常并统一回滚；列出无法恢复的路径。
- [Low][76] .repo_template/scripts/check_review_status.py:33-L35 — review status 与 task view 脚本保留未使用 imports — 证据：check_review_status.py 和 repo_task/view_server.py 中存在未使用导入，增加维护噪声。 — 依据：死代码扫描项。 — 修复：删除确认未使用的 imports。

## Files examined

- .repo_template/scripts/\_id_scan.py
- .repo_template/scripts/check_review_status.py
- .repo_template/scripts/findings.py
- .repo_template/scripts/md_format.py
- .repo_template/scripts/package.json
- .repo_template/scripts/pending.py
- .repo_template/scripts/render_review_prompts.py
- .repo_template/scripts/repo_cleanup.py
