# 审阅结果决策

## 目录

docs/reviews/review_20261027_021416

## 报告来源

- 已读：bundle_cross_validation.md, bundle_cross_validation_regression.md, bundle_unit01.md, bundle_unit02.md, bundle_unit03.md, bundle_unit04.md, bundle_unit05.md, bundle_unit06.md, bundle_unit07.md, bundle_unit08.md, bundle_unit09.md, bundle_unit10.md, bundle_unit11.md, bundle_unit12.md, bundle_unit13.md, review_intensive.md
- 缺失：无
- 合并说明：review_intensive.md 原始去重后条目 441 项，覆盖全部 13 个 unit bundle 共 444 处原始 finding；其中 3 处位置在同一 bundle 内包含独立子项或疑点排除已分别处置并映射；bundle_cross_validation 与 bundle_cross_validation_regression 的全部 62 条交叉复核与回归结果均已完整溯源映射并纳入决策。CV-A04 经核验削弱前提后降为 Medium 采纳；CV-A24 经核验实测证伪后归为不采纳（R）。

## 统计

- 采纳：387 项
- 不采纳：54 项
- 待决定：0 项

## 待决定项（请先决策）

无（全部 5 项已完成决策并转入采纳项 A383–A387）。

## 采纳项

### A1. 忘记密码恢复命令不可执行：bcrypt 示例把中文占位符写进 bytes 字面量必然 SyntaxError

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/guides/troubleshooting.md:38-46
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改为先以普通字符串变量读入再 `.encode()`，例如 `python3 -c "import bcrypt,getpass;print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"`，并注明在仓库根/PYTHONPATH 环境执行

### A2. 归档架构文档仍以「已定稿，供实现」身份描述已被删除的 Gmail API 架构且含多处死链，却被现行 blueprint 作为详尽规范引用

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:5-13
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在文首加过时横幅（定稿日期、已被 blueprint/architecture.md + specs 取代、Gmail 相关章节失效），或将 Gmail 章节逐节标注 Superseded

### A3. CLI 仍接受已被后端删除的 gmail provider，add-account 必然被后端 422 拒绝

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/skills/kkmail-skill/scripts/kkmail_cli.py:502
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：choices 删除 gmail（或映射为 imap+gmail 预设并在 SKILL.md 说明），与 SKILL.md 的 add-account 示例同步

### A4. 同包状态自相矛盾：三份文件仍自称未修复/未实施/未实现，与同目录已完成记录并存且无勘误

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_005019_full_repository/review_report.md:7-7
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：不改写历史正文，在三份文件头部各加一行状态变更注记（已按本包计划实施完毕、最终状态见同目录 repair_results.md、注记日期），或由 repo-hygiene 将整包迁入 docs/archive/reviews/ 并在包首加完成横幅

### A5. 以「当前」口吻发布的 R01–R09 在 HEAD 已全部修复，无过时/已修复标注

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_180800_current_repository/review_report.md:1-9
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：文件头加状态注记（基线 2e29508c 时成立；R01–R09 已于 284233a7 前全部修复，见 docs/handoff.md 对应一节），标题改「2026-10-26 当前仓库审阅（基线 2e29508c）」式历史表述

### A6. verify_restore_operation 未在锁内重读 operation log，沿用锁外 stale stage 做状态回写

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:2052-2135
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：进锁后重读 log 并重跑 `_assert_operation_log_matches` 与 stage 判定，与 resume/cleanup 同构

### A7. 登录限流器在 import 时裸解析 env 且 max_failures 可为 0/负数使 retry_after 下标越界

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/ratelimit.py:74-78
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：构造前 clamp（max_failures>=1、window 有限正数），非法 env 记 warning 用默认值，与 worker/main.py 的 \_positive_float_setting 同款处理，并补 env=0/abc/nan 的单测

### A8. decisions 仍把已删除的 GitHub Actions CI 写成现行决策，与 testing/release 的「无远程 CI」直接矛盾

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/blueprint/decisions.md:60-70
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在该 decisions 条目追加状态变更注记（已被本地门禁决策取代 + 日期），不得静默保留为现行决策

### A9. 半脱敏真实 QQ 邮箱与真实邮箱运行态统计写入公开仓归档

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t012_mark_read_convergence/spec.md:52-52
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：将账号片段完全符号化（如 `user***@example.com` 或仅写「某 QQ 邮箱账号」），运行态统计如需保留追溯价值应与账号标识解耦，或整段移入私有证据文档并在此留勘误注

### A10. 第三轮产物复写个人数据提交的定位符索引（手机号邮箱 + 个人 Gmail/Outlook + Telegram/私人邮箱）

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261025_020805/bundle_docs_reviews.md:15-17
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：与 Critical 条同一轮脱敏中删除两组 sha/路径/行号元组，仅保留脱敏摘要；并核实 7931147f 在公开远端 refs 中确实不存在

### A11. Graph 账号 trash 硬编码 trash_folder_remote_id="Trash"，远程删除必然失败且本地已先删

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/mutations.py:222-275
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：非 IMAP 不传该键（让 provider 用自身缺省），或按 provider 解析 role='trash' 文件夹的 remote_id，与 IMAP 同路

### A12. Thread.subject_norm 未截断，长主题邮件使 assign_thread 在 flush 时溢出 String(998) 列

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/threading/rules.py:82-103
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：normalize_subject 或建 Thread 处统一截断到 998（或把列改 Text），并补超长主题测试

### A13. 部署备份目录 chmod 0777 且备份包只验存在不验完整性

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/deploy_mail_core.sh:28-40
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：目录保持 0700 并让备份容器以可写 uid/gid 运行（或仅对容器用户放 ACL），写后对备份包做校验和/verify 校验再继续，trap 恢复权限只作兜底

### A14. 生效 spec 声称改密/登出后会话「立即失效」，与现行 epoch 5 秒进程内缓存决策矛盾且 spec 未标偏差

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/specs/auth_and_session.md:27
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：AC-004 修订为「本进程立即、跨进程最长 5 秒内失效」或在 spec 未知/偏差清单中显式登记与缓存决策的差异

### A15. cleanup_restore_operation 删除目标目录全部子项而非本操作的文件

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:2208-2267
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。（经 CV-A04 核验：目标目录在恢复前强制校验为空，残余风险较小，采纳为 Medium 级安全加固）
- 修复说明：只删 staging 目录、operation log 与发布清单内的文件；或删除前断言目录内文件集合 ⊆ 本操作发布集合，发现外来文件即拒绝

### A16. current_used_bytes 对去重命中的既有 blob 重复计账，配额被虚增并误触发 paused_quota

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:1042-1050
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：仅当本次 put 实际新写文件时累加（put 返回值需区分 dedup 命中），或累加量取预检的 needed/att_needed 估算值

### A17. IMAP trash 兜底解析是死代码，且修好门闩会立刻触发 CAS 死循环

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/remote_push.py:429-437
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：以 `account_snapshot.provider == "imap"`（或 isinstance(provider, ImapProvider)）判定，并补一条用真实 ImapProvider 形状（无 name 属性）的 push_remote_operations 测试

### A18. capacity 延期路径 float(retry_after) 遇非数值即抛错，把「不计尝试的延期」变成计次失败

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/worker/handlers.py:126-145
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：集中做 \_coerce_retry_after()：try float、校验 isfinite 且 >=0，否则回退 CAPACITY_RETRY_SECONDS；同样处理 L365 的 exc.retry_after_seconds

### A19. statsQuery 的 queryKey 固定而 queryFn 闭包捕获 enabledAccounts/enabledAccountIds，账户集合变化后统计仍按旧名单计算

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/Sidebar.tsx:597-647
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把 enabledAccountIds 摘要纳入 queryKey，或 queryFn 内用 queryClient.getQueryData(queryKeys.accounts) 实时取名单

### A20. OAuth 状态轮询 effect 以整个 oauthFlow 对象为依赖，每次轮询回包都重建 1s 定时器且无 in-flight 守卫

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/settings_account_form.tsx:158-194
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：依赖收窄为 oauthFlow?.flow_id/status/method，check 内加 in-flight ref 守卫，或改递归 setTimeout 串行轮询

### A21. PG 密码 override 与已持久化密码不一致时静默用错密码

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/postgresManager.js:165-195
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：文件已存在时读回持久值返回（override 仅首次落盘生效），或检测不一致时返回带明确原因的错误，禁止用未落盘的 override 拼 `databaseUrl()`/`PGPASSWORD`。

### A22. front matter 序列化不转义换行，title/note 含 `\n` 即破坏状态权威文件并可注入伪造键

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/documents.py:66-71
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`_quote` 同时转义 `\n`→`\\n`、`\r`→`\\r`（`_unquote` 对应还原），并在 `cmd_add`/`cmd_edit` 入口拒绝 title/note 中的换行。

### A23. 契约测试超时使 apply 跳过回滚并以未捕获异常崩溃

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_sync.py:1295-1307
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 `_run_tests` 内捕获 TimeoutExpired 返回 False，或在 cmd_apply 把测试调用纳入与写盘相同的回滚 try

### A24. t054 交付的 Google OAuth / Gmail API 已于 2026-10-26 整体下线，但归档内无任何 superseded 标注或替代位置链接，仍以「全部满足」的当前口吻陈述

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t054_google_oauth_callback/spec.md:5-38
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 t053 spec 与 t054 spec/task 顶部各加一条归档勘误注记（不改写历史正文）：注明 Google OAuth/Gmail API 已由 p055 于 2026-10-26 下线、当前唯一 Google 路径为 IMAP 应用专用密码、权威位置指向 `docs/specs/account_connection.md` 的 2026-10-26 节；t055 中复用 t054 的部分注明仅 Microsoft 侧仍有效

### A25. 0027 回填全表相关扫描且对 to_addresses 形态无防御，大库升级可超时/失败

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py:19-81
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回填前加形态守卫（jsonb_typeof='array'）、按 id 区间分批回填并在迁移说明中标注大表预计时长，或回填降级为可重跑的后台任务、迁移只加列

### A26. resume 在「DB 是否为空未知（None）」时 fail-open 继续重放 pg_restore

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:2014-2033
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`empty is not True` 一律升级 needs_verification 并拒绝自动重放，与 verify_restore_operation 对 None 的处理（2147）保持一致

### A27. parse_mime_content 把整封 MIME 与全部附件 payload 一次性载入内存，无任何尺寸上限

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:271-425
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：附件改流式落 blob（边解码边 hash/写盘），设单封 MIME 与单附件硬上限，超限走 parse_error 结算而非整批进程被 OOM 杀死

### A28. STATUS 取不到 UIDVALIDITY 时以 uv=0 铸造 remote_id，与 reconcile 的 B1 中止策略自相矛盾

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:647-723
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：metadata/delta 在 uidvalidity 为 None 时像 reconcile 一样中止本轮（或回退读取 SELECT 响应码中的 UIDVALIDITY），绝不用 0 命名空间落库

### A29. 看板 HTTP 服务无认证、无 Host 校验，/task-doc 可被 DNS rebinding/局域网读取全部 spec/task 正文

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_server.py:213-271
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：校验 Host ∈ {127.0.0.1, localhost, [::1]}+实际端口、拒绝带外部 Origin 的请求，并为 /task-doc 加一次性 token 查询参数（启动时生成、URL 携带）。

### A30. 容量 deferral 违反自身「不消耗 attempt」约束，op 可被纯容量等待耗尽重试额度

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/remote_push.py:411-505
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：capacity 重置时同步 attempts-1，或将 claim 的 attempts 递增推迟到真正发出 provider 调用后/结算时

### A31. IMAP SEARCH 只读 data[0]，多段响应会丢 UID 致 reconcile 误删（预存）

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:1201-1226
- 优先级：High
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：抽一个 `_search_uids(data)` 遍历全部 chunk 解析整数，reconcile/MODSEQ/flag sweep 三处统一调用

### A32. 维护者本机绝对路径（含用户名）字面写入公开仓产物，与第三轮对 archive 同类问题的定级标准不一致

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_005019_full_repository/repair_plan.md:76-103
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：批量替换为仓库相对表述或 `$REPO`/`$WORKTREES` 占位（首次出现时定义），并按第三轮自家建议加 pre-commit/CI grep 门禁拦截 `/Users/`、`/home/` 字面路径

### A33. 锁原语三处重复实现，与 locks.py 自述「消除多处重复」及单一权威相悖

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/locks.py:1-7
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：ledger/integration 改 import `locks.lock_fh/unlock_fh` 并删除本地副本；头注与实现对齐（DOCUMENTATION_STANDARD 单一权威）。

### A34. 同一泄露凭据的历史处置在三份产物中互相矛盾且无 supersede 关系，多头「唯一权威」并存

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:33-38
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在三份文件头部互加状态注记（哪份已被哪份替代、现行口径以何为准），或把最终口径收敛到 docs/blueprint/decisions.md 后在三处留一行摘要+链接

### A35. aggregate 声称已去重却保留两对同根重复 finding，总数 86 被虚增

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:18-21
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：aggregate 按 file:line+根因合并这两对（86 应为 84），并同步修正 adoption_decision.md 的统计与条目来源

### A36. `git_common_dir` 子进程未处理 TimeoutExpired/FileNotFoundError，与 git_ops 的统一包装口径不一致

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/locks.py:36-50
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改走 `git_ops._git(["rev-parse","--git-common-dir"])` 复用统一超时包装，或本地 catch 后转 OSError 并附 stderr。

### A37. chain_plan.js 仍保留与 plan.py 双份的 chainStopInfo 算法实现，与文件头「不再实现批计划算法」自相矛盾

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_static/chain_plan.js:42-102
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除 JS `chainStopInfo`，stop_reason 缺失时显示空/「后端未提供」；或把该文件降为纯常量/映射并在头注如实标注回退身份（DOCUMENTATION_STANDARD 载体与实现一致）。

### A38. 同文件 AC 编号既有缺号又有同号异义，破坏验收可追溯性

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/specs/mail_sync_and_storage.md:26-51
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：t056 节改用带前缀编号（如 AC-T56-001）并在缺号处加注「编号保留/已废弃」说明，后续新增 AC 只增不复用

### A39. 归档迁移后 4 条跨 task 相对链接失效（死链）

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t027_account_group_ordering/spec.md:85-86
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改为同级相对路径 `../t028_group_mail_scope/spec.md` 等 4 处；归档迁移流程补一步对迁入目录的相对链接全量解析检查

### A40. 三处相对链接确定性失效（死链）

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t032_sidebar_shell_controls/spec.md:48
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：分别改为 `../t027_account_group_ordering/...`、`../../pending/p024_unknown_mail_status_defaults.md`；t049 备份改为纯文本描述（去掉链接语法）并说明备份位置约定

### A41. SUPERSEDED 横幅措辞为无证据的绝对闭环断言，且被无差别贴到非报告文件上

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_011116/review_intensive.md:1-4
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：横幅改为可核验表述（基线 SHA + 处置记录链接，如「结论以 \<后续会话> 为准」），逐项闭环状态指向 adoption/summary 文件；指令类与 \_meta 类文件不贴缺陷闭环横幅，只标「历史会话产物」

### A42. 脱敏占位符 `<local-path>` 无定义、无图例，12 处散落 9 个文件使引用不可复核

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_034329/\_meta/rubric.md:35
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在各会话目录的状态说明中加一行占位符图例（`<local-path>` = 脱敏前的本机绝对路径，已不可复核），或对规范引用改用仓库相对路径/公开链接恢复可达性

### A43. 来源链接 8 条全部失效：p045–p052 已归档，链接仍指向 docs/pending/todo/

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_005019_full_repository/repair_plan.md:5-5
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：将 8 条链接改指 `../../archive/pending/<同名文件>`，或去链保留纯文本编号引用

### A44. manifest 中的 source_database_identity 从未被写入，同 cluster 防护有一半是死代码

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:1223-1290
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：建包时把源库 DatabaseIdentity 写进 manifest；或删除该读取分支并在注释中写明防护只依赖调用方传 source_database_url

### A45. SSE_CORE_CLIENT_EVENTS 漏 sync.request_updated，与前端实际订阅面漂移

- 来源：bundle_unit04
- 位置：src/mail_core/realtime/events.py:16-26
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把 SYNC_REQUEST_UPDATED 加入 CORE 列表，并加一条「CORE∪ARCHIVE == WIRE 全集」的断言测试（现有 test_sse_medium_remaining 只断言子集关系，测不出漏项）

### A46. review 指纹对每个工作区文件全量 `read_bytes` 入内存，无大文件上限

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/monitoring.py:91-122
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：流式分块喂 hashlib；超阈值文件改 (size, mtime_ns, 前缀) 降级并在指纹中标记降级位。

### A47. 有效状态发现是 O(分支×task) 级 git 子进程风暴且被多命令重复执行

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/store.py:263-356
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：单命令内缓存 discover 结果与 `worktree_paths()`；`scan_tasks_at_ref` 批量 `git cat-file --batch` 读 task.md；ps 的 verifier 结果按 (tid, attempt, execution_id, branch tip) 缓存。

### A48. finish/drop 状态迁移不写审计日志，审计账本只覆盖 rewind/purge

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/lifecycle.py:467-548
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`_close_task` 在归档成功后按 rewind 同口径 append_audit（失败按 F15 语义提示索引/审计待补），add/edit/start 至少在 ledger 或审计中留一处可 grep 记录。

### A49. 生效 spec 称列表按 100 封/页加载，实现实际默认 50 封/页

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/specs/inbox_ui_and_search.md:27
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：将 AC-002 改为 50 封/页，或注明 100 为调用方上限而非默认页长

### A50. CLI 正文读取以 snippet 回退冒充正文，违反 blueprint 明定的正文数据源契约

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/skills/kkmail-skill/scripts/kkmail_cli.py:593-604
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：CLI 只输出 body，body 为空时明确输出「正文未归档或为空」状态提示，不回退 snippet

### A51. 当前交接已过时：head_commit 停在 05d2cc84，其后 t056/p058/p059 三批已合入 HEAD 均未反映

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/handoff.md:5-9
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 AGENTS.md 约定在下一次收尾时以新一节替换（branch + head_commit 更新至当前），或在本节追加状态变更注记指向后续提交

### A52. t013–t023 front matter 陈旧：note 仍称「仅创建 backlog」且 branch/diff_anchor 全空，与 done 状态及正文实施记录矛盾

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t013_test_pg_runtime/task.md:14-14
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：以状态变更/勘误方式（不覆写历史）为 11 个 task 补记实际执行方式与对应 commit 锚点，note 改为已执行说明；tasks_index.json 重新生成

### A53. 大量审查/复现证据只存在于 gitignore 的 `.scratch/` 路径，归档后不可复核（全 unit 共 36 处 `.scratch/` 引用）

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t054_google_oauth_callback/review_test.md:76
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：将关键日志/复现脚本随归档迁入对应 task 目录或 `docs/archive/` 证据区并改写引用；无法迁移的在原文旁注记「证据未入库、已随会话销毁」，不得以仓库外路径作为唯一证据

### A54. t041–t043 正文与 front matter 状态自相矛盾且无补记收口

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t041_unknown_mail_status/task.md:29
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：为 t041–t043 各补一节与 t053 同格式的归档补记（状态修正时间、执行 commit、依据），或直接修订正文该句为已修正表述并注明原记录语境

### A55. 第三轮产物转述时保留部分脱敏的真实个人标识残片（邮箱前缀/QQ 号前缀/手机号头尾/账号 UUID 头尾/密码长度）

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261025_020805/bundle_docs_archive.md:6-7
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：转述层统一改为完全符号化（`[REDACTED_EMAIL]`、`account A/B/C`、UUID 只记「内部账号 UUID」），密码长度事实删除；已印残片随 Critical 条的脱敏轮一并处理

### A56. verify_restore_operation 对 stage=complete 直接返回 ok=True，完全不校验 package

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:2097-2107
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：complete 分支也应校验 package digest 与已发布文件集合/校验和，或在返回契约中明确标注「未校验 package」

### A57. \_subs 以 account_id 为键只增不删，任意 UUID 订阅可使分发表无界增长

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/dispatcher.py:47-70
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：unsubscribe/close 后删除空键，或给 \_subs 加键数上界与空键清理

### A58. 搜索不索引 cc_addresses，抄送收件人/别名不可搜

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/search/index.py:105-114
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：to_text 并入 cc（或新增 cc_text 列+trigram 索引+document 重建迁移），补 cc 命中测试

### A59. errorFromBody 丢弃后端结构化 error code，且 Retry-After 仅接受纯秒数

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/client.ts:146-161
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：detail.code/error_code 透传到 ApiError.code；Retry-After 用 Date.parse 兜底解析 date 形式

### A60. 桌面 README 的安全语义与实现漂移（权限与外链两处）

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/README.md:34-40
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按实现改写两句（权限改为「默认全拒、仅本源主框架剪贴板净化写例外」，外链改为「https/mailto/http-loopback」），安全文档与实现不一致按 DOCUMENTATION_STANDARD 属必须修正项。

### A61. 错误响应回显异常原文与绝对路径且无任何安全响应头

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_server.py:200-235
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对外错误改固定文案 + 内部 stderr 记详情；全响应加 `X-Content-Type-Options: nosniff` 与 `Content-Security-Policy: default-src 'self'`。

### A62. 「当前验证基线」停留在 2026-10-24/25 的 569 passed，已被更新的实测结果取代

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/blueprint/testing.md:311-325
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：更新基线表至最近一轮完整门禁证据，或删除计数仅保留指向各 task archive 与 handoff 的链接，避免双处维护漂移

### A63. 已 done 归档的 16 份 spec 共 118 条 AC 仍全为未勾选，与同目录 PASS 结论矛盾

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t001_mail_core_sent_query/spec.md:29-31
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：归档收尾统一处理（二选一并全仓一致）：将已验证 AC 勾为 `[x]`，或在 spec 首部加一行「验收状态见同目录 task.md 收尾报告与 handoff.json」；后续 finish 脚本固化其一

### A64. t013「Review 处置」残留创建期文本「尚未开始 review」，与已存在的 review 及收尾报告直接矛盾

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t013_test_pg_runtime/task.md:46-46
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在该节以勘误行追加指向 review_code.md 的处置结论（保留原文不覆写，符合 archive 只准新增），并在 finish 检查清单中加入「Review 处置节与 review 文件一致性」一项

### A65. 已 done 并归档的 spec 中 AC 复选框全部保持未勾选，与 task.md「全部满足」结论矛盾（全 unit 统计：`- [ ]` 154 条 vs `- [x]` 仅 26 条）

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t053_provider_account_forms/spec.md:31-63
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：归档收尾时统一将已满足 AC 勾为 `[x]`（t049 已有此做法可作范例），或在 spec 顶部加一行状态注记指明「验收结论以 task.md 收尾报告为准，本 spec 复选框未回填」

### A66. 同一文件头内状态互相打架：「已实施」与「不代表修复已经完成」并存

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_commits/repair_design.md:3-5
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除或改写 :5 的状态句（保留「不直接创建 backlog task、执行迁移或部署」的边界句），使文件头只有一套状态语义

### A67. \_verify_restored_state 用 DB 内的 storage_path 直接拼路径，未做规范化校验

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:1502-1607
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用 blobs/access.py 的规范路径校验（resolve 后断言在 root 内），非法 storage_path 直接判验证失败

### A68. \_reclaim_once 把 7 类清扫塞进单一事务，任一失败每 60s 整体回滚

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/worker/main.py:70-106
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：每类清扫独立 session/事务并分别记日志与计数，单项失败不连累其他项

### A69. 全量视图 folder-stats 对每个启用账户并发一个请求，无并发上限（N+1 扇出）

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageList.tsx:213-220
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：优先用全局 stats 端点聚合，逐户路径加并发池（如 8）或后端提供批量 folder-stats

### A70. 名为 design tokens 的文件实为 2,018 行全局样式单体，令牌、基础、全部组件样式（.settings-*/.message-*/.tree-\* 等）与响应式混杂

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/design-system/tokens.css:1-2018
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 tokens/base/components 拆分并以 @import 或构建层级固定层叠顺序，z-index 收敛为 --z-\* 令牌

### A71. 原子写缺目录 fsync，「防掉电」承诺过强；且用进程级 `os.umask` 推导默认权限

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/documents.py:74-113
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：replace 后对父目录 fd 做 fsync（POSIX）；默认 mode 改用固定 0o666&~umask 的一次性子进程/启动期缓存值，docstring 改为「防半写」而非「防掉电」。

### A72. POSTGRES_PASSWORD 未转义直接拼进 DATABASE_URL（四处）

- 来源：bundle_unit08, bundle_cross_validation
- 位置：docker-compose.mail-core.yml:48-151
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：文档与 deploy 脚本强制校验密码字符集（如 `^[A-Za-z0-9_-]+$` 不符即拒绝），或改用分字段环境变量由应用拼 URL

### A73. 基准脚本对目标库无任何防误伤护栏，指向生产库即写入污染数据

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/benchmark_mailbox.py:342-360
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用 owned 校验思路：拒绝非 loopback 主机或库名不含 test/bench 标记的目标，除非显式 `--allow-non-test-db` 确认

### A74. skill 对测试失败后果的描述与 repo_sync.py 实现相反

- 来源：bundle_unit08
- 位置：.repo_template/skills/repo-template-sync-core/SKILL.md:34-34
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：以实现为准改写 skill 第 6 步（一行位置以 repo_sync.py 当前行为核对），或改实现与 skill 对齐，二者取一后在 usage.md 同步

### A75. 密码重置属高风险直改数据库操作，方法一缺停服/备份/验证等前置与恢复条件

- 来源：bundle_unit09
- 位置：docs/guides/troubleshooting.md:38-66
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：两法统一补前置（停服、确认 DATABASE_URL 指向目标实例、备份原 hash）、执行后验证（用新密码登录 + 旧会话失效）与失败恢复（还原备份 hash）

### A76. 第三轮包在 HEAD 的「门面」仍是未加后续状态的 BLOCK 结论，重蹈本包自己对旧包的定级

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261025_020805/review_summary.md:1-7
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：给 review_summary.md 与 review_intensive.md 头部加关闭横幅（结论时点、采纳处置见同目录 adoption_decision.md、后续状态见 docs/reviews/review_20261026\_\* 与 docs/handoff.md），或按 kkmail AGENTS.md 的 repo-hygiene 规则将整包迁 docs/archive/reviews/

### A77. create_account 不校验 group_id 存在性，坏分组以 500 暴露

- 来源：bundle_unit01
- 位置：src/mail_core/accounts/service.py:27-66
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：create_account 在 flush 前查 group 并 raise LookupError("group not found")，与 update 路径一致

### A78. \_read_target_identity 吞掉一切异常返回 None，恢复的多道安全门随之 fail-open

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:1706-1711
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：区分「离线 drill 明确允许」与「生产恢复」：target 不可达时默认中止，仅显式 offline 标志才降级；system_identifier 取不到应视为未知而非「不同 cluster」

### A79. 建包 tar.add 整个 blob root 无排除清单，快照可混入恢复工件与在途临时文件

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:521-550
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用 filter 只收 `*.blob` 规范布局文件并排除点文件/暂存区；建包前要求 blob root 静默或做一致性快照

### A80. 加密建包直接在目标目录内原地组装，非原子发布

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:627-690
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：与平文路径同构，先在同卷 staging 目录完成整包并 verify，再 rename 交换

### A81. iter_plaintext 在摘要校验完成前就逐块产出明文，附件下载据此流式外送未验证内容

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/store.py:120-137
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：下载路径改用先全量校验再发送（get() 或临时文件校验后流式），或在访问层明确拒绝流式未验证输出

### A82. rewrap_all_blobs 传外部 session 时 safe_to_retire_old_keys 恒为 False，scanned 口径在 limit 下亦失真

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/rotate.py:171-294
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：结果中区分「已 rewrap 待调用方 commit」状态供调用方提交后自行判定退休安全性；scanned 报真实扫描总数，limit 另设 truncated 计数

### A83. load_backup_keyring 对 MAIL_CORE_BACKUP_KEY 用 setdefault 静默让位给 KEYS JSON，与 blob 侧冲突即报错的行为相反

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/crypto.py:50-70
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：冲突时报错，或至少 log.warning 明示单键被忽略，避免运维以为已轮换 backup 密钥而实际未生效

### A84. \_inflight_full_root_generation 在根 job 是 delta 时提前 return None，漏查 metadata 阶段的全量扫描

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/sync_requests.py:49-80
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：根 job payload 非 full 时继续查 metadata jobs，任一命中 full generation 即返回它

### A85. apply 阶段的 ScanGenerationMismatch/未捕获异常出口不释放租约

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/engine.py:540-555
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：为这两处补统一的 finally 式 quiet release（仅在 fencing 仍属本 worker 时），或返回前显式 \_release_lease_quiet

### A86. dispatch_once 单次只发布+扇出 100 条且无续跑，突发积压要等下一次 NOTIFY 或 listener 30s idle 才继续

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/dispatcher.py:216-256
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：dispatch_once 内 while batch.count==100 继续下一批（或返回后由 listener 以 0 延迟再调度一轮），并删除或接线 poll_interval_s

### A87. verify_password 吞掉 AuthConfigError，DB 故障被伪装成密码错误并计入登录限流

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:299-309
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：verify_password 只对「无凭据配置」返 False，DB 查询类 AuthConfigError 上抛，由路由回 500（与 logout 的处理一致）

### A88. session_max_age 不校验取值域，0/负数/超大值静默生效

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:120-132
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：限定 (0, 上限如 365 天\]，越界抛 AuthConfigError

### A89. 容量淘汰每次新键触发全表扫描，键喷洒下限流锁内 O(n) 放大

- 来源：bundle_unit04
- 位置：src/mail_core/security/ratelimit.py:38-46
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：淘汰改为近似策略（如随机采样少量键淘汰、或按插入序 OrderedDict 淘汰队首），避免全表扫描

### A90. logout 直接使用 window 而 handleUnauthorized 有 typeof 守卫，非 DOM 环境下登出尾段抛错

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/client.ts:290-305
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：与 handleUnauthorized 一致加 window 守卫，或明确该函数仅 DOM 调用并在签名注释标注

### A91. fetchAccounts 分页上限 10,000 页 ×200 串行请求，后端 has_more 异常时前端放大为万次请求风暴

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/queries.ts:155-181
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：上限降到与产品规模匹配（如 50 页/1 万账户）并在超限时带已拉数据降级返回 + logDiagnostic 记录

### A92. memberships/masterIds/layoutReady 每渲染全量重算且 orderedMembers 内含排序，大账户量下侧栏任意状态变更都付 O(组×账户) 成本

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/Sidebar.tsx:666-681
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：memberships 与 layoutReady 用 useMemo 按 [accounts, groups, layoutSnapshot] 缓存

### A93. 安全敏感的 OAuth URL 构造与厂商推断零单测

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/account_providers.ts:1-44
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补 `account_providers.test.ts` 覆盖 `inferVendor` 域名表、`buildMicrosoftAuthorizeUrl` 的参数编码/login_hint/state，并加一条与后端常量对齐的契约断言。

### A94. 首屏主题引导默认 system 与 store 默认 dark 不一致造成闪变

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/public/theme_bootstrap.js:1-15
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：两处共用同一默认值（store 默认改 `'system'`，或 bootstrap 无存储时默认 dark），并在注释中标明对方位置防再次漂移。

### A95. smoke 失败路径不清理：PG 进程与临时目录双泄漏

- 来源：bundle_unit06
- 位置：src/desktop/scripts/packaged-smoke.js:92-167
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用 try/finally 包住生命周期段，finally 中 best-effort stop 两任 manager 并删除 testDataRoot。

### A96. 厂商域名表与品牌域名表双份维护且覆盖已漂移

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/account_providers.ts:19
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：抽单一域名表供 vendor 推断与品牌识别共用，或加一条交叉一致性测试列出两表差集并逐项裁决。

### A97. 依赖环检测用递归 DFS，超深依赖链触发 RecursionError 裸崩溃

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/scheduling.py:8-30
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改显式栈迭代 DFS，或 catch RecursionError 转 TaskDataError 并提示链深。

### A98. 会话 Cookie Secure 默认关闭

- 来源：bundle_unit08
- 位置：docker-compose.mail-core.yml:111-111
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：默认改 1 并在注释中说明本机 HTTP 调试时显式置 0，或按 HOST_BIND 非 loopback 时在部署文档中强制要求置 1

### A99. 未钉死版本回退到「同源 checksum」校验，供应链校验自证

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/fetch-pg-binaries.sh:39-70
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：无 pin 时默认拒绝，要求显式 `PG_VENDOR_SHA256` 或增加 `--allow-unpinned` 显式开关才允许同源回退

### A100. 迁移回滚吞掉自身错误且无条件宣称「已回滚 N 条」

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/pending.py:169-226
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：记录每条回滚结果，失败时逐条列出未恢复路径与手工恢复方法，并改文案为实际恢复数

### A101. --scale 无下限校验，小规模必然在断言处崩溃且结果不可比

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/benchmark_mailbox.py:326-360
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：main 校验 scale>=250、runs>=1（或断言按 min(count, …) 计算），p95 用最近秩并在 samples\<20 时在报告中标注 p95=max

### A102. 已归档 CHANGELOG 顶部仍保留 [Unreleased] 现行时态段落，与归档属性及 release 流程矛盾

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/archive/CHANGELOG.md:7
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：将 [Unreleased] 内容归入对应版本节或加归档注记（封存于何时、后续变更记录位置），避免被误读为待发布清单

### A103. 生产 API 允许创建 memory/stub 测试 provider 账户

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/accounts.py:89-101
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：API 层 AllowedProvider 只留 imap/graph，memory/stub 仅测试夹具经环境开关启用

### A104. DB 池参数环境变量无解析容错与范围校验

- 来源：bundle_unit01
- 位置：src/mail_core/db/session.py:28-36
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：逐项解析并抛 DatabaseConfigError（含变量名与期望范围），pool_size>=1、timeout>0、recycle>=0

### A105. 改密成功后当前会话即刻失效但接口不处理

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/auth_routes.py:102-110
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：响应中清 session cookie 并明示需重新登录，或为当前会话重签 cookie+csrf

### A106. \_redact_url 只脱敏 userinfo 段，query 串中的凭据原样进 MANIFEST 与 stub 文件

- 来源：bundle_unit02
- 位置：src/mail_core/backup/package.py:74-83
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用 make_url 解析后重组，query 中 password/sslpassword 等键一律剔除或打码，并补单测覆盖带 query 凭据的 URL

### A107. verify 对畸形 manifest 的类型不设防，抛 AttributeError 而非返回 ok=False

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:690-723
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：入口处 isinstance 校验 members 与每个 meta 均为 dict，不符记 errors 并走 RestoreVerifyResult(ok=False)

### A108. reserve_quota 返回值语义含混且硬配额锁内做全盘 walk

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/quota.py:95-133
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用枚举/异常区分「无需预留/超限」，dir 大小改缓存或增量计数，锁只包住「读已预留+判定+插入」的短临界区

### A109. sweep_expired_blobs 无上限加载全部 ref_count\<=0 的 blob 行且 storage_path 未规范化

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/gc.py:86-131
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：keyset 分页分批 sweep 并逐批提交，路径统一走 BlobStore.path_for/规范校验

### A110. iter_wrap 对大块输入的缓冲策略可退化为 O(n²) 拷贝且 wrap/put 全程内存驻留

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/crypto.py:150-185
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：iter_wrap 按 CHUNK_SIZE 切分输入迭代器（memoryview 分片），put 增加流式写盘路径

### A111. run_archive_batch 的 batch_size 与配额 env 解析无校验，畸形值以 ValueError/超大 claim 形式炸掉整个 job

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:676-700
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：集中解析并 clamp（batch 1..200、字节数 >=0），非法配置记明确错误并以配置错误状态退出

### A112. mark_remote_operation 无 revision/fencing 校验，stale worker 可把已被 coalesce 更新的操作误标 DONE

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/remote_ops.py:185-210
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：mark 时要求调用方带其执行时的 revision，revision 已前进时拒绝 DONE 并保持 PENDING 待重推

### A113. reclaim_stale_in_progress 的 SELECT 无 FOR UPDATE SKIP LOCKED，多实例回收互相重复

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/remote_ops.py:212-251
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补 `.with_for_update(skip_locked=True)`，与 archive reclaim 对齐

### A114. sync_all_accounts_app 分页中途逐页 commit，失败时已入队一半且 offset 分页会漂移

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/accounts.py:333-357
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改 keyset 分页（按 account id 游标），并在返回契约中明确部分成功语义或先收集全部 id 再统一入队

### A115. search 两入口均不校验 limit/offset，search_message_ids 还绕过了 MAX_SEARCH_OFFSET

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/search.py:27-68
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：两入口统一校验 0\<=offset\<=MAX_SEARCH_OFFSET、1\<=limit\<=上限

### A116. OAuth 刷新在 credential_edit 的咨询锁+行锁内执行网络 POST，跨进程长时间持锁

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:117-160
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：锁内只做读+版本校验，网络刷新移到锁外，落盘时以 refresh_token 版本做 CAS，冲突时采用已落盘的新 token

### A117. IMAP 登录期非 IMAP4.error 异常泄漏 socket，\_close_client 也不兜底关 socket

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:510-545
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：\_connect 用 try/except BaseException 包裹登录段、失败先关 sock 再抛；\_close_client 在 logout 失败后补 `client.close()`/sock.close 兜底

### A118. p059 迁移回填与运行时 to_text 形态不一致，dict 形收件人在回填后变成 JSON 文本

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/search/index.py:15-31
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回填 SQL 改为取元素 ->>'address' 与 ->>'name' 拼接（或统一走应用层重建索引），并对已迁移库做一次 to_text/recipient_addresses 重建

### A119. 密码字节契约与 API schema 冲突：schema 放行 1024 字符、bcrypt 层 72 字节封顶

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:52-56
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：统一在一处定义密码字节上限并让 schema maxLength 按字节语义对齐（或改用 pre-hash 后 bcrypt），verify 前显式超限返 False 并写明所依赖的 bcrypt 版本行为

### A120. 脱敏模式漏 JWT/Cookie/非 Bearer 认证头与部分 token 形态，泄漏面残留

- 来源：bundle_unit04
- 位置：src/mail_core/security/redact.py:13-34
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补 JWT 正则、Cookie 头整段脱敏、Authorization 全 scheme 兜底（scheme 后非空白串整体替换）

### A121. /api/events 未声明实际会返回的 503，生成客户端无此契约

- 来源：bundle_unit04, bundle_cross_validation
- 位置：schemas/openapi.json:3556-3640
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 sse 路由 responses 补 503 JSON 模型后跑 scripts/export_openapi.py 重新生成并同步 frontend schema.ts

### A122. get_dispatcher() 无锁懒单例，多线程首访可造出两个 dispatcher

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/dispatcher.py:341-345
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：加模块级锁双重检查，或在 app 启动时显式初始化

### A123. useSelectedMail 的 snapshot 只含 id/is_flagged/is_read/subject，其余缓存字段变化不触发阅读器更新

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageReader.tsx:37-67
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：snapshot 纳入渲染实际用到的全部字段，或直接以 mail 对象引用变化为版本信号

### A124. device_code 倒计时用每秒 setNow 重渲染整个 513 行账户对话框

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/settings_account_form.tsx:196-200
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把倒计时拆为独立小组件自带 state，或用 CSS/单节点 ref 更新文本

### A125. 全设置页共用单一 pendingRef 闸门，一个慢操作（如全量同步）期间所有分区操作被静默吞掉

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/SettingsModal.tsx:139-155
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：pending 按 scope 分片；batch 改并发池并逐项回报进度

### A126. handleLoadMore 以整个 query 对象为依赖导致回调与 IntersectionObserver 每渲染重订阅

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageList.tsx:305-333
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：依赖收窄为 fetchNextPage 稳定引用与 searching/hasMore/loadingMore 原始值

### A127. window.open 放行的同源弹窗不继承导航守卫

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/paths.js:48-55
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 `app.on('web-contents-created')` 中对所有 contents 统一挂 `setWindowOpenHandler` 与导航守卫，或对弹窗也走 `createWindow` 同款装配。

### A128. scrubEnv allowlist 放行代码执行/库注入类变量，与文件自述目标冲突

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/startup.js:37-59
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：从 allowlist 移除 `PYTHONPATH/PYTHONHOME/LD_*/DYLD_*`（需要时由 launcher 显式 extras 注入），或在注释中明确这是有意信任父环境并降级其安全声明。

### A129. online/可见性恢复绕过节流器做全量失效

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/hooks/useMailCoreRealtime.ts:58-62
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：恢复路径也走 throttler（或至少把详情失效收窄为活跃 query 的 refetch），五路恢复信号在同一 tick 内去重。

### A130. current attempt 按 (attempt, execution_id) 字典序而非账本顺序判定，同一 attempt 号双 identity 时「当前」取决于 hex 字符串大小

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/attempts.py:75-87
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：project 时记录事件序号，current 按最后 `attempt_reserved` 的账本位置判定，execution_id 仅作同号消歧校验。

### A131. 已存在二进制只查三个文件存在即跳过，无版本/完整性校验

- 来源：bundle_unit08
- 位置：scripts/fetch-pg-binaries.sh:336-347
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：跳过前核对 `pg_ctl --version` 与期望 VERSION（及目标架构），不符则报错要求刷新；版本口径与 compose 的 Tested tag 对齐或在注释中说明分发渠道差异

### A132. 目标库密码经命令行参数 --target-url 传递，进进程列表与 shell history

- 来源：bundle_unit08
- 位置：scripts/migrate_from_legacy_db.py:26-33
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：支持 `--target-url-env VAR` 或从 `MAIL_CORE_DATABASE_URL` 环境变量读取，文档示例改 env 方式，CLI 参数仅保留无密码形式

### A133. Graph 判定用 `"outlook" in email` 子串匹配，容易误判 provider

- 来源：bundle_unit08
- 位置：scripts/migrate_from_legacy_db.py:12-23
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：解析域名后与已知 Microsoft 域名/授权类型字段精确匹配，未知组合显式报错让操作者裁定

### A134. finally 中 cleanup 抛错会掩盖测试失败退出码

- 来源：bundle_unit08
- 位置：scripts/test_pg_runtime.py:293-336
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：cleanup 异常只记录日志并保留原异常/退出码（或以链式 `raise ... from` 并优先返回 TestFailure.code）

### A135. hook 每次 Bash 调用全量读 ledger 与 statusline jsonl 去重，文件无界增长后必超 2s hook 超时

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/track_worktree.py:83-103
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只读尾部若干行做去重（如 seek 尾部 4KB），或用 (size,mtime,inode) 缓存；ledger 解析同样只取该 tid 的尾部事件

### A136. 默认类别删除不区分 git tracked，测试夹具类文件会被当垃圾

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_cleanup.py:63-166
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：脚本层对 tracked 文件默认降级为「需点名确认」清单或新增 `--include-tracked` 开关，apply 默认跳过 tracked 命中

### A137. 简化兑换建号的存在性检查与建号分属不同会话/事务（TOCTOU）

- 来源：bundle_unit01
- 位置：src/mail_core/api/oauth_routes.py:127-183
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把查存+建/更收进同一 session/事务，IntegrityError 映射为冲突后重读走 update 路径

### A138. BlobStore.put 存在 check-then-write 竞态且异常分类不一致、落盘缺目录 fsync

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/store.py:74-107
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：put 内部按 digest 加进程内/建议锁，统一捕获 BlobCryptoError 后重写，replace 后 fsync 目录

### A139. mark_unreferenced_blobs 全表扫描挤在一个事务内，且 marked 计数重复

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/gc.py:37-84
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：逐页短事务提交并记录进度，marked 按 blob 去重计一次

### A140. 账号在 claim 后被删时 acc=None 的 AttributeError 被误分类为 provider_error 烧掉整账号 claim 的重试次数

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:869-930
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：acc 为 None 时按「账号已消失」单独结算（release/丢弃 claim，不计 retry），并与真 provider 故障区分

### A141. FTS 索引只喂 text_plain，HTML-only 邮件永远搜不到，且报头回填失败被静默吞掉

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:1090-1098
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：plain 为空时用 html 去标签文本建索引；回填失败至少 log.warning 带 message_id

### A142. 已有附件换绑 blob 时旧 blob 的 ref_count 不减，靠 GC 全量对账兜底

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:1149-1155
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：换绑/解绑点同步维护旧 blob 计数与 gc_eligible_at，全量对账只作审计而非唯一纠正手段

### A143. list_recent_sync_requests 固定只扫最新 200 条未完成请求且逐条 N+1 生成 report

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/sync_requests.py:470-516
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：scope 过滤尽量下推 SQL 或按 scope 分桶限额，report 批量加载 targets 后内存组装

### A144. \_assert_target_database_is_empty 只数表，放行带视图/序列/函数/数据的「空表」库

- 来源：bundle_unit02
- 位置：src/mail_core/backup/package.py:219-239
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：同时检查各用户 schema 的表行数估算、视图/函数/序列/扩展清单，或要求目标为全新空库（无用户 schema 对象）

### A145. 无 CONDSTORE 的 flag sweep 一次 FETCH 失败即毒死整个文件夹 delta

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:861-905
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：sweep 内部捕获 \_ImapFlagFetchError 并按其 docstring 的 SEARCH 失败语义处理（跳过本轮 sweep、保留 flag_scan_after 进度），或把 sweep 移到新邮件拉取之后

### A146. 同页重复 remote_id 会生成两条 MessageLocation，撞唯一约束毒死整页

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/metadata.py:60-120
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：新建定位后同步写入 locs 字典，并在 apply_metadata_page 入口对 page.items 按 remote_id 去重

### A147. sync_folder_delta 的 fencing_mismatch 出口不重排 followup，周期轮询链会静默断裂

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/delta.py:508-560
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：fencing_mismatch 出口也按 dedupe_key 重排一次延迟 delta（或在 delta_changes 调用之间补 heartbeat），保证 poll chain 不依赖单次调用时长

### A148. reclaim_stale_claims 不计失败次数，崩溃循环的作业会被无限回收永不终态

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/jobs.py:464-505
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回收时递增 failure_attempts（或独立 reclaim 计数），达到上限后按 fail_job 终态路径结算绑定

### A149. markAll 失败回滚无条件把缓存已读态写回 false，与并发的单封已读操作无 revision 协调

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageList.tsx:457-482
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回滚前逐 key 比对当前缓存值仍为乐观值才回退，或走 setReadOptimistic 同款 revision 机制

### A150. 生成说明并列三条再生路径未指明唯一权威，执行者可能用错源产生漂移（视角8）

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/generated/README.md:1-21
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：标注唯一权威链路（后端导出 openapi.json → openapi:gen），其余写为等价快捷方式或删除

### A151. desktop.log 落盘无脱敏，主进程全部 console 输出原样入档

- 来源：bundle_unit06
- 位置：src/desktop/desktopLog.js:31-49
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`DesktopLogger.write` 前复用 `startup.redactSecrets` 的 URL/userinfo 规则与一组已知 secret（至少 DB URL 形态），并补一条含假 URL 密码的落盘脱敏测试。

### A152. OAuth state 在非安全上下文回退到可预测的 Math.random

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/account_providers.ts:30-31
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回退改用 `crypto.getRandomValues` 拼 UUID/hex（非安全上下文亦可用），彻底去掉 `Math.random` 分支。

### A153. macOS 关窗后后端崩溃无人处理，应用变成僵尸

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/main.js:144-150
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：无窗口时后端退出也应 `app.quit()`（或在 activate 重开前先探活/重启后端），不要把崩溃处理绑定在窗口存在上。

### A154. 无 profile 的默认 `up` 会拉起 api 但永不跑迁移

- 来源：bundle_unit08, bundle_cross_validation
- 位置：docker-compose.mail-core.yml:39-145
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：给 api 也加 profile，或头注释显式警告默认 up 不是受支持路径并给出失败判据

### A155. archive-review 目录名无路径校验，可拼 `../` 穿越

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_hygiene.py:175-184
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对 name 做 `re.fullmatch(r"review_[A-Za-z0-9_-]+")` 或 resolve 后断言父目录恒为 REVIEWS_DIR

### A156. handoff 切分不识别 fenced code block，`## ` 代码行会被当章节

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_hygiene.py:59-70
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用 fence 跟踪逻辑（与 repo_task.review 的 visible_markdown_lines 同口径）后再切分

### A157. AGENTS.md 章节定位同样 fence 盲，强制替换可能切错边界

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_sync.py:1182-1197
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：章节扫描跳过 fenced code block 内的行

### A158. retained messages 单事务 + 逐条 flush + identity map 全量驻留，大库内存与锁风险

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/migrate_from_legacy_db.py:542-567
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按批（如 1000 条）分段 commit 并 `session.expunge_all()`，报告计数改为跨批累计

### A159. bulk 类别 rglob 命中经符号链接目录指向仓库外的文件时按仓库内路径删除

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_cleanup.py:118-136
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除前对每个命中做 resolve 后 containment 断言（须在 repo 内），符号链接本身只删链接不跟随

### A160. rm -rf 允许根包含整个仓库，basename 匹配即可删仓库内任意层级目录

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/mail-core-backup-restore-drill.sh:41-90
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：允许根收紧为 `repo_root/.scratch` 与系统 temp，仓库内其它位置拒绝

### A161. 镜像名硬编码 kkmail-\* 前缀，克隆目录改名即部署中途失败

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/deploy_mail_core.sh:50-57
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：从 `docker compose config --images` 或 `docker inspect` 现查实际镜像名，禁止拼前缀假设

### A162. 发起新 OAuth 流程不作废同会话旧 pending 流程

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/accounts/oauth_flow.py:312-320
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：写新指针前先按旧指针 cancel 旧 flow（清 flow/state 记录），或在 complete/consume 时校验 flow_id 仍为 active 指针

### A163. 同步类端点在 report 为 None 时触发响应模型校验 500

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/accounts.py:303-345
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：report 为 None 时 raise HTTPException(404)，去掉 type: ignore

### A164. configure_logging 摘除全部 root handler 且不 close

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/logging_config.py:124-144
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只摘除自己安装的 handler（打标记），摘除时调用 handler.close()

### A165. validate_connection 对未知 provider 与 imap 的 token_uri 不设防

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/accounts/connection.py:104-118
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：provider 先做白名单（imap/graph，内部测试 provider 显式放行），并按 provider 拒绝其字段集之外的凭据键

### A166. unlink_gc_paths 允许带外部 session 时在调用方提交前就 unlink，且 symlink blob 永远清不掉

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/gc.py:132-227
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：API 上拆分「已提交」断言（如要求传入已 commit 的 digest 集合），symlink 孤儿单独计数上报而非静默跳过

### A167. recompute_folder_stats 对不存在行的竞态处理不闭合

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/storage/folder_stats.py:15-42
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改 INSERT ... ON CONFLICT DO NOTHING 后再 FOR UPDATE 读取，或对重取为 None 做有限重试

### A168. 状态/计数字段普遍缺 CHECK 约束，非法值入库后在应用层以 ValueError 形式爆出

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/storage/models.py:298-533
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：为状态列与计数列补 CHECK（迁移随附），至少覆盖 archive state 与 ref_count>=0、reserved_bytes>0

### A169. expires_in 类型异常会回滚整次刷新，已轮换的 refresh_token 随之丢失

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:165-175
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：expires_in 解析失败时按缺失处理（不设过期或默认 3600s），先保证 token 对落盘，再校验可选字段

### A170. \_metadata_uid_scan 缓存不记录扫描下界，start 回退时静默截断

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:647-700
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：缓存键加入起始 start 并要求复用时 cached_start \<= start，或每次 fetch_metadata_page 都以 start=1 的全量 SEARCH 建缓存

### A171. is_restricted_ip 漏掉 CGNAT/组播/site-local 段，SSRF 黑名单不完整

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/host_security.py:17-19
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 `not ip.is_global` 作为受限判据（或显式补 100.64/10、224/4、fec0::/10），并加参数化测试覆盖各特殊段

### A172. delta 合并声称「未知值不抹除已知事实」，但只保护 4 个字段

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/delta.py:140-170
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：保护集改为「凡 newer 值为 None 即不覆盖」，或把上述字段全部纳入现有保护集

### A173. 跨 loop 扇出以 call_soon_threadsafe 成功即记已投递并推进 cursor，目标 loop 停转时事件静默丢失

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/dispatcher.py:135-160
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回调执行时向 dispatcher 回执，未回执的 queue 在 loop 关闭时触发一次 resync hint 或至少记 warning 计数

### A174. 既有 thread 后补 provider_thread_key 时无 savepoint 保护，唯一约束冲突在末尾 flush 裸抛

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/threading/rules.py:204-226
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：该赋值+flush 也包 begin_nested，冲突后回滚 savepoint 并重查已有 thread 复用

### A175. 诊断脱敏词表漏 session 与 OAuth code，导出物仍可含敏感值

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/diagnostics.ts:24-28
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：词表补 `session|code|state` 类键名与 URL 查询参数脱敏（至少 `code=`/`state=`），导出文本对邮箱做掩码，或明确该全局对象仅供本机排障并在文档标注风险。

### A176. 增量同步去重依赖可能过期的 query 缓存，手动同步可被静默吞掉

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/hooks/use_scope_sync.ts:181-196
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：手动触发时先对该 request 做一次权威 refetch 再判活，或缓存缺失/过期时放行 POST（后端已有 `client_request_id` 幂等可兜底）。

### A177. 写队列满时清空全部待写日志而非丢弃溢出部分

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/logRotation.js:100-107
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：队列满时只拒新 chunk（或丢最旧并计 dropped 数），不要连坐清空已排队内容；错误聚合后再经 onError 上报。

### A178. is_read/has_attachments 用裸 bool() 与 is_flagged 的字符串解析口径不一致

- 来源：bundle_unit08
- 位置：scripts/migrate_from_legacy_db.py:249-262
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：三处统一走 `_legacy_flag_value(...) or False` 并对 None 单独计数

### A179. 无 DATABASE_URL 时 OAuth 流程（含 client_secret/暂存 token）落进程级内存明文字典

- 来源：bundle_unit01
- 位置：src/mail_core/accounts/oauth_flow.py:39-68
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回退时至少 log.warning 明示非 durable/明文，或在非测试运行模式直接拒绝启动 OAuth 流程

### A180. mark-all-read 无迭代上限且分批独立提交，异常时部分生效无提示

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/mail.py:527-590
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：加最大批次数/总时长上限并在游标不前进时报错退出；文档或响应中明示该接口非原子、失败可重试（幂等）

### A181. 无效 Bearer 自动回退到 Cookie 会话认证

- 来源：bundle_unit01
- 位置：src/mail_core/api/deps.py:29-44
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：请求带 Authorization 头但 key 不匹配时直接 401，不回退 cookie

### A182. \_backup_destination_lock 为无限阻塞等待，无超时/无可观测

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:85-126
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改 LOCK_NB 轮询 + 总超时（如 300s）并在等待时周期性 log，超时抛明确错误

### A183. setReadOptimistic 的 finally 先 await finishReadMutation 再 releaseSingleReadMutation，全局读变更状态机存在刷新被自身计数挡住的脆弱耦合

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/queries.ts:580-672
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：release 与计数自减合并为单一出口并加不变量断言/专测覆盖 begin/setRead/flag 三路交错序列

### A184. URL 模板源缓存不校验 origin，换源后静默 pull 旧仓

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_sync.py:221-242
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：pull 前比对 `git remote get-url origin` 与 state 值，不符则报错重 clone；对 URL 做协议 allowlist（https/ssh/file 本地路径）

### A185. fetch_mime/apply_remote_operation 接受与 remote_id 内嵌文件夹矛盾的显式 folder，UID 被投到错误邮箱执行（预存）

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:753-790
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：两者不一致时直接拒绝（或忽略外部 folder 只信 id 内嵌值），并对 apply 路径补同类校验

### A186. token 响应缺 expires_in 时过期时间永不更新，每个 API 调用都强制刷新（预存）

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:169-172
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：expires_in 缺失时按 IdP 惯例默认 3600s 计算 expires_at 后再落盘

### A187. provider 响应与 MIME 全量读入内存无大小上限（预存）

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:326-410
- 优先级：Medium
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对 $value/JSON 响应做流式读取并设显式上限（如 MIME 64MiB、JSON 16MiB），超限抛 ProviderHttpError

### A188. \_session_epoch 全局变量重复声明（预存）

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:84-85
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删 L84 重复声明

### A189. `ledger tail -n 0` 输出全量、负数输出错位切片

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/control.py:174-195
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：n\<=0 时明确报错或输出空；argparse 加 `type` 校验/在 cmd 内 clamp 并提示。

### A190. 六个会话的元数据布局与命名互不一致，无统一约定

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_034329/\_meta/\_meta.json:1-6
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：为 docs/reviews/review\_\* 定一份最小布局约定（\_meta 位置、必备文件、bundles 指输入单元数），在 docs/reviews 索引中注明各历史会话的布局差异

### A191. 时间相对词「最新」被写进标题与正文，产物一过期即自相矛盾

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_064335/review_da57df7_findings_and_decisions.md:1
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：标题与正文改用基线锚定表述（「da57df7 基线审查」），「最新」只允许出现在带日期的索引页并随新会话更新

### A192. package.py 导入 decrypt_bytes/encrypt_bytes 后从未使用，同文件 \_fsync_file 定义后零调用

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:25-33
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删未用 import 与 \_fsync_file，避免读者误以为恢复链在用整包内存加解密 API

### A193. search_messages docstring 已与实现漂移

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/search/index.py:150-154
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 \_MATCH 现状重写 docstring

### A194. Realtime 段末句被截断

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/ARCHITECTURE.md:19-19
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补全句子（如「…cannot send Authorization headers, so the stream relies on the session cookie」）并顺手核对全篇有无同类截断。

### A195. 向未声明变量赋值造隐式全局

- 来源：bundle_unit06
- 位置：src/desktop/scripts/packaged-smoke.js:93-93
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改为 `freePort(54329)` 或从 `../postgresManager` 解构 `DEFAULT_PORT` 后传变量。

### A196. `_dependency_implementations` 以裸 `pass` 吞掉全部解析异常，失败诊断信息丢失

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/integration.py:87-119
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：捕获时保留 `last_error` 并拼入最终 TaskDataError 文案（仍 fail-closed 不放行）。

### A197. 文件头 docstring 只列三个 prompt 模板，与实现要求的四个不符

- 来源：bundle_unit08
- 位置：.repo_template/scripts/render_review_prompts.py:2-17
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：docstring 补 general_prompt.txt 并注明 full/single 各用哪组

### A198. 会话/运行时残留写进长期产物：deadman 进程号、用户原话转述、UTC 时间戳与全仓 +08:00 口径混杂

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_034329/\_meta/\_meta.json:51-56
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：\_meta 只保留 target/sha/phase/计数等可复核字段，运行时字段（pid、deadman、intent 转述）在入库前剥离，时间戳统一 +08:00

### A199. 同一 finding 全文多份复制存档，脱敏与勘误被迫逐份重复、易漏改漂移

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:11
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：aggregate 改为只保留计数、标题行与指向 bundle 的相对链接，不复制证据全文；已入库产物做勘误时以脚本按 finding ID 全会话同步替换并回读验证

### A200. 死链：引用的 CI workflow 文件已在后续提交中整目录移除

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_005019_full_repository/review_report.md:151-151
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：去链改纯文本引用并注记「该文件已于 49a6d024 移除」，或指向该提交的历史 blob

### A201. 死代码：SyncJobOut/SyncAllOut 与未用导入

- 来源：bundle_unit01
- 位置：src/mail_core/api/accounts.py:186-193
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除两模型与该导入，或在 sync-body 路由真正映射该异常为 409

### A202. domain 值对象模块整体无生产/测试引用（预存）

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/domain/models.py:1-53
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该模块及 __init__ 再导出，或在 blueprint 中标注其预留性质与接线计划

### A203. 死导出 MAIL_LIST_PREFIX 与 SyncJobOut 全仓无引用（同根因合并）

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/queries.ts:70-70
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除两处导出，或若为预留公共 API 在注释中标注保留理由

### A204. 未使用的权限函数导入形成死代码

- 来源：bundle_unit06
- 位置：src/desktop/main.js:23-29
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删掉 main.js 的两个未用导入；deny 函数若无生产调用方应一并删除或在 hardening.js 注释标明仅为测试保留的基线实现。

### A205. 空壳模块：只有一行注释、无任何导出

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/accounts.ts:1-2
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该文件；若能力门控确有规划，改为在 pending/spec 中登记而非留空文件冒充实现。

### A206. 账本每次读写全量加载且无增长上限，长账本下所有命令线性变慢

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/ledger.py:43-95
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：记录文件 offset/尾部索引或按 tid 分片；至少在 `_with_lock` 内单次读取供同命令复用，并文档化归档策略。

### A207. `_is_loopback_host` 认可 `::1` 但服务器恒 AF_INET，IPv6 回环必然绑定失败

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/view_server.py:274-277
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：host 含 `:` 时切换 AF_INET6 server 类，或从白名单移除 IPv6 并在文档说明仅 IPv4/localhost。

### A208. `unlink_managed_env_links` 对 worktree 整树 os.walk 不剪枝，每次 cleanup/rollback 都全量走树

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/worktrees.py:71-79
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：walk 时原地过滤 dirs（与 link_local_env 共用 skip 集合），.git 目录直接剪枝。

### A209. cmd_start 用裸 `split(",")` 解析 depends_on/conflicts_with，与全仓 parse_tid_list 口径分裂

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/integration.py:144-145
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 `parse_tid_list(ref_fm.get("depends_on",""), field=...)`，与 compute_schedule 同源。

### A210. \_apply_shared_unit 中 AGENTS.md 二次分区处理为不可达死代码

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_sync.py:1263-1293
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除第二处重复判断，保留单一入口

### A211. API Key 说明的权威链接指错：指向 conventions.md 但该文件无 API Key 定义

- 来源：bundle_unit09
- 位置：docs/guides/deployment.md:21
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：链接改指 security.md 对应章节

### A212. 产物内相对链接在当前仓库已失效（链接腐烂）

- 来源：bundle_unit12, bundle_cross_validation
- 位置：docs/reviews/review_20261021_040521/bundle_v6_robustness.md:81
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：历史产物链接统一改注「原文链接，目标已迁至 \<现路径>」或改为 GitHub 永久链接（带 SHA），避免读者点开即 404

### A213. 「摘要」逐字复写聚合报告的 Critical/High 全文，违背单一权威且成倍扩大配方分发面

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261025_020805/review_summary.md:23-117
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：后续轮次起 summary 只保留计数、Verdict 与指向 review_intensive.md 对应节的链接；存量文件随脱敏轮把配方行替换为脱敏摘要

### A214. update_account_sync_status 中 last_synced_at 为死代码

- 来源：bundle_unit01
- 位置：src/mail_core/accounts/service.py:471-474
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删 hasattr 分支，或给模型补列+迁移后去掉守卫

### A215. __main__ 未用导入 Any

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/__main__.py:20-20
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该导入

### A216. MAIL_CORE_PORT 非法值在参数解析期裸崩

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/__main__.py:56-56
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用同一校验逻辑，非法时 argparse 报错退出

### A217. safe_blob_path 无生产调用方，仅被自己的单测引用

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/access.py:96-108
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除 safe_blob_path 及其测试，或让 BlobStore.path_for 复用它收敛为单一实现

### A218. \_query_inbox_stats 含不可达分支

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/queries.py:438-493
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删恒假条件，保留 sync_status 判定

### A219. 超大文件已越过可维护规模：package.py 2267 行、archive.py 1303 行单文件多职责

- 来源：bundle_unit02
- 位置：src/mail_core/backup/package.py:1-2267
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按职责拆分（restore 状态机、校验、建包各成模块），保持包内私有接口不变

### A220. REMOTE_IMAGES_DEFAULT_ON 是无消费者的死常量且加密卷文案指向已不存在的文档路径

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/defaults.py:8-15
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该常量或让就绪检查真正引用它，文案路径改为 blueprint/architecture.md

### A221. 前端 README 的 Layout 表已过时

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/README.md:22-27
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：更新 hooks 行职责并补 theme_bootstrap 一行，或把 Layout 表收敛为只列目录、职责链接到 ARCHITECTURE.md。

### A222. `view --port` 无范围校验，越界端口在 serve 内抛未捕获 OverflowError

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/cli.py:125-128
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：argparse 自定义 type 校验 0-65535，或 serve 入口显式校验并 sys.exit 友好文案。

### A223. `_find_free_port` 探活后释放再重绑存在 TOCTOU 窗口，且 serve 结束未 `server_close`

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_server.py:35-39
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：直接以 port=0 构造服务器并从 `httpd.server_address` 读实际端口拼 URL；退出路径补 `server_close()`。

### A224. 详情渲染直引 `CAT[n.category]` 无未知类别兜底，服务端新增 category 即前端崩溃

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/view_static/board.js:862-866
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：统一经 catStyle/安全访问器取 label，缺失类别回退 backlog 文案。

### A225. `write_front_matter_many` 的 replace 阶段中途失败仍留部分已替换文件，注释承诺与实现有差距

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/documents.py:121-165
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：replace 前备份原文件字节，失败时按备份逐个写回；或 docstring 明示 replace 阶段失败需人工核对两文件（按 DOCUMENTATION_STANDARD 降低断言强度）。

### A226. 导出脚本内置全 A blob key 与占位 SECRET_KEY 作默认环境值

- 来源：bundle_unit08
- 位置：scripts/export_openapi.py:24-29
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改为进程内随机生成一次性值（os.urandom），不保留任何可用形态的常量 key

### A227. IMAP 测试夹具默认口令硬编码 `alice-imap-pass`

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/start-mail-core-imap.sh:10-11
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：默认改为启动时随机生成并打印一次，或未设 env 时拒绝启动 pymap 回退路径

### A228. pending/handoff 的关键证据指向 gitignore 的 .scratch 本地文件，入库读者无法复核

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/archive/pending/p039_body_sync_retry_loop.md:22
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：需长期保留的复现材料移入对应 task/spike 的 code/ 目录并更新引用，其余引用降级为「本地复现（未入库）」标注

### A229. t028–t032 spec 的来源链接为已打码的 ChatGPT 会话 URL，不可达且不可复核

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t028_group_mail_scope/spec.md:48
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除打码链接，来源改为仅引同仓 `source_notes.md`（评估记录），或注记「原始设计聊天未入库归档」

### A230. 决策文件无基线/日期头，「目录」节是空壳（仅一行目录路径）

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261025_020805/adoption_decision.md:1-5
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补头部元信息（来源报告、基线 29dcd3a、决策日期、A/R 编号区间与计数），「目录」节或删除或改为真实条目索引

### A231. 证据链依赖未入库的 .scratch 本机产物，克隆读者无法复核

- 来源：bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261026_180800_current_repository/review_report.md:148-154
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把 48 项失败清单与关键探针结论以脱敏摘要内嵌进报告附录（005019 包 review_evidence.md 已内嵌关键结果，可作范式），.scratch 路径只作本机附加注记

### A232. list_accounts 分组查询时重复执行一次全表 count

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/accounts/service.py:87-95
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 group_id 分支只算一次

### A233. README Layout 与实现漂移（视角8）

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/README.md:58-58
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：该行补 oauth_routes 并注明 app.py 为组装入口

### A234. AccountDTO.status 被硬编码为 "active"，与账号真实状态脱钩

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/accounts.py:105-154
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：由 sync_enabled/sync_status 派生 status，或删该字段只保留后两者

### A235. 生产注释大量引用未定义的内部编号（R12/V2-21/A35/B4/R18/DEFECT 等），读者无从溯源

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/archive.py:151-1303
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把编号替换为自含的一句理由，编号如需保留放进 commit message 或 docs/findings 条目并在注释中给相对链接

### A236. extract_message_ids 文档与行为不符且混合形态 References 会漏 bare id

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/threading/rules.py:53-72
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改正 docstring 为首见优先；bare 提取改为「逐 token 判断是否已被 angle 形式覆盖」而非整段开关

### A237. 桌面 README 环境变量表与测试表均不完整

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/README.md:15-23
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补齐三行变量与测试表，或把测试表改为指向 `package.json` scripts 避免双份维护。

### A238. playwright.config.ts 不在任何 tsconfig 的 include 内

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/tsconfig.node.json:23-23
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：node 工程 include 补 `playwright.config.ts`（其 types 需 `@playwright/test`，已是 devDependency）。

### A239. 手写 front matter 解析偏离 YAML：单引号 `''` 转义不还原、重复键静默覆盖、未引号值含 ` #` 被截断

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/documents.py:16-61
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：单引号分支做 `''`→`'` 还原；重复键报错；注释剥离仅当 `#` 前为空格且值不以引号/方括号开头时执行并在文档标注此子集语义。

### A240. 点名黑名单路径被静默丢弃，与 format_paths 的拒绝语义矛盾

- 来源：bundle_unit08
- 位置：.repo_template/scripts/md_format.py:174-194
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：点名模式下黑名单命中应显式报错列出被拒路径，与库函数语义统一

### A241. 桌面 PG 版本口径（16.6.0）与服务端钉死版本（16.15）长期漂移且无说明

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/fetch-pg-binaries.sh:109-136
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在脚本头注释说明桌面分发版本独立于服务端的原因与升级节奏，或随服务端 Tested tag 同步 bump 并更新 pin

### A242. 领域术语表自称命名权威但漏列多张现行表且 provider 枚举不全

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/blueprint/domain.md:9-22
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补齐现行实体行（或注明本表仅核心实体、完整清单见 db 模型），provider 枚举与 AllowedProvider 对齐

### A243. t013 缺 review_test.md、t013–t023 全批缺 handoff.json，归档完整性口径与前后批次不一致

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t013_test_pg_runtime/task.md:57-57
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 t014–t023 各 task.md 收尾或 archive 统一说明中补一句与 t013 相同的授权省略声明；t013 缺 test review 一事在 review_code 或收尾中明示由 t014 复审覆盖的事实（正文已有此意，提至收尾显处）

### A244. SSE 连接上限缓存进程生命周期内永不失效

- 来源：bundle_unit01
- 位置：src/mail_core/api/sse.py:43-61
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：缓存时记录原始 env 值、变化时重解析，或在启动日志打印生效值并注明需重启

### A245. ExchangeRedirectUrlRequest.email 为死字段

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/oauth_routes.py:115-121
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该字段，或保留时在响应/日志中明示已被 verified email 覆盖

### A246. run_backup 成功后写 backup:last_success 的异常被整体静默吞掉

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:960-981
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：至少 log.warning 记录失败原因，或把该键更新纳入 verify 后的必达步骤

### A247. 每个 \*\_app 函数重复 try/commit/except rollback 样板十余次

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/accounts.py:176-466
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：抽一个 `_run_in_session` 上下文管理器统一事务边界，各函数只写业务体

### A248. IMAP 凭据 dict 形状缺 password 时静默用空密码，JSON 字符串形状却报错，两种形状校验不一致

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/factory.py:158-180
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：dict 分支同样在 password/secret 均缺失时 raise ValueError("credential JSON missing password")

### A249. default_urllib_token_post 不映射 429/503，token 端点限流被当普通失败

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:192-215
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：status==429 时抛 RateLimitedError 并解析 Retry-After，503 同 urllib_json_request 的 GET 重试策略对齐（token POST 为幂等刷新授权，可有限重试）

### A250. auth 层把原始异常文本写进日志并拼进 AuthConfigError，与 listener 的「只记类型」纪律不一致

- 来源：bundle_unit04
- 位置：src/mail_core/security/auth.py:176-199
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：这两处改记 type(exc).__name__ + 固定消息，细节仅在 debug 级经 safe_error 输出

### A251. load_api_keys 把非字符串 JSON 元素 str() 强转成密钥且 JSON 语法错误抛裸 JSONDecodeError

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:158-173
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：元素必须为非空 str 否则 AuthConfigError，json 解析异常 from exc 包装

### A252. \_wait_for_bcrypt_hash 要求 hash 文件恰好 60 字节，带换行/空格的合法 hash 文件使每次启动 5 秒后硬失败

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/runtime/bootstrap.py:61-70
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改为读取内容 strip 后校验长度与 $2 前缀，不再比裸文件大小

### A253. GC/备份 job 的 payload 未纳入 \_validate_job_payload，数值与路径裸转换

- 来源：bundle_unit04
- 位置：src/mail_core/worker/handlers.py:327-346
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：\_validate_job_payload 补 GC（cool_off_hours 有限且 >=0）与 BACKUP（output_dir 为 str 或 None）分支

### A254. isApiError 仅凭 status:number+message:string 判定，任意业务对象可被误判为 ApiError 透传

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/client.ts:163-167
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：给本地合成错误加品牌字段（如 `__apiError: true`）或 Symbol 标记后判定

### A255. 纯文本正文也走 prepareMailHtml 全量 DOMPurify 净化与颜色分类，浪费且语义多余

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageReader.tsx:211-223
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：仅 `html` 为真时计算 preparedMailHtml，其余返回 null

### A256. BRAND_ICON_COMPONENTS 以 Record\<string, …> 定义，品牌枚举新增时漏配图标无类型报错

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/brand-icons/brandIconMap.ts:25-47
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：键类型改为 Record\<AccountBrand, …> 穷尽映射，漏配即编译失败

### A257. settings 查询绕过 queryKeys 中央注册表，手写 ['settings'] 字面量

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/SettingsModal.tsx:54-54
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 queryKeys 增加 settings 条目并全量替换字面量

### A258. hasBinaries 对 PATH 二进制重复探活

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/postgresManager.js:255-261
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`fromHint===name` 时跳过第一次 check 直接走 PATH 分支。

### A259. ThreadingHTTPServer 无请求超时与连接上限，慢连接可长期占线程

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_server.py:280-308
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：handler 设 `timeout = 30` 并在 serve 文档中标注非 loopback 风险，或改用带超时的 server 配置。

### A260. `link_local_env` 全仓 rglob 遍历找 .env 且跟随符号链接，边界与成本未收敛

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/worktrees.py:14-48
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：遍历期剪枝 skip_dirs（os.walk + dirs 过滤）；对 `src.is_symlink()` 的源跳过或显式校验其 resolve 仍在 REPO_ROOT 内。

### A261. goal 快照解析不校验 version 与队列重复 tid

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/goal.py:211-232
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：version != 1 时报错提示 --reset；queue 去重校验 `len(set)==len` 不符即判损坏。

### A262. `_missing_testing_sections` 的 fence 闭合判定与 documents 的权威实现不一致

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/lifecycle.py:268-330
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用 documents 的 fence 状态机（存 (char, len) 并同等判定），消除第二份实现。

### A263. added-lines 漏报内容以 `++` 开头的真实新增行

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_state.py:133-169
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：仅在 hunk 上下文内、且 `+++ ` 后是路径形态时才当文件头，或改用 `git diff --unified=0` + 行号解析

### A264. find_free_port 释放后被 uvicorn 重绑，经典 TOCTOU 端口竞态

- 来源：bundle_unit08
- 位置：scripts/run_full_stack_e2e.py:29-32
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把端口分配推迟到启动前，或启动失败时换端口重试一次

### A265. unit 模式运行目录从不清理，.scratch/test_runs 持续膨胀

- 来源：bundle_unit08
- 位置：scripts/test_pg_runtime.py:371-382
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：unit 结束时删除本次目录（保留 coverage 汇总到固定位置），或复用并轮转单一 unit 目录

### A266. 部署脚本硬编码 OrbStack context 且把 git push 作为隐含副作用

- 来源：bundle_unit08
- 位置：scripts/deploy_mail_core.sh:16-24
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：context 改为可 env 覆盖的期望值并在脚本头注释声明前提；push 前移为显式步骤输出，或加 `--no-push` 开关

### A267. archive/pending 普遍缺时间/版本元数据，59 条中仅 8 条正文含日期

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/archive/pending/p001_trash_action_ux_mismatch.md:1
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：后续归档条目模板强制含提出/闭环日期；存量可在索引层（archive/tasks_index 或目录 README）补一张 pNNN→闭环日期对照表，不逐个改写历史正文

### A268. CLI 旧会话缓存迁移在 base_url 不匹配时仍删除旧缓存文件

- 来源：bundle_unit09
- 位置：docs/skills/kkmail-skill/scripts/kkmail_cli.py:168-178
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：unlink 移入 base_url 匹配分支内，或不匹配时保留文件并打印提示

### A269. 27 份 spec.md 文件内无归档状态标识，被取代契约单看文件会被误读为现行

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t002_frontend_favorites_views/spec.md:1-1
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：归档时由 finish 流程给每份 spec 首部追加一行状态注（归档日期 + 当前权威 `docs/specs/<slug>.md`），或在 docs/archive/tasks/ 根加统一 README 声明本目录 spec 均为历史快照、现行契约以 docs/specs/ 为准（二选一，全目录一致）

### A270. 归档 spec 普遍保留模板作者指令 HTML 注释（「规范（门禁必留，不得删除）」等），属模板/会话残留进入归档正文

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t053_provider_account_forms/spec.md:25
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：归档迁移时统一剥离门禁注释块（规则本身由 `.repo_template` 模板承载），或批量替换为一行「本节格式遵循 task 模板」

### A271. SSE 会话 epoch 已变的流以 200 空流结束

- 来源：bundle_unit01
- 位置：src/mail_core/api/sse.py:262-267
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：订阅前（返回 StreamingResponse 前）先做一次 epoch 校验，不匹配 raise HTTPException(401)

### A272. MANIFEST 明文携带 blob_root 绝对路径与库连接的用户名/主机，包外发即泄漏部署拓扑

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:40-58
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：manifest 只记逻辑名（如 "blobs"）与脱敏后的库标识（db 名+指纹），绝对路径仅写本地 operation log

### A273. IMAP host/port 来自 DB JSON 配置却无类型与范围校验

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/factory.py:182-195
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：统一校验 host 为非空 str、port 为 1-65535 整数，失败抛带字段名的 ValueError

### A274. build_provider 无 session 时每次调用都新开 DB 会话只为读一个超时设置，且 GraphProvider.timeout 存而不用

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/factory.py:126-155
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：超时设置做进程级短 TTL 缓存；GraphProvider.\_call 把 self.timeout 透传给 transport 或删除该字段

### A275. 主循环 time.sleep 不可中断，SIGTERM 后最长要等满 max_idle 才退出

- 来源：bundle_unit04
- 位置：src/mail_core/worker/main.py:321-331
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 threading.Event.wait(sleep_s) 替代 sleep，信号处理 set 事件

### A276. 外部 signal 的 abort 监听从不移除，订阅销毁后监听仍挂在长寿命 signal 上

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/sseStream.ts:285-293
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：保存具名 handler 并在 unsubscribe 中移除

### A277. 远程图片拦截横幅的显隐正则作用于原始 body 而非净化后 HTML，且只识别带引号的 https? src

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageReader.tsx:440-462
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对 preparedMailHtml.sanitizedHtml 做同一判定，并覆盖无引号 src

### A278. 未移除 Electron 默认应用菜单，打包版保留 DevTools 入口

- 来源：bundle_unit06
- 位置：src/desktop/windowOptions.js:7-32
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：生产构建显式设置精简菜单或 `Menu.setApplicationMenu(null)`，DevTools 仅 dev 模式保留。

### A279. displayEmail 对「Name addr@x」格式返回整串而非邮箱

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/displayName.ts:20-28
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：无尖括号时用空白切分取含 `@` 的 token，全无则返回空串。

### A280. API 就绪失败时不回显 api/worker 日志尾，排障需手工找文件

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/run_full_stack_e2e.py:178-195
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：失败路径打印两个日志的最后 N 行或至少输出日志文件路径

### A281. sync_state.json 读写无结构校验，坏 state 以裸异常崩溃

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_sync.py:187-201
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：read_state 捕获解析错误转 SyncError 并校验必需字段，status/plan 对缺键给降级输出

### A282. SKILL 只讲密码注入与清理，未披露 CLI 会把会话 Cookie/CSRF 落盘缓存

- 来源：bundle_unit09
- 位置：docs/skills/kkmail-skill/SKILL.md:11-22
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在认证配置节补一行说明缓存路径、权限与清除方法（删除该文件即注销本机缓存会话）

### A283. 多处归档证据指向已不存在的 .scratch 路径，证据不可复核

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t014_backend_test_isolation/review_test.md:24-28
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对承担验收/缺陷成立作用的运行证据，将摘要（关键数值、命令、commit、时间）或哈希固化进归档文件本身；仅留 .scratch 路径者加注「原始产物已销毁、以下数值以本文记录为准」

### A284. HSTS 无条件全量下发且主应用无 CSP

- 来源：bundle_unit01
- 位置：src/mail_core/api/app.py:121-128
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：HSTS 仅在请求确为 HTTPS（或可信代理头确认）时下发；SPA 响应补 default-src 'self' 型 CSP

### A285. \_may_accept_keyword 注释与行为矛盾

- 来源：bundle_unit01
- 位置：src/mail_core/accounts/credentials.py:24-36
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：统一注释与策略：未知签名时不传 session 并记录，或明确写清「优先传、靠调用方 TypeError 回退」并给 put/delete 都加回退

### A286. sync_message_body 对 DB 中未知 archive state 字符串抛裸 ValueError

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/mail/application/message_details.py:53-106
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：捕获 ValueError 转 MessageArchiveStateUnavailable 并带上原始 state 值

### A287. messages_by_ids 的 folder_id 取多 location 联接的首行，结果不确定

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/queries.py:173-188
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：folder_id 明确取 locations 中按既定优先级的第一项，或标注为任意主文件夹并保证排序确定

### A288. rewrap 的剩余旧版本统计每次全量 rglob 并逐个开文件读头

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/rotate.py:94-110
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：主循环扫描时顺带累计各版本计数，尾部只对失败/未知项复查

### A289. list_folders 吞掉 well-known 端点的一切异常，容量/限流错误被误当「端点不存在」

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/graph.py:131-141
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只吞 404 类 ProviderHttpError，CAPACITY_ERRORS 与 RateLimitedError 向上抛

### A290. Graph fetch_metadata_page/delta_changes 单页无条数上限，与 list/reconcile 的 MAX_GRAPH_ITEMS_PER_CALL 不一致

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/graph.py:190-215
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：parse 前对 data["value"] 长度设上限，超限抛 GraphPaginationError

### A291. urllib_json_request 对 2xx 的非法 JSON 抛裸 JSONDecodeError，写操作会被误判终态失败

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/oauth.py:386-400
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：解码失败时按方法区分：GET 抛 ProviderHttpError，非幂等方法抛 AmbiguousOutcomeError

### A292. Retry-After 只支持秒数，HTTP-date 形式被静默丢弃

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/http.py:35-48
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用 email.utils.parsedate_to_datetime 解析 date 形式并换算为剩余秒数

### A293. 每次带 generation 的 checkpoint 提交都对全账号 full targets 做 GROUP BY 排序查询

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/checkpoints.py:22-70
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只查「是否存在 birth 晚于本 generation 的兄弟」的一行存在性查询（子查询取本 generation 的 min 后做 > 比较 + LIMIT 1），或在 begin_scan_generation 时判定一次并把结果随 job 携带

### A294. healthcheck 在 try 外裸 float() 解析 env 且异常出口打印未脱敏 exc

- 来源：bundle_unit04
- 位置：src/mail_core/worker/healthcheck.py:12-14
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：解析移入 try 并做有限正数校验，错误输出只打 type 名

### A295. 心跳损坏/无时区时间戳被静默 skip 且与 cleanup 口径相反，健康信号可无声失真

- 来源：bundle_unit04
- 位置：src/mail_core/worker/heartbeat.py:74-92
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：get 侧对坏行计数并限频 warning，naive 时间戳按 UTC 解释，两处统一坏行策略

### A296. WorkerHeartbeatLoop.start() 非幂等，重复 start 泄漏线程且 stop 只 join 最后一个

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/worker/heartbeat.py:170-185
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：start 前若线程存活直接返回，stop 后保留引用直至 join 完成

### A297. claim 心跳线程在 claim_times_lock 内做整批 DB 刷新+commit，锁跨 IO 阻塞主线程 claim 校验

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/worker/main.py:114-153
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：锁内只快照 claim_times，DB 刷新在锁外，最后短临界区回写结果

### A298. normalize_subject 前缀表覆盖不全，常见变体串不了线程

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/threading/rules.py:20-32
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补 Re\[\\d+\]: 与全角冒号归一，或明确在 docstring 声明只支持当前前缀集

### A299. TextDecoder 流式解码在连接结束时未 flush，尾部多字节字符可丢失；且 server retry 被钳制最小 1000ms 与服务端指令不符

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/api/sseStream.ts:214-230
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：读毕 flush 一次 decoder；retry 钳制只设上限、保留服务端小值（或注释说明钳制裁决）

### A300. 登录提交无 in-flight 守卫，Enter 连按/慢网可并发多次 api.login

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/LoginPage.tsx:9-22
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：加 submitting ref 守卫，submit 开头判重直接 return

### A301. freePort 存在 TOCTOU：探活端口关闭后到后端真正 bind 之间可被抢占

- 来源：bundle_unit06
- 位置：src/desktop/startup.js:163-181
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：接受现状时在注释标注该竞态与失败形态；更稳妥的做法是让后端 bind 端口 0 后回告实际端口（需后端配合），至少把 health 失败文案区分「端口被占」。

### A302. status() 每次都同步 spawn pg_ctl，start() 一轮内重复调用阻塞主进程

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/postgresManager.js:271-300
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：start 内部缓存一次 status 结果复用，或给 status 加短 TTL 缓存（hasBinaries 已有缓存先例）。

### A303. group 视图忽略 flagged 筛选，标题与列表内容不符

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/listTitle.ts:33-41
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：group/favorite 各分支统一先按 filter 生成后缀，或在函数头集中处理 filter 维度。

### A304. project_attempts 对同 identity 的重复 attempt_reserved 静默整表覆盖，可抹掉已 terminal/report 记录

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/attempts.py:29-72
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：重复 reserved 时抛 TaskDataError 或保留首条并标记损坏，要求人工修复账本。

### A305. 构建产物未做可运行冒烟即拷入 desktop resources

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/build-sidecar.sh:43-52
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：cp 前对产物跑一次最小自检命令并校验退出码，失败即中止

### A306. .env.test 自研解析器会误处理引号与行内注释

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/run_full_stack_e2e.py:35-43
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 dotenv 解析或仅剥成对引号并在文档中声明子集语法

### A307. docker() 失败时丢弃全部 stderr，故障不可诊断

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/test_pg_runtime.py:35-51
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：对 stderr 做凭据模式脱敏后回显（如过滤 password/token 赋值），而非整段丢弃

### A308. \_now_iso 硬编码 +08:00 时区生成 last_synced_at

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/repo_sync.py:1751-1753
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用本地时区 `datetime.now().astimezone()` 输出真实偏移

### A309. scan_max_id 按分支全量扇出子进程，分支多时每次 new 都慢

- 来源：bundle_unit08
- 位置：.repo_template/scripts/\_id_scan.py:183-199
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：单次 `git ls-tree -r` 跨分支批量取数或缓存分支树清单，legacy 正文仅在文件存在时才 show（现已如此，可再并入一次调用）

### A310. 快速开始未提示 initial-password.txt 的明文留置风险与处理

- 来源：bundle_unit08
- 位置：README.md:24-26
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：该段补一句「首次登录后立即改密，改密会自动删除该文件；未改密前按密钥文件同等保护」，并链接 security.md

### A311. 「本会话」类会话残留措辞成批进入归档正文

- 来源：bundle_unit10, bundle_cross_validation
- 位置：docs/archive/tasks/t013_test_pg_runtime/spec.md:48-48
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：后续归档写作将「本会话」统一改写为带日期的决策记录句；存量 11 个 task 可在统一勘误时一并处理，不逐份覆写历史原文时至少在新写入的说明中不再沿用

### A312. t041/t042/t043 三份 task.md 的「最终全量验证说明」整段逐字相同、共用同一运行 ID

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t041_unknown_mail_status/task.md:74
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在三处各加一句注明该全量运行为 t041–t043 同批联合验证（或分别指向各自的定向证据），避免复制段落冒充独立验证

### A313. CORS 凭据模式下 methods/headers 全通配

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/app.py:105-115
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：收敛为实际用到的方法（GET/POST/PATCH/PUT/DELETE）与头（Authorization/Content-Type/X-CSRF-Token/X-Request-ID）

### A314. get_sidebar_layout 全量 FULL OUTER JOIN 后内存去重

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/accounts/service.py:284-295
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改两次简单查询（groups、accounts 各一）本地组装，去掉 full outer join

### A315. 0027 回填逻辑无迁移级测试（视角7）

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py:31-68
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补 PG 迁移测试：预置 0026 数据（含空/多收件人）upgrade 后断言两处回填

### A316. pg_dump/pg_restore 超时 env 用 float() 裸解析，畸形配置抛 ValueError 而非 PgDumpError

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/backup/package.py:463-520
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：解析失败时回退默认值并 log.warning，或统一包装成 PgDumpError

### A317. get_message_detail 的附件按 filename 排序而非 MIME part 顺序

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/queries.py:377-418
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 part_id 的数值序（或新增序号列）排序，filename 仅作次级键

### A318. rewrap_blob_file 的临时文件用默认权限创建且 replace 后不 fsync 目录

- 来源：bundle_unit02, bundle_cross_validation
- 位置：src/mail_core/blobs/rotate.py:132-161
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：以 0o600 创建临时文件，replace 后 fsync 父目录

### A319. metadata 完成分支的 reconcile（非 full 路径）与 archive 批量入队缺 dedupe_key

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/engine.py:694-715
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：分别补 `reconcile:{account_id}:{folder_id}` 与按账号稳定的 archive dedupe_key

### A320. 文件夹一旦被置 PAUSED 永不恢复，远端重建/变可选后仍不再同步

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/engine.py:365-378
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：区分「远端消失/不可选」的系统暂停与其它暂停，前者在文件夹重新可选时恢复 IDLE 并补一次 metadata 入队

### A321. Gmail 虚拟文件夹判定含名字子串启发式，会误停用户自建标签

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/engine.py:332-350
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只按 remote_id 精确集合或 role（all/important）判定，删除名字子串分支，或子串改为全名相等

### A322. \_live_execution_generations 每次孤儿巡检把全部在途作业的 payload 整表读回内存

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/execution.py:596-618
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：把 successor generation 提升为独立列并索引，或用 JSON 路径表达式在 SQL 侧只取 \_queue_next.execution_generation

### A323. metadata page_size 直接取自 cursor 且不设 bounds

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:696-750
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：clamp 到 [1, 500]，非法值回退 50

### A324. cookie_samesite=none 与 cookie_secure 解耦，可配出浏览器必拒或明文跨站的组合

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/auth.py:151-155
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：session_max_age 同处做组合校验：samesite=none 时强制要求 secure，否则回退 lax 并记 warning

### A325. safe_error 对非 ProviderHttpError 异常整段消息脱敏后持久化，SQL/内部细节仍可落 worker_jobs.last_error

- 来源：bundle_unit04
- 位置：src/mail_core/security/redact.py:46-69
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：非 provider 异常也收敛为类型+受控字段摘要，完整消息仅 debug 日志经 formatter 输出

### A326. RedactingFilter 本身不处理 exc_info/exc_text，单独使用时 traceback 明文直出

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/security/redact.py:160-181
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 filter 中对 record.exc_info 预生成并脱敏 exc_text，或在类 docstring 明示必须与 RedactingTraceFormatter 配套

### A327. start() 中 previous.join() 无超时，旧线程卡在 DB 调用时重启路径可无限阻塞

- 来源：bundle_unit04
- 位置：src/mail_core/realtime/listener.py:68-78
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：join 加超时，超时则放弃本次启动并记 error（线程为 daemon，不会挡进程退出）

### A328. 反馈浮层宽度以魔法数 288 写死，窄屏/长错误文案下仍可溢出

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/CopyAddress.tsx:58-65
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：浮层 max-width 用 vw 约束（如 min(288px, calc(100vw - 16px))）并以同一常量参与定位

### A329. 键盘调整直接调用 props 的 onDrag/onDragEnd 而非 ref 版，且长按自动重复每次都触发 onDragEnd

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/ColumnResize.tsx:78-87
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：键盘路径同样走 ref；onDragEnd 仅在 keyup 或按键序列结束时发一次

### A330. dialog 副作用 effect 依赖为空，组件不卸载而 vendor/protocol 变化时帮助内容与已 showModal 的对话框脱节

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/credential_help.tsx:6-11
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：父级以 vendor+protocol 为 key 重挂载，或 effect 依赖纳入 vendor/protocol 并处理已打开状态

### A331. 任意 loopback 端口的 http 链接都被当合法外链交给系统浏览器

- 来源：bundle_unit06
- 位置：src/desktop/paths.js:28-38
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：http-loopback 外开仅放行本应用 origin 端口，或对 loopback http 一律 deny（本应用内导航已有 isLocalAppUrl 分支）。

### A332. matchesShortcut 把 Ctrl 与 Meta 视为等价，与录制语义不符

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/ui_shortcut.ts:50-60
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按 `isMac()` 只认当前平台的主修饰键，或在 Shortcut 结构中分开保存并精确匹配。

### A333. inferVendor 对多 @ 与尾点域名误判

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/account_providers.ts:20-20
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：取最后一个 `@` 之后的部分并去掉尾随 `.` 再查表。

### A334. formatFileSize 对 Infinity 与小数 bytes 输出异常

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/formatSize.ts:5-14
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：入口加 `Number.isFinite` 校验，B 档对小数取整。

### A335. 本地复用既有 server 可能测到假目标

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/playwright.config.ts:20-27
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：复用时加一个可达性+身份校验（如请求 `/` 断言含 kkmail 标记），或默认不复用、仅显式 env 时开启。

### A336. client_request_id 用 Math.random 生成，幂等键强度不足

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/hooks/use_scope_sync.ts:207-207
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 `crypto.randomUUID()`（或 getRandomValues hex）生成 client_request_id。

### A337. `scan_tasks_at_ref` 以目录名作 dict 键，active 与 archive 同名目录静默互相覆盖

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/store.py:103-133
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：键改 (name, archived) 或发现同名跨区时直接 TaskDataError 明示冲突。

### A338. baseline 参数未做 `--end-of-options` 隔离，可被当 git 选项注入

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_state.py:41-62
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：所有调用加 `--end-of-options` 并先校验 baseline 形态

### A339. --check 把 md_kx 任何 exit 1 都当作格式漂移

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/md_format.py:98-145
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：结合 stderr 区分漂移与错误输出，或对 exit 1 再校验输出形态，非漂移按 MdFormatError 抛出

### A340. MAIL_CORE_BLOB_KEY_V1 不校验 base64 合法性与 32 字节长度即构造 Keyring

- 来源：bundle_unit08, bundle_cross_validation
- 位置：scripts/migrate_from_legacy_db.py:380-386
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：入口处一次性校验解码长度 ==32 并给出面向操作者的错误信息，与其它前置校验同阶段完成

### A341. merge_mcp 对非 dict 的 mcpServers 无防御且缺文件时整表复制模板 MCP

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_sync.py:1138-1177
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：合并前校验两侧 mcpServers 均为 dict；整表复制时在报告中逐 server 列出并提示其为可执行配置

### A342. 回滚备份 copytree 跟随符号链接，恢复后链接变实体副本

- 来源：bundle_unit08
- 位置：.repo_template/scripts/repo_sync.py:124-141
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：copytree 传 `symlinks=True`，单文件分支已有 follow_symlinks=False 应与目录分支对齐

### A343. list 对非 UTF-8 条目文件整表崩溃（findings.py 同病）

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/pending.py:146-166
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：读取时 `errors="replace"` 或逐文件捕获并以占位标题继续列出

### A344. extract_tid 正则在任意 Bash 命令文本中误命中

- 来源：bundle_unit08, bundle_cross_validation
- 位置：.repo_template/scripts/track_worktree.py:106-118
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：先确认命令包含 track_worktree.py/task.py 路径再提取 tid（与文件头注释描述的触发条件对齐）

### A345. 背景中的精确数字「3,700 封实际收件膨胀至 7,290 封」无证据来源、以确定事实口吻陈述

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/spec.md:5
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：数字旁注记其来源与未入库状态（如「据用户 2026-10 反馈日志，未入库，仅作量级示意」），或改写为量级表述（「约 2 倍膨胀」）

### A346. 健康指标串行多查且语义与命名不符

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/system_metrics.py:75-205
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：加数秒进程内缓存、字段改名为 last_sync_lag_seconds 或按账户 max 计算、补 unhealthy 判定或删注释值

### A347. enqueue 的 run_after 取 min 合并可提前唤醒退避中的作业

- 来源：bundle_unit03
- 位置：src/mail_core/sync/jobs.py:96-112
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：合并时仅当新 payload 明确要求立即执行才允许提前，或为退避作业打标后禁止 run_after 前移

### A348. LIST 响应正则不处理转义引号与尾随空格邮箱名

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:548-600
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：用支持 `\"` 转义的模式解析引号名，且只 strip 包裹引号外的空白

### A349. heartbeat_lease 不校验租约是否已过期，与 assert_fencing 口径不一

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/leases.py:105-125
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：heartbeat 增加与 assert_fencing 一致的过期校验（或在 docstring 明示「过期可续」并让 reconcile 改用 assert_fencing+独立续租）

### A350. IMAP 主机校验存在 DNS TOCTOU，peer 复核在 TCP/TLS 已建立后

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/factory.py:66-90
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：解析后按 IP 直连并以证书 SAN/主机名校验 TLS，或接受残余风险并在 host_security 注释中明示该窗口

### A351. prune_published 遇 published_at 为 NULL 的已发布行即整批停摆

- 来源：bundle_unit04
- 位置：src/mail_core/realtime/outbox.py:174-181
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：NULL published_at 按 created_at 兜底判定，或一次性数据修复补齐该列并加 NOT NULL 约束

### A352. get_publication_state 无行锁建单例行，多进程首启并发可撞主键

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/publication.py:23-30
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：迁移层预置单例行，或插入走 ON CONFLICT DO NOTHING 后重查

### A353. search 层对 query 长度无上限，防线只在 API 路由一处

- 来源：bundle_unit04
- 位置：src/mail_core/search/index.py:142-149
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 index 层对 query 做长度截断/上限校验，与路由同值

### A354. 诊断日志包含完整 error.stack 与 componentStack 并可一键复制外发，堆栈含源码路径与组件层级

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/ErrorBoundary.tsx:34-42
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：导出时对堆栈做路径裁剪，或在复制按钮旁标注日志含技术细节

### A355. window.open 后以赋值 opener=null 切断引用，个别浏览器静默失败且无 noopener 兜底

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/settings_account_form.tsx:252-290
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：window.open(url, '\_blank', 'noopener') 并保留 opener 赋值作双保险

### A356. waitForHealth 超时拒绝后已排程的重试仍会继续发请求

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/startup.js:186-225
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：加 settled 标志，tick 入口与回调先判 settled，settle 后清掉待排程 tick。

### A357. ensureDatabase 的 marker 写入可抛异常且与真实库状态可脱节

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/postgresManager.js:387-402
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：marker 写失败只记 warn 不失败；或以实际连通性校验替代 marker 作为已建库判据。

### A358. getEmailInitial 对特殊首字符产出错误首字母

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/store/accountIcon.ts:142-150
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：`toUpperCase()` 结果长度 >1 或首码点为 Mark 类时回落到下一个可用字符/返回 null。

### A359. 列表预览对未截断的攻击者可控文本跑多趟正则

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/previewText.ts:9-24
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：进入 strip 前先把输入截到如 4×max 上限，或限制 strip 的输入长度并注释该上限的取舍。

### A360. 剪贴板 fallback 的 finally 里 removeChild 本身可抛错

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/clipboard.ts:44-57
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：removeChild 包 try/catch（或用 `ta.remove()`），并在注释标注 execCommand 仅为 http 非安全上下文的兜底。

### A361. ErrorBoundary 的 resetKey 把 search 逐字输入也算进去

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/App.tsx:186-188
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：resetKey 只含 view/listFilter/selectedKey，search 不进重置维度。

### A362. 全局/分组视图的心跳永远不发送

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/hooks/use_scope_sync.ts:296-324
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：按后端 activity 接口契约决定全局视图应传的 account 集合（或空数组语义），不要在前端静默跳过；若确属只保活单账号则在注释写明。

### A363. child() 在 wait 返回后仍 killpg，存在 pgid 被回收误伤的时序窗

- 来源：bundle_unit08
- 位置：scripts/test_pg_runtime.py:246-272
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：发送前用 `os.killpg` 配合进程组存活判断与子进程孙辈清单，或记录子进程启动时间戳校验 pgid 归属后再发信号

### A364. 备份命令缺执行前提（工作目录/PYTHONPATH），照抄可能直接 ImportError

- 来源：bundle_unit09, bundle_cross_validation
- 位置：docs/guides/upgrade.md:5-9
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：补明工作目录与 PYTHONPATH 前置，并标注该命令为静态核对、未在本轮实测

### A365. OAuth 回调页 CSP 允许 unsafe-inline 脚本/样式

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/oauth_routes.py:387-395
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：脚本/样式改 nonce 或哈希白名单，message 继续保持 escape

### A366. DeltaChange.kind 无校验：未知 kind 被静默忽略，flag 补丁的任意键可让合并抛 TypeError

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/delta.py:125-210
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 DeltaChange 构造/apply 入口校验 kind 白名单，\_flag_patch_values 只保留 is_read/is_flagged 两键

### A367. \_raise_mapped 以 body 子串 "delta"/"sync" 把普通 404 误判 CursorInvalid

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/graph.py:73-86
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：只按状态码 410 与明确错误码（syncStateNotFound/resyncRequired）判定，404 需再核对调用端点是否为 delta URL（oauth.\_url_is_sync_cursor_endpoint 已有现成判据可复用）

### A368. UID STORE/MOVE 对不存在的 UID 也可能报 success

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/imap.py:1110-1165
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：STORE 前后用 UID SEARCH/FETCH 确认该 UID 仍存在，或把 FETCH 回读 flags 作为成功判据

### A369. apply_remote_operation 对非 dict 传输响应直接 AttributeError，绕过 RemoteOperationResult 失败通道

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/graph.py:225-290
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：\_call 出口或各分支入口加 isinstance(data, dict) 归一（非 dict 视为 {} 并记录），或捕获后返回 success=False 的结果对象

### A370. MemoryProvider 按 offset 分页，扫描期间列表增删会跳过/重复条目

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/stub_memory.py:135-165
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用 remote_id 锚点或快照迭代（先复制列表再分页），与真实 provider 的游标语义对齐

### A371. groupColor/providerColor 作为 style.background 原样下发，颜色值来自服务端分组数据，异常值可注入 url() 等 CSS

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/AccountIcon.tsx:37-50
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：下发前以 /^#[0-9a-f]{3,8}$/i 或 CSS color 关键字白名单校验，不合规回退 var(--muted)

### A372. initdb pwfile 写入不带 wx/权限收紧，预置文件可保留宽权限

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/desktop/postgresManager.js:314-325
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：写入前再 `unlink` 一次并用 `openSync(pwFile,'wx',0o600)` 创建后写 fd（与 `password()` 持久化的 wx 做法对齐）。

### A373. archive 事件在 payload 无 message id 时被整体丢弃

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/hooks/useMailCoreRealtime.ts:170-175
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：ids 为空时退化为失效全部 detail（与 message 事件的既有兜底一致），或按后端事件契约补 archive id 的提取。

### A374. DbCredentialStore.get_secret 解码错误逃逸为非 KeyError

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/accounts/credentials.py:105-115
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：在 get_secret 内把 InvalidTag/UnicodeDecodeError 归一为 KeyError 或专用 CredentialCorruptError 并让调用方显式处理

### A375. 控制连接错误信息可能回显 DSN 内容

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/connection_slots.py:180-210
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：ProviderControlError 只保留异常类名与槽位号，DSN 相关文本经 safe_error 脱敏后再拼接

### A376. FixtureTransport 前缀路由按插入序首命中而非最长前缀

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/providers/http.py:95-112
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：前缀候选按 prefix 长度降序匹配

### A377. 运行时 apiBase 无任何校验即可把 API 指向任意源

- 来源：bundle_unit06, bundle_cross_validation
- 位置：src/frontend/src/lib/apiBase.ts:13-17
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：至少校验为 http(s) 且在桌面/同源部署下拒绝跨源覆盖，或在 README/ARCHITECTURE 明确该配置是可信运维面并禁止由页面内容注入。

### A378. generation 先后以 min(created_at) 判定，同事务时间戳并列时旧 generation 可蒙混过关

- 来源：bundle_unit03, bundle_cross_validation
- 位置：src/mail_core/sync/checkpoints.py:41-70
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：改用单调序列（如 request 的自增序号或 created_at+id 的稳定全序）作为 generation 出生序

### A379. SSE epoch 复查临界点可能产生 keepalive 忙循环

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/sse.py:290-310
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：keepalive 分支给 timeout 设下限（如 >=1s）或超时后统一 sleep 到复查点

### A380. fetch_since 是 v1 遗留回放 API，与 v2 publication 流并存且绕过发布序（预存）

- 来源：bundle_unit04, bundle_cross_validation
- 位置：src/mail_core/realtime/outbox.py:83-106
- 优先级：Low
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：删除该函数与导出（测试改用 fetch_published_since），或在 docstring 标 deprecated 并禁止新调用

### A381. 剪贴板回退用已废弃 `document.execCommand('copy')` 且 sheet 文档缓存会话内不失效

- 来源：bundle_unit07, bundle_cross_validation
- 位置：.repo_template/scripts/repo_task/view_static/board.js:101-115
- 优先级：Info
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：回退失败时 showToast 提示手动复制；文档缓存加「重新加载」入口或在 chain-recalc 整页刷新时一并清缓存的说明写入页脚。

### A382. t056 spec 对实现位置的表述与当前代码落点有命名漂移

- 来源：bundle_unit11, bundle_cross_validation
- 位置：docs/archive/tasks/t056_gmail_sync_strategy_and_timeout/spec.md:13-17
- 优先级：Info
- 详细判断理由：问题真实存在，证据确凿，影响代码正确性、健壮性、数据一致性或规范一致性；修复范围明确、成本低、收益明确且无破坏性副作用。
- 修复说明：归档勘误注记中统一实现落点（engine.py 同步阶段），并注明 delta 路径的 20 页为独立默认值、不在本 task 范围

### A383. 历史凭据检索配方与 Git 历史处理策略（采纳选项 A）

- 来源：bundle_unit13, bundle_cross_validation_regression
- 位置：docs/reviews/review_20261025_020805/bundle_regression.md:9-9
- 优先级：CRITICAL
- 详细判断理由：用户决策采纳选项 A：仅在 docs/ 树内执行文档级脱敏，将所有 40 位/短 commit SHA、路径和行号替换为私有占位符（如 [REDACTED_HISTORICAL_COMMIT]），不破坏 Git 历史树与分叉基线。风险收益比最高，彻底阻断检索配方在公开文档中的分发。
- 修复说明：对 docs/reviews/ 历史报告中出现的敏感历史 commit sha（如 34c81310、d368f009 等）、路径及行号元组批量执行文档级占位符替换脱敏。

### A384. 邮件 iframe 弹窗沙箱逃逸策略注释与防护（采纳选项 A）

- 来源：bundle_unit05, bundle_cross_validation
- 位置：src/frontend/src/components/MessageReader.tsx:474-500
- 优先级：HIGH
- 详细判断理由：用户决策采纳选项 A：保持 allow-popups-to-escape-sandbox 以确保邮件中正常外链的 Web 功能可用，在 mailBody.ts 中补充明确的安全威胁模型裁决注释，并保持已有的 strict noopener noreferrer 及外链协议过滤防护。
- 修复说明：在 src/frontend/src/lib/mailBody.ts 中补充关于 allow-popups-to-escape-sandbox 的威胁模型裁决注释，锁定安全理由与防护边界。

### A385. 系统健康指标端点鉴权保护（采纳选项 A）

- 来源：bundle_unit01, bundle_cross_validation
- 位置：src/mail_core/api/app.py:239-248
- 优先级：HIGH
- 详细判断理由：用户决策采纳选项 A：/api/system/health 与 /health/metrics 增加会话鉴权保护，未鉴权请求仅放行无敏感字段的存活探针 /health，防止系统内部运营指标外泄。
- 修复说明：在 src/mail_core/api/app.py 中为 /api/system/health 和 /health/metrics 增加 dependencies=[Depends(require_auth)]，并调整对应单测断言。

### A386. 桌面端废除 HTTP 响应头传递 X-Instance-Token（采纳选项 B）

- 来源：bundle_unit01, bundle_cross_validation_regression
- 位置：src/mail_core/api/app.py:182-187
- 优先级：HIGH
- 详细判断理由：用户决策采纳选项 B（最优架构方案）：彻底废除在 GET /health 响应头回显 X-Instance-Token 的做法；改由桌面端在启动 sidecar 时通过标准输入/私有文件通道安全传递握手 token，实现职责正交与同机网络零泄漏。
- 修复说明：移除 GET /health 中的 X-Instance-Token 响应头逻辑；桌面端与 sidecar 握手改为通过启动私有通道/文件传递验证。

### A387. 历史审阅目录过时横幅统一补齐（采纳选项 A）

- 来源：bundle_unit12, bundle_unit13, bundle_cross_validation
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:1-7
- 优先级：HIGH
- 详细判断理由：用户决策采纳选项 A：保持目录在 docs/reviews/ 位置不变，为 20261022、20261025、20261026 各历史审阅报告头部统一追加标准 SUPERSEDED 历史横幅（明确基线 SHA、记录日期与替代位置），避免破坏已有提交与文档相对链接。
- 修复说明：为 docs/reviews/ 下各历史审阅汇总报告头部添加规范的 SUPERSEDED 历史时点标注与现行替代指引。

## 不采纳项

### R1. 已归档 pending 在公开仓嵌入真实实例数据（真实邮箱/账号 UUID/口令特征）未脱敏

- 来源：bundle_unit09
- 位置：docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:3-11
- 优先级：Critical
- 详细判断理由：CV-A24 实测证伪：原文无真实邮箱明文，已被符号化占位符替换，前提不成立

### R2. 034329 是超时夭折的半成品会话，未加任何未完成标注即入库

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_034329/\_meta/\_meta.json:27-56
- 优先级：Medium
- 详细判断理由：历史会话中断事实，保留原样即可

### R3. 核验总报告的总数与自身统计表自相矛盾（106 ≠ 139）

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:9-26
- 优先级：Medium
- 详细判断理由：历史旧审阅文档统计口径差异，无需重写历史

### R4. bundle.json 内部统计与自身清单不一致，疑为上一会话残留数字未更新

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_034329/bundle.json:543-544
- 优先级：Medium
- 详细判断理由：历史中间数据统计差异，无需回写历史文件

### R5. 040521 会话缺 aggregate 终产物 review_intensive.md，入口缺位导致核验文件被迫充当总报告

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_040521/\_meta/\_meta.json:19-33
- 优先级：Medium
- 详细判断理由：历史未产出 aggregate 会话，无需事后补生成

### R6. 脱敏只改当前树、未改 git 历史：脱敏前版本仍可从公开仓历史直接读出本机绝对路径（含本地用户名段）（预存）

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_034329/\_meta/\_meta.json:4-5
- 优先级：Medium
- 详细判断理由：当前代码树已完成脱敏，不破坏性重写历史 Git 树

### R7. 071448 会话产物严重注水：125 份 bundle 中 94 份是零 finding 的模板残片

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261022_071448/bundle_dir_docs.md:1-13
- 优先级：Low
- 详细判断理由：历史会话既成形态，无需清理

### R8. 视角1 隐私与历史泄漏全扫结论：本 unit 无泄漏

- 来源：bundle_unit02
- 位置：src/mail_core/backup/package.py:1-1
- 优先级：Info
- 详细判断理由：审阅核验结论，已证明当前代码树无隐私泄漏，保持现状

### R9. board.html 未列入 unit07 清单但为 view_server 运行时必需文件，审查范围与真实依赖不一致

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/view_static/board.html:1-138
- 优先级：Info
- 详细判断理由：审阅清单观察，文件实际存在且为运行时正常依赖，无需修改

### R10. 机器生成的打包输入 bundle.json（25-60 KB/份）与人工报告同级混存，且 docs/reviews 下无任何索引说明文件角色

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261022_071448/bundle.json:1
- 优先级：Info
- 详细判断理由：机器生成输入文件留存历史记录，无需回溯清理

### R11. 已排除疑点：keyset 分页的 NULL sort_time 谓词不丢行

- 来源：bundle_unit02
- 位置：src/mail_core/mail/application/queries.py:218-299
- 优先级：Info
- 详细判断理由：原文已明确为排除疑点，静态分析与单测验证行为正确，无需修改

### R12. notify_outbox 用 f-string 拼 pg_notify 而同文件 revocation 版用参数绑定，两处口径不一

- 来源：bundle_unit04
- 位置：src/mail_core/realtime/notify.py:23-33
- 优先级：Info
- 详细判断理由：CHANNEL 为模块常量，无 SQL 注入风险

### R13. 本仓 tests/ 内无 repo_task 工具链的任何测试，视角 7 在本仓无可核覆盖

- 来源：bundle_unit07
- 位置：.repo_template/scripts/repo_task/cli.py:1-244
- 优先级：Info
- 详细判断理由：模板工具链测试在模板仓侧维护并在同步时验证，消费仓无需为模板工具链重复维护测试套件

### R14. 运行 DB 账户构成计数（25 Graph / 9 IMAP）写入公开仓归档

- 来源：bundle_unit11
- 位置：docs/archive/tasks/t055_microsoft_oauth_callback/spec.md:5
- 优先级：Info
- 详细判断理由：聚合运营数据无个人敏感信息，不构成隐私违规

### R15. 各会话 aggregate 完整度口径不一：011116 的 aggregate 只是主题节选，无法据其枚举全部 finding

- 来源：bundle_unit12
- 位置：docs/reviews/review_20261021_011116/review_intensive.md:16-28
- 优先级：Info
- 详细判断理由：历史工具链演进阶段产物差异，无需统一修改

### R16. search 包只导出 2/5 个公共函数，其余靠深路径 import

- 来源：bundle_unit04
- 位置：src/mail_core/search/__init__.py:1-3
- 优先级：Info
- 详细判断理由：内部子模块直接引用，无外部导出缺口

### R17. 0025 downgrade 只恢复 schema 形态不恢复数据

- 来源：bundle_unit01
- 位置：src/mail_core/db/alembic/versions/20261026_0025_sync_execution_tracking.py:120-134
- 优先级：Info
- 详细判断理由：迁移 docstring 已明示数据降级不可逆，且生产环境不需要回滚该迁移

### R18. \_reclaim_once 返回值漏计 converged/resumed/pruned_reservations 三项

- 来源：bundle_unit04
- 位置：src/mail_core/worker/main.py:101-102
- 优先级：Info
- 详细判断理由：内部辅助函数返回值无外部调用方消费，修改无实质收益

### R19. InboxPageData/SearchPageData 接口声明写在组件函数体内（观察）

- 来源：bundle_unit05
- 位置：src/frontend/src/components/MessageList.tsx:126-135
- 优先级：Info
- 详细判断理由：组件私有接口不影响外部模块

### R20. folder-stats 端点路径字符串在三处重复手写，未收敛到 mailCore.ts（观察）

- 来源：bundle_unit05
- 位置：src/frontend/src/components/Sidebar.tsx:126-132
- 优先级：Info
- 详细判断理由：端点契约已定型且极稳定

### R21. 0002 revision ID 与文件命名约定不一致

- 来源：bundle_unit01
- 位置：src/mail_core/db/alembic/versions/20261020_0002_mail_core_unified_schema.py:1-19
- 优先级：Info
- 详细判断理由：已发布的迁移 revision 唯一哈希值不可更改，修改会导致既有数据库版本链断裂

### R22. getDesktopLogger 单例忽略后续调用的 options

- 来源：bundle_unit06
- 位置：src/desktop/desktopLog.js:187-194
- 优先级：Info
- 详细判断理由：桌面单例生命周期行为符合预期

### R23. 设计文档仍以 alpha + 旧产品名呈现为当前实现参照

- 来源：bundle_unit08
- 位置：assets/DESIGN.md:1-4
- 优先级：Info
- 详细判断理由：原型设计文档历史标记，不再演进

### R24. 过度脱敏切断来源可验证性，且关键来源文件不在审阅打包范围内

- 来源：bundle_unit10
- 位置：docs/archive/tasks/t027_account_group_ordering/source_notes.md:6-7
- 优先级：Info
- 详细判断理由：设计聊天链接脱敏属既定隐私保护，保持现状

### R25. 计划预告的交付文件形态与实际产物不一致且无说明

- 来源：bundle_unit13
- 位置：docs/reviews/review_20261026_005019_full_repository/repair_plan.md:493-493
- 优先级：Info
- 详细判断理由：交付记录已合并至 execution_log 与 repair_results，无需拆分单独文件

### R26. 登录页底部明文展示后端环境变量名 MAIL_CORE_LOGIN_PASSWORD / \_HASH（观察）

- 来源：bundle_unit05
- 位置：src/frontend/src/components/LoginPage.tsx:78-82
- 优先级：Info
- 详细判断理由：登录页提示为单用户自托管友好指引，非凭据泄漏

### R27. 自举步骤以裸 cp 覆盖消费仓 repo_sync.py 后立即执行，无完整性核对

- 来源：bundle_unit08
- 位置：.repo_template/skills/repo-template-sync/SKILL.md:13-23
- 优先级：Info
- 详细判断理由：属于用户主动触发模板同步的既定信任模型

### R28. t027 review 双文件 5 轮补丁式堆叠，首轮 FAIL verdict 易被摘引误读

- 来源：bundle_unit10
- 位置：docs/archive/tasks/t027_account_group_ordering/review_code.md:183-183
- 优先级：Info
- 详细判断理由：多轮留痕惯例，最终结论已明确，无需改写历史

### R29. review 文件以多轮追加方式保留互相矛盾的阶段结论（FAIL→PASS、未闭环→撤回），须按时间拼接才能得到最终结论

- 来源：bundle_unit11
- 位置：docs/archive/tasks/t054_google_oauth_callback/review_code.md:102
- 优先级：Info
- 详细判断理由：多轮复审轨迹留痕属规范要求，无需压缩历史

### R30. parsing 包只导出 parse_graph_delta，parse_graph_metadata_page 无包级入口

- 来源：bundle_unit03
- 位置：src/mail_core/providers/parsing/__init__.py:1-3
- 优先级：Info
- 详细判断理由：内部子模块直引属于合法用法

### R31. 文件头称「for sync/archive/remote_ops tests」，与生产用途不符（文档载体不一致）

- 来源：bundle_unit03
- 位置：src/mail_core/providers/stub_memory.py:1-3
- 优先级：Info
- 详细判断理由：文档注记差异，不影响生产运行

### R32. openapi:check 以字节全等比对生成物，生成器小版本升级即全量误报漂移（观察）

- 来源：bundle_unit05
- 位置：src/frontend/src/api/generated/schema.ts:1-5
- 优先级：Info
- 详细判断理由：代码生成严格校验机制，属有效门禁，无需修改

### R33. providerColor 纯工具函数寄居在 store 文件末尾

- 来源：bundle_unit06
- 位置：src/frontend/src/store/mailStore.ts:158-165
- 优先级：Info
- 详细判断理由：代码组织风格偏好，现有引用正常工作，无需额外迁移

### R34. 模块顶层全局注册 DOMPurify hook 存在跨用例副作用

- 来源：bundle_unit06
- 位置：src/frontend/src/lib/mailBody.ts:3-8
- 优先级：Info
- 详细判断理由：目前仅邮件正文渲染使用 DOMPurify，全局单例表现稳定

### R35. DDL 用 f-string 拼标识符与口令（当前输入均为内部随机值）

- 来源：bundle_unit08
- 位置：scripts/run_full_stack_e2e.py:108-111
- 优先级：Info
- 详细判断理由：输入源仅限内部生成的随机 uuid，无注入风险

### R36. format_paths 逐文件起 md_kx 子进程，--all 时串行 O(n) 进程

- 来源：bundle_unit08
- 位置：.repo_template/scripts/md_format.py:98-154
- 优先级：Info
- 详细判断理由：格式化脚本单机执行性能满足需求，无需过度优化

### R37. review 的 reviewed_scope 使用 16 位短哈希，与 diff_anchor 全 SHA 口径并存且无生成说明

- 来源：bundle_unit10
- 位置：docs/archive/tasks/t001_mail_core_sent_query/review_general.md:5-5
- 优先级：Info
- 详细判断理由：已归档历史评审记录，无需回溯修改历史短哈希

### R38. UI 序号浮层（诊断功能）在设置中默认启用，生产构建默认可被快捷键唤出（观察）

- 来源：bundle_unit05
- 位置：src/frontend/src/components/SettingsModal.tsx:41-41
- 优先级：Info
- 详细判断理由：UI 序号浮层为已有的调试辅助功能，无需修改

### R39. 归档 spec 与现行累积 spec 对同一行为使用不同 AC 编号，跨文档按编号引用有碰撞风险

- 来源：bundle_unit10
- 位置：docs/archive/tasks/t001_mail_core_sent_query/spec.md:29-29
- 优先级：Info
- 详细判断理由：task 级 AC 编号内部唯一属模板设计，无需调整历史编号

### R40. worker 线程先于 uvicorn 绑定启动

- 来源：bundle_unit01
- 位置：src/mail_core/__main__.py:84-99
- 优先级：Info
- 详细判断理由：worker 守护线程随主进程退出而终止，启动微秒级窗口无实质危害

### R41. IMAP ID 上报的 version 硬编码 "3.0.20"（上游分叉基线版本），与当前产品版本脱钩

- 来源：bundle_unit03
- 位置：src/mail_core/providers/imap.py:33-34
- 优先级：Info
- 详细判断理由：IMAP 客户端 ID 上报的基线版本号，有利于服务端兼容识别

### R42. StubProvider 随包级懒导出公开，靠 docstring 防误接

- 来源：bundle_unit03
- 位置：src/mail_core/providers/base.py:125-154
- 优先级：Info
- 详细判断理由：已有明确 docstring 说明测试用途

### R43. 会话 epoch 有 5 秒进程内缓存，跨进程吊销存在最长 5s 生效窗

- 来源：bundle_unit04
- 位置：src/mail_core/security/auth.py:320-336
- 优先级：Info
- 详细判断理由：会话 epoch 采用 5 秒缓存属已确认的架构性能与安全取舍

### R44. UI 注册表 SB 编号缺 SB14

- 来源：bundle_unit06
- 位置：src/frontend/src/lib/uiReference.ts:16-22
- 优先级：Info
- 详细判断理由：UI 引用编号不要求严格连续

### R45. 颜色亮度解析对 8 位 hex 只取前 6 位

- 来源：bundle_unit06
- 位置：src/frontend/src/lib/mailBody.ts:47-74
- 优先级：Info
- 详细判断理由：极罕见透明色 edge case，取前 6 位已满足绝大部分邮件视觉亮度判断

### R46. flag 写回渠道写 IMAP/Gmail/Graph，与当前接入面待核对

- 来源：bundle_unit08
- 位置：assets/DESIGN.md:402-402
- 优先级：Info
- 详细判断理由：早期原型设计笔记，非现行契约规范

### R47. api_key_matches 命中即返回且遍历无序集合，存在轻微时序侧信道

- 来源：bundle_unit04
- 位置：src/mail_core/security/auth.py:439-446
- 优先级：Info
- 详细判断理由：单用户自托管环境且已有 compare_digest 比对，时序侧信道风险可忽略

### R48. 初始密码以同步模态框明文展示属设计内但值得留痕

- 来源：bundle_unit06
- 位置：src/desktop/main.js:160-171
- 优先级：Info
- 详细判断理由：初始密码以同步模态框明文展示属单用户桌面初次启动的既定便民设计

### R49. 版本号仍为上游分叉基线 3.0.20（预存）

- 来源：bundle_unit01
- 位置：src/mail_core/__init__.py:6-6
- 优先级：Info
- 详细判断理由：版本号统一管理属于发版流程治理事项，不宜作为局部缺陷随意修改

### R50. 契约 version 停留在 fork 基线 3.0.20（预存）

- 来源：bundle_unit04
- 位置：schemas/openapi.json:2651-2655
- 优先级：Info
- 详细判断理由：同上，版本号需随发版流程整体统一递增，不单独手动修改

### R51. 上游 fork 历史含第三方作者邮箱（预存）

- 来源：bundle_unit06
- 位置：src/desktop/package.json:6-6
- 优先级：Info
- 详细判断理由：上游 fork 历史元数据，保留公开开源归属

### R52. （预存）git 历史中含上游作者公开联系邮箱与 TG 链接

- 来源：bundle_unit08
- 位置：README.md:1-1
- 优先级：Info
- 详细判断理由：上游公开 fork 基线历史自带信息，非本仓用户隐私，保持 Git 历史稳定不重写

### R53. （预存）git 提交者元数据含个人邮箱

- 来源：bundle_unit08
- 位置：AGENTS.md:1-1
- 优先级：Info
- 详细判断理由：上游贡献者历史 git 提交元数据，重写会破坏 commit 签名与历史追溯

### R54. 上游时代「账号详情接口直接返回明文 password」等历史记载属上游遗留记录（预存）

- 来源：bundle_unit09
- 位置：docs/archive/CHANGELOG.md:360-361
- 优先级：Info
- 详细判断理由：上游历史版本 3.0.x 记录，描述已废止的历史行为，作为归档历史保留
