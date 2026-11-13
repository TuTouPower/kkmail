# Task review t079（reviewer_focus: 测试）

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：1
- reviewed_at：2026-11-14T02:47:00+08:00

reviewed_scope: 2a7889bd235375ce

## Findings

### t079_test_f001 - AC-003 守卫只枚举固定文件清单，全仓回归锁定弱于 AC 口径

- 严重度：minor
- 锚点：AC-003（守卫的未来回归锁定范围；AC 本身已经全仓检索独立复核成立，见 AC 复验方式，不阻断本轮打勾）
- 位置：`tests/scripts/test_cookie_secure_removal_t079.py:10-20`（`LIVE_FILES` 清单）
- 问题：守卫只检查 9 个已知曾含该变量的文件。若日后在清单外的新活配置面文件（新 compose 文件、新配置模块、新 guides 文档）重新引入 `MAIL_CORE_COOKIE_SECURE`，该守卫仍会绿。本轮 AC-003 的成立不依赖此守卫——reviewer 已独立跑全仓检索，命中仅为决策记录、p078 转办记录、A98 历史审阅原文、本 task 契约/进度文件与两份新守卫测试（另 `.scratch/` 下实施草稿脚本含该字符串，该目录已被 git 忽略、不属仓库交付面）；活配置面（compose、`.env.example`、`src/`、`docs/guides/`）为零。故此项只是守卫强度提示，不是覆盖缺口。
- 建议：把守卫改为按目录扫活配置面（compose 文件、`.env.example`、`src/`、`docs/guides/`）并以显式 allowlist 排除归档目录，或在新增活配置面文件时同步扩充清单。

## 结论

- 改测方向复核：无「迁就实现」的就地改预期。diff 中测试改动只有整体删除与死引用清理：`tests/mail_core/test_auth.py` 的 `test_cookie_secure_boundary`、`tests/mail_core/test_auth_r4adopt_p16.py` 的 `test_a324_samesite_none_with_secure_is_kept`、`tests/scripts/test_deploy_mail_core_r4adopt_p51.py` 的两个 A98 测试均为整函数删除，删除对象断言的正是被本 task 废除的 env 双输入模型 / compose 默认 1 契约，理由逐条记于 progress.md 且与 diff 实查一致；新语义由 `tests/mail_core/test_cookie_secure_scheme_derived.py` 接续（scheme 两路、未验证转发头不信任、SameSite=None 联动、黑盒闭环）。p16 文件另删两处对已删变量的 `delenv` 死引用行，保留测试的断言一字未改、语义不变。前端无既有测试被改。
- 危险模式扫描：逐条扫过，无恒真断言、无删/反转 expect、无注释掉断言、无 `.skip`/`.only`/`pytest.mark.skip`、无 `eslint-disable`/`@ts-ignore`/`# type: ignore`、无 timeout/重试/容差放大、无条件跳过断言、无程序赋值冒充真实交互。两处语法命中经调查放行并在此说明：`src/frontend/src/api/client.login.test.ts:34` 的 `expect(err.message).toBeTruthy()` 与 `:37` 起的 `rejects.toMatchObject({code})` 不是对既有断言的弱化（均为新测），主断言是错误码 `session_not_established` 的精确 `toBe` 相等，message 非空检查恰好守住登录页显示前提（消息为空则错误区不渲染）；前端 mock 只打在系统边界 `fetch` 上且按 URL 路由，`api.checkSession()` 本身未被 mock、走真实代码路径。后端单测的 `SimpleNamespace` 假 request 只替身 scheme 读取面，且转发头用例使用真实 Starlette `Request`、黑盒用例走真实登录路由，不属 mock 被测逻辑。
- 红绿有效性（reviewer 独立复现）：把 `src/mail_core/security/auth.py` 临时回退到锚点版本后跑新后端测，得 5 failed / 1 passed（通过的是既有转发头不信任语义），与守卫测合算与实施方自报「红 6 failed / 1 passed」一致；另以 cookiejar 实验在旧代码 + env 强制 Secure + http 局域网域名形态下复现 p078 原现象（登录 200、Set-Cookie 带 Secure、jar 回送后 `/api/auth/me` 得 401），同一实验在新代码下 `/me` 得 200，证明黑盒测的 jar 行为真实、非假绿。回退后已恢复新代码并以 diff 复核无残留。
- 门禁数字抽查复跑（全部与实施方自报一致）：模板契约 463 passed / 1 skipped、doctor 的 collect 464 与敏感扫描 PASSED（33 文件 0 违规）；后端 unit 全量 1663 passed / 539 skipped / 0 failed；本 task 定向 5 文件合跑 65 passed / 3 skipped，其中新测 7 passed（后端 6 + 守卫 1）；前端 vitest 590 passed（55 文件）、新 `client.login.test.ts` 单跑 4 passed；blackbox stubApi E2E 21 passed。
- 本轮新发现：1 条（minor，不阻断）
- 未进表的提示：AC-005 的「登录页明确显示」无新组件级用例直接渲染 `LoginPage` 验 `session_not_established` 文案；现有证据链为 api 层拒绝（新测覆盖）+ `src/frontend/src/components/LoginPage.tsx` 既有 catch 到 `setError` 到 `role="alert"` 显示路径 + 既有 `src/frontend/src/components/LoginPage.test.tsx:57` 已钉死该显示机制（拒绝消息原文渲染于 alert 区），故判定覆盖成立；补一条组件级串联用例属可选扩展，不作 finding。
- 总体判断：新测真实红绿、删除合法且有据、七条 AC 的测试与验证证据名副其实，仅一条 minor 守卫强度提示，PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_cookie_secure_scheme_derived.py:96` 黑盒断言 http 局域网域名登录 Set-Cookie 无 Secure 且两次 `/api/auth/me` 均 200；reviewer 另以 jar 实验在新代码复现 200、旧代码复现 401。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_cookie_secure_scheme_derived.py:108` 以 https base_url 等价 scheme 注入断言 Set-Cookie 带 Secure 且会话回送 200（env 故意置 0 仍成立），该用例在旧代码上实测红。
- AC-003：TICK-VALID，re_verified。守卫测 `tests/scripts/test_cookie_secure_removal_t079.py:24` 通过；reviewer 独立全仓检索，活配置面命中为零，剩余命中与 progress.md 例外清单逐项一致。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_cookie_secure_scheme_derived.py:48`、`:56`、`:63`、`:78` 覆盖 http/https 两路、env 正反强置均无效、未验证 `X-Forwarded-Proto` 不抬升、SameSite=None 只随 https 保留，其中三条在旧代码上实测红。
- AC-005：TICK-VALID，re_verified。`src/frontend/src/api/client.login.test.ts` 四用例单跑全绿（回验成功放行、401 与 500 均抛具名 `session_not_established`、冷启动 `checkSession()` 静默返 false），显示路径由 LoginPage 既有错误区与 `LoginPage.test.tsx:57` 的既有断言钉住。
- AC-006：TICK-VALID，re_verified。决策记录 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md` 已落盘且正文明确「正式取代 A98」；p078 文件头实查 status=closed、resolution=transferred、fix_ref=t079。
- AC-007：TICK-VALID，re_verified。reviewer 复跑 doctor_cmd（collect 464、敏感扫描 PASSED）、test_cmd 契约 463 passed / 1 skipped 与前端 590 passed、blackbox_verify 21 passed、后端全量 1663 passed / 539 skipped；4 个失效旧测试的整体删除与逐条理由已核对 diff 与 progress.md 记录一致。

coverage = 7 / 7

verdict: PASS

## Round 2 (2026-11-14T02:56:51+08:00)

reviewed_scope: 056ac5211e840a5c

## Findings

本轮无新 finding。

## 结论

- 前轮 finding 复核：
    - t079_code_f001（minor，code 轴）：已消除。实现实查 `src/frontend/src/api/client.ts:274-277`：`checkSession(opts: { timeoutMs?: number } = {})` 透传 `apiRequest('/api/auth/me', { timeoutMs: opts.timeoutMs })`；`login()` 回验调用点（同文件 :314 附近）已改为 `api.checkSession({ timeoutMs })`，以调用方预算回验。判别力由 reviewer 亲验：把回验调用点临时回退为不传参的 `api.checkSession()` 后，新增用例 `bounds the /me verification by the caller timeout (t079 code f001)`（`src/frontend/src/api/client.login.test.ts:50`）复红——/me 挂起不再受 50ms 预算约束、用例挂起至 vitest 5000ms 测试超时失败（正走向修复前默认 30 秒，正是原缺陷形态）；恢复后该文件 5 passed、tests 合计 60ms（回验腿在预算内以 `timeout` 拒绝）。回退实验后已恢复并以 `git diff --stat` 与 `git status --short` 复核与实验前一致、无残留。语义未换形式弱化：预算内回验失败（401/500 两用例）仍抛 `session_not_established`，仅预算耗尽时与登录其余腿一致报 `timeout`。
    - t079_test_f001（minor，本轴）：已消除。守卫 `tests/scripts/test_cookie_secure_removal_t079.py` 已由 9 文件固定清单改为动态扫描活配置面：固定文件 compose 与 `.env.example`，全树扫描 `src/` 与 `docs/guides/`（剪除 `node_modules`/`dist`/`__pycache__`/`.venv`/`.git`），`docs/blueprint` 仅顶层 `*.md`；文件头写明归档排除理由（`docs/reviews`、`docs/pending`、`docs/tasks`、`docs/blueprint/decisions` 为历史档案、决策记录须点名被删变量，`tests/` 本身故意 setenv 验忽略）。reviewer 自行探针实验（非采信实施方自报）：在 `src/` 新建含该变量文件、在 `docs/guides/` 新建探针、在 `docs/blueprint` 顶层新建探针，三处均判红（offenders 准确列出探针路径）；反向探针——`docs/blueprint/decisions/` 内放同名探针、`src/frontend/node_modules/` 内放探针——守卫保持绿，证明归档排除与剪除真实生效；全部探针撤除后守卫复绿（与后端新测合跑 7 passed）。扫描范围恰当性另核：`docs/blueprint` 实地结构只有顶层 `*.md` 与 `decisions/` 一个子目录，顶层 glob 加 decisions 排除即覆盖全树、无未扫活面；现存活配置面全量基线绿、无误伤（reviewer 独立 grep compose、`.env.example`、`src/`、`docs/guides/` 命中为零）。
- 改测方向复核：无「迁就实现」的改测。本轮 delta 只有新增用例（bounds）与守卫扫描范围扩大，既有断言一字未改、未删；bounds 用例断言的是调用方契约（预算耗尽报 `timeout`），与修复方向一致，非迁就当前输出。
- 危险模式扫描（本轮 delta）：逐条扫过，无恒真断言、无删/反转/注释 expect、无弱化断言、无 `.skip`/`.only`、无静默错误标记、无 timeout/重试放大掩盖（bounds 用例用 50ms 小预算且断言精确错误码，方向与「阈值掩盖」相反）；全文件仅一处存量 `expect(err.message).toBeTruthy()`（`client.login.test.ts:34`），Round 1 已调查放行（主断言为错误码精确相等），本轮未变。
- 回归数字抽查（reviewer 本轮实跑）：前端 vitest 全量 591 passed（55 文件，即 Round 1 的 590 + 新增 bounds 1 条）；`client.login.test.ts` 单跑 5 passed；后端定向 5 文件合跑 65 passed / 3 skipped（与 Round 1 同口径，含后端新测 6 + 守卫 1）；守卫与后端新测在探针撤除后合跑 7 passed。本轮 delta 只触及前端超时透传与守卫扫描，未触后端实现、模板契约与 blackbox 面，其 Round 1 全量门禁数字（doctor collect 464、契约 463 passed / 1 skipped、blackbox 21 passed、后端全量 1663 passed / 539 skipped）对应的交付内容与 Round 1 复核时一致。
- 本轮新发现：0 条
- 未进表的提示：bounds 用例的红形态是 vitest 测试超时（5000ms）而非断言失败，这是修复前 30 秒默认挂起的必然表现；绿形态下断言精确（错误码 `timeout`、全文件 60ms 内完成），不影响判别力，仅记录备查。
- 总体判断：两条 Round 1 minor finding 均经独立红绿/探针实验确认真修、无换形式弱化，七条 AC 在当前 scope 下打勾仍全部成立，无新 critical / important / minor，PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮定向合跑中 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 http 局域网域名黑盒用例通过（Set-Cookie 无 Secure、两次 `/api/auth/me` 均 200），本轮 delta 未触该路径。
- AC-002：TICK-VALID，re_verified。同上合跑中 https scheme 注入用例通过（Set-Cookie 带 Secure、残留 env=0 不影响、会话回送 200）。
- AC-003：TICK-VALID，re_verified。动态守卫经 reviewer 三处活面探针判红、两处归档/剪除反向探针保持绿、撤除复绿；独立 grep 活配置面（compose、`.env.example`、`src/`、`docs/guides/`）命中为零。
- AC-004：TICK-VALID，re_verified。定向合跑中 scheme 两路、env 正反强置无效、未验证转发头不抬升、SameSite=None 联动四类用例全绿，本轮 delta 未触后端判定。
- AC-005：TICK-VALID，re_verified。`client.login.test.ts` 5 passed：回验成功放行、401 与 500 抛具名 `session_not_established`、冷启动 `checkSession()` 静默返 false、新增 bounds 用例钉住回验受调用方 timeoutMs 约束；回退实验反证新用例判别力。
- AC-006：TICK-VALID，re_verified。实读决策记录 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md:4` 明文「正式取代 A98」；p078 文件头实查 status=closed、resolution=transferred、fix_ref=t079。
- AC-007：TICK-VALID，re_verified。本轮实跑前端全量 591 passed、定向合跑 65 passed / 3 skipped、守卫与后端新测 7 passed，与实施方自报一致；本轮 delta 未触的门禁面（doctor、模板契约、blackbox、后端全量）交付内容与 Round 1 独立复跑通过时一致，失效旧测试删除理由记录未变。

coverage = 7 / 7

verdict: PASS

## Round 3 (2026-11-14T03:01:48+08:00)

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：3
- reviewed_at：2026-11-14T03:01:48+08:00

reviewed_scope: 844f8046b4c75940

## Findings

本轮无新 finding。

## 结论

- 前轮 finding 复核：
    - t079_code_f002（minor，code 轴，Round 2 新记）：已消除。守卫 `tests/scripts/test_cookie_secure_removal_t079.py:51-65` 已改为全树反向枚举：以 `ROOT.rglob` 扫整个 worktree，仅按 `PRUNE_DIRS`（`:29-37`）、`EXCLUDE_PREFIXES`（`:38-47`）与 `EXCLUDE_FILES`（`:48`）排除非活面；断言仍为 `offenders == []` 精确相等（`:68-77`），未弱化。reviewer 亲验探针判别力（非采信实施方自报，探针内容均为该变量名加 probe 字样，每处单独写入、单独跑守卫、跑后立即删除）：根目录 `probe_t079_r3.txt` 判红、offenders 精确为 `['probe_t079_r3.txt']`；`scripts/probe_t079_r3.txt` 判红、offenders 精确为 `['scripts/probe_t079_r3.txt']`；`config/probe_t079_r3.txt` 判红、offenders 精确为 `['config/probe_t079_r3.txt']`；`docs/probe_t079_r3.md`（docs 根）判红、offenders 精确为 `['docs/probe_t079_r3.md']`——Round 2 判绿的三处盲区（根目录、`scripts/`、`config/`）与本轮新增核查的 docs 根全部补上。反向探针：`docs/blueprint/decisions/probe_t079_r3.md` 保持绿、`tests/probe_t079_r3.txt` 保持绿，证明决策归档与 tests 排除真实生效、无误伤式全红。全部探针撤除后守卫复绿（1 passed），并以 `git status --short` 复核与探针实验前逐行一致、无任何探针残留。
    - 排除清单与敏感扫描分界一致性：核对一致。敏感扫描的归档分界（`scripts/check_doc_sensitive.py` 的 `ARCHIVE_DIR_PREFIXES` 与 `ARCHIVE_FILES`，及 `docs/blueprint/testing.md`「扫描边界按目录职责分离」段）为 `docs/reviews/`、`docs/archive/`、`docs/tasks/`、`docs/pending/`、`docs/findings/`、`docs/spikes/` 六前缀加 `docs/handoff.md` 单文件；守卫 `EXCLUDE_PREFIXES`/`EXCLUDE_FILES` 与此逐项相同。守卫的三项额外排除均在文件头（`:10-21`）写明理由且不与敏感扫描分界冲突：`docs/blueprint/decisions` 是决策归档（敏感扫描的发布面只含 `docs/blueprint/*.md` 顶层、本就不含 decisions 子目录，且 20261113 决策记录须点名被删变量）；`tests` 含守卫自身的检索常量与故意 setenv 验忽略的方案测试，敏感扫描只扫 `docs`、无此面；`.repo_template` 与 `.git`/`.venv`/`.scratch`/`node_modules`/`dist`/`__pycache__` 属工具链与 VCS/环境/构建目录。守卫的实际扫描面是敏感扫描发布面（`docs/guides/`、`docs/blueprint/*.md`、`docs/specs/*.md`、根 README）的超集——另覆盖根目录、`src/`、`scripts/`、`config/`、`docs/skills/` 等全部活面，未发现被守卫排除而敏感扫描会扫的活面。
    - 守卫文件外无其他测试变动：已核。相对锚点的 tracked 测试 diff 仍只有 Round 1 已审的整体删除三文件（`tests/mail_core/test_auth.py`、`tests/mail_core/test_auth_r4adopt_p16.py`、`tests/scripts/test_deploy_mail_core_r4adopt_p51.py`，删除内容与前轮记录一致）；未跟踪测试文件中只有守卫文件的修改时间落在 Round 2 审阅之后，后端新测与前端 login 测试的修改时间均在 Round 2 之前、内容与前轮审阅一致。本轮 delta 仅守卫一文件。
- 改测方向复核：无「迁就实现」的改测。本轮 delta 只有守卫扫描范围由枚举改为反向全树枚举，断言未改、未删、未弱化，方向是加强回归锁定而非迁就当前输出。
- 危险模式扫描（本轮 delta）：逐条扫过，无恒真断言、无删/反转/注释 expect、无弱化断言（仍为列表精确相等）、无 `.skip`/`.only`/`pytest.mark.skip`、无静默错误标记、无 mock、无 timeout/重试/容差放大、无条件跳过断言。
- 回归数字抽查（reviewer 本轮实跑）：守卫单跑 1 passed；定向 5 文件合跑 65 passed / 3 skipped（`tests/mail_core/test_cookie_secure_scheme_derived.py`、`tests/scripts/test_cookie_secure_removal_t079.py`、`tests/mail_core/test_auth.py`、`tests/mail_core/test_auth_r4adopt_p16.py`、`tests/scripts/test_deploy_mail_core_r4adopt_p51.py`，合集 collect 68，与 65+3 一致），与实施方自报逐项一致；另单跑前端 `src/frontend/src/api/client.login.test.ts` 5 passed 佐证 AC-005 未受本轮 delta 影响。
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：t079_code_f002 经四处活面探针判红、两处排除面探针保持绿、撤除复绿独立确认真修，排除清单与敏感扫描分界对齐，守卫外无其他测试变动，七条 AC 在当前 scope 下打勾仍全部成立，无新 critical / important / minor，PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮定向合跑中 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 http 局域网域名黑盒用例通过（Set-Cookie 无 Secure、两次 `/api/auth/me` 均 200），本轮 delta 未触该路径。
- AC-002：TICK-VALID，re_verified。同上合跑中 https scheme 注入用例通过（Set-Cookie 带 Secure、残留 env 置 0 不影响、会话回送 200）。
- AC-003：TICK-VALID，re_verified。反向枚举守卫经 reviewer 四处活面探针（根目录、`scripts/`、`config/`、docs 根）判红且 offenders 路径准确、两处排除面探针（`docs/blueprint/decisions/`、`tests/`）保持绿、撤除复绿；独立全仓检索剩余命中仅决策记录、p078 转办记录、A98 历史审阅原文、本 task 流程文件与两份守卫/方案测试，活配置面为零。
- AC-004：TICK-VALID，re_verified。定向合跑中 scheme 两路、env 正反强置无效、未验证转发头不抬升、SameSite=None 联动用例全绿，本轮 delta 未触后端判定。
- AC-005：TICK-VALID，re_verified。本轮单跑 `src/frontend/src/api/client.login.test.ts` 5 passed（回验成功放行、401 与 500 抛具名 `session_not_established`、冷启动 `checkSession()` 静默返 false、回验受调用方 timeoutMs 约束），本轮 delta 未触前端。
- AC-006：TICK-VALID，re_verified。实读决策记录 `docs/blueprint/decisions/20261113_cookie_secure_scheme_derived.md` 正文明确「正式取代 A98」；p078 文件头实查 status=closed、resolution=transferred、fix_ref=t079。
- AC-007：TICK-VALID，trust_prior。本轮按窄范围只复跑守卫单跑与定向合跑（65 passed / 3 skipped）及前端 login 单测，未重跑 testing.md 三组全量门禁；全量门禁通过依赖 Round 1 双轴独立实跑记录，本轮 delta 仅守卫测试一文件且该文件已含于本轮定向合跑并通过，失效旧测试删除理由记录未变。

coverage = 6 / 7

verdict: PASS

## Round 4 (2026-11-14T03:07:49+08:00)

- task：`t079_cookie_secure_scheme_derived`
- spec：`docs/tasks/t079_cookie_secure_scheme_derived/task.md`
- diff_anchor：`95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- target：`git diff 95c72cef4f1c0402bb6c47c3afa542a211fa625c`
- round：4
- reviewed_at：2026-11-14T03:07:49+08:00

reviewed_scope: 9ac56619edd02fda

## Findings

本轮无新 finding。

## 结论

- 前轮 finding 复核：
    - t079_code_f003（minor，code 轴，Round 3 新记）：已消除。实现实查 `tests/scripts/test_cookie_secure_removal_t079.py:73-80`：`_iter_live_files()` 对每个候选文件先 `path.resolve()`，再以 `resolved.is_relative_to(ROOT)` 校验，出树目标直接跳过；文件头 `:23-27` 已写明该边界（仓外目标内容不得令本仓守卫红/绿、树内链接如 `.env.example` 照常扫描）。新增用例 `test_cookie_secure_guard_ignores_out_of_tree_symlink` 位于同文件 `:100-108`。判别力由 reviewer 亲验（非采信实施方自报）：（1）临时回退实验——删去 `:77-80` 的出树校验四行后跑守卫，得 1 failed / 1 passed，失败恰为新用例且 offenders 精确为 `['__t079_outside_link_probe__']`；主用例同期仍绿（现存出树 `.env` 目标当前不含该变量，隔离干净）。恢复后 2 passed，且守卫文件与实验前临时备份逐字一致。（2）自建探针复核 offenders 口径——出树探针：仓外临时文件（含该变量）经根目录自建符号链接接入活面，offenders 为 `[]`、链接名不在其中；树内探针：目标文件放在已被排除的 `tests/` 下、自建链接放在根目录活面，offenders 精确为 `['__r4_probe_in_link__']`、目标本身不在其中——证明树内链接照常被扫描（不是对符号链接一律跳过），且 offenders 记的是链接自身的相对路径。探针撤除后 offenders 复为 `[]`。（3）现存实例核对：根 `.env` 为指向仓外主仓部署文件的出树链接、`.env.example` 为指向 `config/.env.example` 的树内链接，与实现口径一致；本轮对主仓部署 `.env` 只做只读检索（该变量 0 命中），未改动任何现役部署文件。全部探针与临时备份已清除，`git status --short` 与实验前逐行一致、无残留。
    - 新用例断言质量核查：无恒真、无弱断言。新用例断言探针名不在 offenders 中，与主用例 `test_cookie_secure_env_removed_from_live_surface` 的 offenders 精确相等断言（同文件 `:96-97`）互补；回退实验已证校验缺失时该断言必然变红，不是恒真。用例以 pytest `tmp_path` 作仓外目标、用 `finally` 加 `unlink(missing_ok=True)` 保证失败路径也清除自建链接，不触任何现役文件。
- 改测方向复核：无「迁就实现」的改测。本轮 delta 只有守卫新增出树校验与一条新增用例；既有主用例断言一字未改、未删、未弱化，方向是补上判别边界而非迁就当前输出。
- 危险模式扫描（本轮 delta）：逐条扫过，无恒真断言、无删/反转/注释掉的断言、无弱化断言、无 `.skip` / `.only` / `pytest.mark.skip`、无静默错误标记、无 mock、无 timeout/重试/容差放大、无条件跳过断言。
- 回归数字抽查（reviewer 本轮实跑）：守卫单跑 2 passed（主用例加新出树链接用例）；定向 5 文件合跑 66 passed / 3 skipped（`tests/mail_core/test_cookie_secure_scheme_derived.py`、`tests/scripts/test_cookie_secure_removal_t079.py`、`tests/mail_core/test_auth.py`、`tests/mail_core/test_auth_r4adopt_p16.py`、`tests/scripts/test_deploy_mail_core_r4adopt_p51.py`），即 Round 3 同口径 65 加新用例 1，与实施方自报逐项一致。
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：t079_code_f003 经回退复红、自建出树/树内双向探针、恢复复绿独立确认真修，新用例判别力成立且无弱断言，七条 AC 在当前 scope 下打勾仍全部成立，无新 critical / important / minor，PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮定向合跑中 `tests/mail_core/test_cookie_secure_scheme_derived.py` 的 http 局域网域名黑盒用例通过（Set-Cookie 无 Secure、两次回验均 200），本轮 delta 未触该路径。
- AC-002：TICK-VALID，re_verified。同上合跑中 https scheme 注入用例通过（Set-Cookie 带 Secure、残留 env 不影响、会话回送 200）。
- AC-003：TICK-VALID，re_verified。守卫 2 passed；回退 resolve 校验使新出树用例精确复红、自建出树探针 offenders 为空、自建树内探针 offenders 精确命中链接路径、撤除复绿；现存出树 `.env` 与树内 `.env.example` 两链接口径与实现一致。
- AC-004：TICK-VALID，re_verified。定向合跑中 scheme 两路、env 正反强置无效、未验证转发头不抬升、SameSite=None 联动用例全绿，本轮 delta 未触后端判定。
- AC-005：TICK-VALID，trust_prior。本轮窄范围未重跑前端测试，依赖 Round 3 单跑 `src/frontend/src/api/client.login.test.ts` 5 passed 的记录；该文件与前端实现修改时间均早于 Round 3 审阅、本轮 delta 未触前端。
- AC-006：TICK-VALID，trust_prior。本轮未重读决策记录与 p078 文件头，依赖 Round 1 至 Round 3 的实读记录（决策记录明文取代 A98、p078 已关闭转办至本 task）；本轮 `git status` 中决策记录仍在未跟踪交付清单、内容未变。
- AC-007：TICK-VALID，trust_prior。本轮按窄范围只复跑守卫单跑与定向合跑，未重跑 testing.md 三组全量门禁；全量门禁通过依赖 Round 1 双轴独立实跑记录，本轮 delta 仅守卫测试一文件且已含于本轮定向合跑并通过，失效旧测试删除理由记录未变。

coverage = 4 / 7

建议合并前人工抽查 trust_prior 项

verdict: PASS
