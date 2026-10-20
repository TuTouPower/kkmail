# kkmail

多账号邮件管理工具。**后端仅为 mail-core**（FastAPI + PostgreSQL + worker）；Flask / 上游镜像路径已移除。

仓库：https://github.com/TuTouPower/kkmail

## 快速开始（mail-core）

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-mail-core.txt
cd frontend && npm ci && npm run build && cd ..

export MAIL_CORE_SECRET_KEY="$(openssl rand -hex 32)"
export MAIL_CORE_LOGIN_PASSWORD='换成强密码'
export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export MAIL_CORE_BACKUP_KEY="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"

docker compose -f docker-compose.mail-core.yml up --build -d
# API + SPA: http://127.0.0.1:8000
# Worker 容器已包含在 compose 中
```

本地无 Docker 时，自行启动 Postgres，然后：

```bash
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://kkmail:$POSTGRES_PASSWORD@127.0.0.1:5433/kkmail_mail
alembic -c mail_core/db/alembic.ini upgrade head
uvicorn mail_core.api.app:app --host 127.0.0.1 --port 8000
python -m mail_core.worker.main
```

文档：
- [架构](docs/mail-core-architecture.md)
- [裁切说明](docs/mail-core-cutover.md)
- [安全](docs/security.md)
- [CI 模板](docs/ci/README.md)

---


## 旧版说明

Flask `web_outlook_app.py` / `outlook_web/segments` / 上游 `docker-compose.yml` 镜像路径已删除。请只用 `docker-compose.mail-core.yml`。
