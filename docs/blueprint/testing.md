# 测试 (Testing & Verification)

项目质量门禁与验证命令。章节名 `doctor_cmd` / `test_cmd` / `blackbox_verify` 是 preflight 与 skill 的机械锚点，不可更改。

## doctor_cmd

环境前置检查：工具链契约测试可成功收集；Markdown 格式化器存在。

```bash
pytest .repo_template/tests -q --collect-only -m contract
command -v md_kx || true
```

## test_cmd

日常全量门禁命令（单元测试、静态类型检查、生产构建与契约核验）：

```bash
pytest .repo_template/tests -q -m contract
pytest tests/mail_core -q
(cd src/frontend && npm test && npx tsc -b && npm run build)
(cd src/desktop && npm test)
```

## blackbox_verify

浏览器端到端轻量冒烟验证：

```bash
npm --prefix src/frontend run test:e2e
```

## Schema / codegen 验证

- **触发路径**：`src/mail_core/api/` (路由与 DTO 改动)、`schemas/openapi.json`、`src/mail_core/db/alembic/versions/`
- **生成命令**：
    ```bash
    python3 scripts/export_openapi.py
    (cd src/frontend && npm run openapi:gen)
    ```
- **验证命令**：
    ```bash
    python3 scripts/export_openapi.py --check
    (cd src/frontend && npm run openapi:check)
    ```
- **合并后动作**：确认生成文件已暂存，无 schema drift。
- **migration 窗口**：涉及数据库表变动时编写 Alembic 迁移脚本，版本号保持严格线性无分叉。

## 门禁类别覆盖清单

|类别|项目对应实现|命令或验证方式|
|:---|:---|:---|
|**前端单元/组件测试**|React 组件与缓存逻辑|`(cd src/frontend && npm test)`|
|**前端类型检查**|全局 TypeScript 强类型|`(cd src/frontend && npx tsc -b)`|
|**前端生产构建**|Vite 生产打包|`(cd src/frontend && npm run build)`|
|**桌面端测试**|Node 进程管理、路径与安全|`(cd src/desktop && npm test)`|
|**模板契约测试**|工具链合法性冒烟|`pytest .repo_template/tests -q -m contract`|
|**后端单元/集成测试**|FastAPI + PG + Worker|`scripts/run-mail-core-tests.sh`|
