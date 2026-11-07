# Intensive Review 第四轮 — 总结（人读版）

- Target: kkmail 全仓 @ `11bfa52a`（2026-10-27 落盘）
- Scope: bundle.py 白名单 810 文件 / 约 105,456 行 / 184 bundle，合并 13 个 unit 全量扫描（8 视角，阈值 0）；另设回归核对一路、validation 真跑一路、交叉验证两路
- 机器聚合报告：同目录 `review_intensive.md`（aggregate.py 产出）；回归明细 `regression.md`；验证明细 `validation.md`；证伪明细 `bundle_cross_validation.md`（A 路）与 `bundle_cross_validation_regression.md`（B 路）

## Verdict: BLOCK

按 skill 确定性矩阵：存在 Critical → BLOCK（且 validation 后端测试失败，单独亦构成 REQUEST CHANGES 以上）。

## Findings 计数（aggregate 去重后）

| Critical | High | Medium | Low | Info | 合计 |
|---|---|---|---|---|---|
| 2 | 34 | 162 | 194 | 49 | 441 |

原始规范行 444 条，聚合按同 file:line+标题归一合并 3 条。

### 交叉验证后的修正（CHALLENGED 共 2 条，均在 A 路；B 路 0 条）

- **[Critical][95] p027 嵌入真实实例数据（unit09）→ 被证伪，建议降 Low[15]**：验证员对 p027 原始字节核查——全文 `@` 计数为 0、邮箱/UUID 正则 0 命中，实际是 `[REDACTED_EMAIL]`/`[REDACTED_ID]` 字面占位符，文件已脱敏；仅残留「当前保存口令长 13 位」一句且无账号标识可挂靠。扫描员此条系误读。
- **[High][75] cleanup 整目录删除（unit02）→ 影响前提被削弱，建议降 Medium[45]**：代码事实成立（删除循环无清单过滤），但恢复入口拒绝非空目标目录、可清理 stage 仅 staging/db_failed，残余风险限于校验后被第三方新增的文件。
- A 路其余 30 条 AGREE、4 条 CONNECT（横切关联，均成立）；B 路 26 条全部 AGREE。
- **修正后仍成立的 Critical 为 1 条**（下方 C2），且回归账本另有 5 条 Critical 仍未处置（见回归节），BLOCK 结论不变。

## Critical（2 条，聚合口径）

- [C][95] `docs/archive/pending/p027_….md:3-11` — 已归档 pending 嵌入真实实例数据未脱敏
- [C][90] `docs/reviews/review_20261025_020805/bundle_regression.md:9` — **第三轮审阅产物自身完整复写历史凭据检索配方**：打印完整 40-hex commit sha + `outlook_mail_reader.py:20 L20-L26`，凑齐 `git show` 全部要素；本机实测该 sha 在 HEAD 仍可达（命中 v1.0.0/v2.0.x 等大量 tag 与 stash），8 位短形亦可唯一解析。另有 6 处短 sha 复写与一条 High 级定位符索引（`bundle_docs_reviews.md:15-17`）。与第三轮 adoption A294「从当前树移除」的要求相悖——审阅产物在重复传播它自己指出的问题。远端 tag 可达性本轮无网络未验证。

## High（34 条，聚合口径；按位置分组，置信度降序摘录全量）

**后端代码（src/mail_core / scripts）**
- [85] `src/mail_core/api/app.py:239-248` — `/api/system/health`、`/health/metrics` 未鉴权公开 worker ID、账号总数、失败任务数、磁盘与备份状态；测试还把未登录 200 写成断言
- [85] `src/mail_core/backup/package.py:2052-2135` — verify_restore_operation 未在锁内重读 operation log（resume/cleanup 上轮已修，唯独 verify 漏改），可致状态倒退
- [85] `src/mail_core/security/ratelimit.py:74-78` — 登录限流器 import 时裸解析 env：`MAX_FAILURES=0` 每次登录 500、非数值 env 使 API 起不来、NaN window 限流静默失效
- [80] `src/mail_core/mail/application/mutations.py:222-275` — Graph 账号 trash 硬编码 `"Trash"`（应为 `deleteditems`），远程删除必失败而本地已先删、两边分叉
- [80] `src/mail_core/threading/rules.py:82-103` — subject_norm 未截断，超长主题邮件同步时溢出 String(998)、整页回滚
- [80] `scripts/deploy_mail_core.sh:28-40` — 部署备份目录 chmod 0777 且备份包只验存在不验完整性，可被本机任意用户替换后当回滚依据
- [75] `src/mail_core/backup/package.py:2208-2267` — cleanup 删除目标目录全部子项而非本操作文件
- [75] `src/mail_core/blobs/archive.py:1042-1050` — current_used_bytes 对去重 blob 重复计账，误触发 paused_quota
- [75] `src/mail_core/sync/remote_push.py:429-437` — IMAP trash 兜底分支是自引入起从未执行的死代码（Provider 无 `name` 属性），门闩修好会触发 CAS 死循环
- [75] `src/mail_core/worker/handlers.py:126-145` — capacity 延期路径 `float(retry_after)` 遇非数值抛错被吞成计次失败，与「不计 attempt」契约相反
- [70] `src/mail_core/db/alembic/versions/20261027_0027_….py:19-81` — 0027 回填全表相关扫描、无分批、单事务长锁；to_addresses 非数组 JSON 即令升级回滚
- [70] `src/mail_core/backup/package.py:2014-2033` — resume 在 DB 空否未知（None）时 fail-open 重放 pg_restore
- [70] `src/mail_core/blobs/archive.py:271-425` — parse_mime_content 全量内存解析无尺寸上限，毒丸邮件可反复 OOM worker
- [65] `src/mail_core/providers/imap.py:647-723` — STATUS 取不到 UIDVALIDITY 时以 uv=0 铸造 remote_id，与同文件 reconcile 的 B1 中止策略矛盾，可致重复入库与误删
- [60] `src/mail_core/sync/remote_push.py:411-505` — 容量 deferral 实际消耗 attempt（claim 已 +1），纯容量等待可耗尽重试额度终态 FAILED
- [0]（预存）`src/mail_core/providers/imap.py:1201-1226` — IMAP SEARCH 只读 data[0]，多段响应丢 UID 致 reconcile 误删；上轮已报、原样存活

**前端 / 桌面**
- [75] `src/frontend/src/components/Sidebar.tsx:597-647` — statsQuery 的 queryKey 固定而 queryFn 闭包捕获账户名单，账户集合变化后未读统计按旧名单算
- [75] `src/frontend/src/components/settings_account_form.tsx:158-194` — OAuth 轮询 effect 以整个 oauthFlow 对象为依赖，每回包重建 1s 定时器且无 in-flight 守卫，可并发重叠、状态回退
- [75] `src/desktop/postgresManager.js:165-195` — PG 密码 override 与已持久化密码不一致时静默用错密码，改过一次 `KKMAIL_PG_PASSWORD` 后每次启动都连不上库
- [50] `src/frontend/src/components/MessageReader.tsx:474-500` — 邮件 iframe 含 `allow-popups-to-escape-sandbox`，邮件链接新窗口完全脱离沙箱

**repo_template / 工具脚本**
- [75] `.repo_template/scripts/repo_task/documents.py:66-71` — front matter 序列化不转义换行，title/note 含 `\n` 即破坏状态权威文件并可注入伪造键
- [75] `.repo_template/scripts/repo_sync.py:1295-1307` — 契约测试超时（TimeoutExpired）逃出 cmd_apply 回滚逻辑并崩溃，留半同步状态（与回归 H46 同根因互证）
- [65] `.repo_template/scripts/repo_task/view_server.py:213-271` — 看板服务无认证、无 Host/Origin 校验，`/task-doc` 可被 DNS rebinding/局域网读全部 spec/task（与回归 H54 同根因互证）
- [90] `docs/skills/kkmail-skill/scripts/kkmail_cli.py:502` — CLI 仍接受后端已删的 gmail provider，add-account 必然 422（Gmail 下线收尾遗漏，与 t054 标注问题同群）

**文档 / 审阅产物**
- [95] `docs/guides/troubleshooting.md:38-46` — 忘记密码恢复命令把中文占位符写进 bytes 字面量，照抄必 SyntaxError（已实测复现）；这是用户锁门外时的唯一恢复路径
- [90] `docs/archive/legacy_architecture/mail-core-architecture.md:5-13` — 仍以「已定稿，供实现」描述已删除的 Gmail API 架构、含死链，且被现行 blueprint 链接为详尽规范
- [90] `docs/reviews/review_20261022_052842/review_intensive.md:1-7` — 20261022 两批产物（141 文件）无任何过时标注且未迁 archive，与已加横幅批次三态混杂
- [90] `docs/reviews/review_20261026_005019_full_repository/review_report.md:7` — 同包内「未修复/计划未实施/未实现」与「全部已完成/22 项已修复」并存，无勘误
- [90] `docs/reviews/review_20261026_180800_current_repository/review_report.md:1-9` — 以「当前仍成立」口吻发布的 R01–R09 在 HEAD 已全部修复，无过时标注
- [85] `docs/blueprint/decisions.md:60-70` — 仍把已删除的 GitHub Actions CI 写成现行决策，与 testing/release 的「无远程 CI」矛盾
- [85] `docs/archive/tasks/t012_mark_read_convergence/spec.md:52` — 半脱敏真实 QQ 邮箱（前 4 位+域名）与精确运行态统计写入公开仓归档
- [85] `docs/reviews/review_20261025_020805/bundle_docs_reviews.md:15-17` — 第三轮产物复写个人数据提交定位符索引（与上方 Critical 同一轮脱敏处置）
- [80] `docs/specs/auth_and_session.md:27` — AC-004 声称改密/登出会话「立即失效」，与 epoch 5 秒进程内缓存决策矛盾且 spec 未标偏差
- [75] `docs/archive/tasks/t054_google_oauth_callback/spec.md:5-38` — Google OAuth/Gmail API 已整体下线，归档仍以「AC 全部满足」现行口吻陈述、无 superseded 标注

## 回归核对（第三轮 C/H → 本轮四态）

第三轮报告自报 Critical 8 / High **57**（任务简报作 50，以报告实际条目为准），实提 65 条逐条核对：

| FIXED | STILL PRESENT | MOOT | CHANGED | 合计 |
|---|---|---|---|---|
| 31 | 26 | 2 | 6 | 65 |

- Critical 8 条：FIXED 3 / STILL PRESENT 5。仍在的 5 条：凭据检索配方三处复写（C01/C02/C03）、template_source git clone 参数注入（C06）、bootstrap 覆盖并执行未审代码（C07）。
- High 57 条：FIXED 28 / STILL 21 / MOOT 2 / CHANGED 6。MOOT 为 CI 工作流整删（H16）与 Gmail API 提供商整删（H36）。
- STILL PRESENT 的代码级 High 包括：`/health` 未鉴权回吐桌面实例 token（H21，`app.py:183-186`）、决策记录「不轮换历史凭据」仍立（H13）、默认 LOGIN_PASSWORD 字面量在公开历史根提交仍可达（H39）、/task-run 一次授权整队执行（H45）、prep 覆盖工具链无回滚（H47）、批量迁移回滚被非 IdScanError 绕过（H48）、start 把主仓.env 软链进每个任务 worktree（H55）。
- 交叉验证 B 路对 26 条 STILL PRESENT 逐条独立复核：**26 AGREE / 0 CHALLENGED**。
- 本轮新扫描与回归多处独立互证（view_server/H54、repo_sync 超时/H46、凭据配方簇/C01–C03），结论可信度高。

## Validation（真跑，HEAD 11bfa52a）

| 项 | 命令口径 | 结果 |
|---|---|---|
| 后端 unit | `scripts/run-mail-core-tests.sh unit` | **807 passed / 15 failed / 280 skipped**（收集 1102），退出码 1 |
| 前端 | `vitest run`（src/frontend） | **448 passed / 0 failed**（46 文件；基线 446，+2），退出码 0 |
| tsc | `tsc -b`（src/frontend） | **绿**，无诊断 |

- 后端 15 个失败经 284233a7 对照 worktree 同口径实测判定（基线精确复现 812/3/280）：仅 2 个为既存 SSRF 环境失败；**13 个为新失败，全部由 t056/p059 引入**——9 条既有测试被打破（迁移头断言 0026→0027 未同步 ×2、search ESCAPE 计数、SQLite 缺 recipient_addresses 列 ×3、默认 timeout 30→60 断言 ×2、worker handlers ×1），4 条新测试自身未过（PG 依赖未做门控，unit 模式抛 DatabaseConfigError）。基线第 3 个既存失败（test_system_health_metrics_calculation）在 HEAD 已消失。
- PG 门控全量套件未执行：本机无 Docker、缺 `.env.test`/`KKMAIL_TEST_PG_PASSWORD`，guard 要求 Docker 所有的专用 PG——如实记录，未伪造（见 validation.md）。

## Strengths（各 unit 独立提出，节选）

- 后端安全基线扎实：CSRF token 仅内存存储、无 localStorage 凭据、无 dangerouslySetInnerHTML；本轮代码 unit 的隐私全扫（当前文件 + git 历史）未发现真实邮箱/明文密钥/内部路径
- 契约门禁有效：generated client 未见手改证据，openapi:check 字节比对把关，openapi 本体与 live app 一致
- 桌面端基线：Electron sandbox/contextIsolation、scrubEnv + 实例 token、PG 0600/scram/loopback、DOMPurify + srcdoc CSP 分层
- repo_task 工具链：git 全程 argv 数组调用、exact identity 状态机、原子写、worktree ownership 校验、前端全程 textContent 渲染
- 归档纪律局部良好：t028–t031 dropped 标注规范；20261021 三批产物已带历史横幅（与 20261022 两批形成对照）
- 测试文化：本轮 validation 能精确复现基线数字并逐个判定新失败归属，说明测试资产可作回归标尺

## 缺口与未验证项（如实）

- 流程缺口：无。13/13 unit、回归、validation、交叉验证 A/B 全部完成并落盘。
- 未验证：凭据配方 sha 在**公开远端** tag/refs 的可达性（本轮环境无网络，仅本机 clone 实测可达）；PG 门控全量套件（环境无 Docker，未跑）；Playwright 类真实集成未在本轮范围内。
- 本轮只读：未修改 OUTDIR 外任何文件，未 commit、未 push。

## 产物清单（同目录）

- `review_intensive.md` — aggregate 聚合全量 findings（441 条）
- `bundle_unit01.md` … `bundle_unit13.md` — 各 unit 分报告
- `regression.md` — 第三轮 65 条 C/H 四态判定明细
- `validation.md` — 三项真跑记录与新失败归属判定
- `bundle_cross_validation.md` / `bundle_cross_validation_regression.md` — 证伪判定表（A 路 36 条 / B 路 26 条）
- `_meta/progress.log` — unit 划分与全程进度
