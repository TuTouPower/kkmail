# 需求规格：用户认证与会话生命周期 (Auth and Session)

## 背景

kkmail 采用自托管单用户架构，需提供稳固的密码鉴权、防暴力破解、全生命周期的会话吊销与跨重启持久化机制。

## 契约区

### 范围

- 基于 bcrypt 的用户登录密码验证。
- 密码 Hash 持久化至 PostgreSQL 数据库（`auth_credentials` 表）。
- 签名 Cookie 会话管理与全局 Session Epoch 吊销机制。
- 不安全 HTTP 请求的 CSRF 令牌校验。
- 客户端登录失败速率限制。

### 非范围

- 多租户用户系统与 RBAC 角色权限。
- 第三方 SSO / OAuth 外部登录。

### 验收标准

- [x] AC-001：用户输入正确密码时系统签发包含当前 `session_epoch` 的签名 Cookie，输入错误密码时返回 401 并记录失败计数。
- [x] AC-002：同一客户端在 300 秒内连续失败 10 次时，接口返回 429 限流并携带 `Retry-After` 头部。
- [x] AC-003：用户调用改密接口时，新密码 bcrypt hash 必须原子持久化至数据库；若写库异常则直接拒绝改密，不更新内存状态。
- [x] AC-004：用户成功修改密码或执行登出操作时，数据库中的 `session_epoch` 自增，所有此前签发的活跃会话本进程立即失效、跨进程最长 5 秒内失效（与 `docs/blueprint/decisions.md` 2026-10-25 会话 epoch 5 秒进程内缓存决策一致）。
- [x] AC-005：所有非幂等写请求（POST、PATCH、DELETE）必须携带有效的 `X-CSRF-Token`，令牌校验失败时请求被拒绝。

### 可测试性声明

全部 AC 可自动测试。

## 上下文区

- 来源：`docs/blueprint/decisions.md` (方案 A 决策)

### 有意不测

- 外部反向代理网络层 IP 伪造攻击（依赖基础设施配置）。

### 测试策略

- 单元测试：`tests/mail_core/test_auth.py` 与 `test_auth_plan_a_db.py`。
- E2E 冒烟测试：`tests/e2e/smoke.spec.ts` 验证登录与登出拦截流。

### 未知契约清单

无

### 风险与回退

- 风险：数据库连接瞬断导致登录无法读取 `auth_credentials` 表。
- 回退：降级尝试从环境变量 bootstrap 配置读取，若仍不可用则 Fail-Closed 拒绝启动。

### 依赖与约束

- 依赖数据库迁移至 `20261021_0013`。

### Finalization 时更新的 blueprint

- `docs/blueprint/decisions.md`：方案 A 认证密码与会话状态统一入库。
