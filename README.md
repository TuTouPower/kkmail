# kkmail

多账号邮件客户端。后端是 **mail-core**（FastAPI + PostgreSQL + worker），前端是 `frontend/` 下的 React SPA，由 mail-core 同源提供。桌面版（`desktop/`）用 Electron 启动本地 PostgreSQL 与 mail-core sidecar。

仓库：https://github.com/TuTouPower/kkmail

## 快速开始

服务器 / 自托管部署见 **[docs/deployment.md](docs/deployment.md)**（唯一部署说明）。本地开发：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cd frontend && npm ci && npm run build && cd ..
# 需要一个 PostgreSQL 16 实例，然后：
python -m mail_core --data-dir ./.kkmail-data   # 迁移 + API + 内嵌 worker，监听 127.0.0.1:8000
```

`python -m mail_core` 首次运行会在 `--data-dir/secrets/` 生成会话、blob、备份密钥，以及一次性的 `initial-password.txt`（登录后修改密码即删除）。数据库连接由 `MAIL_CORE_DATABASE_URL` 指定，未设置时拒绝启动。

## 文档

| 主题 | 文档 |
| --- | --- |
| 部署 | [docs/deployment.md](docs/deployment.md) |
| 架构 | [docs/mail-core-architecture.md](docs/mail-core-architecture.md) |
| 后端模块 / 配置 | [mail_core/README.md](mail_core/README.md) |
| HTTP API | 运行中的 `/docs`（Swagger）与 `/openapi.json`，见 [docs/api.md](docs/api.md) |
| 安全 | [docs/security.md](docs/security.md) |
| 桌面版 | [docs/mail-core-desktop.md](docs/mail-core-desktop.md) |
| 已知限制 | [docs/known-limitations.md](docs/known-limitations.md) |
| 实现状态 | [docs/mail-core-status.md](docs/mail-core-status.md) |
| 故障排查 / 升级 | [docs/troubleshooting.md](docs/troubleshooting.md) · [docs/upgrade.md](docs/upgrade.md) |
| UI 设计令牌 | [DESIGN.md](DESIGN.md) |
| 发布 / 分支保护 / 变更 | [RELEASE.md](RELEASE.md) · [BRANCH_PROTECTION.md](BRANCH_PROTECTION.md) · [CHANGELOG.md](CHANGELOG.md) |
| 编码代理约定 | [AGENTS.md](AGENTS.md) |
