# Task review t055（reviewer_focus: 测试）

- task：`t055_microsoft_oauth_callback`
- spec：`docs/tasks/t055_microsoft_oauth_callback/spec.md`
- diff_anchor：`e1dee25`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff e1dee25`
- round：1
- reviewed_at：2026-10-24T19:09:23+08:00

reviewed_scope: 78d028fee03434f9

## Findings

本轮零 finding。

## 验证与测试可信度

- 独立执行 `KKMAIL_TEST_ELECTRON=1 scripts/run-mail-core-tests.sh run -k microsoft_oauth --no-cov`：26 passed，证据 `.scratch/t055_test_reviewer_r1.log`，含真实 PG、实际 SPA/Electron、生产 HTTP 传输及本地 Microsoft 供应商夹具。
- 独立执行 `npx vitest run src/components/microsoft_account_form.test.tsx src/components/provider_account_form.test.tsx`：21 passed，覆盖 Microsoft 新增/编辑保存、设备短码显示/复制/取消及 Google 原有路径。
- 核查门禁日志：`.scratch/t055_all_backend.log` 完整后端 560 passed（收集早于最后补充的混合凭据等用例，不宣称包含全部晚补项）；`.scratch/t055_final_backend.log` 最终 Microsoft/Google 定向含两套 Electron、混合凭据拒绝与旧配置回归 39 passed，覆盖晚补项；前端全量 296、默认 UI E2E 16、账户 E2E 5、全栈 8、桌面与 packaged smoke、模板 149 passed / 1 skipped，均有相应日志。未把独立定向复验称为重新执行全部门禁。
- 红灯归因：`.scratch/t055_red.log` 记录 Microsoft 授权尚未实现时 8 failed；`.scratch/t055_mixed_red.log` 记录混合手动凭据与已验证流程保存被错误接受，新增用例 `test_verified_oauth_save_rejects_mixed_manual_credentials_without_consuming_result_pg` 现验证拒绝且保留流程供合法保存。不是修改既有预期迁就输出。
- mock 边界：组件/E2E 在 fetch/HTTP 边界设桩；后端主要协议测试将供应商 HTTP 回应注入生产流程，不替换身份判断、权限校验、流程领取、最终保存或真实加密 DB。`test_microsoft_electron_dynamic_localhost_and_cookie_free_callback_pg` 通过本地假供应商 HTTP 服务触达生产 urllib token/profile、Graph 邮箱可用性核对及最终加密凭据；真实 SPA 使用生产 preload、窗口选项和外链 handler，Node HTTP callback 不带 Electron Cookie。
- 并发与时间：`test_device_concurrent_poll_and_save_use_same_identity_guards_pg` 用两个独立 TestClient 及 Barrier 同时轮询，断言两者合法结果、仅一次真实业务 exchange 和重复消费拒绝；interval、slow_down、429 Retry-After、取消、epoch、超时与迟到成功均通过可控时钟和 API/请求次数验证，未通过增加重试或超时掩盖问题。

## 改测与危险模式扫描

- 改测方向复核：无迁就实现的既有测试预期修改。Google 后端与供应商组件用例保持，新增 Microsoft 文件；原 UI E2E 原样保留并新增微软链路。Electron 夹具按供应商参数化，Google 仍精确检查 HTTP scheme、127.0.0.1 和原动态端口，Microsoft 明确检查 localhost/端口；将原 origin 等式拆为 hostname/port 与既有 HTTP 前置校验是等价扩展，没有接受错误端点。
- 恒真断言、删/反转/注释断言、测试删除、独占、禁止类型抑制、阈值放宽、条件绕过关键断言：未发现。组件 `if (!edit)` 仅为新增/编辑提供不同输入，两条参数化路径都必须验证实际 POST/PATCH 保存请求及不携带手动凭据。
- `toMatchObject` 用于新增请求载荷必需字段；之后有实际保存/DB 断言，不是替代既有精确判断。`toBeVisible` 用作交互前置或弹窗关闭结果，微软授权还必须产生已核实邮箱、POST/PATCH 和持久凭据。
- E2E 剪贴板反馈允许“已复制/复制失败”，对应真实浏览器可能拒绝剪贴板权限；组件另精确断言 `writeText('ABCD-EFGH')`，未用可选反馈替代复制行为全部证据。
- PG/桌面 skip 条件是显式运行环境分类；本轮已启用并独立执行 Electron 回归，不将跳过冒充通过。真实外部注册、2FA、管理员同意与真实账号登录属于 spec 有意不测，不报覆盖缺口。
- 七视角：安全核查短码/长码隔离、会话/CSRF/epoch、官方验证地址白名单与脱敏；正确性核查 /me 身份、邮箱/许可、旧 Graph 配置复用和最终保存；契约核查 code/device 两种请求及生成 DTO；性能/资源核查服务端间隔和单轮互斥；架构确认生产流程、真实 DB 与桌面路径可达；健壮性核查拒绝/限流/迟到成功；测试/文档/规格核对用户帮助与门禁命令。无新重要问题。

## 结论

- 本轮新发现：0 条。
- 未进表提示：可补充实际多 API 进程竞争和 Microsoft Web 机密客户端整链专测；现有共享持久流程与网页配置/客户端约束已有测试和生产代码证据，属于补充场景，不构成 AC 完全无测试。真实第三方成功未实测，不宣称已连通微软账号。
- 总体判断：授权码与设备码、身份/邮箱/许可校验、旧账户保护、轮询时序、无 Cookie 桌面回调及最终保存均有有效证据；无未解决 critical/important。
- 系统性 follow-up：无。
- 指纹：独立重算 `78d028fee03434f9` 与 prompt 一致，`git diff --check` 无错误，无 reviewer 不可见的未跟踪交付内容。

### AC 复验方式

- AC-001：`re_verified` — 独立组件参数化新增/编辑分别提交 POST/PATCH；独立 PG 验证浏览器授权新增和旧 Graph 配置/撤销令牌重新授权。
- AC-002：`re_verified` — 核对客户端字段、租户、Secret value 帮助与公共客户端无 Secret 测试，独立 device 无 callback/secret 请求断言。
- AC-003：`re_verified` — 独立真实 Electron/HTTP/PG 用例验证 localhost 动态端口、PKCE 换码、无 Cookie callback 和原应用保存；网页可信 Origin 继续复用 t054 metadata 与配置门禁。
- AC-004：`re_verified` — 独立请求测试精确核对 Microsoft 官方 authority、consumers/organizations、code/PKCE、Graph 两项权限及 offline_access；设备请求排除 state/verifier/secret。
- AC-005：`re_verified` — 独立 profile/mailbox/缺 id/缺 mail 用例验证 /me 身份及可用邮箱；使用 opaque Access Token，无 JWT 解析代替核验。
- AC-006：`re_verified` — 独立 PG 测试同邮箱不同 ID 拒绝、客户端/租户变化拒绝、旧无 ID/已撤销令牌可重授、重复邮箱拒绝，确认失败不改旧凭据。
- AC-007：`re_verified` — 独立测试跨供应商与重放、无登录/跨会话/CSRF、epoch/取消/到期、并发轮询及重复结果保存拒绝；真实 DB 验证回调只暂存。
- AC-008：`re_verified` — 独立参数化错误涵盖管理员同意、拒绝、回调、Secret、租户及缺 scope/RT，错误不回显秘密；PG 保存新凭据，后台刷新保护继承 t054 回归。
- AC-009：`re_verified` — 独立组件新增/编辑帮助均打开并核对注册、公共客户端、Secret ID/value、权限与租户注册前置说明；查证实际帮助正文及官方链接。
- AC-010：`re_verified` — 独立帮助断言 Token 不能门户直接查看；设备 UI 复制短码并提供官方验证链接，保留命名手动字段且保存请求与已验证结果互斥。
- AC-011：`re_verified` — 核对供应商只能 Graph，既有 Microsoft IMAP 拒绝测试无删改；Google/其他 IMAP 组件与完整后端回归保留。
- AC-012：`re_verified` — 核对窄屏 E2E 实际登录/复制/保存链路；独立 PG 验证重新授权保持分组与 sync_enabled=false，短长码秘密不回显、无浏览器持久保存断言有效。
- AC-013：`re_verified` — 独立组件验证选择设备码后无 callback/Secret、短码/剩余时间/复制/官方链接/取消；独立后端无公网 origin 仍申请设备码成功。
- AC-014：`re_verified` — 独立时钟/API/请求计数验证 interval、pending、slow_down、429 Retry-After、取消/过期/epoch、供应商期限与本地上限取短、迟到成功拒绝及并发单次轮询。
- AC-015：`re_verified` — 独立用例验证长 device_code 不回前端、官方验证 URI 白名单和无拼接 code；设备身份核验、原凭据保存前不变、同会话最终保存和重复消费拒绝。
- AC-016：`re_verified` — 独立错误用例验证公共客户端未启用的配置帮助及秘密不回显；独立组件查证两方式切换入口与实际帮助中的 Client ID、自动持续访问说明。

coverage = 16 / 16 (100.0%)

verdict: PASS

## Round 2 (2026-10-24T23:47:17+08:00)

reviewed_scope: 12e66374e938defc

### Findings

本轮零新 finding。

### 前轮复核与新增回归

- 本报告 Round 1 零 finding；首轮微软授权、设备码、身份/邮箱/许可、轮询时序、Electron 与混合凭据保存覆盖保留，未删改原有期望。
- Code `t055_code_f001` 对应新增验证有效：`microsoft_account_form.test.tsx` 参数化 Graph/Gmail 两供应商，各覆盖旧账户原样保存、仅移组、显式改为机密客户端三种操作，共 6 项。先等待实际 metadata 响应，再确认表单仍 public；真实点击保存后精确比较 PATCH 完整 payload，未将错误的默认机密类型加入预期。
- `test_legacy_oauth_ordinary_save_and_group_move_do_not_require_new_secret_pg` 通过真实 API/PG 验证两供应商原样/移组保存成功，`oauth_client_type` 仍 None、原凭据完全相等；显式缺 Secret 的机密升级仍返回 400，证明后端校验没有为前端错误放宽。
- 生产修复复核：metadata 默认客户端类型仅应用于新建账户；普通 PATCH 仅在客户端类型被显式编辑且相对已存值变化时提交 `oauth_client_type`。授权结果恢复和显式登录方式切换仍按既有协议处理，不把普通保存改造成必须重授。

### 独立验证与危险模式扫描

- 独立执行微软与 Google 组件测试：27 passed（含新增 6 项）。
- 独立执行 `scripts/run-mail-core-tests.sh run -k legacy_oauth_ordinary_save_and_group_move_do_not_require_new_secret_pg --no-cov`：2 passed，证据 `.scratch/t055_test_reviewer_r2.log`。
- 核查红灯 `.scratch/t055_legacy_red.log`：4 项普通保存/移组测试因多出隐式机密配置失败；当前回归保留原样/移组应有 payload，并增加显式升级的独立期望，没有把错误输出当正确结果。
- 核查本轮前端全量 302 passed、账户 UI E2E 5 passed、真实全栈 8 passed 日志。本轮生产后端未改；首轮完整后端 560 与最终定向 39（覆盖首轮晚补项）作为保留证据，不宣称本轮又执行完整后端。
- 最终指纹独立重算为 `12e66374e938defc`，与 prompt 一致。
- 改测方向复核：无既有测试就地迁就实现改期望；新回归将新旧行为分开参数化，均精确断言实际提交效果。HTTP 边界桩没有复制/替换生产表单逻辑；真实后端用例未 mock 凭据保存、分组变更或验证。
- 危险模式逐项扫描：无新增测试删除、恒真/反转/注释断言、独占或跳过、类型抑制、超时放大；测试中 move/editType 条件只决定输入与明确的分支预期，所有参数都执行保存并精确比较 payload，不存在前置不满足即不验结果。旧账户普通保存校验从前端到真实 API/DB均有证据。
- 七视角：安全确认显式缺 Secret 升级仍拒绝；正确性确认不隐式改型及移组保存；契约确认 PATCH 只表达用户编辑；性能/资源无本轮新增运行模型；架构确认前端状态来源与服务端校验分离；健壮性确认旧记录字段缺省；测试/文档/规格对应 AC-001/002/012，不扩大未改领域。

### 结论

- 本轮新发现：0 条；新增回归有效覆盖 code f001 的触发与修复行为。
- 未进表提示：首轮已列可选专项验证仍适用，不新增 blocker；真实第三方账号注册/授权继续按 spec 有意不测。
- 系统性 follow-up：无。
- 总体判断：普通编辑不再隐式升级客户端类型，显式升级仍受 Secret 校验；当前无未解决 critical/important，本轮 PASS。

### AC 复验方式

- AC-001：`re_verified` — 独立执行旧 Graph 原样/移组保存，确认已存凭据可复用且无需重授；原登录链路测试保留。
- AC-002：`re_verified` — 独立组件和真实 PG 验证默认 public 不改写，显式机密升级携带 Secret，缺 Secret 服务端拒绝。
- AC-003：`re_verified` — 核对当前完整 diff 的 localhost 动态端口与 Web HTTPS 回调、无 Cookie 桌面测试保留，前端本轮修改未变回调协议。
- AC-004：`re_verified` — 核对 code/PKCE 与 device grant 隔离、Graph 权限/tenant 请求测试保留。
- AC-005：`re_verified` — 核对 /me、inbox 许可及缺邮箱/身份拒绝测试保留。
- AC-006：`re_verified` — 核对旧 Graph 重授、远端身份/邮箱和租户/客户端不匹配拒绝；新增真实 PG 确认普通编辑凭据不变。
- AC-007：`re_verified` — 核对 owner/epoch/CSRF/重放/并发 poll/重复消费测试保留。
- AC-008：`re_verified` — 核对失败保留旧凭据、错误分类与轮换缓存；本轮普通编辑回归精确比较原凭据完全相等。
- AC-009：`re_verified` — 独立微软组件套件仍验证新增/编辑帮助及 Entra 说明。
- AC-010：`re_verified` — 独立组件验证短码操作、命名字段和保存请求，原门户 Token 解释保留。
- AC-011：`re_verified` — 核对 Microsoft Graph-only 与 IMAP 拒绝回归未修改，Google 组件套件独立通过。
- AC-012：`re_verified` — 独立验证 Graph/Gmail 原样、仅移组及显式改型 payload；真实 PG 确认普通保存不改凭据，UI/全栈日志通过。
- AC-013：`re_verified` — 独立微软组件 suite 保留设备码无 Secret/回调、短码、链接、复制和取消验证。
- AC-014：`re_verified` — 核对服务端 interval/slow_down/429/取消/epoch/迟到成功/并发单次轮询测试未改。
- AC-015：`re_verified` — 核对短长码隔离、验证 URL 白名单及设备身份/最终确认保存用例未改。
- AC-016：`re_verified` — 核对设备配置失败指引与自动持续访问说明；浏览器/设备切换入口测试保留。

coverage = 16 / 16 (100.0%)

verdict: PASS

## Round 3 (2026-10-24T23:49:29+08:00)

reviewed_scope: 42658742333b6b92

### Findings

本轮零新 finding。

### 最终范围复核

- 唯一交付变化为 `docs/specs_index.md:7`：`account_connection` 的 task 清单从 `t053` 补齐为 `t053, t054, t055`，与已累积的供应商表单、Google OAuth、Microsoft OAuth spec 内容一致。
- 独立重算最终指纹为 `42658742333b6b92`。只在内存比较树中排除该索引改动后，指纹精确恢复为 Round 2 的 `12e66374e938defc`；因此可确认其余交付代码、测试、配置及 spec 内容与上轮相同，不依赖实施侧口述。未修改任何交付文件。
- 本轮没有代码/测试变化，不重复执行测试。Round 2 独立组件 27、真实 PG 2，以及对应前端全量 302、账户 E2E 5、真实全栈 8 的证据继续对应同一被测实现；更早完整后端 560 与最终晚补定向 39 仍按此前报告分别披露。
- 前轮 finding 复核：本报告历史无 finding；code f001 对应新增 6 项矩阵与真实 PG 回归保持不变，未删除或弱化断言。
- 危险模式与改测方向复核：本轮无测试改动，无新增 skip、mock、阈值或断言变化。
- 七视角：安全、正确性、契约、性能/资源、架构、健壮性均无实现变化；文档/测试/规格索引现完整反映已交付 task，未发现新问题。

### 结论

- 本轮新发现：0 条。
- 未进表提示：无新增；先前有意不测与可选验证说明保持。
- 系统性 follow-up：无。
- 总体判断：单行索引补齐正确，被测实现与 Round 2 完全相同，本轮 PASS。

### AC 复验方式

- AC-001：`re_verified` — 指纹比对确认新增/旧账户保存实现和对应回归与 Round 2 相同。
- AC-002：`re_verified` — 客户端/Secret/租户字段与显式升级回归不变。
- AC-003：`re_verified` — Web/桌面回调及 Electron 验证路径不变。
- AC-004：`re_verified` — 授权码/设备 grant、PKCE 和权限断言不变。
- AC-005：`re_verified` — Graph 身份/邮箱/许可检查及测试不变。
- AC-006：`re_verified` — 旧 Graph 保护、身份及客户端匹配回归不变。
- AC-007：`re_verified` — 会话/epoch/CSRF/消费与并发回归不变。
- AC-008：`re_verified` — 错误提示、旧凭据保护与轮换测试不变。
- AC-009：`re_verified` — 新增/编辑帮助与注册前置说明不变。
- AC-010：`re_verified` — Client ID/Token 解释、设备短码与高级字段不变。
- AC-011：`re_verified` — Graph-only、Microsoft IMAP 拒绝及其他供应商回归不变。
- AC-012：`re_verified` — 窄屏、秘密保护、分组与普通编辑回归不变。
- AC-013：`re_verified` — 设备码无 callback/Secret、复制/链接/取消路径不变。
- AC-014：`re_verified` — 服务端间隔、限流、epoch、取消及迟到成功回归不变。
- AC-015：`re_verified` — 长短码隔离、受信 URL 和最终保存检查不变。
- AC-016：`re_verified` — 配置失败指引、登录方式切换与持续访问说明不变。

coverage = 16 / 16 (100.0%)

verdict: PASS
