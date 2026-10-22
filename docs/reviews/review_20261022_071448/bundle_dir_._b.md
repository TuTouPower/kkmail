# Bundle Review — dir:.\_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 4 allowlisted tracked files

## Findings

- [Medium][96] docker-compose.mail-core.yml:33-L83 — distributed profile 的 API 与 migrate 容器会并发执行 Alembic — 证据：两者都只依赖 Postgres healthy；API 命令默认执行 alembic upgrade head，未依赖 migrate 完成。首次部署或待升级时可能并发 DDL/API 先于 schema 完成启动。 — 依据：src/mail_core/__main__.py:69-70；worker 已依赖 migrate 完成（compose:103-104）。 — 修复：distributed 拓扑只保留一个 migration runner；API 禁止自迁移并等待 migrate 成功，同时保留单进程默认启动路径。
- [Medium][99] docker-compose.mail-core.yml:68-L97 — distributed profile 同时启动内嵌与独立 worker 且共用 worker ID — 证据：API 默认启动 embedded worker，worker 容器又启动 worker；两者 MAIL_CORE_WORKER_ID 均为 compose-worker-1，互增 fencing token 会令另一进程提交失败并产生重试。 — 依据：src/mail_core/__main__.py:44,69-74；src/mail_core/sync/leases.py:80-90。 — 修复：distributed API 禁用 embedded worker，独立 worker 使用唯一实例 ID。

## Files examined

- VERSION
- docker-compose.mail-core.yml
- requirements-dev.txt
- requirements-mail-core.txt
