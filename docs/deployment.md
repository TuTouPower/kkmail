# 部署指南（mail-core）

Flask / 上游 outlookemail 镜像路径已移除。请只用 mail-core。

## 推荐：Docker Compose

```bash
export MAIL_CORE_SECRET_KEY="$(openssl rand -hex 32)"
export MAIL_CORE_LOGIN_PASSWORD='换成强密码'
export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export MAIL_CORE_BACKUP_KEY="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"

docker compose -f docker-compose.mail-core.yml up --build -d
```

API + SPA：`http://127.0.0.1:8000`

详见根目录 `README.md`、`docs/mail-core-architecture.md`、`docs/mail-core-cutover.md`。

## CI

工作流模板在 `docs/ci/`；需人工复制到 `.github/workflows/`（仓库 workflow 写权限受限时）。
