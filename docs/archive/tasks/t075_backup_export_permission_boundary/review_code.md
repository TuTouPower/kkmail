# Task review t075（reviewer_focus: 代码）

- task：`t075_backup_export_permission_boundary`
- spec：`docs/tasks/t075_backup_export_permission_boundary/task.md`
- diff_anchor：`18f0f5e3e1f5d3f5a3437d7d1cc401bf5b0ffd48`
- target：`git -C '/Users/karson/kar/code/kkmail_t075' diff 18f0f5e3e1f5d3f5a3437d7d1cc401bf5b0ffd48`
- round：1
- reviewed_at：2026-11-05T06:50:41+08:00

reviewed_scope: 6d0fc80fca787346

## Findings

### t075_code_f001 - 维护命令只收紧 mode，不改变 uid/gid，无法修复异属主存量

- 严重度：minor
- 锚点：AC-005；范围「存量权限归一化：将现有 blob/备份目录统一到应用 UID + `0600`/`0700`」
- 位置：`src/mail_core/blobs/permissions.py:26-32`、`:45-47`、`:106-108`；`scripts/normalize_mail_core_permissions.py:26`
- 问题：`normalize_private_permissions()` 对每个条目要求 `st_uid/st_gid` 已等于调用进程（或 `owner_uid/owner_gid` 参数，且该参数只用于断言，不是目标值），不相等就抛 `PermissionNormalizationError`；全仓 `src/` 与 `scripts/` 没有任何 `chown`/`fchown` 调用，CLI 也没有目标 owner 选项。因此对「owner 漂移」的存量目录（如旧版 root 写入的 volume），唯一文档化维护路径只会失败或原样保留，无法把 owner 归一化回应用 UID。AC 的 `0600/0700` 部分已实现，`应用 UID` 部分只被「要求」而非「归一化」。当前事故数据本身已是 `10001:999`，故不阻断，但 spec 与实现语义存在缺口。
- 建议：二选一并写清：其一，为维护命令增加显式目标 owner（需 root/容器内特权）并在镜像内文档化 chown 步骤；其二，把 spec/注释统一改为「只归一化 mode，异属主一律拒绝，owner 需另行修复」。

### t075_code_f002 - `os.walk` 未处理遍历错误，根目录不可读时静默返回成功

- 严重度：minor
- 锚点：AC-005（维护命令必须可信地完成归一化）
- 位置：`src/mail_core/blobs/permissions.py:59-61`
- 问题：`os.walk(path_root, topdown=True, followlinks=False)` 未传 `onerror`，扫描失败会被默认忽略。复现：构造 `root` 权限 `0000`、内含 `aa/x.blob`（`0755`/`0644`）后调用 `normalize_private_permissions(root)`，命令返回成功且 `{"files": 0, ...}`，根被改成 `0700`，但子项仍为 `0755`/`0644`。维护命令因此可能向运维报告「归一化完成」而实际未处理子树；根目录初始不可读/不可执行时尤其明显（子目录在递归前已被 chmod，通常不受影响）。
- 建议：给 `os.walk` 传 `onerror` 并在异常时抛 `PermissionNormalizationError`；或在遍历前先收紧根目录再扫描，避免把扫描失败伪装成空树。

### t075_code_f003 - 恢复时中间目录按 umask 创建，归档缺少目录成员时不是 0700

- 严重度：minor
- 锚点：AC-004（同一归档在 umask `022`/`077` 下恢复得到相同 owner/mode；blob 目录 `0700`）
- 位置：`src/mail_core/backup/package.py:1576`、`:1580`、`:1646`、`:1663`；`src/mail_core/backup/package.py:495-504`
- 问题：`_make_private_dir()` 用 `mkdir(parents=True, exist_ok=True)` 后只 chmod 叶子路径，父级由 `mkdir(parents=True)` 按进程 umask 创建。`_validate_blob_members()` 允许 `blobs.tar` 只含文件成员（无 `blobs/aa/`、`blobs/aa/bb/` 目录条目）。复现：用只含 `blobs/aa/bb/x.blob` 的合法 tar 走 `_extract_blobs_to_staging` → `_publish_staged_blobs`，umask `022` 下 `target/aa` 为 `0755`、`target/aa/bb` 为 `0700`；umask `077` 下 `target/aa` 变为 `0700`，即恢复结果的目录 mode 仍随 umask 漂移。本项目的备份生产者 `tar.add(root, arcname="blobs")` 会写入目录条目，故真实包不触发；但恢复器接受的归档范围比生产者更宽。
- 建议：创建目录时按 `rel` 的每一级调用 `_make_private_dir(..., strict=True)`（并校验每级位于 target root 内），或 `mkdir` 后向上收紧本次新建的祖先目录，保证与归档是否含目录成员无关。

### t075_code_f004 - 文档给出的宿主归一化命令在无项目依赖的 python3 下直接失败

- 严重度：minor
- 锚点：AC-005（显式维护路径可用）
- 位置：`docs/guides/deployment.md:38`；`scripts/normalize_mail_core_permissions.py:26`；`src/mail_core/blobs/__init__.py:3`
- 问题：文档写 `python3 scripts/normalize_mail_core_permissions.py <dir>`，但导入 `mail_core.blobs.permissions` 会先执行 `mail_core/blobs/__init__.py`，进而导入 `archive.py`/SQLAlchemy 等服务端依赖。实测系统 `python3 scripts/normalize_mail_core_permissions.py --help` 报 `ModuleNotFoundError: No module named 'sqlalchemy'`；用仓库 `.venv/bin/python` 才能运行。该命令的目标是宿主备份目录，宿主未必有项目依赖，按文档操作会失败。
- 建议：文档统一改用部署所用的解释器（如 `.venv/bin/python scripts/normalize_mail_core_permissions.py`，与 `deploy_mail_core.sh` 的 `python_bin` 选择一致），或让脚本直接从文件加载 `permissions.py` 以避免触发包 `__init__` 的重依赖。

### t075_code_f005 - `testing.md` 宣称的自动化覆盖在列出的测试文件中不存在

- 严重度：minor
- 锚点：文档与实现一致性（AC-002、AC-006 的验证证据）
- 位置：`docs/blueprint/testing.md:213`
- 问题：该行声称已覆盖「以无关 UID 读取失败、备份容器以应用 UID 读取真实 0600 blob」，并列出 `test_blob_permissions.py`、`test_blob_store.py`、`test_backup_package.py`、`test_deploy_mail_core_r4adopt_p51.py` 作为入口。实际这些文件没有任何 Docker/真实 UID 用例（`grep "docker|10001|12345"` 仅命中 `owner_uid=os.getuid()+1` 的异属主拒绝用例），相关行为只在实施方的手工演练中验证。后续维护者会误以为该边界已有回归保护。
- 建议：在补齐隔离 Docker 集成测试前，删去未落地的「无关 UID 读取失败」「应用 UID 读取真实 0600 blob」覆盖声明，或注明仅由手工演练覆盖。

### t075_code_f006 - 权限收紧逻辑在 4 处重复且错误处理语义不一致

- 严重度：minor
- 锚点：代码质量（DRY / 错误处理一致性）
- 位置：`src/mail_core/blobs/store.py:21-32`；`src/mail_core/blobs/rotate.py:180-185`；`src/mail_core/backup/package.py:495-504`；`src/mail_core/blobs/permissions.py:63-88`；`scripts/deploy_mail_core.sh:123-152`
- 问题：`mkdir + chmod 0700` 与「拒绝 symlink / 拒绝非当前 owner / 文件 `0600`」这套逻辑被重复实现 5 次。语义已经分叉：`store.py` 与 `rotate.py` 吞掉 `chmod` 的 `OSError`（权限收紧失败不报错），`package.py` 的 `strict=True` 抛错，`deploy.sh` 内联版本在异属主时 `SystemExit`，`permissions.py` 抛自定义异常。后续只需修正其中一处（如 f002 的 `os.walk` 错误处理），另外几处不会同步，存在安全不变量的修复遗漏风险。
- 建议：抽一个共享的私有权限 helper（可放在不依赖服务端重包的模块），按调用点显式传入 `strict`/`abort-on-foreign-owner` 策略；deploy 脚本直接复用同一实现而不是内联重写。

## 结论

- 前轮 finding 复核：Round 1，无前轮 finding。
- 本轮新发现：6 条（0 critical、0 important、6 minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2634 行（本 task 净增约 19 行）；`tests/mail_core/test_backup_package.py` 1480 行（净增 121 行）。按「文件过大标准」仅结论段提示，不生成 finding。
    - 圈复杂度：`normalize_private_permissions` 手算约 CC 12（≥10 提示、\<15 不出 finding），建议后续拆分目录/文件两个分支。
    - 契约 drift：AC-006 由 `[deploy]` 真实部署改为隔离 Docker，并新增「不在 task 分支内执行生产部署」非范围项；与注入上下文「用户同日补充验收要求 / 生产部署合并后验证」一致，未按未经确认的 AC 变更处理。
    - 范围外观察：Linux 上 `docker cp` 的导出归属仍未实测（上下文已列为合并后部署验证风险）；AC-002/003/006 缺少隔离 Docker 自动化测试属测试轴，见同 task 的测试 review，本报告不重复。
- 总体判断：实现层无未解决的 critical/important，6 条 minor；代码轴 PASS（测试轴证据缺口由独立测试 review 判定）。
- 系统性 follow-up：建议新建 `docker_backup_identity_integration_test`（隔离 Docker 下备份→宿主导出→恢复的真实身份与权限集成测试）；只读查询 `.repo_template/scripts/task.py list` 未发现等价 task。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立以 umask 022/077 跑 `put`/`put_streaming`/`rewrap_blob_file`，文件实测 `0600`、分片目录 `0700`；Docker 中应用 UID 10001 可读真实 `0600` blob，无关 UID 12345 读取被拒。
- AC-002：TICK-VALID，trust_prior。独立核实镜像 `USER 10001:999`、blob 卷 `:ro`、`/backup` 为 10001 所有的 `0700`，且源码不修改源 blob 权限；密封包 `status=ok`/`verified=true` 依赖实施方隔离 Docker 演练，本轮未重跑真实 DB 备份。
- AC-003：TICK-VALID，re_verified。脚本无 `--user`、备份产物写容器私有 `/backup`；`docker cp` 导出到新建 `0700` staging，校验 symlink/归属/mode 与 `verify_backup_package` 通过后才 `mv` 原子发布，EXIT trap 在未发布时清理；`bash -n` 与 A13 用例通过。
- AC-004：TICK-VALID，re_verified。跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077）与恢复后写入/再次备份用例通过；`os.open(...,0o600)`+`fchmod`、目录 `_make_private_dir(0700)`，不应用归档 UID/mode（中间目录边界见 f003）。
- AC-005：TICK-VALID，re_verified。venv 下对 `0755`/`0644` 树执行维护命令得到 `0700`/`0600`；API/Worker 启动路径无递归 chmod（仅 `BlobStore.__init__` 非递归收紧根目录）；owner 语义与遍历错误见 f001/f002。
- AC-006：TICK-VALID，trust_prior。独立验证应用 UID/只读挂载/真实 `0600` 可读/无关 UID 拒绝，以及部署脚本导出→校验→发布路径；完整备份-导出-恢复 drill 依赖实施方隔离 Docker 演练，本轮未重跑。

coverage = 4 / 6

建议合并前人工抽查 trust_prior 项

verdict: PASS

## Round 2 (2026-11-05T07:40:37+08:00)

reviewed_scope: 200d44df201316c0

### t075_code_f007 - AC-005 在实施期被收窄为「只归一化 mode」，与范围条目冲突且无用户确认

- 严重度：important
- 锚点：契约区「范围 / 存量权限归一化」（`docs/tasks/t075_backup_export_permission_boundary/task.md:17`）仍要求「将现有 blob/备份目录统一到应用 UID + `0600`/`0700`」；当前 AC-005（`task.md:43`）却改为「mode 可归一化；条目属主须已为应用 UID，异属主拒绝」。行为差距：维护命令遇到异属主目录只会报错退出，全仓不存在把 owner 归一化回应用 UID 的可达路径。
- 位置：`docs/tasks/t075_backup_export_permission_boundary/task.md:17` vs `:43`；`src/mail_core/blobs/permissions.py:47-51`（docstring 明言 "normalizes mode, not ownership"）、`:28-34`（异属主直接抛 `PermissionNormalizationError`）；`docs/guides/deployment.md:38`、`docs/guides/upgrade.md:20`；`progress.md` 处置表把 f001 的 fix_ref 写成 `task.md AC-005`。
- 问题：Round 1 f001 指出的「应用 UID 部分只被要求而非归一化」没有通过实现解决，而是通过修改验收标准把要求删掉：diff 显示 AC-005 相对 `18f0f5e3` 从「归一化为应用 UID + `0600`/`0700`」改为「只归一化 mode」。`grep -rn "chown" src scripts` 无任何命中，`permissions.py:28-34` 对 `st_uid/st_gid` 不符直接拒绝，因此范围条目承诺的 owner 归一化没有实现。注入上下文只确认了「用户同日补充」的备份/恢复/导出/umask 要求与「生产部署合并后验证」，没有确认 AC-005 缩小范围；按 prompt「契约区 drift 警告」，未经确认的 AC 变更按 blocking 处理。范围与 AC 目前互相矛盾，后续维护者无法判断哪个是契约。
- 建议：二选一并留下证据：其一，取得用户对 AC-005 收窄的明确确认，并同步修改 `task.md:17` 范围条目（删除「统一到应用 UID」），避免契约自相矛盾；其二，保留原范围，新增受控 owner 归一化路径（容器内以 root 显式 `chown` 的维护入口或文档化的宿主 `chown` 步骤）并补相应测试。仅改 AC 而无用户确认不能作为 f001 的关闭依据。

### t075_code_f008 - `make_private_chain` 用 resolve 后的 root 对比未 resolve 的 path，含符号链接祖先的恢复根直接失败

- 严重度：minor
- 锚点：行为缺陷（恢复路径可用性）；影响 AC-004 在带符号链接祖先的 blob 根下的表现
- 位置：`src/mail_core/blobs/private_fs.py:37-42`；调用点 `src/mail_core/backup/package.py:1572`、`:1576`、`:1642`、`:1659`
- 问题：`root_resolved = root.resolve()`，但 `current = path` 从未 resolve；只要 root 路径含符号链接祖先（macOS `/tmp`、`/var`，或相对路径 root），`root_resolved not in current.parents` 恒真并抛 `PrivatePathError: path is outside private root`。实测：`root=Path("/tmp/kk-t075-root")`（`resolve()` 为 `/private/tmp/...`）调用 `make_private_chain(root/"aa"/"bb", root)` 直接抛错；`_extract_blobs_to_staging` 在第一个成员就会中断。另外 `path.mkdir(parents=True)` 位于越界校验之前（`:38`），越界 path 会先创建目录再报错。注：anchor 已有的 `_publish_rename`（`package.py:1618-1621`）有同样的 resolved/unresolved 比较缺陷，故本 task 未造成净行为回退，但新 helper 把该缺陷扩散到提取阶段与 4 个调用点。
- 建议：先 `path_resolved = path.resolve()`，再用 `path_resolved` 与 `root.resolve()` 做 `==` / `.parents` 比较（或 `os.path.commonpath`）；把 `mkdir` 移到越界校验之后；为 `make_private_chain` 增加「root 含符号链接祖先」与「path 越界」单测。

### t075_code_f009 - 导出 CLI 未捕获 `docker cp` 的 `CalledProcessError`，失败时抛 traceback

- 严重度：minor
- 锚点：错误处理 / 可观测（CLI 统一错误出口）
- 位置：`src/mail_core/backup/export.py:32-33`、`:180`
- 问题：`_docker_cp()` 用 `subprocess.run(..., check=True)`，失败抛 `subprocess.CalledProcessError`，而 `main()` 只捕获 `(BackupExportError, PrivatePathError, OSError)`。复现：`python -m mail_core.backup.export --container missing ...` 输出 Python traceback，而不是设计好的 `backup_export_failed: ...` 一行错误。部署脚本因 `set -e` 仍会中断并触发清理，但运维看到的是内部栈而不是可读原因。
- 建议：在 `_docker_cp` 内捕获 `CalledProcessError` 并转成 `BackupExportError`（保留 returncode/stderr 摘要），或在 `main()` 的 except 中加入 `subprocess.CalledProcessError`。

### 前轮 finding 复核

- t075_code_f001：修不彻底。实现未变（`permissions.py:28-34` 仍拒绝异属主、全仓无 `chown`），只是把 AC-005 改成 mode-only 并同步文档（`deployment.md:38`、`upgrade.md:20`）。该收窄未获用户确认且与 `task.md:17` 范围冲突，见本轮 f007；f001 不能按「已修」关闭。
- t075_code_f002：已消除。`permissions.py:69-71` 的 `os.walk(..., onerror=_walk_error)` 在扫描失败时抛 `PermissionNormalizationError`（`:62-65`）；`tests/mail_core/test_blob_permissions.py:61-71` 覆盖不可读子树，本轮重跑通过。
- t075_code_f003：已消除。`package.py:1572/1576/1642/1659` 改用 `make_private_chain` 逐级收紧；`tests/mail_core/test_backup_package.py` 的 `test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members` 覆盖「tar 无目录成员」且 umask 022/077 均通过。新 helper 的路径比较缺陷另见 f008。
- t075_code_f004：修不彻底（minor）。`docs/guides/deployment.md:38` 与 `docs/guides/upgrade.md:20` 已改 `.venv/bin/python scripts/normalize_mail_core_permissions.py`，但 `scripts/normalize_mail_core_permissions.py:11` 的脚本 docstring 仍写 `python3 scripts/normalize_mail_core_permissions.py .scratch/...`；实测系统 `python3 scripts/normalize_mail_core_permissions.py --help` 仍报 `ModuleNotFoundError: No module named 'sqlalchemy'`，按脚本自带用法操作仍失败。
- t075_code_f005：已消除。`docs/blueprint/testing.md:213` 现在引用 `test_backup_container_permissions.py`（真实 Docker）、`test_backup_export.py`、`test_blob_permissions.py`、`test_blob_store.py`、`test_backup_package.py`；这些文件存在且本轮实际运行通过，不再把未落地的手工演练写成自动化覆盖。
- t075_code_f006：已消除。新增 `src/mail_core/blobs/private_fs.py` 共享 helper，`store.py`/`rotate.py`/`package.py`/`permissions.py` 复用；部署脚本内联的 `docker cp`/校验逻辑移入 `src/mail_core/backup/export.py` 并由行为测试覆盖。`package.py:496-501` 保留的 `_make_private_dir` 只是带 `BackupCryptoError` 语义的薄包装，未再出现语义分叉。
- Round 1 未报告其他 finding，无撤回项。

### 本轮结论

- 本轮新发现：3 条（1 important、2 minor）。
- 前轮遗留：f001（由 f007 代表，仍阻断）、f004（minor，脚本自带用法未改）。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2630 行（≥800 实现阈值，净增 +5）；`tests/mail_core/test_backup_package.py` 1511 行（≥1200 测试阈值，净增 +152）。按规则只在结论段提示，不进 finding 表。
    - 圈复杂度：`_secure_exported_tree`（`export.py:49-104`）手算约 CC 11，`normalize_private_permissions`（`permissions.py:37-118`）约 CC 14；均 ≥10 但 \<15，仅提示。
    - 契约 drift：AC-006 由 `[deploy]` 真实部署改为隔离 Docker、新增「不在 task 分支内执行生产部署」非范围项，与注入上下文的用户同日补充要求一致，不作为 finding；AC-005 的收窄见 f007。
    - 范围外观察：Linux 上 `docker cp` 导出归属仍未在本轮实测（上下文已列为合并后部署验证风险项）；生产部署完整流程按 AC-006/上下文本轮不执行。
- 总体判断：实现层主体已按新布局落地且测试可复现通过，但 AC-005 通过改动验收标准而非实现来消除 f001，契约区范围与 AC 自相矛盾且无用户确认记录，按 drift 规则构成 important 阻断；另有 2 条 minor。
- 系统性 follow-up：无（Round 1 建议的隔离 Docker 备份/导出一致性测试已由 `tests/mail_core/test_backup_container_permissions.py` 落地）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。KKMAIL_TEST_MODE=unit 重跑 `test_put_uses_private_file_and_directory_modes`（put/put_streaming × umask 022/077）与 `test_rewrap_replaced_file_has_0600_permissions`（父目录 0755 → 0700）通过；真实 Docker 用例确认无关 UID 12345 读取 `0600` blob 失败。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker，应用 UID `10001:999`、blob 卷 `:ro`）通过：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`。
- AC-003：TICK-VALID，re_verified。核对 `scripts/deploy_mail_core.sh:95-108`：无 `--user`、容器私有 `/backup`、宿主导出到新建 `0700` staging、校验归属/权限与 `verify_backup_package` 后 `os.replace` 原子发布、失败清理；重跑 `test_backup_export.py`（归属/0700/0600、校验失败不发布、拒绝覆盖）与 A13 接线用例通过。完整生产部署按上下文留待合并后。
- AC-004：TICK-VALID，re_verified。重跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077）、`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`、`test_restored_blob_store_can_be_written_and_backed_up_again` 通过：目录链 `0700`、文件 `0600`、owner 为当前 UID，未应用归档 UID/mode（符号链接祖先边界见 f008）。
- AC-005：TICK-VALID，re_verified。重跑 `test_blob_permissions.py`（mode 归一化、symlink/异属主/不可读子树拒绝、CLI JSON 输出）与 `test_blob_store_does_not_recursively_repair_existing_shards` 通过；归一化后恢复、再写入、再次备份用例通过。AC 文本本身已实现；其收窄未获用户确认且与范围冲突，见 f007。
- AC-006：TICK-VALID，re_verified。本轮重跑真实 Docker 集成用例：应用 UID 备份真实 `0600` blob、宿主导出到 `0700` staging、导出包归属与权限断言、无关 UID 读取失败；恢复后应用读取/写入与再次备份由 `test_backup_package.py` 覆盖并通过。

coverage = 6 / 6

verdict: FAIL

## Round 3 (2026-11-05T07:52:30+08:00)

reviewed_scope: 09f49fb0986373cc

### t075_code_f010 - AC-005 文档给出的 owner 归一化命令在目标场景必然失败（能力集不足 + 先 chown 后 chmod）

- 严重度：important
- 锚点：AC-005「存量 blob 与备份目录可通过显式维护命令归一化为应用 UID + `0600`/`0700`」
- 位置：`docs/guides/deployment.md:41-44`、`docs/guides/upgrade.md:20`、`docs/specs/mail_sync_and_storage.md:198`；`src/mail_core/blobs/permissions.py:98-103`、`:114-116`；`docker-compose.mail-core.yml:109`
- 问题：文档唯一给出的 owner 修复入口（`api` 镜像内 `python3`，`--user 0:0` 覆盖镜像 UID）是 `docker compose ... run --rm --no-deps --user 0:0 --cap-add CHOWN ... --target-uid 10001 --target-gid 999`。`api` 服务声明 `cap_drop: [ALL]`，`--cap-add CHOWN` 只补回 CHOWN，进程没有 `CAP_DAC_OVERRIDE/READ_SEARCH`（遍历/读取异属主 `0700` 目录）与 `CAP_FOWNER`（chown 后对非属主文件 chmod）。我用隔离 Docker volume 复现了文档命令的两条失败路径：(a) 树根由非进程 UID（实测 `10001:999`）所有且为 `0700`，命令在 `failed to scan ...: Permission denied` 处退出（缺 DAC_OVERRIDE/READ_SEARCH）；(b) 根目录 root 所有、子目录应用 UID 所有，`_apply_owner()` chown 子目录成功后，`make_private_dir(..., strict=True)` 的 chmod 即刻报 `[Errno 1] Operation not permitted`。两种场景都无法把 owner 归一化回应用 UID；补上 `CHOWN,FOWNER,DAC_OVERRIDE` 后同一模块实测才能把 `0:0` 树迁移为 `12345:12345` 且保持 `0600/0700`，说明缺陷在文档能力集与「先 chown 后 chmod」的权限需求，而非 chown 逻辑本身不可用。现有 `tests/mail_core/test_blob_permissions.py:94-107` 用 monkeypatch 替换 `os.chown`（归属并未改变），因此无法暴露该失败。
- 建议：把 `deployment.md`/`upgrade.md`/spec 的能力集改为实际所需的 `--cap-add CHOWN --cap-add FOWNER --cap-add DAC_OVERRIDE`（或改为两阶段：先以属主/可遍历身份扫描并收紧 mode，再自底向上 chown，降低能力需求）；并补一条真实执行文档命令、以异属主 `0700` fixture 为输入的集成测试，替代当前 monkeypatch 用例。

### 前轮 finding 复核

- t075_code_f001：已消除（代码层）。`permissions.py:69-78` 新增 `_apply_owner` 与 `--target-uid/--target-gid`，`chown` 路径真实存在，AC-005 与范围条目重新一致；但其文档入口不可用，另见 f010。
- t075_code_f002：已消除。`permissions.py:80-88` 的 `os.walk(..., onerror=_walk_error)` 仍把扫描失败转为 `PermissionNormalizationError`；本轮重跑 `test_normalize_private_permissions_refuses_unreadable_subtree` 通过。
- t075_code_f003：已消除。`package.py:1572,1576,1642,1659` 全部改用 `make_private_chain`；本轮重跑 umask 022/077 的「tar 无目录成员」用例与 `test_restore_blobs_have_private_modes_regardless_of_umask` 通过。
- t075_code_f004：已消除。`docs/guides/deployment.md:38`、`docs/guides/upgrade.md:20`、`scripts/normalize_mail_core_permissions.py:11,26-27` 已统一为 `.venv/bin/python`；实测 `.venv/bin/python scripts/normalize_mail_core_permissions.py --help` 正常退出（不再触发 sqlalchemy 缺失）。
- t075_code_f005：已消除。`docs/blueprint/testing.md:213` 引用的 `test_backup_container_permissions.py` 真实 Docker 用例本轮重跑通过，不再把仅手工演练的行为写成自动化覆盖。
- t075_code_f006：已消除。`private_fs.make_private_dir/make_private_chain` 由 `store.py`/`rotate.py`/`package.py`/`permissions.py` 复用，部署脚本内联的导出/校验逻辑已移入 `src/mail_core/backup/export.py` 并由行为测试覆盖；未再发现同一语义散落分叉。
- t075_code_f007：已消除（契约矛盾）。当前 `task.md` AC-005 已恢复为原始「归一化为应用 UID + `0600`/`0700`」，与范围条目一致，可测试性声明同步写明显式目标 owner 的 chown 路径；未再出现「改 AC 代替实现」的情况。剩余可用性缺陷按新发现 f010 处理。
- t075_code_f008：已消除。`private_fs.py:37-43` 改用 `os.path.abspath` 比较且在 `mkdir` 之前做越界校验；`test_make_private_chain_accepts_symlinked_ancestor` 与 `test_make_private_chain_refuses_outside_path_before_creating_it` 本轮重跑通过。
- t075_code_f009：已消除。`export.py:35-45` 把 `docker cp` 的 `CalledProcessError` 转为带 returncode/stderr 摘要的 `BackupExportError`，`main()` 另有兜底；`test_export_cli_reports_docker_cp_failure_without_traceback` 通过。

### 本轮结论

- 本轮新发现：1 条（1 important、0 minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2630 行（相对 anchor 净增约 25 行，已超 800 行实现阈值）；`tests/mail_core/test_backup_package.py` 1511 行（净增约 152 行，已超 1200 行测试阈值）。按规则只在结论段提示，不进 finding 表。`src/mail_core/backup/export.py` 206 行、`src/mail_core/blobs/permissions.py` 174 行未超阈值。
    - 圈复杂度：`normalize_private_permissions`（`permissions.py:37-140`）手算约 CC 19-20（≥10 提示；规模启发式按规则不进 finding 表），建议后续按「目录遍历 / 文件处理 / owner 迁移」拆分。
    - 契约 drift：AC-005 已恢复为 owner 归一化原文；AC-006 由 `[deploy]` 真实部署改为隔离 Docker、并新增「不在 task 分支内执行生产部署」非范围项，与注入上下文一致，未按未经确认的 AC 变更处理。
    - 范围外观察：Linux 主机 `docker cp` 导出归属仍未实测（上下文已列为合并后部署验证风险）；完整生产部署从 sandbox 外的隔离栈执行，本轮不覆盖。`make_private_chain` 使用 abspath 文本比较，根内中间符号链接的理论逃逸路径在恢复目标必须为空的前提下不可达，未单列 finding。
- 总体判断：AC-001/002/003/004/006 的实现与验证可复现通过，但用户恢复的 AC-005 owner 归一化只有「给足能力才可用」的代码路径，文档给出的唯一命令在异属主输入下必败，属 important 阻断。
- 系统性 follow-up：无（Round 1 建议的隔离 Docker 备份/导出一致性测试已由 `tests/mail_core/test_backup_container_permissions.py` 落地）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮重跑 `test_put_uses_private_file_and_directory_modes`（put/put_streaming × umask 022/077）与 `test_rewrap_replaced_file_has_0600_permissions`（父目录 0755 → 0700）通过；真实 Docker 用例确认无关 UID `12345` 读取 `0600` blob 失败。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker，应用 UID `10001:999`、blob 卷 `:ro`）通过：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`。
- AC-003：TICK-VALID，re_verified。核对 `scripts/deploy_mail_core.sh:73-106`：备份无 `--user`、容器私有 `/backup`、宿主导出到新建 `0700` staging、校验归属/权限与 `verify_backup_package` 后 `os.replace` 原子发布、失败清理；`test_backup_export.py`（4 条）与 A13 接线用例通过，Docker 用例覆盖导出归属。完整生产部署按上下文留待合并后。
- AC-004：TICK-VALID，re_verified。本轮重跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077）、`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`、`test_restored_blob_store_can_be_written_and_backed_up_again` 通过：目录链 `0700`、文件 `0600`、owner 为当前 UID，未应用归档 UID/mode。
- AC-005：TICK-VOID，re_verified。默认应用 UID 的 mode 归一化与「启动路径不递归修补」用例通过，但文档唯一 owner 修复命令 `--user 0:0 --cap-add CHOWN --target-uid 10001 --target-gid 999` 在隔离 volume 上实测分别以 `Permission denied` 扫描失败与 chmod `Operation not permitted` 失败，无法完成 owner 归一化，详见 f010。
- AC-006：TICK-VALID，re_verified。本轮重跑真实 Docker 集成：应用 UID 备份真实 `0600` blob、宿主导出到 `0700` staging 并断言归属/权限、无关 UID 读取失败、归一化后再次备份；恢复后应用读取/写入与再次备份由 `test_backup_package.py` 覆盖并通过。

coverage = 6 / 6

verdict: FAIL

## Round 4 (2026-11-05T08:00:43+08:00)

reviewed_scope: 02939cc3e474b5bf

### t075_code_f011 - 代码提示与 spec 摘要仍只写 CAP_CHOWN，未覆盖实际必需的 FOWNER/DAC_OVERRIDE

- 严重度：minor
- 锚点：AC-005 文档/可观测一致性（操作指南已正确，不构成行为阻断）
- 位置：`src/mail_core/blobs/permissions.py:52`、`:77`；`docs/specs/mail_sync_and_storage.md:198`
- 问题：Round 3 修复把 `docs/guides/deployment.md:41-46`、`docs/guides/upgrade.md:20`、`scripts/normalize_mail_core_permissions.py:15-16` 的能力集补成 `CHOWN/FOWNER/DAC_OVERRIDE`，但残留下游提示仍是旧口径：`permissions.py:52` 写 "requires root/CAP_CHOWN"，`:77` 的 chown 失败提示写 "run as root with CAP_CHOWN"，`docs/specs/mail_sync_and_storage.md:198` 写 "以 root/CAP_CHOWN"。可验证失败场景（与 Round 3 实测一致）：仅补 `CAP_CHOWN` 时，异属主 `0700` 根在 `os.walk` 处报 `failed to scan ...: Permission denied`（缺 DAC_OVERRIDE），或在 `_apply_owner()` 成功后 `make_private_dir(..., strict=True)` 的 chmod 报 `[Errno 1] Operation not permitted`（缺 FOWNER）。本轮按新能力集实测已成功，说明只是提示文本落后于实现，非功能缺陷。
- 建议：把上述三处提示统一为 `root + CHOWN/FOWNER/DAC_OVERRIDE`（或直接指向 `docs/guides/deployment.md` 的维护命令），使报错与 spec 摘要可独立指导 owner 迁移。

### 前轮 finding 复核

- t075_code_f001：已消除。`src/mail_core/blobs/permissions.py:69-78` 的 `_apply_owner` 与 CLI `--target-uid/--target-gid`（`:154-155`）仍真实存在；本轮在隔离 volume 上收到真实 chown 生效，非仅断言参数。
- t075_code_f002：已消除。`permissions.py:80-89` 的 `os.walk(..., onerror=_walk_error)` 仍把扫描失败转为 `PermissionNormalizationError`；`test_normalize_private_permissions_refuses_unreadable_subtree` 本轮通过。
- t075_code_f003：已消除。`src/mail_core/backup/package.py:1572,1576,1642,1659` 均使用 `make_private_chain(..., strict=True)`，恢复中间目录不再随 umask 漂移；`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`（022/077）通过。
- t075_code_f004：已消除（文档口径）。`docs/guides/deployment.md:38`、`docs/guides/upgrade.md:20`、`scripts/normalize_mail_core_permissions.py:11` 均为 `.venv/bin/python`；实测 `.venv/bin/python scripts/normalize_mail_core_permissions.py --help` 返回 0。系统 `python3` 直跑仍因 `mail_core.blobs.__init__` 导入 SQLAlchemy 失败，但已无文档指引该用法。
- t075_code_f005：已消除。`docs/blueprint/testing.md:213` 现在指向的 `test_backup_container_permissions.py` 确含真实 Docker 备份/导出/无关 UID 用例，本轮实跑 1 passed，不存在“手工演练写成自动化覆盖”。
- t075_code_f006：已消除。`private_fs.make_private_dir/make_private_chain` 由 `store.py`、`rotate.py`、`package.py`、`permissions.py`、`export.py` 复用；部署脚本内联导出/校验已移入 `src/mail_core/backup/export.py`，未再发现同一语义的自建分支。
- t075_code_f007：已消除。`docs/tasks/t075_backup_export_permission_boundary/task.md:43` 的 AC-005 已恢复为“归一化为应用 UID + `0600`/`0700`”，与 `:17` 范围一致，未再以改 AC 替代实现。
- t075_code_f008：已消除。`src/mail_core/blobs/private_fs.py:38-44` 用 `os.path.abspath` 比较且越界校验先于 `mkdir`；`test_make_private_chain_accepts_symlinked_ancestor` 与 `test_make_private_chain_refuses_outside_path_before_creating_it` 通过。
- t075_code_f009：已消除。`src/mail_core/backup/export.py:32-45` 将 `docker cp` 的 `CalledProcessError` 转成带 returncode/stderr 的 `BackupExportError`，`main()` 另有兜底分支（`:180-197`）；`test_export_cli_reports_docker_cp_failure_without_traceback` 通过。
- t075_code_f010：已消除（阻断层面）。`docs/guides/deployment.md:41-46` 与 `docs/guides/upgrade.md:20` 现给出 `--cap-add CHOWN --cap-add FOWNER --cap-add DAC_OVERRIDE`。本轮用真实 compose 服务配置（`cap_drop: [ALL]`、`no-new-privileges:true`、当前源码重建的 api 镜像）复验：`--user 0:0` 下 `CapEff=0xb`（CHOWN+DAC_OVERRIDE+FOWNER），对 `0:0` 的 `0700` 树执行文档命令后得到 `10001:999`、目录 `0700`、文件 `0600`，退出 0；另一组 `10001:999` 树也能迁移到 `12345:12345`。Round 3 的两条失败路径不再复现。
- 其余前轮 finding 无新增撤回项。

### 本轮结论

- 本轮新发现：1 条（0 critical、0 important、1 minor）。
- 前轮遗留：无阻断项。f010 阻断已消除；f011 仅记录代码/spec 中的能力集措辞残留。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2630 行（≥800 实现阈值，本 task 净增约 31 行）；`tests/mail_core/test_backup_package.py` 1511 行（≥1200 测试阈值，净增约 152 行）。按规则只在结论段提示，不进 finding 表。
    - 圈复杂度：`normalize_private_permissions`（`permissions.py:37-140`）外层分支手算约 CC 11-13；`_secure_exported_tree`（`export.py:49-104`）约 CC 11。均 ≥10、\<15，仅提示。
    - 契约 drift：AC-005 已恢复为 owner 归一化原文；AC-006 由 `[deploy]` 改为隔离 Docker、新增「不在 task 分支内执行生产部署」非范围项，与注入上下文的用户同日补充要求一致，不按未经确认变更处理。
    - 范围外观察：Linux 主机 `docker cp` 导出归属仍未实测（上下文已列为合并后部署验证风险）；完整生产部署不在本 task 分支执行。`tests/mail_core/test_blob_permissions.py:94-107` 仍以 monkeypatch 替换 `os.chown`，owner 迁移的真实能力集回归没有自动化用例；该证据缺口属测试轴，未在本报告重复出 finding。
- 总体判断：Round 3 的 owner 迁移能力集阻断已被真实 compose 配置与真实 chown 复验消除，AC-001～AC-006 实现层与验证均可复现通过；仅余 1 条提示文本 minor。
- 系统性 follow-up：无（Round 1 建议的隔离 Docker 备份/导出身份测试已由 `tests/mail_core/test_backup_container_permissions.py` 落地）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮重跑 `test_put_uses_private_file_and_directory_modes`（put/streaming × umask 022/077，文件 `0600`、分片与根目录 `0700`）与 `test_rewrap_replaced_file_has_0600_permissions`（父目录先 0755，轮换后 `0600`/`0700`）；真实 Docker 用例以 UID `12345` 执行 `test -r /b/aa` 与读取 blob 均失败。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker，应用 UID `10001:999`、blob 卷 `:ro`）：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`。
- AC-003：TICK-VALID，re_verified。核对 `scripts/deploy_mail_core.sh:71-107`：备份无 `--user`、产物写容器私有 `/backup`，宿主导出到新建 `0700` staging，校验 symlink/归属/mode 与 `verify_backup_package` 后 `os.replace` 原子发布，EXIT trap 清理未发布半成品；重跑 `test_backup_export.py` 4 条与 A13 接线用例通过。完整生产部署按上下文留待合并后。
- AC-004：TICK-VALID，re_verified。本轮重跑 `test_backup_package.py` 63 passed，含 umask 022/077 恢复 `0700/0600` 且 owner 为当前进程、无目录成员的中间目录用例、恢复后 `BlobStore` 读取/写入/再次备份并 verify。
- AC-005：TICK-VALID，re_verified。以当前源码重建的 api 镜像 + `cap_drop:[ALL]`/`no-new-privileges:true` 的 compose run 复验文档命令：`--user 0:0 --cap-add CHOWN/FOWNER/DAC_OVERRIDE` 将 `0:0` 的 `0700` 树归一化为 `10001:999`（`0600`/`0700`，退出 0），另组迁移到 `12345:12345` 亦成功；`test_blob_permissions.py` 与 `test_blob_store_does_not_recursively_repair_existing_shards` 本轮通过。残留提示措辞见 f011。
- AC-006：TICK-VALID，re_verified。本轮重跑真实 Docker 集成：应用 UID 备份真实 `0600` blob、宿主导出到 `0700` staging 并断言导出包归属与权限、无关 UID 读取失败；恢复后应用读取/写入与再次备份由 `test_backup_package.py` 覆盖并通过。生产部署黑盒按上下文留待合并后。

coverage = 6 / 6

verdict: PASS

## Round 5 (2026-11-05T08:40:14+08:00)

reviewed_scope: d6d70a1ad0ea951b

### 前轮 finding 复核

- t075_code_f001：已消除。`src/mail_core/blobs/permissions.py:69-78` 的 `_apply_owner` 与 CLI `--target-uid/--target-gid`（`:154-155`）真实存在；本轮用当前源码在隔离 Docker volume 上执行 `--user 0:0 --cap-add CHOWN/FOWNER/DAC_OVERRIDE --target-uid 10001 --target-gid 999`，`stat` 实测根/子目录 `700 10001:999`、文件 `600 10001:999`，非仅断言参数。
- t075_code_f002：已消除。`permissions.py:80-89` 的 `os.walk(..., onerror=_walk_error)` 仍把扫描失败转为 `PermissionNormalizationError`；`test_normalize_private_permissions_refuses_unreadable_subtree` 本轮通过。
- t075_code_f003：已消除。`src/mail_core/backup/package.py:1572,1576,1642,1659` 均使用 `make_private_chain(..., strict=True)`；本轮重跑 `test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`（umask 022/077）通过，中间目录不随 umask 漂移。
- t075_code_f004：已消除。`docs/guides/deployment.md:38`、`docs/guides/upgrade.md:20`、`scripts/normalize_mail_core_permissions.py:12` 均为 `.venv/bin/python`；本轮实测 `.venv/bin/python scripts/normalize_mail_core_permissions.py --help` 退出 0，不再因缺 SQLAlchemy 失败。
- t075_code_f005：已消除。`docs/blueprint/testing.md:213` 指向的 `tests/mail_core/test_backup_container_permissions.py` 确含真实 Docker 备份/导出/无关 UID 用例，本轮实跑 2 passed，不再把手工演练写成自动化覆盖。
- t075_code_f006：已消除。`private_fs.make_private_dir/make_private_chain` 由 `store.py`、`rotate.py`、`package.py`、`permissions.py`、`export.py` 复用；部署脚本内联的导出/校验逻辑已移入 `src/mail_core/backup/export.py` 并由行为测试覆盖，未再发现同一语义的自建分叉。
- t075_code_f007：已消除。`docs/tasks/t075_backup_export_permission_boundary/task.md:43` 的 AC-005 为原始「归一化为应用 UID + `0600`/`0700`」，与 `:17` 范围条目一致，未再以改 AC 替代实现。
- t075_code_f008：已消除。`src/mail_core/blobs/private_fs.py:38-44` 用 `os.path.abspath` 比较且越界校验先于 `mkdir`；`test_make_private_chain_accepts_symlinked_ancestor` 与 `test_make_private_chain_refuses_outside_path_before_creating_it` 本轮通过。
- t075_code_f009：已消除。`src/mail_core/backup/export.py:32-45` 将 `docker cp` 的 `CalledProcessError` 转为带 returncode/stderr 摘要的 `BackupExportError`，`main()` 另有兜底分支；`test_export_cli_reports_docker_cp_failure_without_traceback` 本轮通过。
- t075_code_f010：已消除（阻断层面）。`docs/guides/deployment.md:41-46`、`docs/guides/upgrade.md:20` 给出 `CHOWN/FOWNER/DAC_OVERRIDE`；本轮以当前源码 + 真实 Docker volume 复跑 chown（见 f001 证据），异属主 `0700` 树可归一化为目标 UID，Round 3 的两条失败路径未复现。
- t075_code_f011：已消除。`src/mail_core/blobs/permissions.py:53`（docstring）、`:78`（chown 失败提示）与 `docs/specs/mail_sync_and_storage.md:198` 的能力集均已改为 `CHOWN/FOWNER/DAC_OVERRIDE`；`grep -rn CAP_CHOWN src scripts docs` 除历史 review/progress 记录外无代码或文档命中。
- 无其他前轮 finding 需要撤回。

### 本轮结论

- 本轮新发现：0 条（0 critical、0 important、0 minor）。
- 前轮遗留：无阻断项；f001～f011 全部按当前 diff/代码复核为已消除。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2630 行（≥800 实现阈值，相对 anchor 净增约 5 行）；`tests/mail_core/test_backup_package.py` 1515 行（≥1200 测试阈值，净增约 156 行）。按规则只在结论段提示，不进 finding 表。`src/mail_core/backup/export.py` 206 行、`src/mail_core/blobs/permissions.py` 175 行未超阈值。
    - 圈复杂度：`normalize_private_permissions`（`permissions.py:37-140`）手算约 15-18（含 `if`/`for`/`except` 与嵌套 helper），达到提示阈值但未产出可观测缺陷；`_secure_exported_tree`（`export.py:60-111`）约 CC 11。按规模启发式只作提示，不进 finding 表。
    - 契约 drift：AC-005 已恢复 owner 归一化原文；AC-006 由 `[deploy]` 改为隔离 Docker、并新增「不在 task 分支内执行生产部署」非范围项，与注入上下文的用户同日补充要求一致，不按未经确认变更处理。
    - 范围外观察：Linux 主机 `docker cp` 导出归属仍未实测（上下文已列为合并后部署验证风险）；完整生产部署不在本 task 分支执行。`permissions.py` 的 lstat→chown/chmod 存在理论符号链接替换竞态，但维护命令由运维在受控树执行且各层已拒绝符号链接，未构成可复现缺陷，不单列 finding。
- 总体判断：Round 4 唯一 minor（f011 能力集措辞）已修复，前轮全部 finding 按当前代码复核为已消除，本轮无新 finding；实现层与验证均可复现通过，代码轴 PASS。
- 系统性 follow-up：无（隔离 Docker 备份/导出/owner 迁移的真实身份测试已由 `tests/mail_core/test_backup_container_permissions.py` 覆盖）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮重跑 `test_put_uses_private_file_and_directory_modes`（put/streaming × umask 022/077）与 `test_rewrap_replaced_file_has_0600_permissions`（umask 参数化，父目录 0755 → 0700）通过；真实 Docker 用例以 UID `12345` 对 `/b/aa` 执行 `-r`/`-x` 与读取 blob 均失败。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker，应用 UID `10001:999`、blob 卷 `:ro`）：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`。
- AC-003：TICK-VALID，re_verified。核对 `scripts/deploy_mail_core.sh:99-110`：备份无 `--user`、产物写容器私有 `/backup`，宿主导出到新建 `0700` staging，`export_container_package` 校验 symlink/归属/mode 与 `verify_backup_package` 后 `os.replace` 原子发布，EXIT trap 清理未发布半成品；重跑 `test_backup_export.py` 4 条与 A13 接线用例通过。完整生产部署按上下文留待合并后。
- AC-004：TICK-VALID，re_verified。本轮重跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077）、`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`、`test_restored_blob_store_can_be_written_and_backed_up_again` 通过：目录链 `0700`、文件 `0600`、owner 为当前进程，未应用归档 UID/mode，恢复后可读取/写入并再次备份。
- AC-005：TICK-VALID，re_verified。`test_blob_permissions.py`、`test_blob_store_does_not_recursively_repair_existing_shards` 与真实 Docker 用例 `test_owner_normalization_migrates_foreign_private_tree` 通过；本轮另以当前源码在隔离 volume 上实测 `0:0` 的 `0700` 树归一化为 `10001:999`（`700/600`），API/Worker 启动路径仅非递归收紧根目录。
- AC-006：TICK-VALID，re_verified。本轮重跑真实 Docker 集成：应用 UID 备份真实 `0600` blob、宿主导出到 `0700` staging 并断言导出包归属与权限、无关 UID 读取失败；恢复后应用读取/写入与再次备份由 `test_backup_package.py` 覆盖并通过。生产部署黑盒按上下文留待合并后。

coverage = 6 / 6

verdict: PASS

## Round 6 (2026-11-05T08:45:23+08:00)

reviewed_scope: 5a13ad32a8a09133

本轮仅因 `md_format.py` 在 `docs/guides/deployment.md` 的列表项之间插入空行而触发：相对 Round 5，工作区未暂存差异仅为该文件 2 处空行（`git diff -- docs/guides/deployment.md`），`task.md` / `progress.md` 属流程文件，源码与测试无变化。语义内容未变，前轮结论继续适用；以下按当前完整 diff 重新独立复验。

### 前轮 finding 复核

- t075_code_f001：已消除。`src/mail_core/blobs/permissions.py:70-80` 的 `_apply_owner` 与 CLI `--target-uid/--target-gid`（`:155-156`）真实存在；本轮 Docker `test_owner_normalization_migrates_foreign_private_tree` 实测 `0:0` 的 `0700` 树迁移为 `600 10001 999` 成功，非仅参数断言。
- t075_code_f002：已消除。`permissions.py:88-89` 的 `os.walk(..., onerror=_walk_error)` 仍把扫描失败转为 `PermissionNormalizationError`；`test_normalize_private_permissions_refuses_unreadable_subtree` 本轮通过。
- t075_code_f003：已消除。`src/mail_core/backup/package.py:1572,1576,1642,1659` 均使用 `make_private_chain(..., strict=True)`；`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`（umask 022/077）本轮通过。
- t075_code_f004：已消除。`docs/guides/deployment.md:40`、`docs/guides/upgrade.md:20`、`scripts/normalize_mail_core_permissions.py:11` 均为 `.venv/bin/python`；本轮实测 `.venv/bin/python scripts/normalize_mail_core_permissions.py --help` 退出码 0。
- t075_code_f005：已消除。`docs/blueprint/testing.md:213` 指向的 `tests/mail_core/test_backup_container_permissions.py` 确含真实 Docker 备份/导出/无关 UID 用例，本轮实跑 2 passed。
- t075_code_f006：已消除。`src/mail_core/blobs/private_fs.py` 的 `make_private_dir/make_private_chain` 由 `store.py`、`rotate.py`、`package.py`、`permissions.py`、`export.py` 复用；`package.py:496-500` 仅为带 `BackupCryptoError` 语义的薄包装，部署脚本内联导出/校验已移入 `src/mail_core/backup/export.py`。
- t075_code_f007：已消除。`docs/tasks/t075_backup_export_permission_boundary/task.md:43` 的 AC-005 为原始「归一化为应用 UID + `0600`/`0700`」，与 `:17` 范围条目一致。
- t075_code_f008：已消除。`private_fs.py:38-41` 用 `os.path.abspath` 比较且越界校验先于 `mkdir`；`test_make_private_chain_accepts_symlinked_ancestor` 与 `test_make_private_chain_refuses_outside_path_before_creating_it` 本轮通过。
- t075_code_f009：已消除。`src/mail_core/backup/export.py:32-45` 将 `docker cp` 的 `CalledProcessError` 转成带 returncode/stderr 摘要的 `BackupExportError`，`main()` 另有兜底分支；`test_export_cli_reports_docker_cp_failure_without_traceback` 本轮通过。
- t075_code_f010：已消除（阻断层面）。`docs/guides/deployment.md:40-47`、`docs/guides/upgrade.md:20` 的能力集为 `CHOWN/FOWNER/DAC_OVERRIDE`；本轮 Docker 用例以 `--cap-drop ALL --cap-add CHOWN/FOWNER/DAC_OVERRIDE` 复跑 owner 迁移成功，Round 3 的两条失败路径未复现。
- t075_code_f011：已消除。`permissions.py:53`、`:78` 与 `docs/specs/mail_sync_and_storage.md:198` 均为 `CHOWN/FOWNER/DAC_OVERRIDE`；`grep -rn CAP_CHOWN src scripts docs` 除历史 review/progress 记录外无代码/文档命中。
- 无其他前轮 finding 需要撤回。

### 本轮结论

- 本轮新发现：0 条（0 critical、0 important、0 minor）。
- 前轮遗留：无阻断项；f001～f011 全部按当前 diff/代码复核为已消除。
- 未进表的提示：
    - 文件过大：`src/mail_core/backup/package.py` 2630 行（≥800 实现阈值）；`tests/mail_core/test_backup_package.py` 1515 行（≥1200 测试阈值）。按规则只在结论段提示，不进 finding 表。
    - 圈复杂度：`normalize_private_permissions`（`permissions.py:37-140`）手算约 15-18，`_secure_exported_tree`（`export.py:60-111`）约 CC 11；均未产出可观测缺陷，按规模启发式只作提示。
    - 契约 drift：AC-006 由 `[deploy]` 真实部署改为隔离 Docker、并新增「不在 task 分支内执行生产部署」非范围项，与注入上下文的用户同日补充要求一致，不按未经确认变更处理；AC-005 已为 owner 归一化原文。
    - 范围外观察：Linux 主机 `docker cp` 导出归属仍未实测（上下文已列为合并后部署验证风险）；完整生产部署不在本 task 分支执行。本轮 scope 变化仅为 `md_format.py` 的 Markdown 空行，`docs/guides/deployment.md` 内容语义未变。
- 总体判断：当前 diff 无未解决的 critical/important；仅有的改动是文档空行，源码与测试相对 Round 5 未变且本轮定向测试全部通过，代码轴 PASS。
- 系统性 follow-up：无（隔离 Docker 备份/导出/owner 迁移的真实身份测试已由 `tests/mail_core/test_backup_container_permissions.py` 覆盖）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。本轮重跑 `test_put_uses_private_file_and_directory_modes`（put/streaming × umask 022/077）与 `test_rewrap_replaced_file_has_0600_permissions`（umask 022/077，父目录 0755 → 0700）通过；真实 Docker 用例以 UID `12345` 对 `/b/aa` 执行 `-r`/`-x` 与读取 blob 均失败。
- AC-002：TICK-VALID，re_verified。本轮重跑 `tests/mail_core/test_backup_container_permissions.py`（真实 Docker，应用 UID `10001:999`、blob 卷 `:ro`）：`status=ok`、`verified=true`，备份前后 `stat` 均为 `600 10001 999`。
- AC-003：TICK-VALID，re_verified。核对 `scripts/deploy_mail_core.sh:66-108`：备份无 `--user`、产物写容器私有 `/backup`，宿主导出到新建 `0700` staging，`mail_core.backup.export` 校验 symlink/归属/mode 与 `verify_backup_package` 后 `os.replace` 原子发布，EXIT trap 清理未发布半成品；重跑 `test_backup_export.py` 4 条与 A13 接线用例通过。完整生产部署按上下文留待合并后。
- AC-004：TICK-VALID，re_verified。本轮重跑 `test_restore_blobs_have_private_modes_regardless_of_umask`（022/077）、`test_restore_staging_makes_intermediate_dirs_private_without_tar_dir_members`、`test_restored_blob_store_can_be_written_and_backed_up_again` 通过：目录链 `0700`、文件 `0600`、owner 为当前进程，未应用归档 UID/mode，恢复后可读取/写入并再次备份。
- AC-005：TICK-VALID，re_verified。`test_blob_permissions.py`（mode 归一化、symlink/异属主/不可读子树拒绝、CLI JSON、chown 失败提示）、`test_blob_store_does_not_recursively_repair_existing_shards` 与真实 Docker `test_owner_normalization_migrates_foreign_private_tree` 本轮通过；`.venv/bin/python scripts/normalize_mail_core_permissions.py --help` 退出码 0。
- AC-006：TICK-VALID，re_verified。本轮重跑真实 Docker 集成：应用 UID 备份真实 `0600` blob、宿主导出到 `0700` staging 并断言导出包归属/权限、无关 UID 读取失败、归一化后再次备份 `verified=true`；恢复后应用读取/写入与再次备份由 `test_backup_package.py` 覆盖并通过。生产部署黑盒按上下文留待合并后。

coverage = 6 / 6

verdict: PASS
