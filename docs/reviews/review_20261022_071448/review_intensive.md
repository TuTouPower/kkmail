# Intensive Review — 全仓审阅 @ f915e78bcfc81767386f86b5e9f2448235f44fa7 · 2026-10-22

- Target: 当前全部已跟踪、符合 review 白名单的仓库文本文件；包含本次审阅中新提交的 task/spec。

- Scope: 496 files, 72,627 lines, 125 bundles；另手工检查了自动 vendor 排除规则外的桌面 vendor README。

- Review: 安全、正确性、契约、性能、架构、健壮性、测试/规格、文档八视角；所有 finding 均保留并按根因合并。

- Validation: 静态审阅；未运行 test、lint、typecheck 或 build。

- Generated: 2026-10-22T07:37:29.626702+08:00

- OUTDIR: docs/reviews/review_20261022_071448

- Bundles: 125

- Findings: Critical=0 High=11 Medium=40 Low=25 Info=0 (deduped 76)

- Verdict: **REQUEST CHANGES**

## Critical / High (必修)

- [High][99] .repo_template/scripts/md_format.py:117-L193 — Markdown 格式化器接受绝对路径和路径遍历并可改写仓外文件 — 证据：调用参数未经仓根 containment 校验；REPO_ROOT / rel 可接收绝对路径或 ../../，随后传给 md_kx。 — 依据：脚本说明要求仓内路径，但当前没有对应运行时验证（md_format.py:7-10,117-145）。 — 修复：解析 realpath 并验证仓根包含关系；拒绝逃逸软链及仓外路径。
- [High][99] .repo_template/scripts/repo_sync.py:590-L649 — 模板同步可跟随目标软链写入仓外文件 — 证据：目的地文件或目录为 symlink 时写入会跟随链接；回滚备份保留的是链接本身，无法还原被覆盖的目标文件。 — 依据：模板同步回滚需覆盖实际写入目标；代码在 repo_sync.py:124-137,590-597 未做 containment 校验。 — 修复：拒绝目标路径软链，或验证 realpath 始终在消费仓内并按目标内容备份恢复。
- [High][99] scripts/migrate_from_legacy_db.py:50-L57 — 旧密文解密失败被静默转换为空凭据并继续迁移 — 证据：enc: 字段解密任意异常后返回空字符串；调用方仍保存 credentials 并提交迁移，错误旧密钥或损坏密文会造成静默凭据丢失。 — 依据：scripts/migrate_from_legacy_db.py:158-178；src/mail_core/accounts/credentials.py:249-259 未拒绝空值。 — 修复：迁移对密文解密 fail closed；提交前验证所有加密字段成功解密并报告行号/字段名。
- [High][99] scripts/run-mail-core-tests.sh:13-L17 — 测试数据库安全门禁只检查 test 子串，attest 等生产库名也会通过 — 证据：shell 只判 DB_NAME 是否包含 test；attest 符合子串条件，后续脚本会对该数据库执行 Alembic upgrade 和 pytest。 — 依据：升级命令见同脚本第 30 行。 — 修复：要求严格数据库名模式或显式 disposable 标志，并校验数据库连接目标。
- [High][99] src/mail_core/api/accounts.py:114-L152 — AccountDTO 使用 slots 却通过 __dict__ 序列化，账户 API 返回 500/400 — 证据：AccountDTO 声明 @dataclass(frozen=True, slots=True)，没有 __dict__；list 账户访问时异常成为 500，create/update 的宽泛 catch 会转成 400。 — 依据：src/mail_core/mail/application/accounts.py:25-38。 — 修复：显式构造 AccountOut 字段，或使用 dataclasses.asdict/dataclasses.fields 兼容 slots。
- [High][99] src/mail_core/security/auth.py:255-L361 — 改密后会话 epoch 更新失败仍返回成功，跨进程旧会话继续有效 — 证据：密码先提交，随后写 sidecar/清初始密码，再调用失效逻辑；该逻辑吞掉数据库更新异常并只写 warning，路由仍返回成功。 — 依据：docs/specs/auth_and_session.md:26-27 要求改密与立即撤销一致。 — 修复：密码 hash 与 epoch 在同一 DB transaction 提交；epoch 失败则改密失败，避免夹在提交后的 sidecar 副作用。
- [High][98] .repo_template/scripts/repo_task/integration.py:218-L240 — 并发 task start 补偿可能删除另一会话创建的 worktree 和分支 — 证据：失败会话只按同一 branch 与 base SHA 判断资源归属；并发会话先成功创建 worktree 后，失败会话可将其强制清理。 — 依据：多会话并发约定见 .repo_template/docs/usage.md:75。 — 修复：用仓库级锁覆盖检查、创建、初始化及补偿；只删除本调用可证明创建的资源。
- [High][96] .repo_template/scripts/repo_cleanup.py:124-L213 — 清理目标根目录为软链时会扫描并删除仓外数据 — 证据：点名 .scratch、artifacts 或 data 后，扫描其后代并对匹配项执行 unlink/rmtree；若根本身指向仓外目录，apply 会作用于仓外路径。 — 依据：cleanup 目录边界与 repo-cleanup/SKILL.md:15-16 的确认约定。 — 修复：扫描和 apply 均拒绝根软链，并在删除前解析确认目标仍位于仓根内。
- [High][96] scripts/mail-core-backup-restore-drill.sh:32-L42 — 备份演练输出目录的逻辑路径校验可被父目录软链绕过 — 证据：pwd 保留逻辑 symlink 路径并通过仓内或 /tmp 字符串检查，随后 rm -rf OUT；父目录链接到仓外时可删除仓外同名目录。 — 依据：脚本第 21-42 行按字符串界定删除边界。 — 修复：用物理 realpath 校验；拒绝路径祖先软链，删除前再次确认目标 containment。
- [High][96] src/mail_core/api/app.py:68-L74 — 默认信任任意代理头，可伪造来源 IP 绕过登录限流 — 证据：代理头中间件默认启用，未配置可信 IP 时 trusted_hosts='\*'；登录失败计数用 request.client.host，直连客户端可轮换 X-Forwarded-For。 — 依据：src/mail_core/api/auth_routes.py:63-68；docs/guides/security.md:71 要求显式配置可信代理。 — 修复：默认不信任转发头；只有明确配置可信代理 IP/CIDR 才启用，并从已验证的 ASGI scheme 判断 Secure cookie。
- [High][96] src/mail_core/blobs/gc.py:149-L181 — GC 的二次引用查询与 unlink 之间存在竞态，会删除刚重新引用的 blob — 证据：GC 查询 digest 的 live_refs 为 0 后直接 unlink；归档可在查询后提交同 digest 的 MessageBlob/link，unlink 后 DB 留下指向缺失文件的行。 — 依据：src/mail_core/blobs/archive.py:464-466,507-527；docs/specs/mail_sync_and_storage.md:28 要求 race-safe 二次校验。 — 修复：按 digest 串行化引用创建与 unlink，或采用 tombstone/引用核验协议。

## Medium / Low / Info (建议)

- [Medium][100] .repo_template/skills/repo-template-sync-core/SKILL.md:34-L34 — 同步 skill、实现和测试对测试失败后的文件状态契约相反 — 证据：skill 声称测试失败后保留已写文件；repo_sync.py:1550-1558 与 tests/test_repo_sync.py:592-614 却执行并验证完整回滚。 — 依据：单一权威流程要求 skill、实现和测试一致。 — 修复：统一测试失败恢复契约，并同步更新 skill、实现与测试。
- [Medium][100] src/frontend/src/api/client.ts:251-L251 — SPA 没有用户可见的登出入口 — 证据：API 已实现 logout，但生产代码没有调用点，设置页面也没有登出操作，用户无法主动吊销当前会话。 — 依据：docs/specs/auth_and_session.md AC-004 包含登出及其测试策略。 — 修复：增加可见登出操作，并覆盖调用与会话失效行为。
- [Medium][100] src/frontend/src/lib/mailBody.ts:47-L48 — 邮件 iframe 允许弹窗逃离 sandbox，与安全契约冲突 — 证据：sandbox flags 含 allow-popups-to-escape-sandbox，新窗口不再继承 iframe sandbox 限制；测试也固化了该标记。 — 依据：docs/specs/inbox_ui_and_search.md:42 与 docs/guides/security.md:42 明确要求只保留 allow-popups；上一轮采用记录 A17 又要求保留，权威状态冲突。 — 修复：按决策治理确定契约，并同步实现、spec、安全指南及测试。
- [Medium][100] src/mail_core/backup/crypto.py:80-L105 — 密封备份加解密一次性读入整个文件并占用 O(n) 内存 — 证据：加密与解密分别调用 read_bytes()/f.read() 后一次性 AESGCM；数据库与 blob 打包 tar 可很大，处理峰值内存接近整个备份大小。 — 依据：src/mail_core/backup/package.py:295-303 先生成完整 tar；流式备份契约与 blobs/crypto.py 的分块实现不一致。 — 修复：改用带认证的分块 frame，并检测截断与重排。
- [Medium][100] src/mail_core/blobs/archive.py:556-L567 — 同名且无 Content-ID 的不同附件被当成重复项静默丢弃 — 证据：附件去重键为 (filename, content_id)；同一邮件含两个 filename 相同、CID 为空的 MIME part 时，第二个被跳过。 — 依据：docs/specs/mail_sync_and_storage.md:27 要求解析生成全部 Attachment。 — 修复：按 MIME part 身份或序号区分附件；重放保护不得合并不同 part。
- [Medium][100] src/mail_core/security/auth.py:217-L300 — 5 秒 epoch 缓存与立即撤销契约冲突 — 证据：多 API 进程分别缓存 session_epoch，logout/change-password 后其他进程在缓存期内仍接受旧 cookie。 — 依据：docs/specs/auth_and_session.md:27 规定跨进程即时吊销。 — 修复：认证时读取权威 epoch，或使用可靠的跨进程失效通知。
- [Medium][100] src/mail_core/sync/engine.py:79-L101 — 限流时既排 Retry-After 任务又让当前 job 按短退避重试 — 证据：限流分支已 enqueue 延后任务并返回 rate_limited；worker handler 随后把当前 job 当普通失败再次短退避重排，导致 Retry-After 前重复请求并多出队列任务。 — 依据：src/mail_core/sync/delta.py:302-315；src/mail_core/worker/handlers.py:19-28,67-92,138-153。 — 修复：原 job 完成并只保留带 Retry-After 的重试，或直接更新原 job 的 run_after。
- [Medium][99] docker-compose.mail-core.yml:68-L97 — distributed profile 同时启动内嵌与独立 worker 且共用 worker ID — 证据：API 默认启动 embedded worker，worker 容器又启动 worker；两者 MAIL_CORE_WORKER_ID 均为 compose-worker-1，互增 fencing token 会令另一进程提交失败并产生重试。 — 依据：src/mail_core/__main__.py:44,69-74；src/mail_core/sync/leases.py:80-90。 — 修复：distributed API 禁用 embedded worker，独立 worker 使用唯一实例 ID。
- [Medium][99] src/desktop/postgresManager.js:310-L326 — PostgreSQL 停止失败仍返回 stopped=true 且阻止重试 — 证据：停止前设置 \_stopped；即使 pg_ctl 失败也回报 stopped，main 忽略结果，可能让服务继续运行且后续 stop 无法重试。 — 依据：src/desktop/main.js:227 忽略返回值；测试断言 ok || stopped（postgresManager.test.js:157-160）会掩盖失败。 — 修复：仅成功确认停止后设置 \_stopped；返回失败时保留重试并由主进程报告。
- [Medium][99] src/desktop/scripts/pack-linux.js:25-L59 — Linux 打包脚本可能删除既有 frontend/dist 内容 — 证据：只要 dist 缺 index.html 就创建临时 stub，结束时递归删除整个 dist；已有部分构建资产会一并被删。 — 依据：pack-linux.js:25,56-59。 — 修复：只删除本次创建的 stub，或在临时目录构建并原子替换。
- [Medium][99] src/mail_core/blobs/archive.py:260-L327 — 额度暂停归档没有生产恢复调用，释放空间后任务永久停住 — 证据：resume_quota_paused_archives() 只有测试调用；运行时超限会把剩余邮件设为 ARCHIVE_PAUSED_QUOTA，claim batch 不再领取该状态。 — 依据：ARCHIVE_PAUSED_QUOTA 状态机允许恢复，但生产路径不存在。 — 修复：容量恢复后由受控周期任务重置并重新排队暂停归档。
- [Medium][99] src/mail_core/sync/engine.py:62-L76 — provider 构造失败发生在 lease/claim 清理保护区之外 — 证据：获取并提交 lease 后才 build_provider()，但 try 从后续网络路径开始；坏凭据/构造异常会留下 lease，重试需等过期。archive 也先 claim 再构造 provider。 — 依据：相关路径见 sync/delta.py:227-255、sync/remote_push.py:89-133、blobs/archive.py:394-446。 — 修复：在 claim 前构造 provider，或在 claim 后立即进入覆盖构造的 try/finally 并释放 lease/reset claim。
- [Medium][98] .repo_template/scripts/repo_task/view_server.py:51-L55 — 任务看板 JSON 转义可被大小写混合的 script 闭合绕过 — 证据：序列化后只替换小写 \</；HTML script 标签大小写不敏感，标题含 </ScRiPt> 可提前闭合数据块并注入脚本。 — 依据：看板在 view_static/board.html:8 将该值放入 script 数据上下文。 — 修复：将所有 < 编码成 \\u003c，并覆盖大小写混合闭合 payload。
- [Medium][98] src/mail_core/blobs/archive.py:529-L548 — 正文归档入库后未刷新全文搜索索引 — 证据：metadata 阶段先调用 upsert_message_search，此时 body 尚未归档；本处写入 MessageBody 后没有再次更新索引，全文搜索长期只有 snippet。 — 依据：src/mail_core/search/index.py:23-35；docs/specs/inbox_ui_and_search.md:14 与 AC-005。 — 修复：归档事务写 body 后同事务 upsert search row，并增加归档到搜索的行为覆盖。
- [Medium][97] src/desktop/startup.js:62-L62 — Electron 子进程会继承父 shell 中全部 MAIL_CORE\_/KKMAIL\_ 密钥 — 证据：环境白名单按整个前缀放行；main 与 PostgreSQL 子进程因此收到父 shell 的 login password、API key 或 blob key，initdb/二进制探测部分路径还继承完整环境。 — 依据：src/desktop/README.md:22,53 明确说这些值由启动器设置，不继承父 shell。 — 修复：仅向每个子进程传入必要的显式变量，并为 PostgreSQL 子进程使用最小环境。
- [Medium][96] docker-compose.mail-core.yml:33-L83 — distributed profile 的 API 与 migrate 容器会并发执行 Alembic — 证据：两者都只依赖 Postgres healthy；API 命令默认执行 alembic upgrade head，未依赖 migrate 完成。首次部署或待升级时可能并发 DDL/API 先于 schema 完成启动。 — 依据：src/mail_core/__main__.py:69-70；worker 已依赖 migrate 完成（compose:103-104）。 — 修复：distributed 拓扑只保留一个 migration runner；API 禁止自迁移并等待 migrate 成功，同时保留单进程默认启动路径。
- [Medium][96] .repo_template/scripts/repo_task/documents.py:11-L72 — task title/note 含换行可破坏权威 front matter — 证据：输入仅转义引号与反斜线，多行值被写入按行解析的 front matter，后续 task parser 可能无法读取。 — 依据：task.md 是 task 状态权威文件。 — 修复：拒绝换行和控制字符，或正确编码并验证 YAML 往返解析。
- [Medium][96] src/desktop/logRotation.js:112-L112 — 日志轮换或退出时可能丢失尚未完成的异步写入 — 证据：队列数据先出队再 fs.write，回调不检查 error/bytesWritten；轮换与 end 可在写入回调前关闭 fd，main 在 exit 或 close 任一事件到达时结束流。 — 依据：src/desktop/main.js:247；exit 可早于 stdout/stderr 完全排空。 — 修复：串行化写、轮换和关闭，处理部分写入/错误；等 close 后结束流。
- [Medium][96] src/frontend/src/components/MessageList.tsx:189-L189 — 最早优先只重排当前已加载的一页邮件 — 证据：本地 raw 列表反向排序；API 没有排序参数，后端固定按 sort_time DESC。超过 100 封时首屏仍取最新 100 封，无法展示真正最早邮件。 — 依据：src/frontend/src/api/mailCore.ts:50 无排序参数。 — 修复：提供服务端排序及匹配游标方向，或明确限制排序只作用于已加载页。
- [Medium][96] src/mail_core/backup/package.py:276-L548 — 备份明文 staging 目录权限宽且异常终止会留下明文数据 — 证据：默认 staging 位于共享临时父目录，写入明文 DB dump、blob tar 和恢复树；依赖默认 umask，SIGKILL/断电不会执行 finally 清理。 — 依据：docs/guides/security.md:74-78 要求密封备份并保护明文数据。 — 修复：在受控私有目录创建 0700 stage、文件设为 0600，清理 stale stage；尽可能流式校验以减少持久明文树。
- [Medium][95] .repo_template/scripts/repo_cleanup.py:284-L290 — 清理 apply 重扫后会删除未展示给用户的新命中项 — 证据：apply 阶段重扫目录后直接删除新出现的匹配项，没有核对与用户先前审阅的 scan 清单是否一致。 — 依据：违反 repo-cleanup/SKILL.md:15-16 的变化后重新确认约定。 — 修复：apply 比较 scan 清单摘要；期间变化时停止并重新展示清单。
- [Medium][95] docs/skills/kkmail/SKILL.md:101-L101 — 技能示例把账户密码直接放在命令行参数中 — 证据：示例使用 --password secret；真实密码通过 shell history 与进程参数暴露，且文档鼓励不安全用法。 — 依据：同文件第 15 行已有环境变量入口。 — 修复：示例改为环境变量/交互提示读取，不展示密码参数。
- [Medium][95] src/frontend/src/components/MessageList.tsx:268-L368 — 全部已读和未读数只处理已加载邮件 — 证据：按钮只把 visible 当前页传给 markReadOptimistic，禁用条件与角标也基于本地已加载项；后续页未读邮件会被当作不存在。 — 依据：全局精准统计应来自服务端计数与批量操作契约。 — 修复：增加服务端批量标记全部已读，或明确把控件限制为当前已加载邮件。
- [Medium][95] src/mail_core/sync/delta.py:316-L338 — provider 异常原文会被持久化到任务与账号状态 — 证据：str(exc) 被写入 WorkerJob payload/detail、Account.config.last_sync_error 和 remote operation；异常可能包含响应 body 或敏感文本，路径未统一使用 safe_error。 — 依据：docs/guides/security.md:63 禁止持久化 provider 响应体。 — 修复：所有持久化只保存异常类型/HTTP 状态摘要，移除原始响应文本。
- [Medium][95] src/mail_core/sync/remote_push.py:31-L42 — RateLimitedError 可能被判永久失败且忽略 Retry-After — 证据：错误分类只查看 status_code 或 response，不识别异常的 .status=429；重试延迟又不读取 .retry_after_seconds，某些 429 进入 FAILED。 — 依据：src/mail_core/providers/http.py:26-44 暴露 typed status 与 retry_after。 — 修复：按 ProviderHttpError/RateLimitedError 类型分类并遵守 Retry-After。
- [Medium][95] tests/scripts/test_fetch_pg_binaries_helpers.sh:8-L69 — 安全 helper 测试复制实现而不是调用生产脚本 — 证据：测试文件内重写 assert_tar_safe 与 url_allowed，测试通过不能证明 scripts/fetch-pg-binaries.sh 的实际函数行为未回归。 — 依据：生产实现见 scripts/fetch-pg-binaries.sh:174-200。 — 修复：抽取可 source 的 helper 或直接运行生产脚本函数进行 fixture 验证。
- [Medium][94] .repo_template/scripts/repo_sync.py:428-L496 — worktree 查询失败被当作无活动 worktree 并放行 schema 迁移 — 证据：git worktree list 失败返回空列表，后续迁移门禁据此误判没有活动 worktree。 — 依据：repo_template/docs/usage.md:100 要求存在活动 worktree 时阻断迁移。 — 修复：命令失败按未知状态处理并 fail closed，保留错误诊断。
- [Medium][93] docs/skills/kkmail/scripts/kkmail_cli.py:22-L46 — CLI 将长期有效 session cookie/CSRF token 明文写入缓存且未限制权限 — 证据：默认缓存位于 home 下 .cache；保存用 write_text，未设置 0600 文件或 0700 父目录。标准 umask 下同机可遍历该目录的用户可能读取可重放 cookie，默认有效期 30 天。 — 依据：src/mail_core/security/auth.py:76-77；跨用户读取还依赖 home 目录权限。 — 修复：私有 cache dir 与文件权限设为 0700/0600，并使用原子写；限制缓存有效期或提供禁用缓存选项。
- [Medium][93] src/mail_core/blobs/archive.py:464-L527 — 删除邮件与归档写入并发会留下不受 GC 管理的加密孤儿文件 — 证据：archive 先把 blob 写到文件系统；若此时 trash/delete 级联移除 archive state，随后代码跳过 DB MessageBlob/link 创建。GC 只枚举 DB MessageBlob，故文件不会被回收。 — 依据：src/mail_core/blobs/gc.py:52,92 仅处理有数据库记录的 blob。 — 修复：状态重查失败时按 digest 安全核验清理，或增加与 GC race-safe 的孤儿文件对账器。
- [Medium][92] .repo_template/scripts/repo_sync.py:1294-L1296 — 拼错的本地模板路径会被保存为远端 URL 并覆盖原来源 — 证据：本地路径不存在时落入 URL 分支，随后写入 state，原有 template_source 被替换。 — 依据：state 是后续同步的来源权威；不存在的本地路径不应改变它。 — 修复：区分本地路径与 URL；本地路径不存在时在写 state 前拒绝。
- [Medium][92] .repo_template/scripts/repo_sync.py:1099-L1136 — 合法 JSON 的错误 MCP 结构会触发未捕获异常且跳过回滚 — 证据：顶层数组或 mcpServers 为列表等合法 JSON 结构被按 dict 使用，可抛 AttributeError/TypeError；若此前已写文件则统一回滚逻辑不会执行。 — 依据：同步输入需结构校验且纳入统一事务处理。 — 修复：验证顶层及 mcpServers 均为对象，并将结构异常纳入回滚分支。
- [Medium][91] .repo_template/scripts/md_format.py:122-L151 — 批量格式化遇到 IO/超时异常会留下部分已格式化文件 — 证据：恢复逻辑只捕获 MdFormatError；子进程 TimeoutExpired、OSError 或读写错误可逃出，前面完成的文件不回滚。 — 依据：批量命令应保证失败后状态可解释且一致。 — 修复：捕获预期 IO/子进程异常并统一恢复，报告恢复失败路径。
- [Medium][91] .repo_template/scripts/repo_sync.py:142-L160 — 回滚恢复错误被吞掉却仍报告完整回滚 — 证据：恢复各路径时异常被忽略；测试失败路径仍输出完整恢复语义，用户无法知道哪些文件未还原。 — 依据：错误处理需准确反映回滚结果。 — 修复：收集每个恢复失败路径；仅全部成功时报告完整回滚。
- [Medium][90] .repo_template/scripts/repo_sync.py:194-L200 — 固定 state.tmp 无锁写入会让并发同步丢失保护状态 — 证据：多个会话同时读取旧 state、各写同名临时文件并 replace，后写者可覆盖先写入的 user prompt。 — 依据：state 中的保护项需跨会话保留。 — 修复：增加 state 锁，锁内重新读取合并，并使用唯一临时文件。
- [Medium][90] .repo_template/scripts/repo_task/plan.py:435-L466 — 冲突定序边可能与硬依赖成环，fallback 会输出违反依赖的计划 — 证据：冲突关系按 task ID 加排序边后可能和 depends_on 构成环；cycle fallback 再按 ID 输出，破坏依赖先后。 — 依据：task plan 必须满足登记的硬依赖。 — 修复：只为无依赖关系的冲突任务定序；真依赖环应报错或阻塞。
- [Medium][90] docs/skills/kkmail/scripts/kkmail_cli.py:19-L204 — CLI 允许把登录密码或 API key 发往任意明文 HTTP URL — 证据：--url 可覆盖默认 loopback 地址；没有限制非 loopback URL 必须 HTTPS，login body 与后续 API key 会经 urllib 明文发送。 — 依据：CLI 请求构造见 kkmail_cli.py:65-69,100-120,203-204。 — 修复：非 loopback 地址强制 HTTPS；仅允许 HTTP loopback。
- [Medium][90] src/mail_core/blobs/archive.py:362-L468 — 硬配额会被单封大邮件或并发归档超出 — 证据：容量仅在归档前检查；完整 MIME/附件写完才增加统计，无跨 worker 预留，且以明文字节计数而磁盘保存 AEAD framing ciphertext。 — 依据：MAIL_CORE_BLOB_HARD_BYTES 的名称与 hard quota 行为不符。 — 修复：基于最终 ciphertext 字节跨 worker 预留容量，并在提交前处理将超限对象。
- [Medium][90] src/mail_core/security/auth.py:118-L194 — 数据库凭据查询失败会被当成首启无记录并回退旧环境密码 — 证据：数据库异常返回 None，调用方随后使用环境变量/hash 文件 bootstrap 密码；数据库恢复后进程仍缓存旧 hash。 — 依据：docs/blueprint/decisions.md Plan A 规定初始化后数据库为权威。 — 修复：区分空记录与查询失败；配置数据库但查询失败时 fail closed，不回退 bootstrap 值。
- [Medium][88] .repo_template/scripts/repo_sync.py:1544-L1569 — state 写入失败不在内容回滚事务内 — 证据：模板文件修改与测试结束后才调用 write_state；该调用位于异常恢复区外，写 state 失败会留下新内容和旧 state。 — 依据：repo-template-sync-core/SKILL.md:33-34 规定写盘失败恢复。 — 修复：把 state 更新纳入事务，或失败时恢复模板文件并保留诊断备份。
- [Medium][84] .repo_template/scripts/pending.py:176-L224 — 批量 pending 迁移在 IO 或 Git 异常时可能半迁移 — 证据：回滚只针对 IdScanError；OSError 或 git 超时等异常可让部分文件已迁移后直接退出。 — 依据：pending 状态仅允许经脚本迁移，失败应保留一致状态。 — 修复：捕获预期文件和 Git 异常并统一回滚；列出无法恢复的路径。
- [Low][100] docs/guides/desktop.md:77-L81 — 桌面打包指南声称缺 PostgreSQL 时支持外接数据库，与实现冲突 — 证据：指南写缺少 vendor/pgsql 可生成壳层且启动需要 external DB；同文件第 48 行与主进程则说明无 PostgreSQL 会 fatal，代码不存在外部 DB 连接回退。 — 依据：src/desktop/postgresManager.js 与 src/desktop/main.js；指南另见第 48 行。 — 修复：按实际唯一 PostgreSQL 子进程行为修正文档或实现，并统一本地构建说明。
- [Low][100] src/frontend/src/components/LoginPage.tsx:74-L74 — 登录页建议检查不存在的 LOGIN_PASSWORD 环境变量 — 证据：提示列出 MAIL_CORE_LOGIN_PASSWORD / LOGIN_PASSWORD；仓库未使用后者，桌面初始密码由 main 随机生成并通过启动对话框展示。 — 依据：真实变量见 API/desktop startup 配置。 — 修复：按部署方式显示有效环境变量或桌面初始密码路径。
- [Low][100] tests/e2e/stubApi.ts:76-L94 — E2E 登录 stub 缺少 CSRF token，测试未发现后续写操作失败 — 证据：/me 与 login body 未提供 client 读取的 csrf_token；打开邮件会触发标记已读，但 E2E 只断言详情渲染。相关 spec 路径还指向不存在的 src/frontend/e2e/。 — 依据：src/frontend/src/api/client.ts:240 从登录 body 读取 token；docs/specs/auth_and_session.md:45、docs/specs/inbox_ui_and_search.md:50 的 E2E 路径过时。 — 修复：stub 补齐 token 契约，断言写请求携带 CSRF；更正 spec 路径并覆盖登出。
- [Low][99] src/frontend/src/components/MessageList.tsx:55-L55 — CJK 单字搜索仍等待 250ms 防抖 — 证据：所有输入统一走 250ms timer，CJK 单字也延后更新搜索状态。 — 依据：docs/specs/inbox_ui_and_search.md AC-004 要求 CJK 单字即时触发、纯英文防抖。 — 修复：CJK 输入即时更新，保留英文防抖及最短字符门槛。
- [Low][99] src/frontend/src/components/ErrorBoundary.tsx:30-L30 — 复制诊断日志在异步失败时仍提示成功 — 证据：未等待 Clipboard API Promise，立即设置已复制；权限拒绝会形成未处理 rejection 且错误提示不实。 — 依据：异步操作的成功状态应在 Promise resolve 后设置。 — 修复：await 写入并处理拒绝；仅成功后显示成功状态。
- [Low][99] src/frontend/src/components/SettingsModal.tsx:213-L218 — 创建分组失败会清空输入，同一 helper 会覆盖同步任务结果消息 — 证据：run() 捕获错误并正常返回，调用方 await 后无条件清空 groupName；sync-all 回调的数量消息也被通用成功文案覆盖。 — 依据：失败时应保留用户输入并准确呈现操作结果。 — 修复：让 run 返回成功状态，仅成功时清空；保留具体回调消息。
- [Low][98] .repo_template/scripts/repo_task/lifecycle.py:493-L508 — drop 归档失败恢复状态时会遗留重复 dropped note — 证据：先追加 note 再移动归档；移动失败只恢复 status，note 保留，重试可重复追加。 — 依据：操作失败需恢复写入前的 task 状态。 — 修复：归档成功后追加 note，或失败时恢复 front matter 快照。
- [Low][98] src/frontend/package.json:12-L14 — 前端 npm 脚本依赖 POSIX shell且 schema 检查失败会遗留临时文件 — 证据：脚本使用 NODE_PATH=... 与 rm -f，Windows 默认 cmd 无法执行；openapi:check 由 && 连接时校验失败会跳过清理。 — 依据：仓库声明支持 Windows 桌面构建。 — 修复：改为 Node 跨平台脚本，临时文件清理放在 finally。
- [Low][98] src/frontend/src/lib/mailBody.ts:50-L55 — 旧生产 helper 仅被单测调用且注释仍描述已取消的回复功能 — 证据：htmlToText 仅测试引用，注释描述回复/转发引用；canSendFrom 与旧 EventSource helper 也无生产调用，测试仍覆盖旧路径。 — 依据：产品范围明确不含发信；当前实时 hook 使用 subscribeMailCoreStream。 — 修复：移除确认废弃的 helper 或让测试覆盖实际生产调用路径。
- [Low][95] docs/reviews/review_20261021_040521/bundle_v8_docs.md:81-L81 — 已入库 review 产物含断链，引用了不存在的桌面 vendor README 路径 — 证据：相对链接解析到 docs/desktop/vendor/README.md；后续 review 文件也使用同一失效路径。 — 依据：docs/reviews/review_20261022_052842/bundle_v8_docs.md:14、review_intensive.md:72；真实文件在 src/desktop/vendor/README.md。 — 修复：修正相对链接并保持 review artifact 的来源引用可读。
- [Low][95] src/desktop/README.md:8-L34 — 前端与桌面文档仍引用迁移前路径和不存在的架构文档 — 证据：桌面 README 指示 cd desktop 并链接 docs/mail-core-desktop.md；前端 README 仍用 cd frontend 并链接不存在的文档；桌面指南和安全指南也指向旧 desktop/main.js、hardening.js 路径，src/mail_core/__init__.py:3 指向已不存在的架构文件。 — 依据：实际目录为 src/desktop、src/frontend；当前权威文档位于 docs/blueprint/ 与 docs/guides/。 — 修复：统一更正工作目录、文件路径和相对链接。
- [Low][94] src/frontend/src/components/Sidebar.tsx:16-L90 — 侧栏统计请求失败会显示为零未读 — 证据：单账号 folder-stats 异常被 catch 并转为 0；全局 stats 与兜底失败后仍用零显示，用户无法区分真实零值与加载失败。 — 依据：docs/specs/inbox_ui_and_search.md AC-001 要求精准计数。 — 修复：失败时显示未知或不可用状态，不伪装成零。
- [Low][93] .repo_template/scripts/repo_task/lifecycle.py:687-L700 — purge 审计失败恢复 task 目录后没有重建派生索引 — 证据：索引先重建、审计随后失败时会恢复 task 目录但不再重建 index，派生清单缺项。 — 依据：task index 为派生视图，需与权威目录一致。 — 修复：恢复目录后重建 index，并报告恢复后的实际位置。
- [Low][93] docs/archive/legacy_architecture/mail-core-architecture.md:172-L667 — 历史架构文档保留多处失效相对链接 — 证据：archive 文档指向不存在的 mail-core-desktop.md、mail-core-status.md、known-limitations.md 与 api.md。 — 依据：docs/archive/legacy_architecture/mail-core-architecture.md:172,587,667。 — 修复：若保留追溯价值，改为有效 archive 链接或明确外部归档位置。
- [Low][90] docs/blueprint/decisions.md:63-L66 — 历史凭据处置决策与后续 review adoption 记录相反 — 证据：蓝图称不执行 Git 历史重写；较新的 review adoption A53/A54 记录用户接受历史重写与个人信息脱敏。当前权威决策和执行状态不一致。 — 依据：docs/reviews/review_20261022_052842/adoption_decision.md:441-455。 — 修复：核对最终用户决定与当前 Git 状态，更新权威 decisions 记录并标明未执行项。
- [Low][88] .repo_template/scripts/repo_task/lifecycle.py:642-L653 — rewind 审计成功而 front matter 写失败会形成状态分叉 — 证据：审计先记录 rewind，随后 front matter 写入失败；task 仍处于旧状态，worktree/branch 清理可能已经完成。 — 依据：状态与审计记录需可恢复、幂等。 — 修复：让审计和状态更新可恢复、幂等，并在写失败时准确补偿。
- [Low][88] scripts/fetch-pg-binaries.sh:111-L159 — PostgreSQL 二进制下载没有连接或总时限，网络停滞可让脚本无限等待 — 证据：下载命令配置 retry 但未配置 connect-timeout/max-time；连接保持挂起时重试策略不会及时推进或失败。 — 依据：外部下载需有明确超时以保证脚本可恢复。 — 修复：设置连接与总时限，并让有限重试后明确失败。
- [Low][86] .repo_template/scripts/repo_task/documents.py:370-L380 — AC 提取器会把 fenced code 中的示例误识别为验收条件 — 证据：解析器只按 AC 标记提取，没有跳过 Markdown fenced code；示例 ID 可能进入真实 handoff 清单。 — 依据：handoff 证据应对应正文中的真实 AC。 — 修复：跳过 fenced code，并统一使用结构化 AC 解析。
- [Low][85] .repo_template/scripts/repo_task/view_server.py:35-L300 — view server 接受 IPv6 loopback 但实际 socket 使用 IPv4 — 证据：参数校验允许 ::1，端口探测和 HTTPServer 却用默认 IPv4；指定 --host ::1 --port 0 无法启动。 — 依据：CLI 应只接受实际可绑定的地址，或提供匹配的 IPv6 server。 — 修复：支持 IPv6 bind，或在参数校验时拒绝并提示。
- [Low][84] .repo_template/scripts/repo_task/worktrees.py:15-L78 — worktree env 扫描先递归依赖和缓存目录再过滤 — 证据：env 搜索与清理遍历先进入 node_modules/cache，再过滤结果，依赖树大时做无用递归。 — 依据：脚本注释声称跳过依赖与缓存目录。 — 修复：top-down walk 时剪枝跳过目录，避免进入后再过滤。
- [Low][81] .repo_template/scripts/repo_sync.py:1256-L1266 — 契约测试超时未进入正常失败与恢复处理 — 证据：subprocess.run 超时抛出 TimeoutExpired，异常没有统一捕获，会输出 traceback 并绕过可读恢复提示。 — 依据：同步失败需维持一致的诊断与恢复路径。 — 修复：捕获 TimeoutExpired 并按测试失败恢复策略处理。
- [Low][78] .repo_template/scripts/repo_hygiene.py:175-L184 — archive-review 参数未限制为 review basename — 证据：参数仅要求以 review\_ 开头，未拒绝路径分隔符或 ..，可能让归档命令尝试迁移 reviews 目录外的路径；git mv 的实际行为尚未验证。 — 依据：归档操作应限定在 docs/reviews/ 内。 — 修复：严格校验 basename 格式，并验证源与目标 realpath 的父目录边界。
- [Low][76] .repo_template/scripts/check_review_status.py:33-L35 — review status 与 task view 脚本保留未使用 imports — 证据：check_review_status.py 和 repo_task/view_server.py 中存在未使用导入，增加维护噪声。 — 依据：死代码扫描项。 — 修复：删除确认未使用的 imports。
- [Low][55] docs/reviews/review_20261021_034329/\_meta/\_meta.json:4-L5 — 公开仓历史 review 产物包含本机绝对路径和用户目录信息 — 证据：旧 review metadata 及正文在多个行记录本机 home、项目和外部工具仓路径；可关联真实个人账户与目录结构。当前新报告已使用相对路径。 — 依据：同类证据见 review_20261021_034329/\_meta/rubric.md:35、review_20261021_040521/\_meta/\_meta.json:4-5 及若干 bundle。 — 修复：清理已公开报告中的本机路径或迁移到脱敏版本；避免新报告再次写绝对路径。
- [Low][50] docs/reviews/review_20261021_034329/\_meta/rubric.md:35-L35 — 公开 Git 作者元数据含多个个人邮箱格式地址，公开意图无法核实 — 证据：历史提交作者记录中存在多个个人邮箱格式地址；邮箱是否为公开联系地址或专用 noreply 地址无法从仓库验证，因此仅列隐私核对项。 — 依据：公开仓安全审计应确认作者元数据是否经本人授权公开。 — 修复：核实公开意图；若非公开地址，按仓库治理流程更新 author metadata。

## Spec Compliance

- docs/specs/auth_and_session.md：AC-004 登出入口缺失；跨进程立即撤销被 epoch 缓存和失败吞并破坏。
- docs/specs/inbox_ui_and_search.md：精准未读统计、CJK 即时搜索、iframe sandbox 标记与实现存在差异；归档正文也未进入 FTS。
- docs/specs/mail_sync_and_storage.md：相同名称且无 Content-ID 的附件被合并；blob GC 二次检查存在并发窗口。
- docs/guides/security.md：代理头未按指南限制可信代理；备份明文 staging 权限与清理边界不足。
- docker-compose.mail-core.yml：distributed profile 未串行化迁移，且 API 与独立 worker 重复启动同 ID worker。
- .repo_template：工具、skill 与测试之间出现回滚、清理确认、路径边界等契约不一致。

## Strengths

- IMAP 删除路径避免无差别 EXPUNGE；provider 请求配置超时并默认 TLS。
- Blob 存储使用认证加密分块与 key version，附件/API 以 UUID 能力访问。
- OpenAPI、生成类型、Alembic 迁移与 Dovecot fixture 为主要接口和同步流程提供可追溯边界。

## Sources

- bundle_dir\_.\_a.md
- bundle_dir\_.\_b.md
- bundle_dir\_.claude.md
- bundle_dir\_.opencode_commands_a.md
- bundle_dir\_.opencode_commands_b.md
- bundle_dir\_.repo_template_docs.md
- bundle_dir\_.repo_template_docs_review_prompts.md
- bundle_dir\_.repo_template_docs_task_template.md
- bundle_dir\_.repo_template_hooks.md
- bundle_dir\_.repo_template_scripts_a.md
- bundle_dir\_.repo_template_scripts_b.md
- bundle_dir\_.repo_template_scripts_repo_task_a.md
- bundle_dir\_.repo_template_scripts_repo_task_b.md
- bundle_dir\_.repo_template_scripts_repo_task_c.md
- bundle_dir\_.repo_template_scripts_repo_task_view_static.md
- bundle_dir\_.repo_template_skills_bug-to-pending.md
- bundle_dir\_.repo_template_skills_pending-record.md
- bundle_dir\_.repo_template_skills_repo-cleanup.md
- bundle_dir\_.repo_template_skills_repo-hygiene.md
- bundle_dir\_.repo_template_skills_repo-template-sync-core.md
- bundle_dir\_.repo_template_skills_repo-template-sync.md
- bundle_dir\_.repo_template_skills_task-create.md
- bundle_dir\_.repo_template_skills_task-from-pending.md
- bundle_dir\_.repo_template_skills_task-integrate.md
- bundle_dir\_.repo_template_skills_task-merge.md
- bundle_dir\_.repo_template_skills_task-preflight.md
- bundle_dir\_.repo_template_skills_task-run.md
- bundle_dir\_.repo_template_skills_task-schedule.md
- bundle_dir\_.repo_template_skills_task-work.md
- bundle_dir\_.repo_template_skills_template-issue-report.md
- bundle_dir\_.repo_template_tests_a.md
- bundle_dir\_.repo_template_tests_b.md
- bundle_dir\_.repo_template_tests_c.md
- bundle_dir\_.repo_template_tests_d.md
- bundle_dir\_.repo_template_tests_fixtures.md
- bundle_dir_assets.md
- bundle_dir_config.md
- bundle_dir_docs.md
- bundle_dir_docs_archive.md
- bundle_dir_docs_archive_legacy_architecture.md
- bundle_dir_docs_archive_pending.md
- bundle_dir_docs_archive_tasks_t001_mail_core_sent_query.md
- bundle_dir_docs_archive_tasks_t002_frontend_favorites_views.md
- bundle_dir_docs_archive_tasks_t003_reader_toolbar_and_context_menu.md
- bundle_dir_docs_blueprint.md
- bundle_dir_docs_guides.md
- bundle_dir_docs_pending_todo.md
- bundle_dir_docs_reviews_review_20261021_011116_a.md
- bundle_dir_docs_reviews_review_20261021_011116_b.md
- bundle_dir_docs_reviews_review_20261021_034329.md
- bundle_dir_docs_reviews_review_20261021_034329\_\_meta.md
- bundle_dir_docs_reviews_review_20261021_040521\_\_meta.md
- bundle_dir_docs_reviews_review_20261021_040521_a.md
- bundle_dir_docs_reviews_review_20261021_040521_b.md
- bundle_dir_docs_reviews_review_20261021_064335.md
- bundle_dir_docs_reviews_review_20261022_052842_a.md
- bundle_dir_docs_reviews_review_20261022_052842_b.md
- bundle_dir_docs_skills_kkmail.md
- bundle_dir_docs_skills_kkmail_scripts.md
- bundle_dir_docs_specs.md
- bundle_dir_docs_tasks_t004_fix_accounts_dto_and_sidebar_error.md
- bundle_dir_schemas.md
- bundle_dir_scripts_a.md
- bundle_dir_scripts_b.md
- bundle_dir_src_desktop_a.md
- bundle_dir_src_desktop_b.md
- bundle_dir_src_desktop_scripts.md
- bundle_dir_src_frontend_a.md
- bundle_dir_src_frontend_b.md
- bundle_dir_src_frontend_public.md
- bundle_dir_src_frontend_scripts.md
- bundle_dir_src_frontend_src.md
- bundle_dir_src_frontend_src_api_a.md
- bundle_dir_src_frontend_src_api_b.md
- bundle_dir_src_frontend_src_api_generated.md
- bundle_dir_src_frontend_src_components_a.md
- bundle_dir_src_frontend_src_components_b.md
- bundle_dir_src_frontend_src_design-system.md
- bundle_dir_src_frontend_src_hooks.md
- bundle_dir_src_frontend_src_lib_a.md
- bundle_dir_src_frontend_src_lib_b.md
- bundle_dir_src_frontend_src_lib_c.md
- bundle_dir_src_frontend_src_lib_d.md
- bundle_dir_src_frontend_src_store.md
- bundle_dir_src_frontend_src_test.md
- bundle_dir_src_frontend_src_types.md
- bundle_dir_src_mail_core.md
- bundle_dir_src_mail_core_accounts.md
- bundle_dir_src_mail_core_api.md
- bundle_dir_src_mail_core_backup.md
- bundle_dir_src_mail_core_blobs.md
- bundle_dir_src_mail_core_db.md
- bundle_dir_src_mail_core_db_alembic.md
- bundle_dir_src_mail_core_db_alembic_versions_a.md
- bundle_dir_src_mail_core_db_alembic_versions_b.md
- bundle_dir_src_mail_core_mail.md
- bundle_dir_src_mail_core_mail_application.md
- bundle_dir_src_mail_core_mail_domain.md
- bundle_dir_src_mail_core_mail_storage.md
- bundle_dir_src_mail_core_providers_a.md
- bundle_dir_src_mail_core_providers_b.md
- bundle_dir_src_mail_core_providers_parsing.md
- bundle_dir_src_mail_core_realtime.md
- bundle_dir_src_mail_core_runtime.md
- bundle_dir_src_mail_core_search.md
- bundle_dir_src_mail_core_security.md
- bundle_dir_src_mail_core_sync_a.md
- bundle_dir_src_mail_core_sync_b.md
- bundle_dir_src_mail_core_threading.md
- bundle_dir_src_mail_core_worker.md
- bundle_dir_tests.md
- bundle_dir_tests_e2e.md
- bundle_dir_tests_mail_core_a.md
- bundle_dir_tests_mail_core_b.md
- bundle_dir_tests_mail_core_c.md
- bundle_dir_tests_mail_core_d.md
- bundle_dir_tests_mail_core_e.md
- bundle_dir_tests_mail_core_f.md
- bundle_dir_tests_mail_core_fixtures.md
- bundle_dir_tests_mail_core_fixtures_dovecot.md
- bundle_dir_tests_mail_core_fixtures_maildir_alice_Maildir_new.md
- bundle_dir_tests_mail_core_g.md
- bundle_dir_tests_mail_core_h.md
- bundle_dir_tests_mail_core_i.md
- bundle_dir_tests_scripts.md

## Appendix — Traceability

- Aggregate generated by `intensive-review/scripts/aggregate.py` from 125 bundle reports.

- Dedup key: `file:line | title[0:120]` normalized.

- Cross-validation: 12 项候选均未发现直接反证（原 11 项候选加账户 DTO）；11 项为 High，cookie cache 风险因依赖 home 可遍历权限归为 Medium。

- Snapshot: bundle 清单根据当前 HEAD 生成；检查中发生的 task commit 已纳入目标快照。

- Privacy: 本报告不复制历史报告中的绝对本机路径、原始邮箱或凭据。
