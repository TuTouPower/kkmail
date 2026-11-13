# Task spec

## 背景

p078（2026-11-13 用户实报并实测坐实）：手机经 http://karsondemacbook-pro.local:37281/ 登录 mail-core，POST /api/auth/login 返回 200 后 GET /api/auth/me 返回 401，前端静默弹回登录框。根因：docker-compose.mail-core.yml 把 MAIL_CORE_COOKIE_SECURE 默认置 1，src/mail_core/security/auth.py 的 cookie_secure() 在 env 已设值时直接采用 env、不看请求 scheme，登录下发的会话 Cookie 带 Secure 属性；iOS Safari 在 http 明文下不保存/回送 Secure Cookie，会话在浏览器侧被传输规则丢弃。本机 localhost 因浏览器破例接受而长期掩盖。

引入史：会话 Cookie 鉴权诞生时（ce9b1a61，2026-10-21）cookie_secure() 即按请求 scheme 推导；审阅项 A98（review_20261027_021416 的 adoption_decision.md）以「默认关不安全」为由要求默认改 1，712faf77（2026-10-27）落地默认值 0→1，自此 http 入口静默不可用，前端 checkSession() 对 401 静默 return false 使故障未显形。

用户 2026-11-13 拍板：不用 HTTPS（手机常开 VPN 与 Tailscale 冲突、局域网软件不可用），接受局域网 http 明文传输风险；正解是让 Secure 属性回归「由连接协议推导」、删掉配置项，并补登录回验闭环。严禁把默认值翻回 0 了事。

## 契约区

### 范围

- docker-compose.mail-core.yml 删除 MAIL_CORE_COOKIE_SECURE 注入整段（变量行与注释）。
- src/mail_core/security/auth.py：cookie_secure() 删除 env 分支、只按请求实际 scheme 判定；模块头文档同步删该 env 说明；设置会话 Cookie 的调用点确保传入 request；cookie_samesite() 联动不回归。
- .env.example 与配置参考文档（src/mail_core/README.md 等）清除该变量残留。
- 前端 src/frontend/src/api/client.ts：login 成功后回验 /api/auth/me；回验失败抛出有名的会话建立失败错误并在登录页明确显示；checkSession() 冷启动静默行为与登录后回验分开。
- 后端单测（scheme 推导两路与 SameSite 联动）与黑盒验证（http 非 localhost 域名登录闭环、https scheme 下 Secure）补强；断言旧 env 行为的既有测试整体删除并在 progress.md 逐条记录理由。
- docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md 决策记录取代 A98；p078 经 pending.py 转办指向本 task。

### 非范围

- 不保留 MAIL_CORE_COOKIE_SECURE 配置项（含改默认值回 0 的做法）。
- 不引入 HTTPS/TLS 入口或任何反向代理部署变更。
- 不改现役部署：不动 Mac 上 .env、不重建/重启现役容器；本 task 不合入、不 push、不部署。
- 不改 SameSite 默认值（lax）与会话时长、登录限流等其他鉴权语义。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：经 http 入口（非 localhost 域名形态）登录后下发的会话 Cookie 不带 Secure 属性；回送后 GET /api/auth/me 返回 200 且刷新后会话保持（黑盒验证）。
- [ ] AC-002：经 https 入口登录后下发的会话 Cookie 带 Secure 属性（黑盒或等价 scheme 注入验证，方法记入 progress.md）。
- [ ] AC-003：MAIL_CORE_COOKIE_SECURE 彻底移除：compose 不注入、后端不读取、.env.example 与配置文档无残留，全仓检索为零（例外逐项在 progress.md 说明）。
- [ ] AC-004：Secure 判定只取决于请求实际 scheme（含既有代理信任边界），单测覆盖 http/https 两路，SameSite=None 联动规则不回归。
- [ ] AC-005：前端在 login 成功但回验失败时显示明确的会话建立失败错误、不静默回登录表单；冷启动未登录仍直接显示登录页不报错；前端测试覆盖两条路径。
- [ ] AC-006：A98 被新决策记录正式取代并落盘；p078 已更新指向本 task。
- [ ] AC-007：testing.md 的 doctor_cmd、test_cmd、blackbox_verify 全量通过；失效旧测试的删除逐条记录理由于 progress.md。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。AC-001 以真实 HTTP 黑盒验证（非 localhost 域名形态的 Host + http scheme，带 cookiejar 的客户端走完登录闭环）；AC-002 以等价 scheme 注入验证（测试客户端以 https base_url 走同一登录路径断言 Set-Cookie 带 Secure），方法记入 progress.md。AC-003 以全仓检索命令验证；AC-006 以文件存在性与 pending.py 状态验证；AC-007 以 testing.md 三组命令的实际执行结果验证。

## 上下文区

- 关联 spec：无
- 来源：p078（2026-11-13 核实并实测坐实；根因、复现证据与已排除项见 docs/pending/p078_mobile_http_login_secure_cookie_silent_bounce.md，后经 pending.py 转办至本 task）

### 有意不测

- 真实 iOS Safari 行为：无法在门禁环境驱动真机 Safari；以遵循浏览器 Cookie 规则的 cookiejar 客户端复现传输层丢弃/回送行为替代，p078 已有同法实测证据。

### 测试策略

- 后端：先写红测（scheme 推导、env 不再影响判定、SameSite=None 联动），再改实现转绿；黑盒用带 cookiejar 的 HTTP 客户端以非 localhost 域名形态走登录闭环。
- 前端：Vitest 覆盖 login 回验失败显式报错与冷启动静默两条路径；既有前端全量测试不回归。
- 门禁：testing.md 的 doctor_cmd / test_cmd / blackbox_verify 全量执行。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：删除 env 变量后若有仓外脚本或部署文档仍引用该变量，行为预期不一致；以全仓检索（含 docs、scripts、compose）清零并在决策记录中写明取代关系应对。
- 风险：cookie_secure() 的 scheme 取值依赖既有代理信任边界（A21/A37 已落地）；实现时须核实登录响应路径上 request scheme 的来源不被未信任的转发头污染，单测覆盖。
- 回退：实现 commit 单笔可整体 revert；compose 与代码同 commit 回滚即恢复旧行为。

### 依赖与约束

- 用户决策（2026-11-13）：局域网 http 明文为已接受的传输形态；不得以「不安全」为由恢复强制 Secure 或引入 HTTPS 依赖。
- 边界：做到 finish 为止，不 integrate、不 push、不动现役部署。

### Finalization 时更新的 blueprint

- `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md`：新增决策记录，正式取代 A98（review_20261027_021416 adoption_decision.md 中 A98 条目）。
