# Bundle Review — dir:src/desktop_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 7 allowlisted tracked files

## Findings

- [Medium][97] src/desktop/startup.js:62-L62 — Electron 子进程会继承父 shell 中全部 MAIL_CORE\_/KKMAIL\_ 密钥 — 证据：环境白名单按整个前缀放行；main 与 PostgreSQL 子进程因此收到父 shell 的 login password、API key 或 blob key，initdb/二进制探测部分路径还继承完整环境。 — 依据：src/desktop/README.md:22,53 明确说这些值由启动器设置，不继承父 shell。 — 修复：仅向每个子进程传入必要的显式变量，并为 PostgreSQL 子进程使用最小环境。
- [Medium][99] src/desktop/postgresManager.js:310-L326 — PostgreSQL 停止失败仍返回 stopped=true 且阻止重试 — 证据：停止前设置 \_stopped；即使 pg_ctl 失败也回报 stopped，main 忽略结果，可能让服务继续运行且后续 stop 无法重试。 — 依据：src/desktop/main.js:227 忽略返回值；测试断言 ok || stopped（postgresManager.test.js:157-160）会掩盖失败。 — 修复：仅成功确认停止后设置 \_stopped；返回失败时保留重试并由主进程报告。

## Files examined

- src/desktop/paths.js
- src/desktop/paths.test.js
- src/desktop/postgresManager.js
- src/desktop/postgresManager.test.js
- src/desktop/preload.js
- src/desktop/startup.js
- src/desktop/startup.test.js
