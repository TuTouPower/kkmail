# Bundle Review — dir:.repo_template/scripts_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 6 allowlisted tracked files

## Findings

- [High][99] .repo_template/scripts/repo_sync.py:590-L649 — 模板同步可跟随目标软链写入仓外文件 — 证据：目的地文件或目录为 symlink 时写入会跟随链接；回滚备份保留的是链接本身，无法还原被覆盖的目标文件。 — 依据：模板同步回滚需覆盖实际写入目标；代码在 repo_sync.py:124-137,590-597 未做 containment 校验。 — 修复：拒绝目标路径软链，或验证 realpath 始终在消费仓内并按目标内容备份恢复。
- [Medium][94] .repo_template/scripts/repo_sync.py:428-L496 — worktree 查询失败被当作无活动 worktree 并放行 schema 迁移 — 证据：git worktree list 失败返回空列表，后续迁移门禁据此误判没有活动 worktree。 — 依据：repo_template/docs/usage.md:100 要求存在活动 worktree 时阻断迁移。 — 修复：命令失败按未知状态处理并 fail closed，保留错误诊断。
- [Medium][92] .repo_template/scripts/repo_sync.py:1294-L1296 — 拼错的本地模板路径会被保存为远端 URL 并覆盖原来源 — 证据：本地路径不存在时落入 URL 分支，随后写入 state，原有 template_source 被替换。 — 依据：state 是后续同步的来源权威；不存在的本地路径不应改变它。 — 修复：区分本地路径与 URL；本地路径不存在时在写 state 前拒绝。
- [Medium][90] .repo_template/scripts/repo_sync.py:194-L200 — 固定 state.tmp 无锁写入会让并发同步丢失保护状态 — 证据：多个会话同时读取旧 state、各写同名临时文件并 replace，后写者可覆盖先写入的 user prompt。 — 依据：state 中的保护项需跨会话保留。 — 修复：增加 state 锁，锁内重新读取合并，并使用唯一临时文件。
- [Medium][88] .repo_template/scripts/repo_sync.py:1544-L1569 — state 写入失败不在内容回滚事务内 — 证据：模板文件修改与测试结束后才调用 write_state；该调用位于异常恢复区外，写 state 失败会留下新内容和旧 state。 — 依据：repo-template-sync-core/SKILL.md:33-34 规定写盘失败恢复。 — 修复：把 state 更新纳入事务，或失败时恢复模板文件并保留诊断备份。
- [Medium][92] .repo_template/scripts/repo_sync.py:1099-L1136 — 合法 JSON 的错误 MCP 结构会触发未捕获异常且跳过回滚 — 证据：顶层数组或 mcpServers 为列表等合法 JSON 结构被按 dict 使用，可抛 AttributeError/TypeError；若此前已写文件则统一回滚逻辑不会执行。 — 依据：同步输入需结构校验且纳入统一事务处理。 — 修复：验证顶层及 mcpServers 均为对象，并将结构异常纳入回滚分支。
- [Medium][91] .repo_template/scripts/repo_sync.py:142-L160 — 回滚恢复错误被吞掉却仍报告完整回滚 — 证据：恢复各路径时异常被忽略；测试失败路径仍输出完整恢复语义，用户无法知道哪些文件未还原。 — 依据：错误处理需准确反映回滚结果。 — 修复：收集每个恢复失败路径；仅全部成功时报告完整回滚。
- [Low][78] .repo_template/scripts/repo_hygiene.py:175-L184 — archive-review 参数未限制为 review basename — 证据：参数仅要求以 review\_ 开头，未拒绝路径分隔符或 ..，可能让归档命令尝试迁移 reviews 目录外的路径；git mv 的实际行为尚未验证。 — 依据：归档操作应限定在 docs/reviews/ 内。 — 修复：严格校验 basename 格式，并验证源与目标 realpath 的父目录边界。
- [Low][81] .repo_template/scripts/repo_sync.py:1256-L1266 — 契约测试超时未进入正常失败与恢复处理 — 证据：subprocess.run 超时抛出 TimeoutExpired，异常没有统一捕获，会输出 traceback 并绕过可读恢复提示。 — 依据：同步失败需维持一致的诊断与恢复路径。 — 修复：捕获 TimeoutExpired 并按测试失败恢复策略处理。

## Files examined

- .repo_template/scripts/repo_hygiene.py
- .repo_template/scripts/repo_state.py
- .repo_template/scripts/repo_sync.py
- .repo_template/scripts/spikes.py
- .repo_template/scripts/task.py
- .repo_template/scripts/track_worktree.py
