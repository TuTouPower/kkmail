# bundle_local_scripts_and_ops

## responsibilities

- 提供 mail-core 及其依赖服务（PostgreSQL、Dovecot、Worker）的容器化编排与 Docker 构建配置
- 提供自动化部署流程脚本，覆盖主分支保护、自动全量加密备份验证、镜像构建打标与静态资源一致性校验
- 提供端到端测试运行环境隔离支持（test_pg_runtime），管理测试专用 PG 实例与临时数据库生命周期
- 管理第三方二进制分发物安全拉取（fetch-pg-binaries.sh），执行域名白名单过滤、归档 SHA-256 固定校验及防路径穿越解压
- 提供开发与构建辅助工具，包括依赖 lockfile 校验、OpenAPI 契约导出、邮箱基准压测工具及权限规范化工具

## interfaces

- docker compose profile 接口（distributed, maintenance, imap）
- scripts/deploy_mail_core.sh CLI 入口（--no-push）
- scripts/run-mail-core-tests.sh 测试调度入口
- scripts/fetch-pg-binaries.sh 二进制拉取入口（--os, --arch, --version, --allow-unpinned）
- scripts/export_openapi.py CLI（--check）
- scripts/check_dep_locks.py CLI（--check）

## dependencies

- Docker & Docker Compose（OrbStack / Docker Desktop 环境）
- PostgreSQL 16（官方镜像 postgres:16.15 与 theseus-rs 便携分发包）
- uv / pip-tools（Python 依赖锁定与编译）
- Dovecot（测试用轻量 IMAP 镜像）
- Node.js 22 & npm（前端构建阶段）

## flows

- 部署流程：检查环境与工作区 clean -> git 祖先校验 -> 自动运行加密全量备份 -> 打标 rollback 镜像 -> build 与 up 服务 -> 轮询 /ready 与 /health -> 校验前端静态资源 -> 输出部署结果
- 测试 PG 运行时流：检查 Docker -> 启动隔离 compose 容器 -> 生成随机租户 DB 与密码 -> 执行 Alembic 迁移 -> 注入环境变量并执行 pytest -> 销毁临时 DB 保持宿主环境纯净
- 备份演练流程：解析安全目录 -> 执行备份并在隔离容器中导出包 -> 解密还原 dry-run -> 验证数据结构与成员完整性

## constraints

- 生产环境必须启用宿主磁盘/卷加密（Docker volume 不提供加密）
- POSTGRES_PASSWORD 仅允许 URL 安全字符（^[A-Za-z0-9\_-]+$），防止 DATABASE_URL 拼接截断
- 禁止裸 docker compose up，必须通过 --profile distributed 显式指定 api worker migrate
- 容器运行降权：Dockerfile 中使用 kkmail (uid 10001) / 10001:999 运行，关闭特权提升并丢弃全部 Linux Capabilities
- 仅允许从指定白名单源拉取 PG 二进制，且强制要求 SHA-256 校验

## decisions

- 备份导出采用无宿主目录挂载设计，由 host 端通过 docker cp / export 提取，避免 0600 权限文件在跨 uid 挂载时的写冲突与信息泄漏
- 测试运行时采用完全独立的容器与临时命名空间，杜绝测试代码意外篡改生产/开发数据库
- 前端静态文件直接打包进 Python 镜像，由 FastAPI / KKMAIL_FRONTEND_DIST 同源托管提供

## evidence

- docker-compose.mail-core.yml:47-196（cap_drop [ALL], no-new-privileges, 绑定 loopback）
- Dockerfile.mail-core:17-20（USER kkmail 降权与依赖哈希校验）
- Dockerfile.mail-core-backup:17-22（USER 10001:999 权限与隔离路径）
- scripts/deploy_mail_core.sh:45-198（密码正则校验、备份导出、静态资源一致性比对）
- scripts/fetch-pg-binaries.sh:24-103（域名白名单、SHA-256 强校验、防穿越提取）
- scripts/test_pg_runtime.py:42-76（凭据脱敏回显、独立测试 DB 隔离管理）

## uncertainties

## Findings

No findings.

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_ops"
  }
}
```

## files_reviewed

```json
[
  ".claude/settings.json",
  ".dockerignore",
  ".env.example",
  ".gitignore",
  ".md_kx.toml",
  ".prettierignore",
  "Dockerfile.mail-core",
  "Dockerfile.mail-core-backup",
  "VERSION",
  "assets/email-icons/126.svg",
  "assets/email-icons/139.svg",
  "assets/email-icons/163.svg",
  "assets/email-icons/189.svg",
  "assets/email-icons/aliyun.svg",
  "assets/email-icons/default-mail.svg",
  "assets/email-icons/enterprise.svg",
  "assets/email-icons/exchange.svg",
  "assets/email-icons/foxmail.svg",
  "assets/email-icons/gmail.svg",
  "assets/email-icons/google.svg",
  "assets/email-icons/icloud.svg",
  "assets/email-icons/outlook.svg",
  "assets/email-icons/protonmail.svg",
  "assets/email-icons/qq.svg",
  "assets/email-icons/sina.svg",
  "assets/email-icons/sohu.svg",
  "assets/email-icons/variants/qq-original.svg",
  "assets/email-icons/variants/qq-variant-b.svg",
  "assets/email-icons/variants/yandex-original.svg",
  "assets/email-icons/variants/yandex-variant-b.svg",
  "assets/email-icons/variants/yandex-variant-c.svg",
  "assets/email-icons/yahoo.svg",
  "assets/email-icons/yandex.svg",
  "assets/email-icons/yeah.svg",
  "config/.env.example",
  "config/test_pg_compose.yaml",
  "docker-compose.mail-core.yml",
  "requirements-ci.in",
  "requirements-dev.txt",
  "requirements-mail-core.txt",
  "scripts/benchmark_mailbox.py",
  "scripts/build-sidecar.sh",
  "scripts/check_dep_locks.py",
  "scripts/deploy_mail_core.sh",
  "scripts/export_openapi.py",
  "scripts/fetch-pg-binaries.sh",
  "scripts/gen-openapi.sh",
  "scripts/mail-core-backup-restore-drill.sh",
  "scripts/mail-core-chaos-lease.sh",
  "scripts/migrate_from_legacy_db.py",
  "scripts/normalize_mail_core_permissions.py",
  "scripts/run-mail-core-tests.sh",
  "scripts/run_full_stack_e2e.py",
  "scripts/start-mail-core-imap.sh",
  "scripts/test_pg_client/pg_dump",
  "scripts/test_pg_client/pg_restore",
  "scripts/test_pg_runtime.py"
]
```
