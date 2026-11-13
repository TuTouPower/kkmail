# Task review t079（reviewer_focus: 代码）

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：1
- reviewed_at：2026-11-14T02:48:00+08:00

reviewed_scope: 2a7889bd235375ce

## Findings

### t079_code_f001 - login 回验请求未纳入 login 自身的超时约束

- 严重度：minor
- 锚点：行为缺陷 — `login(password, { timeoutMs })` 的超时只约束登录 POST 本身，新增的回验腿不受该超时约束，调用方传入短超时时行为与函数契约不一致
- 位置：`src/frontend/src/api/client.ts:314`
- 问题：`login()` 在 `src/frontend/src/api/client.ts:286-296` 以 `opts.timeoutMs` 建 `tmo` 并只传给登录 POST 的 fetch；`:314` 的回验 `await api.checkSession()` 未传任何超时/信号，`checkSession()`（`:274`）经 `apiRequest` 使用默认 30 秒超时。可复现场景：`api.login('pw', { timeoutMs: 30 })` 且 POST 快速成功、`/api/auth/me` 挂起时，login 不会在 30ms 报错，而是等回验自身的 30 秒超时后才以 `session_not_established` 拒绝；且若等待期间 `tmo` 已触发，`:326` 的外层 catch 又会把回验失败改标为 `timeout`，掩盖真实失败类别。现役唯一调用方 LoginPage 用默认超时（30 秒，与回验默认一致），故当前用户面无可观测影响，仅为契约一致性缺口，不违反任何 AC。
- 建议：让回验复用 login 的剩余超时预算（把 timeoutMs/signal 透传给 checkSession 或在 login 内以同一 `tmo` 包裹回验），并补一条「POST 成功但 /me 挂起 + 短 timeoutMs」的用例。

## 结论

- 本轮新发现：1 条（minor 1；critical 0 / important 0）
- 未进表的提示：文件过大（按降级规则只提示）— `src/mail_core/security/auth.py` 564 行、`src/frontend/src/api/client.ts` 475 行，均已过实现源码 400 行 minor 阈值且本 task 分别净增数行 / 18 行；两文件均为存量大文件，本 task 未在其中引入可观测缺陷，故不进 finding 表。圈复杂度 — `cookie_secure()` 约 4、`login()` 约 7，均未达提示阈值，无提示。范围外观察 — `.scratch/` 为 gitignore 的实施侧草稿目录、不属交付内容，其内旧代码片段不构成活配置面残留；logout 的 `_clear_session_cookie` 未传 secure/samesite 为存量行为、本 diff 未触及，不在本轮范围。
- 七视角扫描确认：安全（scheme 只信经 ProxyHeadersMiddleware 以 trusted_hosts 写入 scope 的值，`src/mail_core/api/app.py:87-103`；未验证转发头不抬升判定；无凭证/日志问题）、正确性（scheme 推导、SameSite 联动、回验闭环均与契约一致）、契约·Breaking（删除配置键为 spec 明确要求的破坏性变更，已有决策记录与 guides/README 同步说明迁移）、性能·资源（每登录多一次 `/me` 为 AC-005 固有要求，无 N+1/阻塞 IO）、架构（死字段 `AppConfig.cookie_secure` 与失去调用点的 `_parse_optional_bool` 随变量一并删除，无残留引用）、健壮性·可观测（见 f001）、文档·规格（README、deployment、security 三处文档与实现一致）均已扫过，除 f001 外未命中。
- 总体判断：实现完整覆盖 AC-001～AC-007，无未解决 critical / important，仅 1 条 minor，判 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。自跑 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 `test_login_http_lan_host_roundtrip_despite_legacy_env` 通过：http + 非 localhost 域名形态登录 200、Set-Cookie 无 Secure、两次 `/api/auth/me` 均 200（定向合跑 34 passed）。
- AC-002：TICK-VALID，re_verified。同文件 `test_login_https_sets_secure_cookie_despite_legacy_env` 通过：https scheme 注入下登录 Set-Cookie 含 Secure 且 `/me` 200，残留 env=0 不影响判定。
- AC-003：TICK-VALID，re_verified。本人全仓检索复跑：活配置面（compose、`config/.env.example`、`src/`、`docs/guides/`）零命中，剩余命中仅决策记录、p078、A98 历史审阅、task.md、两份守卫测试与 progress.md 自身，与 progress.md 例外清单一致；守卫测试通过；diff 实查 compose 整段、loader 解析行、models 死字段、desktop 透传名单均已删除。
- AC-004：TICK-VALID，re_verified。`cookie_secure()`（`src/mail_core/security/auth.py:177-193`）只读 ASGI scope scheme（回退 `url.scheme`）、env 分支已删；单测覆盖 http/https 两路、`test_cookie_secure_ignores_unvalidated_forwarded_proto` 与 SameSite=None 联动 `test_cookie_samesite_none_follows_scheme_not_env` 均自跑通过，唯一设 Cookie 调用点 `src/mail_core/api/auth_routes.py:71-80,104` 传 request。
- AC-005：TICK-VALID，re_verified。`src/frontend/src/api/client.ts:307-325` login 成功后回验、失败抛具名 `session_not_established`，`src/frontend/src/components/LoginPage.tsx:19-25` 既有错误区显示其 message；`checkSession()` 冷启动 401 静默返回 false 未改；自跑 `src/frontend/src/api/client.login.test.ts` 4 passed（回验 401、回验 500、回验成功、冷启动静默四路）。
- AC-006：TICK-VALID，re_verified。实读 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md`：明文正式取代 A98 并给出理由与回退；实查 `docs/pending/p078_mobile_http_login_secure_cookie_silent_bounce.md` 文件头 status=closed、resolution=transferred、fix_ref=t079。
- AC-007：TICK-VALID，re_verified。本人实跑 testing.md 三组门禁：doctor_cmd（collect 464、md_kx 存在、敏感扫描 PASSED 33 文件）、test_cmd（模板契约 463 passed / 1 skipped、前端 vitest 55 文件 590 passed + `tsc -b` + build、桌面 npm test exit 0、敏感扫描 PASSED）、blackbox_verify（stubApi E2E 21 passed）；另自跑 `tests/mail_core/test_auth.py` 18 passed / 3 skipped；旧测试 4 个整体删除与 progress.md 逐条理由比对一致（整函数删除，保留测试仅删 delenv 死引用行、无断言改动）。

coverage = 7 / 7

verdict: PASS

## Round 2 (2026-11-14T02:56:00+08:00)

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：2
- reviewed_at：2026-11-14T02:56:00+08:00

reviewed_scope: 056ac5211e840a5c

### Findings

### t079_code_f002 - AC-003 守卫动态扫描仍漏根目录与 scripts/ 等活配置面

- 严重度：minor
- 锚点：行为缺陷（守卫强度）— AC-003 当前事实不受影响（本人本轮全仓检索活配置面仍为零），但守卫对清单外活文件仍有盲区，与 test 轴 f001 举例的「新 compose 文件」一类回归仍可漏过
- 位置：`tests/scripts/test_cookie_secure_removal_t079.py:19-48`
- 问题：动态扫描只覆盖固定文件 `docker-compose.mail-core.yml` 与 `.env.example`（`:19-22`）、`src/` 与 `docs/guides/` 两棵树（`:23-26`）及 `docs/blueprint` 顶层 `*.md`（`:29-30,47-48`）。本人本轮探针实测（探针写入后立即删除、`git status` 复原）：`src/`、`docs/guides/`、`docs/blueprint` 顶层探针均使守卫判红；`docs/blueprint/decisions/` 探针判绿属文件头声明的有意排除（决策记录须点名被删变量）；但 `scripts/probe_t079.sh`、根目录 `docker-compose.probe.yml`、`config/probe_t079.txt` 三处探针均判绿（守卫通过、未捕获）。其中根目录新 compose 文件正是前轮 test 轴 f001 举例的回归形态，`scripts/` 内含部署脚本（如 `scripts/deploy_mail_core.sh`）同属活配置面，在其中重新引入该变量守卫不会报警。未发现误伤：`src/` 全树扫描对现存前端测试与生成物无假阳性（剪除 `node_modules`/`dist`/`__pycache__` 后全量前端与守卫测试均绿）。
- 建议：把扫描面补上根目录通配（如 `docker-compose*.yml`、`Dockerfile*`、根目录 `*.md`）与 `scripts/`、`config/` 树，或改为「全仓扫描减去文件头已声明的历史归档排除清单」的反向枚举，使新增活文件默认被覆盖。

## 结论

- 前轮 finding 复核：t079_code_f001 已消除 — `src/frontend/src/api/client.ts:274` `checkSession(opts: { timeoutMs?: number } = {})` 将 `opts.timeoutMs` 透传 `apiRequest`（`:276`），`login()` 在 `:314` 以调用方 `timeoutMs` 回验；未传参时 `apiRequest` 回落默认 30 秒，冷启动调用方 `src/frontend/src/App.tsx:119` 的无参 `api.checkSession()` 与既有 spy/mock 调用方（`src/frontend/src/app.test.tsx`、`src/frontend/src/app.errorBoundary.test.tsx`）签名兼容、行为不变，本轮前端全量 55 文件 591 passed 佐证。新增用例 `src/frontend/src/api/client.login.test.ts:50`（bounds the /me verification）本轮自跑通过：回验挂起且预算 50ms 耗尽报 `timeout`，预算内回验 401/500 仍报 `session_not_established`（同文件其余用例）。语义说明：透传的是每腿同额预算而非剩余预算，最坏总时长约 2 倍 `timeoutMs`，但这正是 Round 1 建议给出的透传方案且原缺陷（回验走默认 30 秒、不受调用方预算约束）已消除，故只作提示不另出 finding。t079_test_f001（test 轴，本轮受托一并核范围）：固定 9 文件清单已改为动态扫描、`src/` 与 `docs/guides/` 与 blueprint 顶层的新文件回归已被守住，核心缺陷消除；但根目录/`scripts/`/`config/` 仍漏扫，见本轮 f002（minor）。
- 本轮新发现：1 条（minor 1；critical 0 / important 0）
- 未进表的提示：文件过大（降级规则）— `src/mail_core/security/auth.py` 564 行、`src/frontend/src/api/client.ts` 475 行，与 Round 1 相同，均为存量大文件、本轮净增极小且未引入可观测缺陷。超时总时长语义提示见上（每腿同额预算、最坏约 2 倍）。回归扫查 — 本轮 diff 其余部分（`cookie_secure()` scheme 推导与 SameSite 联动、compose/loader/models/desktop 删除、文档同步）与 Round 1 复核内容一致，未见签名变更外溢或新问题；七视角（安全/正确性/契约/性能/架构/健壮性/文档）已扫，除 f002 外未命中。
- 总体判断：两条前轮 minor 的核心缺陷均已消除，仅新增 1 条 minor 守卫盲区，无未解决 critical / important，判 PASS。
- 系统性 follow-up：无（f002 为本 task 内守卫范围补强，由实施方在本 task 处置表处理即可）

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮自跑后端定向组 38 passed / 3 skipped，其中 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 http 非 localhost 域名登录闭环（Set-Cookie 无 Secure、回送后 `/api/auth/me` 200）通过。
- AC-002：TICK-VALID，re_verified。同文件 https scheme 注入用例通过：登录 Set-Cookie 含 Secure 且残留 env 不影响判定。
- AC-003：TICK-VALID，re_verified。本轮本人全仓检索复跑：活配置面（compose、`.env.example`、`src/`、`docs/guides/`、`scripts/`、根目录文件）零命中，剩余命中仅决策记录、p078、A98 历史审阅、task.md、两份守卫/回归测试与 `.scratch/` 草稿，与 progress.md 例外清单一致；守卫盲区只影响未来回归强度、已出 f002，不改变当前清零事实。
- AC-004：TICK-VALID，re_verified。复读 `src/mail_core/security/auth.py` 的 `cookie_secure()`：env 分支已删、只读 ASGI scope scheme（回退 `url.scheme`）；本轮自跑 http/https 两路、未验证转发头不抬升、SameSite=None 联动用例均通过。
- AC-005：TICK-VALID，re_verified。本轮自跑前端全量 55 文件 591 passed，含 `client.login.test.ts` 5 用例（回验成功、401、500、冷启动 401 静默、回验超时边界）；`checkSession` 签名变更对冷启动与其他调用方无回归（见前轮复核段）。
- AC-006：TICK-VALID，re_verified。本轮全仓检索实见 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md` 明文记载删除该配置项并取代 A98，`docs/pending/p078_mobile_http_login_secure_cookie_silent_bounce.md` 记载已转办 t079。
- AC-007：TICK-VALID，trust_prior。本轮未重跑 testing.md 三组全量门禁，仅重跑受 Round 2 改动影响的部分（后端定向 38 passed、前端全量 vitest 591 passed 及 openapi/css 检查 exit 0、守卫 7 passed 含于定向组）；全量门禁结果依赖 Round 1 本人实跑记录（doctor/test_cmd/blackbox 全绿，见 Round 1 节）。

coverage = 6 / 7

verdict: PASS

## Round 3 (2026-11-14T03:03:00+08:00)

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：3
- reviewed_at：2026-11-14T03:03:00+08:00

reviewed_scope: 844f8046b4c75940

### Findings

### t079_code_f003 - AC-003 守卫跟随符号链接读到 worktree 外文件，判定可被仓外内容影响

- 严重度：minor
- 锚点：行为缺陷（守卫判定边界）— AC-003 当前事实不受影响（守卫现绿、活面探针全对），但守卫的红/绿可由 worktree 外文件内容决定，与文件头声明的「扫整个 worktree」边界不符
- 位置：`tests/scripts/test_cookie_secure_removal_t079.py:51-65`（`_iter_live_files`）、`:72`（`read_text`）
- 问题：`_iter_live_files()` 以 `ROOT.rglob("*")` 枚举后只按相对路径剪枝/排除，未处理符号链接，`path.is_file()` 与 `read_text` 均跟随链接。本人本轮探针实测：根目录放一符号链接指向仓外含该变量的临时文件，守卫判红；删链接后复绿，证明扫描确实读出 worktree。现存实例：worktree 根 `.env` 是指向同级另一 checkout 的 `.env` 的符号链接（本 task 非范围明确不动现役 `.env`），本轮实测其目标文件含该变量 0 处、故守卫现绿；但若该仓外部署文件日后写入旧变量残留，守卫会在本仓活面全清的情况下误报红。覆盖无依赖此行为：另一符号链接 `.env.example` 的目标 `config/.env.example` 本身就在树内被直接扫描，跳过出树链接不丢覆盖。
- 建议：在 `_iter_live_files()` 中跳过解析后落到 ROOT 之外的符号链接（或对符号链接文件一律跳过并在文件头注明），并补一条出树链接探针用例锁定边界。

## 结论

- 前轮 finding 复核：t079_code_f002 已消除 — 守卫已改为全树反向枚举（`tests/scripts/test_cookie_secure_removal_t079.py:29-65`：`rglob` 全树枚举，`PRUNE_DIRS` 剪除 `.git`/`.venv`/`.scratch`/`.repo_template`/`node_modules`/`dist`/`__pycache__`，`EXCLUDE_PREFIXES` 与 `EXCLUDE_FILES` 仅排归档/非活面，理由写入文件头 `:1-22`）。本人本轮探针逐个实测（写入即跑、撤除即复跑、全部清除后 `git status` 复核无残留）：根目录普通文件与 `docker-compose.probe_t079.yml`、`scripts/`、`config/`、`docs/` 根、`docs/blueprint` 顶层、`docs/specs/`、`src/`、`docs/guides/`、根与 `config/` 下的隐藏文件探针均判红、撤除全部复绿；`docs/blueprint/decisions/` 与 `tests/` 内探针保持绿，证明两处排除真实生效。排除清单核查：与 `docs/blueprint/testing.md` 敏感扫描分界对照一致（reviews/archive/tasks/pending/findings/spikes/handoff.md 为已评审归档），decisions 为须点名被删变量的决策档案、tests 为故意 setenv 的回归测试与守卫常量本身，均非活面；反向核查未见误排活面——`docs/guides/`、`docs/specs/`、`docs/skills/`、`docs/blueprint` 顶层、`schemas/`、`assets/` 探针均判红（在扫），`.repo_template` 探针保持绿（工具链剪除生效）。t079_code_f001 维持已消除：`src/frontend/src/api/client.ts` 自 Round 2 后未再改动，本轮自跑 `src/frontend/src/api/client.login.test.ts` 5 passed（含回验超时边界用例）。
- 本轮新发现：1 条（minor 1；critical 0 / important 0）
- 未进表的提示：范围对照 — 除守卫文件外，其余交付与 Round 2 scope 相比无变化：`git diff` 对锚点仍为 14 文件（78 insertions / 113 deletions）、未跟踪交付文件清单与 Round 2 相同，关键文件修改时间均早于 Round 2 审阅时点、仅守卫文件在其后更新；本轮定向合跑与 Round 2 同为 65 passed / 3 skipped。文件过大（降级规则）— `src/mail_core/security/auth.py` 564 行、`src/frontend/src/api/client.ts` 475 行，与前轮相同，均为存量大文件且本轮未触及。圈复杂度 — 新守卫 `_iter_live_files()` 约 5、`test_cookie_secure_env_removed_from_live_surface()` 约 3，未达提示阈值。七视角扫查本轮聚焦守卫变更面：安全（守卫只读不执行、无凭证问题）、正确性（前缀匹配带 `/` 边界、无误排同名前缀目录）、契约、性能（全树读文件仅测试期一次性扫描）、架构、健壮性（`OSError` 跳过与前轮一致）、文档（文件头排除理由与实现一致）均已扫过，除 f003 外未命中。
- 总体判断：f002 修复真实有效，AC-001～AC-007 仍全部成立，无未解决 critical / important，仅新增 1 条 minor（守卫符号链接边界），判 PASS。
- 系统性 follow-up：无（f003 为本 task 内守卫边界补强，由实施方在本 task 处置表处理即可）

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮自跑定向合跑 65 passed / 3 skipped，其中 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 http 非 localhost 域名登录闭环（Set-Cookie 无 Secure、回送后 `/api/auth/me` 200）通过。
- AC-002：TICK-VALID，re_verified。同文件 https scheme 注入用例通过：登录 Set-Cookie 含 Secure 且残留 env 不影响判定。
- AC-003：TICK-VALID，re_verified。本轮本人全仓检索复跑：剩余命中仅两份 tests 守卫/回归测试、`docs/blueprint/decisions` 决策记录、`docs/pending` 的 p078 转办记录、`docs/reviews` 的 A98 历史审阅与 `docs/tasks` 本 task 流程文件，与 progress.md 例外清单一致，活配置面为零；新守卫全树探针实测（根/`scripts/`/`config/`/`docs/` 根判红、decisions 与 tests 排除判绿）见前轮复核段。
- AC-004：TICK-VALID，re_verified。复读 `src/mail_core/security/auth.py` 的 `cookie_secure()`：env 分支已删、只按请求 scheme 判定；合跑中 http/https 两路、未验证转发头不抬升与 SameSite=None 联动用例均通过。
- AC-005：TICK-VALID，re_verified。本轮自跑 `src/frontend/src/api/client.login.test.ts` 5 passed：回验成功、回验 401、回验 500、冷启动 401 静默、回验超时边界五路均绿，`client.ts` 与 Round 2 复核内容一致。
- AC-006：TICK-VALID，re_verified。本轮全仓检索实见 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md` 正文点名被删配置项并记载取代 A98，`docs/pending/p078_mobile_http_login_secure_cookie_silent_bounce.md` 记载已立项转办 t079。
- AC-007：TICK-VALID，trust_prior。本轮未重跑 testing.md 三组全量门禁，仅重跑受守卫改动影响的定向合跑（65 passed / 3 skipped，与 Round 2 同数）与前端 login 单测（5 passed）；全量门禁结果依赖 Round 1 本人实跑记录（doctor/test_cmd/blackbox 全绿，见 Round 1 节），且本轮已证其余交付与 Round 2 scope 相比除守卫外无变化。

coverage = 6 / 7

verdict: PASS

## Round 4 (2026-11-14T03:07:26+08:00)

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：4
- reviewed_at：2026-11-14T03:07:26+08:00

reviewed_scope: 9ac56619edd02fda

### Findings

本轮无新 finding。

## 结论

- 前轮 finding 复核：t079_code_f003 已消除 — 守卫 `tests/scripts/test_cookie_secure_removal_t079.py:58-82` 的 `_iter_live_files()` 对每个候选文件先 `path.resolve()`（`:74`），解析结果不 `is_relative_to(ROOT)` 时跳过（`:77-80`），文件头 `:19-24` 写明该边界与理由；新增探针用例 `test_cookie_secure_guard_ignores_out_of_tree_symlink`（`:100`）随附。本人本轮自建探针亲验（全部探针写入即测、撤除即复跑，结束时 `git status` 与实验前一致、无残留）：（1）仓外链接探针 — 在 worktree 根放符号链接指向仓外含该变量的临时文件，`_collect_offenders()` 不含该链接名、守卫保持绿；现存实例根 `.env`（指向主仓部署 `.env`、解析后在 ROOT 外）实测不在活文件清单内，本人对该部署文件只做只读检索、未作任何改动。（2）树内链接探针 — 根目录符号链接指向树内（`tests/` 下、其直接路径本身属排除区）含该变量的文件，offenders 含该链接名、判红，证明树内链接照常经链接路径扫描；现存 `.env.example`（指向 `config/.env.example`）实测在活文件清单内。（3）树内真实文件探针 — `config/` 下普通文件含该变量判红，证明 resolve 校验未误伤树内真实文件覆盖。撤除全部探针后 offenders 复归空、守卫 2 passed。t079_code_f001、t079_code_f002 维持已消除：相关文件自各自修复轮次后未再改动（修改时间与 `git status` 清单核对），本轮前端 login 单测 5 passed、定向合跑含 f002 的全树探针结论所依守卫用例均绿。
- 本轮新发现：0 条
- 未进表的提示：范围对照 — 除守卫文件（本轮 f003 修复对象）与流程文件 `progress.md` 的 Round 3 处置节外，其余交付与 Round 3 scope 相比无变化：`git status --short` 清单与 Round 3 相同，关键交付文件修改时间均不晚于各自修复轮次（`auth.py`、`client.ts`、`client.login.test.ts` 均在 Round 3 审阅时点之前），相对锚点的 tracked diff 增量仅来自 `progress.md` 处置记录。文件过大与复杂度同前轮（存量大文件、本轮未触及），无新提示。七视角本轮聚焦守卫变更面扫查：正确性（resolve 后边界校验对真实文件、树内链接、出树链接三态均亲验）、安全（守卫只读不执行；出树跳过避免仓外内容影响本仓判定）、健壮性（`resolve()` 的 `OSError` 跳过与既有 `read_text` 容错一致）、其余视角无命中。
- 总体判断：f003 修复真实有效且边界三态（出树跳过 / 树内链接扫描 / 树内真实文件扫描）均经独立探针证实，AC-001～AC-007 仍全部成立，无未解决 critical / important、无新 finding，判 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮定向合跑 66 passed / 3 skipped，其中 http 非 localhost 域名登录闭环用例（Set-Cookie 无 Secure、回送后 `/api/auth/me` 200）通过。
- AC-002：TICK-VALID，re_verified。同合跑 https scheme 注入用例通过：登录 Set-Cookie 含 Secure 且残留 env 不影响判定。
- AC-003：TICK-VALID，re_verified。本轮亲验守卫边界三态探针（出树链接跳过、树内链接判红、树内真实文件判红、撤除复绿，见前轮复核段）；守卫现 2 用例自跑 2 passed；活配置面零残留事实与前轮全仓检索结论一致且守卫文件外无交付变化。
- AC-004：TICK-VALID，re_verified。定向合跑中 scheme 推导 http/https 两路、未验证转发头不抬升与 SameSite=None 联动用例均通过，实现文件自 Round 1 后未改动。
- AC-005：TICK-VALID，re_verified。本轮自跑前端 `client.login.test.ts` 5 passed（回验成功、401、500、冷启动静默、回验超时边界）。
- AC-006：TICK-VALID，trust_prior。决策记录与 p078 转办状态自 Round 3 本人实查后未改动（修改时间核对），本轮依赖 Round 3 的实查证据。
- AC-007：TICK-VALID，trust_prior。本轮未重跑 testing.md 三组全量门禁，仅重跑受 f003 修复影响的定向合跑（66 passed / 3 skipped，与实施方记录一致、较 Round 3 的 65 条正好多出新增的出树链接探针用例）与前端 login 单测；全量门禁结果依赖 Round 1 本人实跑记录（doctor/test_cmd/blackbox 全绿），且本轮已证其余交付除守卫外无变化。

coverage = 5 / 7

verdict: PASS
