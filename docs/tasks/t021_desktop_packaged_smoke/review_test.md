# t021 测试审查

## 范围与执行方式

核查桌面打包产物冒烟与嵌入式 PostgreSQL 生命周期测试：

- `src/desktop/scripts/packaged-smoke.js` (严格打包冒烟测试)
- `src/desktop/postgresManager.test.js` (内置 PG 进程管理器单元测试与真实启停验证)
- `src/desktop/package.json` 中的 `test` 与 `test:packaged`

## 门禁验证结果

1. **打包产物真实冒烟**: `npm run --prefix src/desktop test:packaged` 执行通过。验证 `mac-arm64` 打包产物内真实 SPA 前端（无 stub）、真实 PostgreSQL 二进制（initdb/pg_ctl/postgres）、首启建库、密码落库 0600、停止后端口释放、重启同一 dataRoot 保留状态不重置。
2. **桌面基础测试套件**: `npm run --prefix src/desktop test` 6 项测试全通，包含 `postgresManager.test.js: real start/stop smoke ok`。

## 结论

PASS。测试严格摆脱了纯 stub 模式，证明实际打包产物包含并能正确运行真实内置数据库。
