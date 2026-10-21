# 发版说明

历史变更记录见 [docs/archive/CHANGELOG.md](../archive/CHANGELOG.md)。

## 分支与版本

- 稳定分支：`main`。版本号 `MAJOR.MINOR.PATCH`，写在 `VERSION`。
- 本仓库无 GitHub Actions 远程发布工作流；发版前必须在本地完成全量校验与测试，打标签 `vX.Y.Z` 仅用于代码归档标记。

## 产物

|产物|来源|
|---|---|
|Docker 镜像|`Dockerfile.mail-core`（API + worker + SPA）|
|桌面安装包|`src/desktop/`：`./scripts/build-sidecar.sh`（PyInstaller 打包 `python -m mail_core`）+ `scripts/fetch-pg-binaries.sh`（内置 PostgreSQL）+ `npm run dist:<平台>`|

## 发版前检查

1. 本地全量测试通过：
    - 门禁契约：`pytest .repo_template/tests -q -m contract`
    - 后端：`scripts/run-mail-core-tests.sh`（包含 alembic 迁移升级与完整 DB 测试）
    - 前端：`(cd src/frontend && npm run lint && npx tsc -b && npm test && npm run build)`
    - 桌面：`(cd src/desktop && npm test)`
    - 端到端：`npm --prefix src/frontend run test:e2e`
2. `VERSION` 与 `src/desktop/package.json` 版本号已同步更新。
3. 新增迁移已在干净库上 `alembic upgrade head` 验证，且 `/ready` 为 200。
4. 架构与指南变化已写入 `docs/`。

## 步骤

```bash
git checkout main && git pull
echo X.Y.Z > VERSION   # 并补 src/desktop/package.json
git add VERSION src/desktop/package.json
git commit -m "chore(release): vX.Y.Z" && git push origin main
git tag vX.Y.Z && git push origin vX.Y.Z
```

## 发版后核对

- 桌面包首次启动：生成 `secrets/` 与一次性初始密码（`<data-dir>/initial-password.txt`），`/health` 正常。
