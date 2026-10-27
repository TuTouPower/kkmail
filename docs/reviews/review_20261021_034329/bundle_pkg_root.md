> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

> [!NOTE]
> **勘误注记（A399 / R3-H03）**：本包 `bundle.json` 的 `stats` 字段声称 files: 177 / bundles: 42，与该文件自身数组实数（files 168 / bundles 40，逐项复点）不符。`bundle.json` 为机器文件，其统计字段按处置口径不回写；引用本包范围统计以实数 168 / 40 为准，177 / 42 勿再引用。此注记即为勘误。

# Bundle pkg_root

## Findings

- [High][93] docker-compose.mail-core.yml:50 — api 与 worker 不共享 blob 目录，且未设置 MAIL_CORE_BLOB_ROOT — 两服务都没挂卷、也没设该变量；默认根是各容器自己的 [REDACTED]mail-core-blobs（mail_core/blobs/archive.py:41）。worker 把 MIME/附件写入自己的可写层，API 下载走 mail_core/mail/application/attachments.py 的另一份 blob_root。重建容器后文件消失。备份默认同样落在 [REDACTED]mail-core-backup（mail_core/backup/package.py:484）。本文件 volumes 只有 Postgres（116 行）。正文在库里，不在这份结论里 — 给 api 与 worker 挂同一加密卷，并设置 MAIL_CORE_BLOB_ROOT 与 MAIL_CORE_BACKUP_DIR
- [Medium][85] docker-compose.mail-core.yml:45 — api 与 postgres 没有 restart，worker 却是 unless-stopped — postgres（16 行）与 api（45 行）未写 restart，默认 no；worker 在 98 行是 unless-stopped。守护进程或进程重启后只有 worker 会被拉起，depends_on 不会再次生效，数据库未起时 worker 空转，API 保持停止 — api 与 postgres 改为 restart: unless-stopped；migrate 维持 restart: "no"
- [Low][95] docker-compose.mail-core.yml:52 — MAIL_CORE_PUBLIC_BASE 没有读者 — 全库只有这一处赋值。CORS 源在 mail_core/api/app.py 写死，登录限速看套接字对端，不读该变量 — 删掉该键，或在应用里定义并实现它
- [Low][96] RELEASE.md:8 — 发版说明仍写推送 tag 会触发发布工作流 — .github 下没有 workflow 文件。CHANGELOG.md:37 与 BRANCH_PROTECTION.md:28 写明仓库已无 GitHub Actions。同文件 35 行仍要求 Release 附件齐全且镜像标签可拉取 — 改成当前能执行的本机构建或手动发布，删掉不存在的工作流和镜像发布断言
- [Low][78] RELEASE.md:29 — git commit -am 会收进全部已跟踪改动，推送 main 与 tag 没有恢复步骤 — 该行在改 VERSION 之后立刻 commit -am 并 push origin main，下一行推 tag。工作区里无关改动会进发布提交；错误 tag 或错误提交没有停止、删除 tag 或回退说明 — 只提交 VERSION 与 CHANGELOG，并写明失败时如何停止以及如何删除错误 tag

## Notes

### 安全

未发现 compose 把数据库或 API 绑到 0.0.0.0。postgres 是 127.0.0.1:5433，API 是 127.0.0.1:8000，imap profile 是 127.0.0.1:1143。容器内 uvicorn `--host 0.0.0.0` 只监听容器网络，宿主机发布仍是 loopback。docs/deployment.md 把 5433 的 loopback 发布写成现行部署，不记缺陷。

未发现 docker.sock。未发现可启动的默认口令或示例密钥。POSTGRES_PASSWORD、MAIL_CORE_SECRET_KEY、MAIL_CORE_BLOB_KEY_V1、MAIL_CORE_BACKUP_KEY 使用 `:?`，缺省则 compose 失败。登录口令环境变量允许空字符串，mail_core/security/auth.py 对空值拒绝启动。注释里的 `(set-a-strong-password)` 是占位说明，不是写入镜像的口令。imap 夹具口令在 tests/mail_core/fixtures/dovecot/users，profile 默认不启动，不记入本文件。

CHANGELOG 未发布条目「所有 API 需认证」：邮件、账户、SSE 路由带 require_auth。登录、`/health`、`/ready` 与 SPA 静态页公开，属于入口而不是未授权业务 API，不记缺陷。

### 正确性

blob 分裂见 Findings。正文存在 Postgres（mail_core/mail/storage/models.py 的 body_text），丢失面是归档 MIME 与附件，不是整库。

README 的本地启动与实现一致：默认绑定 127.0.0.1:8000（mail_core/__main__.py），未设置 MAIL_CORE_DATABASE_URL 时 mail_core/db/session.py 拒绝启动，`--data-dir` 生成 0600 密钥，改密后 clear_initial_password 删除 initial-password.txt。

Alpine 3.20 的 busybox `nc` 支持 `-z`，imap healthcheck 写法可以执行。镜像安装了 curl，API healthcheck 与 Dockerfile.mail-core 一致。migrate 只需要数据库 URL，alembic env 不要求 blob 密钥。

### 契约

MAIL_CORE_PUBLIC_BASE 见 Findings。其余 compose 键（数据库 URL、会话密钥、登录口令、blob 密钥版本、备份密钥、API keys）都有对应读取方。deployment.md 要求的 FORWARDED_ALLOW_IPS 是 uvicorn 自身的环境变量，不是 mail-core 配置键；默认不设置时只信任 127.0.0.1，与 loopback 发布不冲突。

### 性能

未发现。这三个服务重复 build 同一 Dockerfile 是否被 Compose 去重，未实测，不报。

### 架构

api / worker 拆进程但不共享 blob 根，见 Findings。AGENTS.md 点到的路径都在：mail_core、frontend/src/api、desktop/postgresManager.js、tests/mail_core、scripts/gen-openapi.sh、scripts/export_openapi.py、tests/mail_core/test_openapi_contract.py、docs/mail-core-architecture.md §11.4。browser-extension、outlook_web、docs/ci 只作为禁止恢复的对象出现，目录已不存在，不是使用说明里的死链。`export_openapi.py --check` 没写 scripts/ 前缀，同句已给出 scripts/gen-openapi.sh，脚本本身在 scripts/export_openapi.py，不记缺陷。

### 健壮性

restart 不一致见 Findings。worker 启动会 load_keyring_from_env，compose 已用 `:?` 提供 blob 与 backup 密钥。登录空口令不会被当成默认密码放行。

### 测试

未发现这些文件里的假断言或跳过失败。compose 是否挂上共享 blob 卷没有自动化检查；该缺口附在 High 那条上，不另计。

### 文档

发版步骤过时见 Findings。README 第 9 行把部署指到 docs/deployment.md，并写明那是唯一部署说明。本地段只覆盖 venv、requirements-dev.txt、前端构建和 `python -m mail_core --data-dir`，没有第二份 compose、反代或密钥流程。不构成双权威。

DESIGN.md 开头写明动作清单是视觉参考，实际交付以 docs/known-limitations.md 为准。没有把「没有发信 / 联系人 / 扩展」报成缺口。抽样核对的主色、表面色和 760px 与 frontend/src/design-system/tokens.css 一致。

CHANGELOG.md 已全文阅读。已发布版本描述的是替换前的 Flask 产品，README 与未发布节没有把那些能力写成当前事实，历史条目不报。未发布节里已核对的当前断言（无 GitHub Actions、compose 只绑 127.0.0.1、无默认密钥、Electron ^44.9.2、前端已去掉 @radix-ui 与 clsx）与仓库一致。

BRANCH_PROTECTION.md 把分支规则写成建议，并把「没有 GitHub Actions、合并前本机测试」写成当前事实，与空的 .github 一致。Optional Future Enhancements 已标成未来。

已完整阅读：AGENTS.md、BRANCH_PROTECTION.md、CHANGELOG.md、DESIGN.md、README.md、RELEASE.md、docker-compose.mail-core.yml，以及 rubric。交叉核对用了 docs/deployment.md、docs/known-limitations.md、mail_core 启动/认证/blob 路径、Dockerfile.mail-core、desktop/package.json、frontend/package.json。
