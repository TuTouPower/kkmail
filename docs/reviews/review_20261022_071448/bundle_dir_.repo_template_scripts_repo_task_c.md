# Bundle Review — dir:.repo_template/scripts/repo_task_c

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 4 allowlisted tracked files

## Findings

- [Medium][98] .repo_template/scripts/repo_task/view_server.py:51-L55 — 任务看板 JSON 转义可被大小写混合的 script 闭合绕过 — 证据：序列化后只替换小写 \</；HTML script 标签大小写不敏感，标题含 </ScRiPt> 可提前闭合数据块并注入脚本。 — 依据：看板在 view_static/board.html:8 将该值放入 script 数据上下文。 — 修复：将所有 < 编码成 \\u003c，并覆盖大小写混合闭合 payload。
- [Low][84] .repo_template/scripts/repo_task/worktrees.py:15-L78 — worktree env 扫描先递归依赖和缓存目录再过滤 — 证据：env 搜索与清理遍历先进入 node_modules/cache，再过滤结果，依赖树大时做无用递归。 — 依据：脚本注释声称跳过依赖与缓存目录。 — 修复：top-down walk 时剪枝跳过目录，避免进入后再过滤。
- [Low][85] .repo_template/scripts/repo_task/view_server.py:35-L300 — view server 接受 IPv6 loopback 但实际 socket 使用 IPv4 — 证据：参数校验允许 ::1，端口探测和 HTTPServer 却用默认 IPv4；指定 --host ::1 --port 0 无法启动。 — 依据：CLI 应只接受实际可绑定的地址，或提供匹配的 IPv6 server。 — 修复：支持 IPv6 bind，或在参数校验时拒绝并提示。

## Files examined

- .repo_template/scripts/repo_task/scheduling.py
- .repo_template/scripts/repo_task/store.py
- .repo_template/scripts/repo_task/view_server.py
- .repo_template/scripts/repo_task/worktrees.py
