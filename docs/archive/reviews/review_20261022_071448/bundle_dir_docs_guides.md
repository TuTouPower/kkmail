# Bundle Review — dir:docs/guides

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 6 allowlisted tracked files

## Findings

- [Low][100] docs/guides/desktop.md:77-L81 — 桌面打包指南声称缺 PostgreSQL 时支持外接数据库，与实现冲突 — 证据：指南写缺少 vendor/pgsql 可生成壳层且启动需要 external DB；同文件第 48 行与主进程则说明无 PostgreSQL 会 fatal，代码不存在外部 DB 连接回退。 — 依据：src/desktop/postgresManager.js 与 src/desktop/main.js；指南另见第 48 行。 — 修复：按实际唯一 PostgreSQL 子进程行为修正文档或实现，并统一本地构建说明。

## Files examined

- docs/guides/deployment.md
- docs/guides/desktop.md
- docs/guides/release.md
- docs/guides/security.md
- docs/guides/troubleshooting.md
- docs/guides/upgrade.md
