# bundle_local_backend_runtime_security

## responsibilities

- 集中管理核心配置项（MailCoreConfig），实施强约束边界校验与数据目录运行环境自举
- 统一鉴权体系：基于签名的 Cookie 会话、数据库 session_epoch 驱动的即时全集群撤销机制、API Token 与 CSRF 防护
- 登录失败速率限制保护（LoginRateLimiter），采用有序字典进行 O(1) 淘汰防暴力破解与内存膨胀
- 全系统敏感信息自动脱敏过滤（RedactingFilter, RedactingTraceFormatter），阻断凭据与敏感字段输出至日志
- 远程图片防 SSRF 安全流式代理（remote_image_proxy）：阻断私有/保留网段与云元数据地址，防范 DNS 重绑定，执行 Magic Number 位图检测与 SVG 静态安全扫描
- 维护事务性 Outbox 事件的有序全局发布序数（publication_seq）与基于 PostgreSQL LISTEN/NOTIFY 的即时广播通知
- 独立 Worker 任务执行循环与并发线程池：基于 SKIP LOCKED 的安全任务认领、心跳续约与崩溃清理、流量分级与优雅停机
- 全文搜索倒排索引（FTS tsvector）与三元组（trigram）同步增量索引维护，以及基于 Message-ID 链的会话聚合分析

## interfaces

- MailCoreConfig.validate(), load_config(env)
- issue_session(), read_session(cookie_value), invalidate_all_sessions(), verify_password(password)
- detect_safe_image_mime(header), validate_svg_payload(payload), fetch_remote_image(url)
- OutboxDispatcher.subscribe(), OutboxDispatcher.dispatch_once()
- publish_committed_batch(session), fetch_published_since(session, ...)
- WorkerHeartbeatLoop, UnifiedClaimHeartbeatLoop, JobWakeListener
- assign_thread_for_message(session, ...)
- search_messages_with_total(session, ...)

## dependencies

- pydantic (模型验证与系统指标聚合)
- itsdangerous (会话与防篡改临时令牌签名)
- bcrypt (密码哈希与防时序攻击比对)
- psycopg (原生 LISTEN/NOTIFY 交互与自动提交连接)
- sqlalchemy (数据库模型、查询与事务管理)

## flows

- 用户认证 -> verify_password -> issue_session (签署带当前 session_epoch 与 csrf token 的 Cookie) -> 响应 Set-Cookie
- 密码修改/强制注销 -> invalidate_all_sessions (行锁自增 AuthCredential.session_epoch) -> notify_session_revocation 发送广播 -> 各 API 进程断开旧 epoch 的 SSE 连接并拒绝后续请求
- 远程图片代理请求 -> 校验签名 URL 临时 Token (15分钟有效期) -> 解析 URL 验证 scheme 与标准端口 -> 获取真实 IP 验证非内网/非保留/非云元数据 -> TCP 连接后重验对端 Peer IP (防 DNS Rebinding) -> 读取响应流检测安全位图文件头 -> 流式写出
- 业务事务提交 -> 写入 OutboxEvent -> notify_outbox 发送 NOTIFY -> 监听线程唤醒 OutboxDispatcher.dispatch_once -> publish_committed_batch 分配单调递增 publication_seq -> SSE 订阅队列扇出
- 消息入库 -> 触发 assign_thread_for_message 依据 provider_thread_key / In-Reply-To / References 聚合成 Thread -> 触发 upsert_message_search_batch 生成 FTS 搜索向量

## constraints

- 密码严格限制在 UTF-8 编码 72 字节以内，避免 bcrypt 底层实现因版本差异产生截断碰撞安全漏洞
- 生产环境敏感数据（数据库与存储根目录）要求挂载在操作系统级加密卷之上
- 远程图片代理严禁访问任何私网 IP（包括私有、回环、CGNAT、保留段及云元数据 169.254.169.254），SVG 格式严禁包含内联脚本或外部资源引用
- 日志与异常堆栈输出前必须全部经过脱敏过滤规则，严禁明文记录凭据、DSN、JWT 或 OAuth 回调参数

## decisions

- 采用数据库集中存储的 session_epoch 结合无状态签名 Cookie 实现有状态的即时分布式撤销，兼顾水平扩展性能与即时注销能力
- 采用事务性 Outbox 模式并在提交后通过单例行行锁分配全局递增序号 publication_seq，彻底解决事务提交时间与事件 ID 顺序不一致导致的漏读问题
- Worker 内部通过统一心跳管理线程集中刷新所有正在执行任务的 locked_at，将心跳开销从单任务分散化转变为全局批处理
- 全文检索采用 PostgreSQL 内置 tsvector + pg_trgm 混合模式，兼顾英文分词、中文前缀与模糊子串查询

## evidence

- src/mail_core/security/auth.py:74-78
- src/mail_core/security/auth.py:431-468
- src/mail_core/security/remote_image_proxy.py:117-146
- src/mail_core/realtime/publication.py:51-98
- src/mail_core/worker/main.py:341-399
- src/mail_core/threading/rules.py:129-268

## uncertainties

## Findings

- [Low][95] src/mail_core/worker/main.py:42 — __getattr__ 签名引用未导入的 Any 类型

    - ID: f_backend_runtime_01; verification: static
    - Evidence: src/mail_core/worker/main.py:14 仅导入了 from typing import NamedTuple; src/mail_core/worker/main.py:42 def __getattr__(name: str) -> Any:
    - Impact: 由于存在 from __future__ import annotations，模块启动执行不报错，但使用 typing.get_type_hints 进行类型自省或测试检查时会抛出 NameError: name 'Any' is not defined。
    - Fix: 在 src/mail_core/worker/main.py 中修改为 from typing import Any, NamedTuple。

- [Low][95] src/mail_core/search/index.py:15 — \_format_recipient_text 函数签名引用未导入的 Any 类型

    - ID: f_backend_runtime_02; verification: static
    - Evidence: src/mail_core/search/index.py:7 仅导入了 from typing import Sequence; src/mail_core/search/index.py:15 def \_format_recipient_text(addresses: Sequence[Any] | None) -> str:
    - Impact: 在运行时对该函数执行 typing.get_type_hints 时会抛出 NameError: name 'Any' is not defined。
    - Fix: 在 src/mail_core/search/index.py 中修改为 from typing import Any, Sequence。

- [High][95] src/mail_core/realtime/outbox.py:83-123 — 保留废弃的 v1 顺序回放接口与专属兼容测试，违反零兼容性负担铁律

    - ID: f_arch_deprecated_v1_replay_api; verification: static
    - Evidence: src/mail_core/realtime/outbox.py:83-123 保留 fetch_since 废弃函数及 DeprecationWarning 包装; tests/mail_core/test_a380_fetch_since_deprecated.py:1-40 专门编写测试套件断言废弃接口在报警后仍正常返回数据
    - Impact: 在 Outbox 升级到 v2 连续序列号（publication_seq）后，未执行破坏性清理，保留了按自增 id 排序的旧接口与测试预算，形成长期兼容债务。
    - Fix: 依据零兼容负担铁律，物理删除 outbox.py 中的 fetch_since 废弃函数及其专属测试文件 test_a380_fetch_since_deprecated.py，上层调用统一使用 fetch_published_since。

- [High][95] src/mail_core/runtime/bootstrap.py:41-55, 61-76 — 单机文件并发写入采用 time.sleep(0.01) 自旋死等，违反拒绝妥协铁律

    - ID: f_arch_secret_write_busy_spin; verification: static
    - Evidence: src/mail_core/runtime/bootstrap.py:41-55 在写入密钥文件捕获 FileExistsError 后，使用 while time.monotonic() < deadline 并在循环内执行 time.sleep(0.01) 忙轮询等待; src/mail_core/runtime/bootstrap.py:61-76 同样存在同型自旋死等逻辑
    - Impact: 创建密钥文件时未采用 POSIX 原子替换范式，并发进程在竞争时被迫自旋死等，不仅浪费 CPU，而且存在超时未写完的死锁风险，属典型用 sleep 掩盖原子写入缺陷的妥协方案。
    - Fix: 重构为原子写入范式：先写入带随机后缀的临时文件，刷盘 fsync 后通过 os.replace 原子重命名为目标路径，彻底移除 time.sleep 自旋等待循环。

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  }
}
```

## files_reviewed

```json
[
  "schemas/openapi.json",
  "src/mail_core/README.md",
  "src/mail_core/__init__.py",
  "src/mail_core/__main__.py",
  "src/mail_core/config/__init__.py",
  "src/mail_core/config/loader.py",
  "src/mail_core/config/models.py",
  "src/mail_core/logging_config.py",
  "src/mail_core/realtime/__init__.py",
  "src/mail_core/realtime/dispatcher.py",
  "src/mail_core/realtime/events.py",
  "src/mail_core/realtime/listener.py",
  "src/mail_core/realtime/notify.py",
  "src/mail_core/realtime/outbox.py",
  "src/mail_core/realtime/publication.py",
  "src/mail_core/runtime/__init__.py",
  "src/mail_core/runtime/bootstrap.py",
  "src/mail_core/search/__init__.py",
  "src/mail_core/search/index.py",
  "src/mail_core/security/__init__.py",
  "src/mail_core/security/auth.py",
  "src/mail_core/security/defaults.py",
  "src/mail_core/security/inline_preview.py",
  "src/mail_core/security/ratelimit.py",
  "src/mail_core/security/redact.py",
  "src/mail_core/security/remote_image_proxy.py",
  "src/mail_core/system_metrics.py",
  "src/mail_core/threading/__init__.py",
  "src/mail_core/threading/rules.py",
  "src/mail_core/worker/handlers.py",
  "src/mail_core/worker/healthcheck.py",
  "src/mail_core/worker/heartbeat.py",
  "src/mail_core/worker/main.py",
  "src/mail_core/worker/wake.py"
]
```
