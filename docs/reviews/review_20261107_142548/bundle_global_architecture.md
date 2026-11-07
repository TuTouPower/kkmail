# bundle_global_architecture

## Summary

kkmail 整体架构清晰，职责划分与安全防御体系高度纯粹。PostgreSQL 与 BlobStore 职责分明，分别确立了元数据与加密正文内容的单一权威；MailProvider 协议抽象彻底收敛了 IMAP 与 Microsoft Graph 的异构差异；受控无脚本沙箱 iframe、严格同源 CSP 与服务端图片反向代理构建了严密闭环的零外部出网信任边界。系统大体遵循 FastAPI -> Service/Application -> Storage/Provider 的单向调用，但在底层存在 3 处通过 lazy import 规避的跨层反向依赖与依赖环，需在后续演进中完成下沉解耦。

## Findings

- [Medium][95] src/mail_core/security/auth.py:564 — 底层认证模块反向依赖运行时引导模块形成导入环

    - ID: f_arch_auth_bootstrap_cycle; verification: static
    - Evidence: src/mail_core/security/auth.py:564: from mail_core.runtime.bootstrap import clear_initial_password; src/mail_core/runtime/bootstrap.py:129: from mail_core.security.auth import \_bcrypt_password_bytes
    - Impact: 底层核心安全认证模块（security.auth）在改密成功后反向感知并调用进程启动引导模块（runtime.bootstrap）的清理逻辑。尽管使用函数内延迟导入避开了加载期报错，但在架构层级上违反自底向上的单向依赖原则，形成 security.auth \<-> runtime.bootstrap 循环依赖。
    - Fix: 将首启密码清理逻辑解耦为生命周期事件钩子，或移至顶层应用服务层（API 路由/应用服务）作为改密完成后的编排逻辑调用，解除底层安全认证模块对运行时引导模块的反向依赖。

- [Medium][95] src/mail_core/providers/factory.py:209 — 协议适配工厂与账号连接校验模块双向依赖

    - ID: f_arch_provider_factory_accounts_cycle; verification: static
    - Evidence: src/mail_core/accounts/connection.py:81: from mail_core.providers.factory import validate_imap_host; src/mail_core/providers/factory.py:209: from mail_core.accounts.connection import reject_microsoft_imap; src/mail_core/providers/__init__.py:4: the whole package graph (avoids import cycles between accounts/sync/providers)
    - Impact: 账号连接层依赖适配工厂的主机校验，适配工厂又反向依赖账号层的微软协议拦截逻辑，导致 providers 与 accounts 形成双向依赖环，迫使 providers 包使用 PEP 562 延迟导出（__getattr__）以规避循环导入崩溃。
    - Fix: 将网络主机安全校验（validate_imap_host）与协议拦截规则（reject_microsoft_imap）统一下沉至底层 host_security 模块（src/mail_core/providers/host_security.py），实现纯净单向依赖。

- [Low][90] src/mail_core/accounts/credentials.py:16 — 通用凭据存储仓储放置于 accounts 业务包导致底层基础设施反向引用

    - ID: f_arch_credentials_layer_misplacement; verification: static
    - Evidence: src/mail_core/providers/oauth.py:34: from mail_core.accounts.credentials import ...; src/mail_core/blobs/archive.py:24: from mail_core.accounts.credentials import CredentialStore, get_credential_store; src/mail_core/blobs/rotate.py:45: from mail_core.accounts.credentials import credential_lock_key
    - Impact: CredentialStore / DbCredentialStore 属于基于 AES-256-GCM 与数据库锁的通用机密持久化基础设施，目前置于上层业务模块 accounts 中，导致底层协议层（providers.oauth）与存储归档层（blobs.archive/rotate）必须反向依赖 accounts 包，层级定位错位。
    - Fix: 将凭据存储接口与加密仓储下沉迁移至独立基础设施包（如 mail_core.security.credentials），accounts 仅保留账户聚合逻辑与 DTO。

## questions

```json
[]
```

## question_decisions

```json
{}
```
