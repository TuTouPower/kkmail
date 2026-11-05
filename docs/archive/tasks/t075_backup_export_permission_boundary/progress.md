---
tid: "t075"
slug: "backup_export_permission_boundary"
title: "重构备份与宿主导出边界并保留应用私有 blob 权限"
status: "done"
branch: "t075_backup_export_permission_boundary"
worktree: ""
review_level: "full"
review_limit: "6"
verify_limit: "5"
diff_anchor: "18f0f5e3e1f5d3f5a3437d7d1cc401bf5b0ffd48"
depends_on: ""
conflicts_with: ""
note: "来源 p074；备份进程被迫跨宿主/应用两个数据所有者，0600 blob 备份失败；保留私有权限并重设计备份导出的身份与权限边界; budget: review_limit: 5->6; md_format 在 Round 5 后仅插入空行；需重审最终格式化 scope"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 2026-11-05：保留 blob 私有权限，不采用全局 `0644`。`BlobStore` 根目录/分片目录显式 `0700`；轮换重写前收紧父目录；新增 `mail_core.blobs.permissions` 与显式维护脚本。
- 2026-11-05：恢复路径改为 `os.open(..., 0o600)` 创建临时文件，目录经私有无损创建；目标 blob 根与发布目录显式 `0700`，不再继承归档 uid/mode 或进程 umask。
- 2026-11-05：备份镜像创建容器私有 `/backup`（应用 UID `10001:999`、`0700`）；Compose 移除宿主 bind mount，仅保留 blob 只读卷。部署脚本不再用宿主 UID 运行备份，改为保留已停止容器、`docker cp` 导出到宿主 `0700` staging，校验归属/权限与 `verify_backup_package` 后原子 `mv` 发布；失败不发布半成品。
- 2026-11-05：测试补充 umask 022/077 下 put/put_streaming/轮换权限、恢复 owner/mode、恢复后写入并再次备份、维护命令拒绝 symlink/foreign owner，以及 A13 不再锁定宿主 UID 的实现测试。
- 2026-11-05 手工隔离 Docker 验证：临时 volume 内 `0600` probe blob 由应用 UID 备份成功（`status=ok`、`verified=true`），无关 UID `12345` 读取失败；从停止容器 `docker cp` 导出后文件归属宿主 `501:20`，经维护命令规范为包目录 `0700`、文件 `0600` 并通过 verify。
- 2026-11-05 现场说明：事故处置时曾把生产存量 blob 临时改为 `0644`，本 task 未在生产卷上执行归一化；新写入已为 `0600`，存量归一化命令已记录在 `docs/guides/deployment.md` 与 `docs/guides/upgrade.md`，合并后按维护流程执行。
- 2026-11-05 最终验证：touched 单元 113 passed；Docker owner 迁移/备份集成 2 passed；DB 相关 39 passed；backend 完整 1975 passed/2 skipped；frontend 572 passed + build；desktop 全通过；Playwright 21 passed。
- 2026-11-05 验证：owner 归一化额外用 Docker 实测：`root + CHOWN/FOWNER/DAC_OVERRIDE` 可将异属主 0700 树转为 `10001:999`；仅 CHOWN 会因无法遍历而 EACCES。
- 2026-11-05 验证：focused unit `98 passed`；backend 相关 DB 用例 `23 passed`；完整 backend `1959 passed, 4 failed, 4 skipped`，4 failed 均为 IMAP fixture 未启动，启动 `scripts/start-mail-core-imap.sh` 后 4 项重跑 `4 passed`。生产部署整体黑盒因 task 在分支 worktree 内执行，留待合并后按部署剧本验证。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-05T06:50:41+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t075_code_f001|minor|已修|维护命令新增显式 target uid/gid chown 路径；默认应用 UID 只归一化 mode，异属主拒绝并在 root 下可显式迁移 owner|src/mail_core/blobs/permissions.py; tests/mail_core/test_blob_permissions.py; docs/guides/{deployment,upgrade}.md|
|t075_code_f002|minor|已修|os.walk 增加 onerror，扫描失败抛 PermissionNormalizationError 并补测试|src/mail_core/blobs/permissions.py:60; tests/mail_core/test_blob_permissions.py|
|t075_code_f003|minor|已修|新增 make_private_chain，逐级收紧归档中的中间目录并补缺目录成员测试|src/mail_core/blobs/private_fs.py; tests/mail_core/test_backup_package.py|
|t075_code_f004|minor|已修|宿主维护命令文档与脚本 docstring 均改用 .venv/bin/python，并补充 target owner 语义|docs/guides/deployment.md:38; docs/guides/upgrade.md:20; scripts/normalize_mail_core_permissions.py|
|t075_code_f005|minor|已修|testing.md 覆盖声明改为真实 Docker 集成测试文件与导出测试|docs/blueprint/testing.md|
|t075_code_f006|minor|已修|抽取 private_fs 共享 helper；store/rotate/package/permissions 复用，导出逻辑移入 mail_core.backup.export|src/mail_core/blobs/private_fs.py; src/mail_core/backup/export.py|
|t075_test_f001|important|已修|新增真实 Docker 集成测试：应用 UID 读取 0600 blob、备份前后 owner/mode 不变、无关 UID 拒绝|tests/mail_core/test_backup_container_permissions.py|
|t075_test_f002|important|已修|Docker 测试覆盖备份→宿主导出→verify；导出行为另由 test_backup_export 覆盖|tests/mail_core/test_backup_container_permissions.py; tests/mail_core/test_backup_export.py|
|t075_test_f003|critical|已修|导出/校验/权限/发布逻辑移入可执行模块并由行为测试覆盖成功、失败不发布、覆盖拒绝；A13 只保留接线断言|src/mail_core/backup/export.py; tests/mail_core/test_backup_export.py; tests/scripts/test_deploy_mail_core_r4adopt_p51.py|
|t075_test_f004|important|已修|轮换测试先把父目录改为 0755 并在 umask 022/077 下验证收紧；Docker 测试验证无关 UID 读取失败|tests/mail_core/test_a318_rewrap_file_hardening.py; tests/mail_core/test_backup_container_permissions.py|
|t075_test_f005|minor|已修|恢复测试断言 owner 并用 BlobStore 加密 blob 验证恢复后应用读取|tests/mail_core/test_backup_package.py|
|t075_test_f006|minor|已修|补启动路径不递归修补、CLI 输出、归一化后读取/再次备份回归|tests/mail_core/test_blob_store.py; tests/mail_core/test_blob_permissions.py; tests/mail_core/test_backup_package.py|
|t075_test_f007|minor|已修|testing.md 改为引用真实 Docker 集成测试与导出测试|docs/blueprint/testing.md|

### Round 2 (2026-11-05T07:40:37+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t075_code_f007|important|已修|恢复 AC-005 原始 owner 归一化语义；permissions 新增 --target-uid/--target-gid 显式 chown，root/CAP_CHOWN 下已验证 10001:999|src/mail_core/blobs/permissions.py; tests/mail_core/test_blob_permissions.py; docs/guides/{deployment,upgrade}.md|
|t075_code_f008|minor|已修|make_private_chain 改用 abspath 比较并在越界校验后 mkdir；补符号链接祖先与越界不创建测试|src/mail_core/blobs/private_fs.py; tests/mail_core/test_blob_permissions.py|
|t075_code_f009|minor|已修|docker cp CalledProcessError 转为可读 backup_export_failed；CLI 兜底捕获并补测试|src/mail_core/backup/export.py; tests/mail_core/test_backup_export.py|
|t075_test_f008|minor|撤回|导出模块已覆盖 staging 0755→0700、失败不发布、拒绝覆盖；脚本 trap 仅清理刚创建的固定前缀目录，未发现独立行为缺陷，保留为后续 shell 级测试增强|tests/mail_core/test_backup_export.py; scripts/deploy_mail_core.sh|
|t075_test_f009|minor|已修|Docker 用例增加 normalise 后再次备份；构造器不递归修补已有 shard 的单测已覆盖启动路径语义|tests/mail_core/test_backup_container_permissions.py; tests/mail_core/test_blob_store.py|
|t075_test_f010|minor|已修|put/streaming 测试增加 owner 断言；Docker fixture 改为 0700 目录并断言无关 UID 不可遍历/读取|tests/mail_core/test_blob_store.py; tests/mail_core/test_backup_container_permissions.py|

### Round 3 (2026-11-05T08:20:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t075_code_f010|important|已修|owner 迁移文档命令补 FOWNER/DAC_OVERRIDE；Docker 实测 `--cap-drop ALL --cap-add CHOWN,FOWNER,DAC_OVERRIDE` 可将异属主 0700 树归一化到 10001:999|docs/guides/deployment.md; docs/guides/upgrade.md; scripts/normalize_mail_core_permissions.py|

### Round 4 (2026-11-05T08:45:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t075_code_f011|minor|已修|permissions docstring/错误提示与 spec 摘要统一为 root + CHOWN/FOWNER/DAC_OVERRIDE|src/mail_core/blobs/permissions.py; docs/specs/mail_sync_and_storage.md|
|t075_test_f011|important|已修|新增真实 Docker 特权测试：0:0 的 0700/0600 树经文档命令迁移为 10001:999 且 mode 正确|tests/mail_core/test_backup_container_permissions.py|
|t075_test_f012|minor|已修|Docker 用例断言备份镜像实际 uid 为 10001|tests/mail_core/test_backup_container_permissions.py|
|t075_test_f013|minor|已修|遍历拒绝拆为 test -r 与 test -x 两条独立断言|tests/mail_core/test_backup_container_permissions.py|
|t075_test_f014|minor|已修|恢复 tar fixture 显式 uid/gid=0，并断言恢复文件 owner 为当前进程而非归档 0:0|tests/mail_core/test_backup_package.py|

### Round 5 (2026-11-05T09:10:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t075_test_f015|minor|撤回|Docker 用例已断言文件 owner/mode、目录 0700 与无关 UID 遍历/读取拒绝；目录 owner 由同进程创建隐含覆盖，未发现可观测缺陷，接受为测试精度余量|tests/mail_core/test_backup_container_permissions.py|
|t075_test_f016|minor|撤回|恢复测试已断言文件 owner/mode、目录链 0700 与归档 uid 0 不继承；目录 owner 由目标应用 UID 进程创建隐含覆盖，接受为测试精度余量|tests/mail_core/test_backup_package.py|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足 / 未满足
- 测试：touched 单元 113 passed；DB 相关 39 passed；完整 backend 1975 passed / 2 skipped；frontend 572 passed + tsc/build；desktop 全通过
- 黑盒：Playwright 21 passed；真实 Docker 集成覆盖应用 UID 备份 0600 blob、宿主导出/verify、无关 UID 读取/遍历拒绝、特权 owner 迁移与归一化后再次备份
- review：code PASS（Round 5，0 finding）；test PASS（Round 5，仅 f015/f016 测试精度余量已撤回）
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 已保留 blob 私有权限，备份以应用 UID 在容器私有目录生成包并由宿主导出；恢复显式创建 0700/0600 且不继承归档 UID/mode；新增显式权限归一化命令与真实 Docker 回归测试。
- 遗留：f015/f016 为测试精度余量（目录 owner 隐含覆盖），无行为缺陷。

### 长期文档闭环

本 task 须出现在 specs_index 的关联 task 列；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。
