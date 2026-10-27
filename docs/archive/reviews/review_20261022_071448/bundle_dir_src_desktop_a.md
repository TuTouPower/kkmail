# Bundle Review — dir:src/desktop_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][96] src/desktop/logRotation.js:112-L112 — 日志轮换或退出时可能丢失尚未完成的异步写入 — 证据：队列数据先出队再 fs.write，回调不检查 error/bytesWritten；轮换与 end 可在写入回调前关闭 fd，main 在 exit 或 close 任一事件到达时结束流。 — 依据：src/desktop/main.js:247；exit 可早于 stdout/stderr 完全排空。 — 修复：串行化写、轮换和关闭，处理部分写入/错误；等 close 后结束流。
- [Low][95] src/desktop/README.md:8-L34 — 前端与桌面文档仍引用迁移前路径和不存在的架构文档 — 证据：桌面 README 指示 cd desktop 并链接 docs/mail-core-desktop.md；前端 README 仍用 cd frontend 并链接不存在的文档；桌面指南和安全指南也指向旧 desktop/main.js、hardening.js 路径，src/mail_core/__init__.py:3 指向已不存在的架构文件。 — 依据：实际目录为 src/desktop、src/frontend；当前权威文档位于 docs/blueprint/ 与 docs/guides/。 — 修复：统一更正工作目录、文件路径和相对链接。

## Files examined

- src/desktop/README.md
- src/desktop/hardening.js
- src/desktop/hardening.test.js
- src/desktop/icon.svg
- src/desktop/logRotation.js
- src/desktop/logRotation.test.js
- src/desktop/main.js
- src/desktop/package.json
