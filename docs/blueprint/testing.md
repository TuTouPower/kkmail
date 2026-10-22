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
scripts/run-mail-core-tests.sh run
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
|**后端单元/集成测试**|FastAPI + PG + Worker|`scripts/run-mail-core-tests.sh run`|

## PostgreSQL 测试运行时（t013）

环境安装与测试执行分开，复用仓库 `.venv`：

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

启动前由操作者设置随机专用 `KKMAIL_TEST_PG_PASSWORD`。禁止复用业务 `.env` 密码。服务采用 `config/test_pg_compose.yaml`，独立 Compose project `kkmail_test_pg`，PostgreSQL 16 仅绑定 `127.0.0.1`，默认端口 15433；端口可经 `KKMAIL_TEST_PG_PORT` 指定。不得连接业务 Compose 或挂载业务卷。

```bash
scripts/run-mail-core-tests.sh start
scripts/run-mail-core-tests.sh run
scripts/run-mail-core-tests.sh unit
scripts/run-mail-core-tests.sh stop
```

`start` 显式启动或复用测试服务；`run` 要求服务已启动，每轮创建唯一 `kkmail_test_<UUID>` 数据库，经生产 Alembic 升级后运行 Python 套件。容器 ID、PG cluster system identifier、数据库 comment 和仓库所有权记录必须一致，才允许迁移、fixture 删除和清理。直接 pytest 也执行保护；URL 查询参数一律拒绝。`unit` 明确报告未执行 PG 套件，不代表全量通过。

每轮数据库、Blob、备份、临时文件和 JUnit 报告对应 `.scratch/test_runs/<UUID>/`。正常结束、断言失败、SIGINT/SIGTERM 后清理本轮子进程和数据库，不停止常驻服务；所有权记录与报告保留。阶段日志输出耗时和状态，不打印数据库 URL 或密码。强制终止后，仅允许指定确切 UUID 回收：

```bash
scripts/run-mail-core-tests.sh cleanup <run_uuid>
```

所有权或实例身份不符时拒绝清理；不扫描删除未知数据库。显式 `stop` 遇到带运行标记的数据库时拒绝停止。每轮使用独立 NOLOGIN owner role 原子标记建库归属，覆盖建库与 comment 写入间中断；creating 状态仅回收所有者匹配的确切数据库，运行态额外要求 comment 匹配。

当前验证：17 项保护测试通过，独立仓库并发、真实迁移失败与 SIGTERM 清理已验证。完整套件为 337 passed / 2 failed / 2 skipped，失败集中于前序残留 Outbox 与无 subscriber 的旧测试；完整连续两轮验收待 t014 收口，当前不宣告全量通过。
