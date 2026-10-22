# Bundle Review — dir:.repo_template/scripts/repo_task_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [High][98] .repo_template/scripts/repo_task/integration.py:218-L240 — 并发 task start 补偿可能删除另一会话创建的 worktree 和分支 — 证据：失败会话只按同一 branch 与 base SHA 判断资源归属；并发会话先成功创建 worktree 后，失败会话可将其强制清理。 — 依据：多会话并发约定见 .repo_template/docs/usage.md:75。 — 修复：用仓库级锁覆盖检查、创建、初始化及补偿；只删除本调用可证明创建的资源。
- [Medium][90] .repo_template/scripts/repo_task/plan.py:435-L466 — 冲突定序边可能与硬依赖成环，fallback 会输出违反依赖的计划 — 证据：冲突关系按 task ID 加排序边后可能和 depends_on 构成环；cycle fallback 再按 ID 输出，破坏依赖先后。 — 依据：task plan 必须满足登记的硬依赖。 — 修复：只为无依赖关系的冲突任务定序；真依赖环应报错或阻塞。
- [Low][98] .repo_template/scripts/repo_task/lifecycle.py:493-L508 — drop 归档失败恢复状态时会遗留重复 dropped note — 证据：先追加 note 再移动归档；移动失败只恢复 status，note 保留，重试可重复追加。 — 依据：操作失败需恢复写入前的 task 状态。 — 修复：归档成功后追加 note，或失败时恢复 front matter 快照。
- [Low][93] .repo_template/scripts/repo_task/lifecycle.py:687-L700 — purge 审计失败恢复 task 目录后没有重建派生索引 — 证据：索引先重建、审计随后失败时会恢复 task 目录但不再重建 index，派生清单缺项。 — 依据：task index 为派生视图，需与权威目录一致。 — 修复：恢复目录后重建 index，并报告恢复后的实际位置。
- [Low][88] .repo_template/scripts/repo_task/lifecycle.py:642-L653 — rewind 审计成功而 front matter 写失败会形成状态分叉 — 证据：审计先记录 rewind，随后 front matter 写入失败；task 仍处于旧状态，worktree/branch 清理可能已经完成。 — 依据：状态与审计记录需可恢复、幂等。 — 修复：让审计和状态更新可恢复、幂等，并在写失败时准确补偿。

## Files examined

- .repo_template/scripts/repo_task/integration.py
- .repo_template/scripts/repo_task/ledger.py
- .repo_template/scripts/repo_task/lifecycle.py
- .repo_template/scripts/repo_task/locks.py
- .repo_template/scripts/repo_task/monitoring.py
- .repo_template/scripts/repo_task/plan.py
- .repo_template/scripts/repo_task/recovery.py
- .repo_template/scripts/repo_task/review.py
