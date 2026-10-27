# Bundle Review — dir:src/frontend_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Low][98] src/frontend/package.json:12-L14 — 前端 npm 脚本依赖 POSIX shell且 schema 检查失败会遗留临时文件 — 证据：脚本使用 NODE_PATH=... 与 rm -f，Windows 默认 cmd 无法执行；openapi:check 由 && 连接时校验失败会跳过清理。 — 依据：仓库声明支持 Windows 桌面构建。 — 修复：改为 Node 跨平台脚本，临时文件清理放在 finally。

## Files examined

- src/frontend/.env.example
- src/frontend/.gitignore
- src/frontend/.oxlintrc.json
- src/frontend/ARCHITECTURE.md
- src/frontend/README.md
- src/frontend/index.html
- src/frontend/package.json
- src/frontend/playwright.config.ts
