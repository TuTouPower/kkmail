---
name: kkmail
description: 接入并操控自托管邮件客户端 kkmail（基于 mail-core）。支持邮件查收、全文搜索、正文与附件读取、已读/星标/废纸篓标记、邮箱账号管理与邮件同步。提供开箱即用的 CLI 工具与标准 REST API 接口规范。
---

# kkmail

通过 CLI 脚本或 REST API 接入并操控自托管邮件客户端 kkmail。

## 环境变量与认证配置

默认连接本地最小化运行态：

- `KKMAIL_BASE_URL`：服务地址，默认为 `http://127.0.0.1:37281`。远程连接必须使用 HTTPS，HTTP 仅限 loopback 本机地址（127.0.0.1, localhost, ::1）。
- `KKMAIL_PASSWORD`：管理员密码。建议通过静默读取注入环境变量，运行后及时清理（避免泄露至命令行参数或 shell 历史）：
    ```bash
    read -s -p "Enter KKMAIL_PASSWORD: " KKMAIL_PASSWORD && export KKMAIL_PASSWORD
    # 运行完成后清理
    unset KKMAIL_PASSWORD
    ```
- `KKMAIL_API_KEY`：可选 Bearer Token（配置 `MAIL_CORE_API_KEYS` 后免 Session/CSRF，亦可通过环境变量 `KKMAIL_API_KEY` 提供）

______________________________________________________________________

## 推荐方式：CLI 工具

Skill 内置零依赖 CLI 执行器，Agent 可直接在终端调用：

```bash
# 路径
CLI="python3 docs/skills/kkmail/scripts/kkmail_cli.py"
```

### 常用命令

1. **服务健康与未读概览**：

    ```bash
    $CLI health
    $CLI stats
    ```

2. **读取收件箱邮件列表**：

    ```bash
    # 获取最新 20 封邮件
    $CLI list --limit 20

    # 仅查看未读邮件
    $CLI list --unread

    # 查看加星标的邮件
    $CLI list --flagged

    # 过滤特定账号邮件
    $CLI list --account <ACCOUNT_ID>

    # 获取原始 JSON 格式（便于 Agent 结构化解析）
    $CLI --json list --limit 10
    ```

3. **阅读邮件详情与正文**：

    ```bash
    # 查看完整元数据与正文
    $CLI read <MESSAGE_ID>

    # 仅输出纯文本正文内容
    $CLI read <MESSAGE_ID> --body-only
    ```

4. **全文检索（支持中英文即时搜索）**：

    ```bash
    $CLI search "验证码"
    $CLI search "OpenAI" --limit 10
    ```

5. **邮件状态标记**：

    ```bash
    # 标记已读 / 未读
    $CLI mark <MESSAGE_ID> read
    $CLI mark <MESSAGE_ID> unread

    # 加星标 / 取消星标
    $CLI mark <MESSAGE_ID> star
    $CLI mark <MESSAGE_ID> unstar

    # 移入废纸篓（删除）
    $CLI mark <MESSAGE_ID> trash
    ```

6. **邮箱账号与同步管理**：

    ```bash
    # 查看已绑定的账号列表
    $CLI accounts

    # 触发所有账号同步最新邮件
    $CLI accounts --sync
    # 或触发指定账号同步
    $CLI sync <ACCOUNT_ID>

    # 添加 IMAP 账号（交互静默读取密码注入环境变量，避免命令行明文暴露）
    read -s -p "Enter IMAP password: " KKMAIL_ACCOUNT_PASSWORD && export KKMAIL_ACCOUNT_PASSWORD
    $CLI add-account --email user@example.com --provider imap --host imap.example.com --port 993
    unset KKMAIL_ACCOUNT_PASSWORD
    ```

______________________________________________________________________

## 直接调用 REST API

若 Agent 处于不支持执行 Python 脚本的纯 HTTP 环境，可直接调用 REST 接口：

### 鉴权机制

1. **Bearer API Key（推荐）**：请求头携带 `Authorization: Bearer <API_KEY>`，无需 CSRF 校验。
2. **Cookie Session**：
    - 登录：`POST /api/auth/login`，Body `{"password": "<PASSWORD>"}`。返回 `Set-Cookie: kkmail_mc_session=...` 及 `{"csrf_token": "..."}`。
    - 写操作（POST/PUT/DELETE）：携带 Cookie 头与 `X-CSRF-Token: <csrf_token>`。

### 核心 API 端点

- `GET /health`：服务健康检查
- `GET /api/mail/stats`：未读邮件聚合统计
- `GET /api/mail/inbox?limit=50&unread_only=true`：收件箱游标检索
- `GET /api/mail/search?q={query}&limit=20`：全文检索
- `GET /api/mail/messages/{id}`：获取邮件元数据、解析后的 HTML/Text 正文与附件清单
- `GET /api/mail/attachments/{attachment_id}`：下载指定附件流
- `POST /api/mail/messages/{id}/read`：Body `{"is_read": true|false}`
- `POST /api/mail/messages/{id}/flag`：Body `{"is_flagged": true|false}`
- `POST /api/mail/messages/{id}/trash`：移动至废纸篓
- `GET /api/accounts`：列出所有邮箱账号
- `POST /api/accounts/{id}/sync`：排队异步同步指定账号
- `POST /api/accounts/sync-all`：排队异步同步所有已启用账号

______________________________________________________________________

## 业务边界说明

- 产品范围**不包含**撰写与发送邮件、联系人与系统通知。
- 如需发信操作，应引导用户通过 SMTP 服务商或外部专业通道完成。
