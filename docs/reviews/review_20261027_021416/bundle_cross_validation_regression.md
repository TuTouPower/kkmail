# Cross Validation B — Regression STILL PRESENT 条目证伪复核（第二意见）

基线：当前树 HEAD 11bfa52a；复核对象为 regression.md 中判定 STILL PRESENT 的 Critical 5 条与 High 21 条，共 26 条。方法：逐条回读当前树原文与 git 可达性，主动尝试证伪（代码已改、文件已删、已有横幅、sha 不可达、路径不存在等方向）；无直接反证者标 AGREE。CHALLENGED 不删除条目，本表仅为判定记录。

| 编号 | 回归条目 | 判定 | 证据位置 | 一句话理由 |
|---|---|---|---|---|
| CV-B01 | R3-C01 历史凭据检索配方仍发布（040521 安全包） | AGREE | docs/reviews/review_20261021_040521/bundle_v1_security.md:21；git cat-file -t 34c81310… = commit 且在 rev-list --all 中 | 该行仍含完整 sha、路径与 git show 检索表述，且目标 commit 本机实测可达、git show 可读，文件头部的 SUPERSEDED 横幅并未移除配方。 |
| CV-B02 | R3-C02 新包再次发布同一凭据检索配方（052842 安全包） | AGREE | docs/reviews/review_20261022_052842/bundle_v1_security.md:10 | 该行仍完整给出 sha 与 git show 34c81310:outlook_mail_reader.py 命令，文件无任何横幅，配方原样可执行。 |
| CV-B03 | R3-C03 交叉验证文件给出可执行凭据检索指令 | AGREE | docs/reviews/review_20261022_052842/bundle_cross_validation.md:17 | 「直接验证」一行仍写明执行 git show 加完整 sha 与路径，且该 sha 实测可达，指令仍可照做。 |
| CV-B04 | R3-C06 git clone 参数注入（template_source URL） | AGREE | .repo_template/scripts/repo_sync.py:231（resolve_src 内 clone 调用）；同文件 init 处 kind 判定约 :1333 | clone 仍以 value 作为位置参数直接传入，无 --end-of-options、无 scheme/host 白名单、无前导短横拒绝，以短横开头的 URL 仍可被 git 解析为选项。 |
| CV-B05 | R3-C07 自举先覆盖并执行未审模板源代码、无批准门 | AGREE | .repo_template/skills/repo-template-sync/SKILL.md:13 起第 2 步与第 4 步 | 第 2 步仍要求在跑任何子命令前先 cp 覆盖 repo_sync.py、第 4 步即运行 prep 执行之，全程无源路径/HEAD SHA 的显式确认门；文末「随 core 最终审批一起处理」在执行之后，不构成事前门。 |
| CV-B06 | R3-H01 核验标题数与自家表格矛盾 | AGREE | docs/reviews/review_20261021_040521/summary_verification_report.md:9 与 :20-28 | 头部仍称全部 106 项，而表格 V1–FOL 各行本轮逐行复加为 9+36+23+17+2+20+6+22+4=139，矛盾未改。 |
| CV-B07 | R3-H02 机器包总数与同包 meta 矛盾 | AGREE | docs/reviews/review_20261021_011116/bundle_zz_findings_machine.md（本轮正则实数 C4/H36/M49/L24/I11=124）与同目录 review_intensive.md:11（total 118 / M45 / L22） | 两文件数字本轮重新计数仍互相矛盾，均未重生成。 |
| CV-B08 | R3-H03 范围统计虚假且与另一审阅雷同 | AGREE | docs/reviews/review_20261021_034329/bundle.json stats 段（files:177/bundles:42） | 本轮以脚本解析该 JSON 实测顶层 files 数组 168、bundles 数组 40，stats 仍为 177/42，未重生成。 |
| CV-B09 | R3-H05 超时包仍被当作完整呈现 | AGREE | docs/reviews/review_20261021_040521/_meta/_meta.json:19 附近（phase=timeout、deadman_fired=true） | 该目录 review_intensive.md 本轮确认仍不存在，summary_verification_report.md 头部仅有 SUPERSEDED 横幅、未提 timeout。 |
| CV-B10 | R3-H13 已记录决策令历史凭据不轮换、历史不重写 | AGREE | docs/reviews/review_20261021_040521/summary_verification_report.md:38；34c81310 仍在 rev-list --all | 决策行仍写「不执行破坏性 Git 历史重写…保持 Git 树稳定」，全仓未见取代该决策的新记录，凭据 commit 仍可达。 |
| CV-B11 | R3-H15 基线混同与「全部真实」裁决仍在 | AGREE | docs/reviews/review_20261021_040521/summary_verification_report.md:9,22 | 仍称 Git HEAD 基线 c9b67a2 对应 daca631，各行仍为「全部真实存在」，无逐条 open/fixed 状态列。 |
| CV-B12 | R3-H19 检索配方在交叉验证表重述 | AGREE | docs/reviews/review_20261021_040521/bundle_cross_validation.md:21（V1-03 行） | 该行仍含 git show 加完整 sha、路径与四常量长度元组（31/14/36/424），配方要素齐全。 |
| CV-B13 | R3-H20 横幅虚假宣称缺陷已彻底修复闭环（截至 da57df7） | AGREE | docs/reviews/review_20261021_040521/summary_verification_report.md:3 | 横幅原文仍在且未按条目限定例外，而同包多条缺陷经本轮复核仍在（如 CV-B01/B06），宣称与事实不符。 |
| CV-B14 | R3-H21 未认证 /health 泄漏桌面实例 token | AGREE | src/mail_core/api/app.py:183-186 | health() 仍无鉴权依赖（app 级中间件仅安全头与 trace），仍把原始 KKMAIL_INSTANCE_TOKEN 写进 X-Instance-Token 响应头。 |
| CV-B15 | R3-H23 共享根因重复计数进核验总数 | AGREE | docs/reviews/review_20261021_040521/summary_verification_report.md:22（V3 行） | V3 行仍自注「部分与 V2 共享根因」却仍全额计 23 项，全包无去重后的根因总数。 |
| CV-B16 | R3-H29 归档架构文档自呈为现行约束性规格 | AGREE | docs/archive/legacy_architecture/mail-core-architecture.md:7 与文末「本文件即为实现与验收的依据」 | 正文仍称「已定稿，供实现」，全文件 grep 无归档/被取代横幅；其位于 archive 目录一事第三轮已知悉且不改变正文自呈问题，不构成反证。 |
| CV-B17 | R3-H30 两份已提交决策记录就同一凭据直接矛盾、无取代标注 | AGREE | docs/reviews/review_20261022_052842/adoption_decision.md A53 段（约 :441-448，主张 filter-repo 重写加吊销）与 040521 summary :38（不重写） | 本轮双向 grep 两文件均无对对方的引用或取代标注，矛盾原样并存。 |
| CV-B18 | R3-H31 052842 整包把过时结论当现行呈现、无状态横幅 | AGREE | docs/reviews/review_20261022_052842/review_intensive.md:7（Verdict BLOCK、Critical=6） | 本轮对该包全目录 grep SUPERSEDED 与历史/过时类标注均为零命中，整包无状态横幅。 |
| CV-B19 | R3-H39 公开历史根提交含默认 LOGIN_PASSWORD 字面量 | AGREE | git cat-file -t e945533c… = commit 且在 rev-list --all 中；该 commit 的 web_outlook_app.py:27 有 LOGIN_PASSWORD 字面量赋值 | 当前树该文件虽已不存在，但历史 commit 本轮实测仍可达、字面量仍可读，与第三轮判定口径一致。 |
| CV-B20 | R3-H42 个人数据提交检索配方（手机号邮箱与个人账号） | AGREE | docs/reviews/review_20261022_052842/bundle_v1_security.md:11；第三轮原文 docs/reviews/review_20261025_020805/bundle_docs_reviews.md:15 | 该行完整 sha、App.tsx:18-21 与 demoAccounts 定位元组仍在；目标 sha 在本 clone 缺失一事第三轮原文已自带 caveat 并明确危害在定位符公开本身，故 sha 本地不可达不构成反证，证伪失败。 |
| CV-B21 | R3-H45 一次 /task-run 即批准整队列执行到 commit、无逐 task 确认 | AGREE | .repo_template/skills/task-run/SKILL.md:13 | 仍写「触发本 skill 即批准队列成员执行到各自执行 commit…不逐 task 询问 commit」，无参数时仍默认全部 backlog 与 active，全文无队列回显确认步骤。 |
| CV-B22 | R3-H46 契约测试超时逃逸 cmd_apply 且不回滚 | AGREE | .repo_template/scripts/repo_sync.py:1295-1303（_run_tests）与 :1593-1607（cmd_apply 测试调用段）、:1807-1814（main 异常处理） | _run_tests 仍未捕获 TimeoutExpired，cmd_apply 中测试调用仍在回滚 try 之外，main 仅捕获 SyncError/OSError，TimeoutExpired 仍以裸 traceback 逃逸且不触发 _rollback_changes。 |
| CV-B23 | R3-H47 prep 直接覆盖现行工具链、无回滚清理与失败恢复 | AGREE | .repo_template/scripts/repo_sync.py:1657-1689（cmd_prep 函数体） | 函数体仍直接 sync_dir_oneway、sync_skill、repair_symlinks，全程无 _rollback_changes 与 _cleanup_rollback 调用；底层 helper 内的 _stage_rollback 仅备而不用，不构成恢复路径。 |
| CV-B24 | R3-H48 批量迁移回滚被非 IdScanError 失败绕过 | AGREE | .repo_template/scripts/pending.py:206 与 :225 附近（per-item 与外层 except） | 两层仍只 except IdScanError，read_bytes、atomic_write_text 等抛出的 OSError 仍可绕过已迁移条目的回滚循环，留下部分 git mv 状态。 |
| CV-B25 | R3-H54 看板服务器无认证、无 Host/Origin 校验 | AGREE | .repo_template/scripts/repo_task/view_server.py:199-213（_Handler 与 _send_bytes）与 :290 附近（--allow-non-loopback） | do_GET 仍无 token、无 Host/Origin 校验，_send_bytes 仍只发 Content-Type/Length/Cache-Control，无 CSP/nosniff 头，非 loopback 放行路径仍在。 |
| CV-B26 | R3-H55 start 把主仓全部 .env 软链进每个 task worktree | AGREE | .repo_template/scripts/repo_task/worktrees.py:12,26（link_local_env） | 仍以 REPO_ROOT.rglob(".env") 全量收集并逐个 symlink，无显式 allowlist、无源解析出仓拒绝；新增的噪声目录与目标 worktree 自身跳过不改变全量链接性质。 |

## 统计

CHALLENGED 0 条、AGREE 26 条。本轮对每条均尝试了证伪方向（横幅是否已加、sha 是否可达、文件/代码是否已改、原报告是否已自带 caveat），其中 CV-B20 的「sha 本地不可达」与 CV-B16 的「文件已在 archive 目录」两条候选反证经回读第三轮原文后确认均已被原判定预先涵盖，不成立；其余各条证据位置本轮逐一实测与回归判定一致。
