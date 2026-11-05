# Task review t075（reviewer_focus: 测试）

- task：`t075_backup_export_permission_boundary`
- spec：`docs/tasks/t075_backup_export_permission_boundary/task.md`
- diff_anchor：`18f0f5e3e1f5d3f5a3437d7d1cc401bf5b0ffd48`
- target：`git -C '/Users/karson/kar/code/kkmail_t075' diff 18f0f5e3e1f5d3f5a3437d7d1cc401bf5b0ffd48`
- round：1
- reviewed_at：2026-11-05T06:40:08+08:00

reviewed_scope: 6d0fc80fca787346

## Findings

### t075_test_f001 - AC-002 备份身份、只读卷与 blob 权限不变均无自动化验证

- 严重度：important
- 锚点：AC-002
- 位置：`tests/mail_core/test_backup_package.py:21`（`test_create_backup_package_writes_manifest`）；diff 中无 Docker 备份测试
- 问题：diff 只新增/修改进程内 `create_backup_package` / `restore_backup_package` 单测；没有任何测试以应用 UID 启动备份服务、只读挂载 blob 卷、断言 `status=ok` / `verified=true`，也没有断言备份前后源 blob 的 `st_uid` / `st_mode` 不变。`progress.md` 的“手工隔离 Docker 验证”是实施侧自述，不能作为 AC 证据。AC-002 在 `task.md` 已打勾且可测试性声明为“可自动测试”，实际无自动化覆盖。
- 建议：新增隔离 Docker 集成测试：构造真实 `0600` blob volume，以镜像应用 UID 运行 backup 服务（blobs 只读），断言密封包 verify 成功，并比较备份前后 blob 的 owner/mode。

### t075_test_f002 - AC-006 无隔离 Docker 备份/导出/恢复自动化测试

- 严重度：important
- 锚点：AC-006
- 位置：`tests/scripts/test_deploy_mail_core_r4adopt_p51.py:97`（仅 YAML 断言）；diff 无新集成测试文件
- 问题：AC-006 要求在隔离 Docker 环境完成备份→宿主导出→恢复，并验证无关 UID 读取失败。diff 中没有任何测试启动容器、执行 `docker cp` 导出或切换 UID 读取；`test_a13_compose_backup_has_no_host_bind_and_blob_is_read_only` 只解析 compose YAML。`progress.md` 的手工演练不是可重复证据。
- 建议：新增黑盒/集成测试，使用临时 volume 与临时 staging，实际执行 backup 容器、宿主导出、无关 UID 读取失败断言、恢复后应用读写与再次备份。

### t075_test_f003 - AC-003 A13 仍以脚本文本匹配替代部署行为验证

- 严重度：critical
- 锚点：AC-003
- 位置：`tests/scripts/test_deploy_mail_core_r4adopt_p51.py:56-116`
- 问题：所有 A13 测试仍读取 `scripts/deploy_mail_core.sh` 文本做子串/`text.index` 顺序断言（如 `:64` `"--user" not in run_line`、`:75-86` `cp_idx < verify_idx < publish_idx`）。这直接违反 spec 测试策略“将 A13 从脚本文本匹配宿主 UID 改为验证备份身份能读应用数据、宿主导出目录 0700、导出包归执行者、校验后原子发布；补充失败路径断言”。文本断言无法证明脚本实际导出成功、归属为执行者、staging 为 0700、发布原子性，也无法发现运行时错误；失败清理路径完全没有测试。该 AC 看似覆盖但实际未验证。
- 建议：把 A13 改成执行隔离脚本/受控 Docker 的集成测试；至少覆盖成功路径的导出归属、0700、verify 后发布，以及 backup/export/verify 失败时不发布半成品。

### t075_test_f004 - AC-001 轮换父目录断言恒真，且无关 UID 读取未验证

- 严重度：important
- 锚点：AC-001
- 位置：`tests/mail_core/test_a318_rewrap_file_hardening.py:26`
- 问题：`_make_old_blob(tmp_path)` 把 blob 直接放在 `tmp_path`，pytest `tmp_path` 本身即 `0700`，所以新增的 `assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700` 在删除 `rotate.py:183` 的 `path.parent.chmod(0o700)` 后仍会通过；它没有验证轮换把 0755 父目录收紧。该测试也没有 umask 022/077 参数化，且没有任何测试以非应用 UID 尝试读取/遍历。AC-001 的“轮换后父目录 0700”和“非应用 UID 无法读取/遍历”因此无有效证据。
- 建议：在轮换测试中先把父目录 chmod 0755 并在 umask 022/077 下运行；增加真实无关 UID 读取/遍历失败断言（可在 Docker 或可降权环境）。

### t075_test_f005 - AC-004 owner 与恢复后应用层读取未断言

- 严重度：minor
- 锚点：AC-004
- 位置：`tests/mail_core/test_backup_package.py:1364-1412`、`:1415-1480`
- 问题：恢复测试只断言 `stat.S_IMODE`，从未断言 `st_uid` / `st_gid`，也未比较两次 umask 运行的 owner；`test_restored_blob_store_can_be_written_and_backed_up_again` 用 `read_bytes()` 读取恢复出的明文探针文件，随后只对新写入的 blob 调 `BlobStore.get`，没有证明应用能通过 BlobStore 解密读取恢复出的真实 blob。AC-004 的 owner 一致性与“应用可读取”仍是弱覆盖。
- 建议：断言 owner 与目标应用 UID 一致；用 BlobStore 生成的加密 blob 做恢复 fixture，并通过 `BlobStore.get` 读取恢复结果。

### t075_test_f006 - AC-005 启动路径不递归与归一化后回归未测

- 严重度：minor
- 锚点：AC-005
- 位置：`tests/mail_core/test_blob_permissions.py:18-56`
- 问题：只测了 `normalize_private_permissions` 的收紧、symlink 与 foreign owner；没有测试 API/Worker 启动路径不调用递归权限修补，也没有在归一化后重跑 AC-002/AC-004 回归；`python -m mail_core.blobs.permissions` 的 CLI 入口与 `scripts/normalize_mail_core_permissions.py` 也未被执行。
- 建议：补启动路径无递归 chmod 的断言（或代码级入口测试）、归一化后的备份/恢复回归，以及 CLI 参数/退出码测试。

### t075_test_f007 - 文档宣称的自动化覆盖不存在

- 严重度：minor
- 锚点：AC-002、AC-006（文档证据）
- 位置：`docs/blueprint/testing.md:213`
- 问题：该行声称已覆盖“以无关 UID 读取失败、备份容器以应用 UID 读取真实 0600 blob”，但 diff 中没有对应自动化测试；后续维护者会误以为这些边界已有回归保护。
- 建议：删除未落地的覆盖声明，或在新增集成测试后再写入。

## 结论

- 前轮 finding 复核：Round 1，无前轮 finding。
- 改测方向复核：A13 的 `--user` 断言反转由 spec 明确要求（移除宿主 UID），属规格驱动；`test_a13_backup_package_is_verified_after_write` 删除 `MANIFEST` 文本断言，但其验证意图由 `verify_backup_package` 调用覆盖，属合法删除。未发现为迁就实现而改预期。
- 本轮新发现：7 条（1 critical、3 important、3 minor）。
- 未进表的提示：契约区 AC-006 从 `[deploy]` 改为隔离 Docker 的 drift 与注入上下文“用户同日补充验收要求 / 生产部署合并后验证”一致，未按未经确认的 AC 变更处理。已跑 touched 文件 `91 passed`；未执行真实 Docker 集成，不能替代缺失的 AC-002/003/006 验证。
- 总体判断：FAIL：AC-001/002/003/006 打勾缺乏有效测试支撑。
- 系统性 follow-up：建议新建 `docker_backup_identity_integration_test`（隔离 Docker 备份/导出/恢复身份与权限集成测试）；当前 `.repo_template/scripts/task.py list` 无等价 task。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。put/streaming 有 umask 022/077 模式断言，但轮换父目录断言在已是 0700 的 `tmp_path` 上恒真，且无 owner/无关 UID 读取验证。
- AC-002：TICK-VOID，re_verified。无任何测试以应用 UID + 只读卷运行备份或断言 blob owner/mode 未变；仅有进程内 create/verify 单测。
- AC-003：TICK-VOID，re_verified。A13 仍只读脚本文本做子串/顺序断言，未执行导出、归属、0700、原子发布或失败清理。
- AC-004：TICK-VALID，re_verified。umask 022/077 恢复模式与再次写入/备份有真实单测；owner 与真实加密 blob 的应用层读取未断言（见 f005）。
- AC-005：TICK-VALID，re_verified。归一化函数对 0755/0644 树、symlink、foreign owner 有真实单测；启动路径不递归与归一化后 AC-002/004 回归未测（见 f006）。
- AC-006：TICK-VOID，re_verified。无隔离 Docker 备份→导出→恢复自动化测试；仅 progress.md 手工声明。

coverage = 2 / 6

verdict: FAIL

## Round 2 (2026-11-05T07:40:20+08:00)

- round：2
- reviewed_at：2026-11-05T07:40:20+08:00

reviewed_scope: 200d44df201316c0

### 本轮新增 Findings

#### t075_test_f008 - AC-003 部署脚本自身的失败清理与编排仍未被行为测试执行

- 严重度：minor
- 锚点：AC-003（失败时不留下可被 rollback 引用的半成品）
- 位置：`scripts/deploy_mail_core.sh:71-84`；`tests/scripts/test_deploy_mail_core_r4adopt_p51.py:56-90`
- 问题：`export_container_package` 的失败不发布已有真实单测（`tests/mail_core/test_backup_export.py:65-87`），但部署脚本的 `cleanup_deploy_backup`（删除 staging；未发布时删除 `backup_dir`）没有被任何测试执行或断言。A13 仍只对脚本做文本匹配；`docker compose run backup` 在导出前失败时，AC-003 的失败清理只能靠人工阅读脚本。另外 staging 的 `0700` 只由脚本文本断言和测试里预置 `mkdir(mode=0o700)` 保证，`export_container_package` 对 staging 的 `make_private_dir` 没有在预置为 0755 的 staging 上验证。
- 建议：用隔离的 docker/python stub 执行脚本备份段，断言 backup/export 失败后 `backup_dir` 与 `staging_dir` 被清理且不存在 `package`；增加预置 0755 staging 的导出测试断言导出后为 0700；或把清理逻辑提取为可单测函数。

#### t075_test_f009 - AC-005 启动路径与归一化后 AC-002 回归仍缺直接验证

- 严重度：minor
- 锚点：AC-005
- 位置：`tests/mail_core/test_blob_store.py:127-141`；`tests/mail_core/test_backup_package.py:1466-1486`
- 问题：`test_blob_store_does_not_recursively_repair_existing_shards` 只以 `BlobStore(root)` 构造器代理“API/Worker 启动路径”，没有真正运行 API lifespan 或 Worker 启动；“归一化后 AC-002 继续通过”只在进程内 `create_backup_package` 复跑，未在归一化后重跑应用 UID 的 Docker 备份。`scripts/normalize_mail_core_permissions.py` 入口也未被执行（只测了 `main()`）。
- 建议：补 API/Worker 启动入口在存量 0755/0644 shard 下不递归修改的断言；在隔离 Docker 归一化后复跑 AC-002 备份；执行一次脚本入口。

#### t075_test_f010 - AC-001 的属主与“不可遍历”缺少直接断言

- 严重度：minor
- 锚点：AC-001
- 位置：`tests/mail_core/test_blob_store.py:106-124`；`tests/mail_core/test_backup_container_permissions.py:102-104,203-217`
- 问题：新写入/轮换测试只断言 `S_IMODE`，未断言 `st_uid`/`st_gid` 为应用 UID；Docker 无关 UID fixture 故意把 `/b/aa`、`/b/aa/bb` 设为 0755，只验证 0600 文件读取失败，没有用 0700 目录验证“无关 UID 无法遍历”。模式断言已结构性覆盖，故不阻断。
- 建议：在 put/rewrap 测试断言 owner；增加无关 UID 对 0700 目录 `ls`/`test -x` 失败的断言。

## 结论

- 前轮 finding 复核（Round 2）：
    - f001（AC-002，important）：已消除。`tests/mail_core/test_backup_container_permissions.py:137-217` 用真实备份镜像（`Dockerfile.mail-core-backup` 的 `USER 10001:999`）在 `:ro` volume 上运行 `run_backup`，断言退出码 0 与 `"verified": true`，并在备份前后断言 blob 为 `600 10001 999`；本轮实跑 1 passed。
    - f002（AC-006，important）：已消除。同一 Docker 测试真实启动容器、执行 `docker cp` 导出并切换 UID 12345 读取失败；恢复后应用读写/再次备份按可测试性声明由 `tests/mail_core/test_backup_package.py:1418-1487` 覆盖。
    - f003（AC-003，critical）：已消除核心问题。导出 0700/0600、执行者归属、verify 后原子发布与失败不发布由 `tests/mail_core/test_backup_export.py:38-105` 的真实逻辑验证；Docker 测试用真实 `docker cp` 导出并 verify。A13 仍对脚本做文本匹配，但只验证接线（不强制宿主 UID）；脚本级失败清理的残余见 f008（minor）。
    - f004（AC-001，important）：已消除。`tests/mail_core/test_a318_rewrap_file_hardening.py:22-36` 先把父目录改为 0755，再在 umask 022/077 下断言轮换后 0700，原恒真断言不再恒真；无关 UID 读取失败由 Docker 测试覆盖（遍历未直接断言，见 f010）。
    - f005（AC-004，minor）：已消除。`tests/mail_core/test_backup_package.py:1415` 断言 `st_uid`/`st_gid`；`:1430-1472` 用 `BlobStore` 生成真实加密 blob，恢复后通过 `BlobStore.get` 解密读取。
    - f006（AC-005，minor）：大部分消除。新增 `test_normalize_cli_reports_summary`、`test_blob_store_does_not_recursively_repair_existing_shards` 与归一化后再次读写/备份；启动入口与归一化后 AC-002 的残余见 f009（minor）。
    - f007（文档，minor）：已消除。`docs/blueprint/testing.md:213` 声明的 Docker/无关 UID/导出覆盖现已对应真实测试文件。
- 改测方向复核：无“迁就实现”的改测。A13 的 `--user` 断言反转与 `test_a13_backup_package_is_verified_after_write` 的整体替换均由 spec 要求（移除宿主 UID 锁定、改为行为验证）；`test_rewrap_replaced_file_has_0600_permissions` 为参数化扩展。旧测试的预期未被改成新实现的输出。
- 本轮新发现：3 条（0 critical、0 important、3 minor）。
- 未进表的提示：
    - 契约区 drift（AC-006 去掉 `[deploy]`、AC-005 措辞调整）与注入上下文“用户同日补充验收要求 / 生产部署合并后验证”一致，按已确认变更处理，不判 blocking。
    - `tests/mail_core/test_backup_container_permissions.py:44-47` 在 docker CLI/daemon 不可用时 `pytest.skip`。本轮本机 Docker 可用，测试实跑通过；发布门禁需确保 Docker 可用，否则 AC-002/006 的自动化证据会静默缺失。已调查，属环境前置而非掩盖失败，不作出 finding。
    - `tests/mail_core/test_backup_package.py:1468` 在读恢复 blob 前先调用 `normalize_private_permissions`；独立 restore 测试已断言 0600/0700，但该读路径本身不能单独证明恢复产物可读，属测试结构可优化点。
    - 实测：`KKMAIL_TEST_MODE=unit .venv/bin/pytest -q` 跑 touched 文件 99 passed；`test_backup_container_permissions.py` 1 passed；`-k "backup or blob or rewrap or permission"` 273 passed、15 skipped（缺 DB/`/dev/shm` 环境）。
- 总体判断：PASS。前轮 critical/important 已被真实 Docker 与模块行为测试消除，仅余 minor 覆盖补强。
- 系统性 follow-up：Round 1 建议的 Docker 身份集成测试已在本 task 落地；剩余脚本级失败清理与启动路径断言建议 `deploy_backup_failure_cleanup_test`（非阻断），当前 task 列表无等价项。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_put_uses_private_file_and_directory_modes`（umask 022/077 × put/streaming）断言 0600/0700；`test_rewrap_replaced_file_has_0600_permissions` 先把父目录改 0755 再断言轮换后 0700；Docker 测试以 UID 12345 读取 0600 blob 失败（owner/遍历残余见 f010）。
- AC-002：TICK-VALID，re_verified。`test_backup_container_permissions` 用真实备份镜像在 `:ro` volume 上运行 `run_backup`，断言退出 0、`verified: true`，且备份前后 `_blob_stat` 均为 `600 10001 999`；本轮实跑 1 passed。
- AC-003：TICK-VALID，re_verified。`test_backup_export` 验证导出到 0700 staging、归属当前宿主用户、校验后 `os.replace` 原子发布、失败不发布；Docker 测试用真实 `docker cp` 导出并 verify；A13 文本断言仅保留脚本接线（无宿主 UID 强制），脚本级失败清理残余见 f008。
- AC-004：TICK-VALID，re_verified。`test_restore_blobs_have_private_modes_regardless_of_umask` 在 umask 022/077 下断言目录 0700/文件 0600 且 owner 为恢复进程，源 0644 未继承；`test_restored_blob_store_can_be_written_and_backed_up_again` 用 `BlobStore` 解密读取恢复 blob、写入并再次备份 verify。
- AC-005：TICK-VALID，re_verified。`test_blob_permissions` 覆盖 0755/0644 树归一化、symlink 拒绝、异属主拒绝、CLI 汇总；`test_blob_store_does_not_recursively_repair_existing_shards` 断言构造器不递归修补存量 shard；`test_restored_blob_store...` 归一化后再次读出/写入/备份（启动入口与 AC-002 回归残余见 f009）。
- AC-006：TICK-VALID，re_verified。`test_backup_container_permissions` 在隔离 Docker 中完成应用 UID 备份 0600 blob、宿主导出到 0700、无关 UID 读取失败；恢复后应用读写/再次备份由 `test_restored_blob_store...` 按可测试性声明覆盖。

coverage = 6 / 6

verdict: PASS

## Round 4 (2026-11-05T08:02:00+08:00)

- round：4
- reviewed_at：2026-11-05T08:02:00+08:00

reviewed_scope: 02939cc3e474b5bf

### 本轮新增 Findings

#### t075_test_f011 - AC-005 owner 归一化仍由 mock 调用撑起，未验证真实 chown 结果

- 严重度：important
- 锚点：AC-005；范围「存量权限归一化：统一到应用 UID + `0600`/`0700`」
- 位置：`tests/mail_core/test_blob_permissions.py:94-113`（`:100-104` 用 lambda 替换 `os.chown`，`:111` 只断言 `assert calls`）
- 问题：唯一覆盖 `--target-uid/--target-gid` 的测试把 `os.chown` 整个 mock 掉，只断言调用列表非空；且 `target_uid=os.getuid()`（`:106-108`）与 fixture 现属主相同，`_require_owner` 在 mock 未改变归属时也必然通过。这样无法发现：只 chown 根或部分条目、传入错误 uid/gid（target 与现属主相同时交换 uid/gid 也通过）、以及文档能力集不足导致真实 chown 失败（Round 3 code f010 正是该缺陷，该单测未能暴露）。reviewer 用隔离 Docker 以 root + `CHOWN/FOWNER/DAC_OVERRIDE` 对 `0:0` 的 `0700` 树执行文档命令，实测可迁移到 `10001:999` 且保持 `0600`/`0700`；说明实现当前可用，但交付的自动化证据仍是 mock 调用，不能作为 AC-005 owner 归一化的回归保护。可测试性声明把该路径列为可自动测试，未兑现。
- 建议：新增真实 Docker/特权集成测试：构造异属主 `0700`/`0600` fixture，执行 `python -m mail_core.blobs.permissions --target-uid ... --target-gid ...`，断言每个目录/文件最终 `st_uid/st_gid` 与目标一致；最低限度也要断言 `calls` 中每个路径的 uid/gid 均等于目标，并把 target 换成与现属主不同的值，才能覆盖真实迁移。

#### t075_test_f012 - AC-002/AC-006 未断言备份进程的实际 UID

- 严重度：minor
- 锚点：AC-002、AC-006「备份服务以应用 UID 运行」
- 位置：`tests/mail_core/test_backup_container_permissions.py:168-184`；`Dockerfile.mail-core-backup:22`；`docker-compose.mail-core.yml:65-92`
- 问题：Docker 用例直接以镜像默认身份运行 `run_backup`，没有断言容器内 `id -u` 或包文件属主；测试成功只证明「某个身份能读 0600 blob」。若 compose service 增加 `user: "0:0"` 或在运行参数中改成 root，A13 的 `--user` 文本断言（`tests/scripts/test_deploy_mail_core_r4adopt_p51.py:62-72`）不覆盖 compose 的 `user:` 字段，Docker 用例仍会通过（root 可读 0600），AC 的「以应用 UID 运行」缺少行为证据。
- 建议：在容器内断言 `id -u == 10001`（或写入后 stat `/backup/package` 属主为 `10001:999`），并把 compose 解析后的 `user`/镜像 `USER` 作为显式前置。

#### t075_test_f013 - AC-001 遍历拒绝用 `test -r` 断言，未验证 execute 位

- 严重度：minor
- 锚点：AC-001「非应用 UID 无法读取文件或遍历目录」
- 位置：`tests/mail_core/test_backup_container_permissions.py:203-217`
- 问题：`sh -c 'test -r /b/aa'` 只验证读权限；`0711`（others 可遍历但不可读）目录会让该断言继续成立，却违反「不可遍历」。fixture 手工把 `/b/aa` 设为 `0700`（`:103`），当前结果正确，但断言没有对准 AC 的 execute 语义；目录 mode 的回归另有 put/rewrap 单测覆盖，故不阻断。
- 建议：同时断言 `test -x /b/aa` 失败（或 `test ! -r` 且 `test ! -x`），或直接尝试 `ls /b/aa` 并断言失败。

#### t075_test_f014 - AC-004「不继承归档 UID」未被真实构造验证

- 严重度：minor
- 锚点：AC-004「不继承归档中的 UID/mode」
- 位置：`tests/mail_core/test_backup_package.py:1365-1415`、`:1490-1511`
- 问题：恢复用例的源 blob 与归档由当前进程创建，归档 uid == 进程 uid，因此 `:1415` 的 owner 相等断言无法区分「显式创建为进程 UID」与「继承归档 UID」。`:1490-1511` 的 tar 成员默认 uid/gid 为 0，但只断言 mode，未断言 owner；如果恢复实现开始沿用 tar 的 uid（在 root 下会成功），这两个用例都不会失败。mode 的 `0644`→`0600` 已真实覆盖，故只标 minor。
- 建议：在 `test_restore_staging...` 或新的恢复测试中显式断言 `x.blob`/中间目录的 `st_uid/st_gid` 为进程 UID（且不等于 tar 的 `0:0`），直接证明不继承归档 UID。

### 前轮 finding 复核

- t075_test_f001（important，AC-002）：已消除。`tests/mail_core/test_backup_container_permissions.py:137-184` 用真实备份镜像（`USER 10001:999`）在 `:ro` volume 上运行 `run_backup`，断言退出 0、`"verified": true`，备份前后 `_blob_stat` 均为 `600 10001 999`；本轮重跑 1 passed。
- t075_test_f002（important，AC-006）：已消除。同一 Docker 用例执行真实 `docker cp` 导出（`export_container_package` 默认实现）、verify、无关 UID `12345` 读取失败；恢复后应用读写/再次备份按可测试性声明由 `tests/mail_core/test_backup_package.py:1418-1487` 覆盖。
- t075_test_f003（critical，AC-003）：已消除核心问题。`tests/mail_core/test_backup_export.py:38-108` 行为验证 staging `0755`→`0700`、导出归属当前执行者、`0600`/`0700`、verify 后 `os.replace` 原子发布、失败不发布与拒绝覆盖；Docker 用例用真实 `docker cp` 导出并 verify。A13 仍对脚本做接线文本断言，但已不再锁定宿主 UID；脚本级 trap 的残余见 f008。
- t075_test_f004（important，AC-001）：已消除。`tests/mail_core/test_a318_rewrap_file_hardening.py:21-35` 先把父目录改为 `0755`，再在 umask `022`/`077` 下断言轮换后 `0700`，原恒真断言不再成立；无关 UID 读取失败由 Docker 用例覆盖（遍历断言精确性见 f013）。
- t075_test_f005（minor，AC-004）：已消除。`tests/mail_core/test_backup_package.py:1415` 断言 `st_uid`/`st_gid`；`:1430-1487` 用 `BlobStore` 生成真实加密 blob，恢复后通过 `BlobStore.get` 解密读取、写入并再次备份。归档 UID 继承未被真实构造，另见 f014。
- t075_test_f006（minor，AC-005）：已消除。`test_normalize_cli_reports_summary`、`test_blob_store_does_not_recursively_repair_existing_shards`、归一化后再次读写/备份均存在并通过；CLI 入口与归一化后 AC-002 回归已补。启动入口语义残余归入 f009。
- t075_test_f007（minor，文档）：已消除。`docs/blueprint/testing.md:213` 现引用 `test_backup_container_permissions.py`（真实 Docker）、`test_backup_export.py`、`test_blob_permissions.py`、`test_blob_store.py`、`test_backup_package.py`，本轮实际运行通过。
- t075_test_f008（minor，AC-003 失败清理）：部分消除，同意其非阻断撤回定性。staging 预置 `0755` 的归一化已由 `tests/mail_core/test_backup_export.py:43-57` 覆盖；部署脚本 `cleanup_deploy_backup` 的 trap 仍未被执行或断言，只保留为可选 shell 级测试增强。
- t075_test_f009（minor，AC-005）：部分消除。Docker 用例已增加「维护命令归一化后再次备份并 verify」（`tests/mail_core/test_backup_container_permissions.py:219-251`），归一化后 AC-002 回归已覆盖；「API/Worker 启动路径」仍只由 `BlobStore(root)` 构造器代理，未运行真实 lifespan/Worker 启动，维持 minor。
- t075_test_f010（minor，AC-001）：修不彻底。Docker fixture 已改为 `0700` 目录并增加无关 UID 读取/遍历拒绝；但 `test_put_uses_private_file_and_directory_modes`（`tests/mail_core/test_blob_store.py:106-124`）与轮换用例仍只断言 mode，未断言 `st_uid`/`st_gid`。owner 由创建进程隐含，故维持 minor；遍历断言用了 `test -r`，精确性另见 f013。

### 本轮结论

- 前轮 finding 复核：f001、f002、f003、f004、f005、f006、f007 已消除；f008 部分消除（同意非阻断撤回）；f009、f010 部分消除，均维持 minor。
- 改测方向复核：无。A13 的 `--user` 断言反转与旧 `test_a13_backup_package_is_verified_after_write` 替换均由 spec「移除宿主 UID 锁定、改为行为验证」驱动；`test_rewrap...` 增加 umask 参数与 `0755` 前置属强化，不是让断言迁就实现。旧测试预期未被改成新实现的输出。
- 本轮新发现：4 条（1 important、3 minor）。
- 未进表的提示：
    - Docker 用例在 CLI/daemon 不可用时 `pytest.skip`（`tests/mail_core/test_backup_container_permissions.py:44-47`）。本轮本机 Docker 可用，实跑 1 passed；发布门禁需保证 Docker 可用，否则 AC-002/006 的自动化证据会静默缺失。已调查，属环境前置而非掩盖失败，不作出 finding。
    - 本轮实测：`KKMAIL_TEST_MODE=unit` 跑 touched 单测 104 passed；`tests/mail_core/test_backup_container_permissions.py` 1 passed。另以隔离 Docker 手动执行 `--target-uid 10001 --target-gid 999` 对 `0:0` 的 `0700` 树归一化，结果 owner `10001:999`、mode `0700`/`0600`，支持 f011 中对实现可用性的判断，但未落为仓库内自动化测试。
    - 完整生产部署按契约上下文留待合并后按运维步骤验证，本轮不执行。
- 总体判断：FAIL。前轮 critical/important 已由真实 Docker 与行为测试消除，但 AC-005 的 owner 归一化仍由 mock 调用冒充覆盖（f011，important），且目录遍历/归档 UID 继承/备份运行身份存在 minor 断言缺口。
- 系统性 follow-up：无（f011 的真实 owner 迁移测试应在本 task 内补；脚本级失败清理只是可选 shell 测试增强）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_put_uses_private_file_and_directory_modes`（put/put_streaming × umask 022/077）与 `test_rewrap_replaced_file_has_0600_permissions`（父目录 0755→0700 × umask 022/077）断言文件 0600/目录 0700；Docker 用例以 UID 12345 `cat` 0600 blob 失败（owner 未直接断言、遍历用 `test -r`，见 f010/f013）。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker、镜像 `USER 10001:999`、blob 卷 `:ro`）1 passed：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`；进程实际 UID 未断言，见 f012。
- AC-003：TICK-VALID，re_verified。`test_backup_export` 4 条通过：staging 0755→0700、导出目录/文件 0700/0600 且归属执行者、verify 后 `os.replace` 原子发布、校验失败/已有包时不发布；Docker 用例用真实 `docker cp` 导出并 verify。部署脚本失败 trap 仍无行为测试（f008 残余）。
- AC-004：TICK-VALID，re_verified。重跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077，目录链 0700、文件 0600、owner 为当前 UID）、`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`、`test_restored_blob_store_can_be_written_and_backed_up_again` 通过；归档 UID 非继承未被真实构造，见 f014。
- AC-005：TICK-VOID，re_verified。mode 归一化、symlink/异属主/不可读子树拒绝、CLI 汇总与「构造器不递归修补」均有真实测试并通过；但显式 `--target-uid/--target-gid` 的 owner 迁移只有 monkeypatch `os.chown` + `assert calls`（`tests/mail_core/test_blob_permissions.py:94-113`），无法验证真实归属或部分 chown，见 f011。reviewer 的临时 Docker 验证通过不改变该打勾缺少仓库内自动化证据的事实。
- AC-006：TICK-VALID，re_verified。Docker 用例完成应用镜像身份备份真实 0600 blob、真实 `docker cp` 宿主导出到 0700 staging、导出包归属/权限、无关 UID 读取失败、归一化后再次备份 verify；恢复后应用读取/写入/再次备份由 `test_backup_package.py` 覆盖并通过（运行身份未直接断言，见 f012）。

coverage = 6 / 6

verdict: FAIL

## Round 5 (2026-11-05T08:38:55+08:00)

- round：5
- reviewed_at：2026-11-05T08:38:55+08:00

reviewed_scope: d6d70a1ad0ea951b

### 本轮新增 Findings

#### t075_test_f015 - AC-005 owner 迁移测试只断言文件归属，目录 owner 未验证

- 严重度：minor
- 锚点：AC-005（存量 blob 与备份目录归一化为应用 UID）
- 位置：`tests/mail_core/test_backup_container_permissions.py:273-334`（`:320-332` 只 stat `/b/aa/x.blob`）
- 问题：真实 Docker 特权迁移用例已把 `0:0` 的 `0700/0600` 树 chown 到 `10001:999` 并断言文件为 `600 10001 999`，f011 的假绿核心已消除；但它只检查文件，没有 stat `/b`、`/b/aa` 的 owner，也没有在迁移后的树上以应用 UID 再执行遍历/备份。若实现只 chown 文件、漏掉目录（或漏掉根目录），该用例仍会通过；此时应用 UID 会因目录 owner 仍是 root 而无法遍历，AC-005 的“blob 与备份目录归一化为应用 UID”只有文件证据。
- 建议：在同一用例追加 `/b`、`/b/aa` 的 `%a %u %g` 断言，并在迁移后以 `10001:999` 执行一次只读遍历或备份。

#### t075_test_f016 - AC-004 恢复目录 owner 未被断言

- 严重度：minor
- 锚点：AC-004（以目标应用 UID 显式创建 blob 目录 `0700`、文件 `0600`）
- 位置：`tests/mail_core/test_backup_package.py:1408-1415`、`:1511-1515`
- 问题：两个恢复用例只断言文件 `st_uid/st_gid` 与目录 mode，没有断言 `target_blobs`、`aa`、`bb` 目录的 owner。`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members` 只证明 tar 的 `0:0` 未传给文件；实现若把目录 owner 改成显式异属主或继承，现有断言不会失败。
- 建议：对恢复根与各级 shard 目录追加 `(st_uid, st_gid) == (os.getuid(), os.getgid())` 断言。

### 前轮 finding 复核

- f001（important，AC-002）：已消除。`tests/mail_core/test_backup_container_permissions.py:137-186` 用真实备份镜像（`USER 10001:999`）在 `:ro` volume 上运行 `run_backup`，`:146-147` 断言容器 `id -u` 为 10001，`:184-186` 断言退出 0、`"verified": true` 且备份前后 `_blob_stat` 均为 `600 10001 999`；本轮实跑 2 passed。
- f002（important，AC-006）：已消除。同一 Docker 用例执行真实 `docker cp` 导出（`:192-203`）、verify，并以 UID 12345 `cat` blob 失败（`:256-270`）；恢复后应用读写/再次备份按可测试性声明由 `tests/mail_core/test_backup_package.py:1418-1487` 覆盖。
- f003（critical，AC-003）：已消除核心问题。`tests/mail_core/test_backup_export.py:38-136` 行为验证 staging 0755→0700、导出目录/文件 0700/0600 且归属执行者、verify 后 `os.replace` 原子发布、校验失败/已有包不发布、CLI 失败信息；Docker 用例用真实 `docker cp` 导出并 verify。A13 仅保留脚本接线文本断言；脚本级 trap 残余见 f008。
- f004（important，AC-001）：已消除。`tests/mail_core/test_a318_rewrap_file_hardening.py:21-36` 先把父目录改为 `0755`，在 umask `022`/`077` 下断言轮换后父目录 `0700`、文件 `0600` 且 owner 为当前 UID，原恒真断言不再成立；无关 UID 读取/遍历由 Docker 用例覆盖。
- f005（minor，AC-004）：已消除。`tests/mail_core/test_backup_package.py:1415` 断言 `st_uid`/`st_gid`；`:1430-1487` 用 `BlobStore` 生成真实加密 blob，恢复后通过 `BlobStore.get` 解密读取、写入并再次备份 verify。目录 owner 残余见 f016。
- f006（minor，AC-005）：已消除。`test_normalize_cli_reports_summary`、`test_blob_store_does_not_recursively_repair_existing_shards`、归一化后再次读写/备份均存在并通过；启动入口语义残余归入 f009。
- f007（minor，文档）：已消除。`docs/blueprint/testing.md:213` 现引用真实测试文件（`test_backup_container_permissions.py`、`test_backup_export.py`、`test_blob_permissions.py`、`test_blob_store.py`、`test_backup_package.py`），本轮实际运行通过。
- f008（minor，AC-003 失败清理）：仍存在。部署脚本 `cleanup_deploy_backup`（`scripts/deploy_mail_core.sh:71-84`、`:105-108`）仍无任何测试执行或断言，A13 只做文本匹配；`export_container_package` 在 docker cp 失败时的清理也未断言。维持 minor，非阻断。
- f009（minor，AC-005 启动路径）：仍存在。`test_blob_store_does_not_recursively_repair_existing_shards`（`tests/mail_core/test_blob_store.py:127-141`）仍只以 `BlobStore(root)` 构造器代理 API/Worker 启动，未运行真实 lifespan/Worker 启动。维持 minor。
- f010（minor，AC-001 owner/遍历）：部分消除。遍历拒绝已改为 `-r` 与 `-x` 双断言（`test_backup_container_permissions.py:205-220`），轮换用例已断言 owner；但 `test_put_uses_private_file_and_directory_modes`（`tests/mail_core/test_blob_store.py:106-124`）仍只断言 mode，未断言 `st_uid/st_gid`。维持 minor。
- f011（important，AC-005 owner 归一化 mock）：blocker 已消除。新增 `test_owner_normalization_migrates_foreign_private_tree`（`tests/mail_core/test_backup_container_permissions.py:273-334`）以 root + `CHOWN/FOWNER/DAC_OVERRIDE` 对 `0:0` 的 `0700/0600` 树执行真实 `python3 -m mail_core.blobs.permissions --target-uid 10001 --target-gid 999`，断言结果文件 `600 10001 999`；本轮实跑通过，不再是 monkeypatch 假绿。旧 mock 用例 `tests/mail_core/test_blob_permissions.py:94-113` 仍在，但已非唯一证据；目录 owner 残余记为 f015。
- f012（minor，AC-002/006 运行身份）：已消除。Docker 用例新增 `id -u == 10001` 断言（`test_backup_container_permissions.py:146-147`），且 A13 断言部署行无 `--user`（`tests/scripts/test_deploy_mail_core_r4adopt_p51.py:62-73`）。compose 解析后的 `user:` 字段仍无显式断言，属可选增强。
- f013（minor，AC-001 遍历）：已消除。`test_backup_container_permissions.py:205-220` 对 UID 12345 同时断言 `test -r /b/aa` 与 `test -x /b/aa` 失败。
- f014（minor，AC-004 归档 UID 继承）：已消除。`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members` 构造 `uid=0/gid=0` 的 tar 成员并断言恢复后 blob `st_uid/st_gid` 为当前进程；目录 owner 残余见 f016。

### 本轮结论

- 前轮 finding 复核：f011 的 important blocker 已由真实 Docker 特权 owner 迁移测试消除；f001、f002、f003、f004、f005、f006、f007、f012、f013、f014 已消除；f008、f009、f010 维持 minor；f015、f016 为本轮新增 minor。
- 改测方向复核：无“迁就实现”的改测。A13 的 `--user` 断言反转、`test_a13_backup_package_is_verified_after_write` 替换、compose 无宿主 bind 断言均由 spec“移除宿主 UID 锁定、改为行为验证”驱动；`test_rewrap...` 增加 umask 参数与 `0755` 前置属强化断言，不是弱化。旧测试预期未被改成新实现的输出。
- 本轮新发现：2 条（0 critical、0 important、2 minor）。
- 未进表的提示：
    - `tests/mail_core/test_backup_container_permissions.py:44-47` 在 docker CLI/daemon 不可用时 `pytest.skip`。本轮本机 Docker 可用，实跑 2 passed；发布门禁须确保 Docker 可用，否则 AC-002/006 证据会静默缺失。已调查，属环境前置而非掩盖失败，不作出 finding（与前轮一致）。
    - `test_export_cli_reports_docker_cp_failure_without_traceback` monkeypatch `_docker_cp`，未走真实的 `CalledProcessError → BackupExportError` 转换；两条路径输出相同，属可选增强。
    - 完整生产部署按契约上下文留待合并后按运维步骤验证，本轮不执行。
    - 本轮实测：touched 单测 `104 passed`（6 个文件）；`tests/mail_core/test_backup_container_permissions.py` `2 passed`（真实 Docker，含 owner 迁移）。
- 总体判断：PASS。前轮 critical/important 已消除，仅余 minor 覆盖补强。
- 系统性 follow-up：无。f015/f016 的直接断言应在本 task 内补齐；脚本 trap 与启动入口的残余已由 f008/f009 跟踪，不需要新增 task。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_put_uses_private_file_and_directory_modes`（put/streaming × umask 022/077）断言 0600/0700；`test_rewrap_replaced_file_has_0600_permissions`（父目录 0755→0700 × umask 022/077）断言 0600/0700 与 owner；Docker 用例以 UID 12345 断言 `test -r`/`test -x /b/aa` 均失败、`cat` blob 失败。put owner 未断言见 f010。
- AC-002：TICK-VALID，re_verified。`test_backup_container_permissions` 真实 Docker：镜像 `USER 10001:999`，`id -u == 10001`，blob 卷 `:ro`，断言退出 0、`verified: true`，备份前后 stat 均为 `600 10001 999`；本轮 2 passed。
- AC-003：TICK-VALID，re_verified。`test_backup_export` 验证 staging 0755→0700、导出目录/文件 0700/0600 且归属当前执行者、verify 后 `os.replace` 原子发布、校验失败/已有包时不发布、CLI 失败信息；Docker 用例用真实 `docker cp` 导出并 verify。脚本 trap 无行为测试见 f008（minor）。
- AC-004：TICK-VALID，re_verified。`test_restore_blobs_have_private_modes_regardless_of_umask`（umask 022/077）断言目录链 0700、文件 0600 与文件 owner；`test_restore_staging...` 断言 tar `0:0` 未传给恢复文件且目录 0700；`test_restored_blob_store_can_be_written_and_backed_up_again` 用 `BlobStore.get` 读取、写入并再次备份 verify。目录 owner 见 f016。
- AC-005：TICK-VALID，re_verified。`test_blob_permissions` 覆盖 mode 归一化、symlink/异属主/不可读子树拒绝、CLI 汇总；新增真实 Docker `test_owner_normalization_migrates_foreign_private_tree` 以 root + 最小 caps 把 `0:0` 树迁移到 `10001:999` 并断言文件 `600 10001 999`；`test_blob_store_does_not_recursively_repair_existing_shards` 断言构造器不递归修补；Docker 用例归一化后再次备份 verify。目录 owner 见 f015，启动入口见 f009。
- AC-006：TICK-VALID，re_verified。Docker 用例完成应用镜像身份（`id -u == 10001`）备份真实 0600 blob、真实 `docker cp` 宿主导出到 0700 staging、导出包 0700/0600、无关 UID 读取/遍历失败、归一化后再次备份 verify；恢复后应用读取/写入/再次备份由 `test_backup_package.py` 覆盖并通过。

coverage = 6 / 6

verdict: PASS

## Round 6 (2026-11-05T08:44:47+08:00)

- round：6
- reviewed_at：2026-11-05T08:44:47+08:00

reviewed_scope: 5a13ad32a8a09133

### 本轮新增 Findings

无。本轮相对 Round 5 的唯一交付变化是 `docs/guides/deployment.md` 经 md_format 在「部署备份与权限边界」各段之间插入空行（`docs/guides/deployment.md:26-52`），测试文件、测试断言与生产代码相对 anchor 均未变化。重新扫描恒真断言、删/反转 expect、`.skip`/`.only`、mock 误用、阈值掩盖等危险模式，无新增命中；`tests/mail_core/test_backup_container_permissions.py:45-47` 的 `pytest.skip` 仍只是 Docker CLI/daemon 不可用时的环境前置，本轮 Docker 可用且测试实跑通过，不构成掩盖失败。文档空行不影响任何 AC 的测试证据。

### 前轮 finding 复核

- f001（important，AC-002）：仍为已消除。`tests/mail_core/test_backup_container_permissions.py:137-186` 真实 Docker 备份用例未变，本轮重跑 2 passed。
- f002（important，AC-006）：仍为已消除。同一 Docker 用例的 `docker cp` 导出、verify 与无关 UID 读取失败断言未变，本轮重跑通过。
- f003（critical，AC-003）：仍为已消除核心问题。`tests/mail_core/test_backup_export.py` 4 条行为测试未变，本轮重跑通过；A13 文本接线断言仍不锁宿主 UID。
- f004（important，AC-001）：仍为已消除。`tests/mail_core/test_a318_rewrap_file_hardening.py:21-36` 的 0755 前置与 umask 参数化未变，本轮重跑通过。
- f005（minor，AC-004）：仍为已消除。恢复用例的文件 owner 与 `BlobStore.get` 解密读取断言未变，本轮 `test_backup_package.py` 63 passed。
- f006（minor，AC-005）：仍为已消除。归一化、CLI 汇总与构造器不递归修补测试未变，本轮重跑通过。
- f007（minor，文档）：仍为已消除。`docs/blueprint/testing.md:213` 引用的测试文件均真实存在并通过。
- f011（important，AC-005）：仍为已消除。真实 Docker owner 迁移用例 `test_owner_normalization_migrates_foreign_private_tree` 未变，本轮重跑通过；不再是 mock 假绿。
- f012（minor，AC-002/006）：仍为已消除。容器 `id -u == 10001` 断言与 A13 无 `--user` 断言未变，本轮通过。
- f013（minor，AC-001）：仍为已消除。UID 12345 对 `/b/aa` 的 `test -r`/`test -x` 双失败断言未变。
- f014（minor，AC-004）：仍为已消除。tar `uid=0/gid=0` 成员恢复后的文件 owner 断言未变。
- f008（minor，AC-003 脚本级失败清理）：仍存在。`scripts/deploy_mail_core.sh:71-84` 的 `cleanup_deploy_backup` 与 `export_container_package` 的 docker cp 失败清理仍只由脚本文本/人工阅读保证，无测试执行；本轮无相关改动，维持 minor。
- f009（minor，AC-005 启动路径）：仍存在。`tests/mail_core/test_blob_store.py:127-141` 仍以 `BlobStore(root)` 构造器代理 API/Worker 启动，未运行真实 lifespan/Worker；维持 minor。
- f010（minor，AC-001 put owner）：仍存在。`tests/mail_core/test_blob_store.py:106-124` 仍只断言 mode，未断言 `st_uid`/`st_gid`；轮换用例已断言 owner，维持 minor。
- f015（minor，AC-005 目录 owner）：仍存在。`tests/mail_core/test_backup_container_permissions.py:330` 仍只 stat `/b/aa/x.blob`，未断言 `/b`、`/b/aa` 目录 owner，也未在迁移后以应用 UID 再遍历；维持 minor。
- f016（minor，AC-004 恢复目录 owner）：仍存在。`tests/mail_core/test_backup_package.py:1415`、`:1515` 仍只断言文件 owner，恢复根与各级 shard 目录只断言 mode；维持 minor。

### 本轮结论

- 前轮 finding 复核：f001～f007、f011～f014 仍为已消除；f008、f009、f010、f015、f016 均维持 minor，无新增或复发 blocker。以当前 diff 与重跑结果为准，未采信处置表自述。
- 改测方向复核：无。本轮无测试改动，不存在「迁就实现」的改测。
- 本轮新发现：0 条（0 critical、0 important、0 minor）。
- 未进表的提示：
    - 契约区 drift（AC-006 去掉 `[deploy]`、新增「不在 task 分支内执行生产部署」）与注入上下文一致，按已确认变更处理，不判 blocking。
    - `docs/guides/deployment.md` 仅经 md_format 插入空行，未改变部署命令或权限契约内容；本轮 AC 复验结论沿用同一交付内容的测试证据。
    - Docker 集成用例在 CLI/daemon 不可用时 `pytest.skip`。本轮本机 Docker 可用，`tests/mail_core/test_backup_container_permissions.py` 实跑 2 passed；发布门禁仍须确保 Docker 可用，否则 AC-002/006 证据会静默缺失（环境前置，非掩盖失败，不作出 finding）。
    - 完整生产部署按契约上下文留待合并后按运维步骤验证，本轮不执行。
    - 本轮实测：`KKMAIL_TEST_MODE=unit` 重跑 6 个 touched 测试文件合计 `106 passed`（41 + 63 单测 + 2 Docker）。
- 总体判断：PASS。AC-001～AC-006 的打勾均由当前交付内容中的真实测试支撑；仅余前轮已记录的 minor 覆盖补强。
- 系统性 follow-up：无。f008/f009/f010/f015/f016 的直接断言应在本 task 内补齐，不需要新增 task。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_put_uses_private_file_and_directory_modes`（put/streaming × umask 022/077）断言文件 0600、目录 0700；`test_rewrap_replaced_file_has_0600_permissions`（父目录先 0755 × umask 022/077）断言 0600/0700 与 owner；Docker 用例以 UID 12345 断言 `test -r`/`test -x /b/aa` 与 `cat` blob 均失败。put 的 owner 未断言见 f010。
- AC-002：TICK-VALID，re_verified。`test_backup_container_permissions` 真实 Docker：镜像 `USER 10001:999`、`id -u == 10001`、blob 卷 `:ro`，断言退出 0、`"verified": true`，备份前后 `stat` 均为 `600 10001 999`；本轮 2 passed。
- AC-003：TICK-VALID，re_verified。`test_backup_export` 验证 staging 0755→0700、导出目录/文件 0700/0600 且归属当前执行者、verify 后 `os.replace` 原子发布、校验失败/已有包不发布、CLI 失败信息；Docker 用例用真实 `docker cp` 导出并 verify；脚本级 trap 无行为测试见 f008（minor）。
- AC-004：TICK-VALID，re_verified。`test_restore_blobs_have_private_modes_regardless_of_umask`（umask 022/077）断言目录链 0700、文件 0600 与文件 owner；`test_restore_staging...` 构造 tar `0:0` 成员并断言恢复文件 owner 为当前进程、目录 0700；`test_restored_blob_store_can_be_written_and_backed_up_again` 用 `BlobStore.get` 读取、写入并再次备份 verify。目录 owner 未断言见 f016。
- AC-005：TICK-VALID，re_verified。`test_blob_permissions` 覆盖 mode 归一化、symlink/异属主/不可读子树拒绝、CLI 汇总；真实 Docker `test_owner_normalization_migrates_foreign_private_tree` 以 root + 最小 caps 把 `0:0` 树迁移到 `10001:999` 并断言文件 `600 10001 999`；`test_blob_store_does_not_recursively_repair_existing_shards` 断言构造器不递归修补；Docker 用例归一化后再次备份 verify。目录 owner 见 f015、启动入口见 f009。
- AC-006：TICK-VALID，re_verified。Docker 用例完成应用镜像身份（`id -u == 10001`）备份真实 0600 blob、真实 `docker cp` 宿主导出到 0700 staging、导出包 0700/0600、无关 UID 读取/遍历失败、归一化后再次备份 verify；恢复后应用读取/写入/再次备份由 `test_backup_package.py` 覆盖并通过。

coverage = 6 / 6

verdict: PASS
