# kkmail

基于 mail-core 的现代化自托管多账号邮件客户端。后端为 FastAPI + PostgreSQL + Worker，前端为 React SPA（同源托管），桌面版基于 Electron 调度本地嵌入式后端。

- 代码仓库：https://github.com/TuTouPower/kkmail
- 规范框架：采用 `repo_template` 自动化工作流与 Blueprint 契约体系

## 快速开始

自托管部署请参阅 **[docs/guides/deployment.md](docs/guides/deployment.md)**。本地快速开发调试：

```bash
# 1. 准备后端环境与依赖
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-mail-core.txt -r requirements-dev.txt

# 2. 构建前端单页应用
cd src/frontend && npm ci && npm run build && cd ../..

# 3. 配置数据库与启动服务（需本地 PostgreSQL 16）
export MAIL_CORE_DATABASE_URL="postgresql+psycopg://user:pass@127.0.0.1:5433/kkmail_mail"
export PYTHONPATH=src
python3 -m mail_core --data-dir ./.kkmail-data
```

`python3 -m mail_core --data-dir` 首次运行会在 `<data-dir>/secrets/` 自动生成所需密钥，并在 `<data-dir>/initial-password.txt` 写入一次性初始登录密码。首次登录后立即改密，改密会自动删除该文件；未改密前按密钥文件同等保护。详见 [docs/guides/security.md](docs/guides/security.md)。

## 核心安全基线

实例为**单用户架构**：登录会话 Cookie 或 Bearer API Key 是唯一安全边界。资源 UUID 即能力凭据（Capability-based），非多租户行级 ACL。详见 [docs/blueprint/conventions.md](docs/blueprint/conventions.md) 与 [docs/guides/security.md](docs/guides/security.md)。

## 文档导航

|主题|文档落点|说明|
|:---|:---|:---|
|**系统架构蓝图**|[docs/blueprint/architecture.md](docs/blueprint/architecture.md)|系统拓扑、模块分层与数据流转（长期真相）|
|**领域实体模型**|[docs/blueprint/domain.md](docs/blueprint/domain.md)|核心概念、数据库表与中英术语表|
|**工程约定与安全**|[docs/blueprint/conventions.md](docs/blueprint/conventions.md)|安全沙箱、UUID 能力模型、CSRF 与状态防损|
|**架构决策日志**|[docs/blueprint/decisions.md](docs/blueprint/decisions.md)|密码持久化方案 A、IMAP 阻断策略等重大取舍|
|**门禁与测试规范**|[docs/blueprint/testing.md](docs/blueprint/testing.md)|全套日常测试、端到端与契约校验命令|
|**需求规格索引**|[docs/specs_index.md](docs/specs_index.md)|当前生效 Spec 汇总列表（在表即生效）|
|**部署指南**|[docs/guides/deployment.md](docs/guides/deployment.md)|Docker Compose 自托管与多环境配置手册|
|**故障排查手册**|[docs/guides/troubleshooting.md](docs/guides/troubleshooting.md)|数据库改密、常见连接与运行故障解决|
|**升级与备份**|[docs/guides/upgrade.md](docs/guides/upgrade.md)|数据备份、加密还原与数据库迁移操作|
|**桌面端指南**|[docs/guides/desktop.md](docs/guides/desktop.md)|Electron 架构与跨平台 PostgreSQL 依赖|
|**安全配置指南**|[docs/guides/security.md](docs/guides/security.md)|会话吊销、反向代理受信与请求限速说明|
|**版本发布说明**|[docs/guides/release.md](docs/guides/release.md)|标签发布与产物验证指南|
|**接口数据契约**|[schemas/openapi.json](schemas/openapi.json)|统一 OpenAPI 3.1 机器可读接口契约|
|**设计系统规范**|[DESIGN.md](DESIGN.md)|视觉 Design Tokens 与交互规范|
|**编码代理指南**|[AGENTS.md](AGENTS.md)|模板分区协议与规范开发原则|
