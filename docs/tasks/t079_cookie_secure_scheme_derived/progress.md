---
tid: "t079"
slug: "cookie_secure_scheme_derived"
title: "会话 Cookie 的 Secure 属性改为由连接协议推导并补齐登录回验闭环"
status: "done"
branch: "t079_cookie_secure_scheme_derived"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "95c72cef4f1c0402bb6c47c3afa542a211fa625c"
spec_source_sha: "95c72cef4f1c0402bb6c47c3afa542a211fa625c"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-11-13 实施（worktree kkmail_t079，base 95c72cef）：

- 实现摘要：auth.py 的 cookie_secure() 删除 env 分支，只按请求 ASGI scope scheme（回退 request.url.scheme）判定，函数注释写明「连接事实、不可配置」与 p078 教训；模块头 Env contract 删除该变量行并注明推导规则。config/loader.py 删除该变量解析行、config/models.py 删除只写不读的 AppConfig.cookie_secure 死字段、loader 中随之失去唯一调用点的 \_parse_optional_bool 一并删除。docker-compose.mail-core.yml 删除变量行与 5 行注释整段。src/desktop/startup.js 删除透传名单中的该变量。src/mail_core/README.md 配置表、docs/guides/deployment.md（2 处）、docs/guides/security.md（2 处）改写为「按请求 scheme 推导、无配置项」。前端 client.ts 的 login() 在 POST 成功后回验 checkSession()，回验 false 或抛错时抛具名错误 session_not_established 并由 LoginPage 既有错误区显示；checkSession 冷启动静默语义不变。设置 Cookie 的唯一调用点 \_set_session_cookie 本就传 request（login 路由），改密按 A105 要求重登录、不设 Cookie，无其他调用点。
- TDD：先写新测得红 6 failed / 1 passed（通过的是既有转发头不信任语义），实现后全绿。黑盒有效性先行实验：在旧代码上以 TestClient（base_url=http://karsondemacbook-pro.local:37281）且 env 强制 Secure 时，登录 200 而 /me 401——TestClient 的 cookie jar 严格执行浏览器 Secure 规则，与 p078 现象同构，故 AC-001/AC-002 的黑盒以 TestClient 走真实登录路由完成（AC-002 为 https base_url 的等价 scheme 注入，方法即此）。
- 删除的旧测试（整体删除，禁止就地改预期；新语义由新测接续）：
    1. tests/mail_core/test_auth.py::test_cookie_secure_boundary——其契约主体是「explicit config 或 verified scheme」双输入模型，第 3 段断言 env=1 时 HTTP 也 Secure，双输入模型被本 task 废除；第 1、2 段的 scheme 推导与未验证 X-Forwarded-Proto 不信任由 tests/mail_core/test_cookie_secure_scheme_derived.py 接续覆盖。
    2. tests/mail_core/test_auth_r4adopt_p16.py::test_a324_samesite_none_with_secure_is_kept——前半断言 env=1 使无请求时 SameSite=None 被保留（旧语义）；后半 HTTPS 下保留 None 由新测 test_cookie_samesite_none_follows_scheme_not_env 接续。
    3. tests/scripts/test_deploy_mail_core_r4adopt_p51.py::test_a98_cookie_secure_defaults_to_on——断言 compose 默认 1；A98 已被决策 016 取代、断言对象不复存在，由 tests/scripts/test_cookie_secure_removal_t079.py 的活配置面零残留守卫接续。
    4. tests/scripts/test_deploy_mail_core_r4adopt_p51.py::test_a98_compose_comment_explains_local_http_opt_out——断言 compose 注释含 opt-out 说明，随变量整段删除失效，同上接续。
    5. 附带清理（非断言变更）：test_auth_r4adopt_p16.py 两处对已删变量的 delenv 死引用行删除（不改变任何断言）；其余保留的 a324 测试语义不变、实测仍绿。
- AC-003 例外清单（全仓检索 MAIL_CORE_COOKIE_SECURE 的全部剩余命中，均为非活配置面）：docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md（决策记录正文须点名被删配置项）；docs/pending/p078_mobile_http_login_secure_cookie_silent_bounce.md（已关闭转办记录）；docs/reviews/review_20261027_021416/bundle_unit08.md 与 review_intensive.md（A98 历史审阅原文）；docs/tasks/t079_cookie_secure_scheme_derived/task.md（本 task 契约文本）；tests/mail_core/test_cookie_secure_scheme_derived.py（故意 setenv 敌意残留值以证明后端不再读取的回归守卫）；tests/scripts/test_cookie_secure_removal_t079.py（守卫的检索常量本身）。活配置面（compose、.env.example、src/、docs/guides/）为零，守卫测试锁定。
- 门禁实数（2026-11-13 本机实测）：doctor_cmd——模板契约 collect 464、md_kx 存在、敏感扫描 PASSED（33 文件 0 违规）；test_cmd——模板契约 463 passed / 1 skipped，前端 vitest 590 passed（55 文件）+ tsc -b 通过 + build 通过 + lint 0 warnings / 0 errors，桌面 npm test exit 0（OAuth 集成按设计 skip），敏感扫描同上；blackbox_verify——stubApi E2E 21 passed；后端 unit 全量 1663 passed / 539 skipped / 0 failed；本 task 新测 7 passed，受影响文件合跑 64 passed / 3 skipped（PG 依赖跳过），p16 清理后单跑 27 passed。
- 未跑项：后端完整 PG 套件（run-mail-core-tests.sh run）不在 AC-007 的三组门禁内（testing.md 明示其为 task/release 阶段单独执行项），本轮未跑；本 task 后端测试在 unit 模式已全量覆盖。真实 iOS Safari 未测（task.md「有意不测」已声明，TestClient jar 的浏览器规则复现替代，p078 另有真机现象与 cookiejar 实测）。

2026-11-14 接续复核（前任执行者 2026-11-13 23:06 被运行时中断，接续者接同一 attempt 1 / execution_id 1d577dd4b0a2424db88c801ac0af3c57 / owner cloud-kkmail-scheme，未重复 run-begin）：

- 逐项核对批准方案 5 项均落地：compose 变量行与注释整段删除；cookie_secure() 只按 ASGI scope scheme（回退 url.scheme）判定、env 分支删除，唯一设 Cookie 调用点 \_set_session_cookie 传 request（login 路由），cookie_samesite 的 None 联动改走同一 scheme 判定；前端 login() 在 POST 成功后回验 checkSession()，失败抛具名错误 session_not_established 并经 LoginPage 既有错误区显示，checkSession 冷启动静默语义未动；黑盒以 TestClient 走真实登录路由（http 局域网域名形态回送闭环、https scheme 注入断言 Secure）；旧测试 4 个整体删除与 progress 既录逐条比对一致（diff 实查：整函数删除，保留测试仅删两处 delenv 死引用行、无断言改动）。
- AC-003 全仓检索复跑：命中仅决策记录、p078 转办记录、A98 历史审阅原文、task.md/progress.md 本 task 流程文件与两份新守卫测试（及 __pycache__ 产物），与既录例外清单一致；活配置面（compose、.env.example、src/、docs/guides/）为零。
- AC-006 复核：决策记录 docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md 已落盘并明文取代 A98；p078 status=closed、resolution=transferred、fix_ref=t079。
- 门禁数字全部由接续者本机实跑复核（2026-11-14）：doctor_cmd——collect 464、md_kx 存在（~/.local/bin/md_kx）、敏感扫描 PASSED（33 文件 0 违规）；test_cmd——模板契约 463 passed / 1 skipped，前端 vitest 590 passed（55 文件）、tsc -b exit 0、build 通过，桌面 npm test exit 0（OAuth 集成按设计 skip），敏感扫描同上；blackbox_verify——stubApi E2E 21 passed；后端 tests 全量（unit 模式）1663 passed / 539 skipped / 0 failed；本 task 定向 5 文件合跑 65 passed / 3 skipped（新测 7 = 后端 6 + 守卫 1，p16 单跑 27 passed）。与前任自报逐项一致。
- 未跑项同前任记录：后端完整 PG 套件不在 AC-007 三组门禁内，本轮未跑；真实 iOS Safari 未测（task.md「有意不测」，TestClient jar 复现替代）。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-14T02:52:04+08:00)

双轴均 PASS（code / test），AC 7/7 全部 TICK-VALID；finding 2 条，均为 minor，已全部在本轮修复，待 Round 2 确认复审。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t079_code_f001|minor|已修|login() 新增的回验 checkSession() 未纳入调用方 timeoutMs、走默认 30 秒，短超时调用时回验腿不受预算约束；现 checkSession 接受可选 timeoutMs 并透传 apiRequest，login 以调用方预算回验，预算耗尽与其余腿一致报 timeout（预算内回验失败仍为 session_not_established）；先加红测后转绿|src/frontend/src/api/client.ts（checkSession 签名与 login 调用点）、src/frontend/src/api/client.login.test.ts（新增 bounds 用例）|
|t079_test_f001|minor|已修|AC-003 守卫只枚举 9 个固定文件、清单外新活配置面文件重新引入该变量时守卫仍绿；现改为动态扫描活配置面（compose、.env.example、src/ 与 docs/guides/ 全树、docs/blueprint 顶层文档），归档目录排除理由写入文件头；探针文件实测判红、撤除后复绿|tests/scripts/test_cookie_secure_removal_t079.py|

### Round 2 (2026-11-14T02:58:26+08:00)

双轴均 PASS；Round 1 两条 finding 经双轴亲验确认已消除、AC 7/7 全部 TICK-VALID。code 轴新记 minor 1 条（守卫扫描范围残漏），已在本轮修复，待 Round 3 确认复审。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t079_code_f002|minor|已修|AC-003 守卫动态扫描仍漏根目录新文件、scripts/ 与 config/ 树（评审探针实测判绿）；改为全树反向枚举：扫整个 worktree、仅排除归档与非活面（docs/reviews、docs/archive、docs/tasks、docs/pending、docs/findings、docs/spikes、docs/handoff.md、docs/blueprint/decisions、tests、.repo_template 及 VCS/环境/构建目录，边界与 testing.md 敏感扫描分界对齐并写入文件头）；根目录 compose、scripts/、config/、docs/ 根四处探针实测全判红、撤除复绿|tests/scripts/test_cookie_secure_removal_t079.py|

### Round 3 (2026-11-14T03:05:03+08:00)

双轴均 PASS；t079_code_f002 经双轴亲验确认已消除、AC 7/7 全部 TICK-VALID。code 轴新记 minor 1 条（守卫跟随出树符号链接），已在本轮修复，待 Round 4 确认复审。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t079_code_f003|minor|已修|守卫原样跟随符号链接读到 worktree 外（根 .env 链接到主仓部署 .env），仓外文件内容可令本仓活面全清时误报红；现 \_iter_live_files 对每个文件 resolve 后校验仍在 ROOT 内、出树目标跳过（树内链接如 .env.example -> config/.env.example 照常扫描），并新增出树链接探针用例；实施方另以真实实例判别：向主仓 .env 临时写入该变量守卫仍绿、随后按备份字节还原（grep 0 命中）|tests/scripts/test_cookie_secure_removal_t079.py|

### Round 4 (2026-11-14T03:08:54+08:00)

双轴均 PASS；t079_code_f003 经双轴亲验确认已消除（含回退实验复红、树内/出树探针口径复核），本轮零新 finding。终轮指纹双轴一致（9ac56619edd02fda），AC 7/7 全部 TICK-VALID。四轮 finding 共 4 条 minor，全部已修，无遗留。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：接续者 2026-11-14 本机实跑复核——doctor_cmd（模板契约 collect 464、md_kx 存在、敏感扫描 PASSED 33 文件 0 违规）；test_cmd（模板契约 463 passed / 1 skipped；前端 vitest 591 passed / 55 文件、tsc -b 通过、build 通过；桌面 npm test exit 0，OAuth 集成按设计 skip；敏感扫描同上）；后端 tests 全量（unit 模式）1663 passed / 539 skipped / 0 failed；本 task 定向 5 文件合跑 66 passed / 3 skipped（其中新测后端 6 + 守卫 2，含出树链接用例；前端 login 新测 5 条含回验超时用例，计入 vitest 591）。未跑：后端完整 PG 套件不在 AC-007 三组门禁内（testing.md 明示为 task/release 阶段单独执行项），本轮未跑；本 task 后端改动在 unit 模式已全量覆盖。
- 黑盒：AC-001/AC-002 以 TestClient 走真实登录路由（http 局域网域名形态：Set-Cookie 无 Secure、cookiejar 回送后 /me 两次 200；https scheme 注入：Set-Cookie 带 Secure、回送 200），旧代码同条件复现 p078 的 401，双轴审阅均独立复跑；blackbox_verify stubApi E2E 21 passed。真实 iOS Safari 未测，按 task.md「有意不测」以遵循浏览器 Cookie 规则的 TestClient jar 替代，p078 另有真机现象与 cookiejar 实测证据。
- review：双轴独立审阅 4 轮（review_limit 5 内）：Round 1 双 PASS（finding 2 minor）；Round 2 双 PASS（Round 1 两条确认消除，新记 code_f002）；Round 3 双 PASS（f002 确认消除，新记 code_f003）；Round 4 双 PASS（f003 确认消除，零新 finding）。终轮指纹双轴一致 9ac56619edd02fda。
- AC 判定：见 `task.md` 行内打勾（7/7，四轮双轴逐条 TICK-VALID）

### 结果摘要

- MAIL_CORE_COOKIE_SECURE 配置项彻底删除（compose 注入、后端读取、桌面端透传、配置文档），cookie_secure() 只按请求实际 scheme 推导 Secure，SameSite=None 联动同一判定；前端 login 成功后回验 /me，失败抛具名错误 session_not_established 并在登录页明确显示，冷启动静默语义不变；回验腿已纳入调用方超时预算。
- 决策记录 docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md（016）正式取代 A98；p078 已 closed/transferred 并指向本 task。
- 失效旧测试 4 个整体删除（理由见实施笔记逐条记录），由新测接续覆盖；AC-003 守卫经三轮强化为全树反向枚举并跳过出树符号链接。
- 遗留：无。本 task 按边界不合入、不 push、不部署（合入、部署与现役容器验证由主 agent 另行处理）。

### 长期文档闭环

- specs_index: not_applicable: 本 task 无关联长期 spec（task.md 关联 spec 为「无」），无 spec 正文变更；长期文档闭环为新增决策记录 docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md（正式取代 A98），已落盘。无正式 spike。
