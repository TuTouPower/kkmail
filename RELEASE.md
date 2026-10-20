# 发版说明

分支保护与必需检查见 [BRANCH_PROTECTION.md](BRANCH_PROTECTION.md)；变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 分支与版本

- 开发：`dev`；稳定：`main`。版本号 `MAJOR.MINOR.PATCH`，写在 `VERSION` 与 `CHANGELOG.md`（`## [X.Y.Z] - YYYY-MM-DD`）。
- 推送标签 `vX.Y.Z` 触发发布工作流。

## 产物

| 产物 | 来源 |
| --- | --- |
| Docker 镜像 | `Dockerfile.mail-core`（API + worker + SPA） |
| 桌面安装包 | `desktop/`：`./scripts/build-sidecar.sh`（PyInstaller 打包 `python -m mail_core`）+ `scripts/fetch-pg-binaries.sh`（内置 PostgreSQL）+ `npm run dist:<平台>` |

## 发版前检查

1. `main` 上 `tests` 与 `frontend` 检查通过。
2. `VERSION`、`CHANGELOG.md` 已更新。
3. 新增迁移已在干净库上 `alembic upgrade head` 验证，且 `/ready` 为 200。
4. 行为变化已写入 `docs/`（部署、安全、已知限制）。

## 步骤

```bash
git checkout main && git pull
echo X.Y.Z > VERSION   # 并补 CHANGELOG
git commit -am "chore(release): vX.Y.Z" && git push origin main
git tag vX.Y.Z && git push origin vX.Y.Z
```

## 发版后核对

- Release 附件齐全；镜像标签 `vX.Y.Z` 可拉取。
- 桌面包首次启动：生成 `secrets/` 与一次性初始密码，`/health` 正常。
