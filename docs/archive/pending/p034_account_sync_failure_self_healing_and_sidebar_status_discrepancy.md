# p034 账号同步失败状态缺失自愈机制且侧栏仅空文件夹展示失败导致与设置页严重矛盾

- 现象：
    1. 用户在主界面左侧边栏（Sidebar）的账号列表中，仅看到 `[REDACTED_EMAIL]` 展开后提示红字“同步失败，请检查账户设置”，其他所有账号（如 163、Outlook 等）未显示任何错误提示。
    2. 打开“设置”对话框的“账户管理”面板时，28 个启用同步的账号中，全部 28 个账号的状态列均显示红点“同步失败”（除 126 邮箱和 1 个 QQ 邮箱因密码/服务配置真实鉴权失败外，其余 26 个正常账号后台全部 83000+ 个任务实际均已成功完成（done）且无待执行任务）。
    3. 侧栏与设置页同步状态呈现严重矛盾，给用户造成“左侧明明只有 126 同步失败，为什么设置里全部失败”的假象与困惑。
- 影响：
    1. 正常账号被虚假锁定在“同步失败”：任何子任务（增量同步、元数据拉取、对账、归档等）因瞬时网络抖动或历史缺陷报错一次，账号全局 `sync_status` 即被标记为 `failed`，且在所有后续任务重试成功或周期性同步完成时均无法自愈，永久残留错误态。
    2. 侧栏账号行存在故障感知盲区：侧栏账号根行缺少同步状态指示器；`AccountFolders` 的失败提示仅在 `folders.length === 0` 时触发。一旦账号已同步出历史文件夹（`folders.length > 0`），即使账号同步已失败，侧栏仍照常展示旧文件夹树，完全掩盖失败真相。
- 根因：
    1. 后端状态机自愈机制缺失（产品缺陷）：
        - `src/mail_core/worker/handlers.py:210-216`：任何 worker job 抛出异常均直接无差别调用 `update_account_sync_status(session, account_id, "failed", error=...)`，粗粒度污染账号全局状态；
        - `src/mail_core/worker/handlers.py:19-45`：`_evaluate_result` 在 job 成功时仅调用 `complete_job`，从未检查并自愈恢复账号的 `sync_status` 为 `idle`（仅初次目录发现 `sync_account_folders` 会置为 `idle`）；此前由跟进任务 `folder_id` 缺失遗留的 212 条 `KeyError` 导致 26 个正常账号被锁定为 `failed` 且无法自愈。
    2. 前端侧栏状态呈现逻辑缺失且仅对 0 文件夹做特殊兜底（UI 缺陷）：
        - `src/frontend/src/components/Sidebar.tsx:684-702`：`renderAccount` 账号节点未消费 `account.sync_status`，折叠时不表达任何失败状态；
        - `src/frontend/src/components/Sidebar.tsx:183-188`：`AccountFolders` 仅当 `folders.length === 0` 时才渲染“同步失败，请检查账户设置”；`folders.length > 0` 时直接渲染文件夹树，掩盖同步中断；与 `SettingsModal.tsx` 直接读取 `account.sync_status` 产生强烈认知冲突。
    3. 已确认同类位点清单：
        - `src/mail_core/worker/handlers.py:201-221`：worker 异常捕获中无差别将所有 job 类型错误（包括辅助归档 `archive_mime_batch`）提升为账号级同步失败。
        - `src/mail_core/worker/handlers.py:19-45`：`_evaluate_result` 成功分支未在账号无活跃错误任务时自愈清空 `failed` / `last_sync_error`。
        - `src/mail_core/sync/delta.py` & `src/mail_core/sync/reconcile.py`：单文件夹同步/对账成功后未向上反馈账号健康度。
        - `src/frontend/src/components/Sidebar.tsx:684-702`：账号根行缺少同步状态错误角标或视觉指示。
        - `src/frontend/src/components/Sidebar.tsx:183-188`：`AccountFolders` 在已有文件夹时若账号同步失败，缺少离线或同步错误提示。
- 测试缺口：
    1. 后端集成测试：缺少“worker job（如 `sync_folder_delta`）失败后，后续任务成功完成或重试成功时，账号 `sync_status` 自动自愈回 `idle` 并清除 `last_sync_error`”的状态机测试。
    2. 前端组件测试：缺少“当账号含有文件夹（`folders.length > 0`）且处于 `sync_status === 'failed'` 时，Sidebar 账号行展示明确故障指示器，且与 Settings 状态一致”的组件测试。
- 线索：
    - `.scratch/repro_sync_status_inconsistency.py`
    - `src/mail_core/worker/handlers.py:19-50, 201-221`
    - `src/mail_core/sync/engine.py:80-135, 198-208`
    - `src/frontend/src/components/Sidebar.tsx:183-188, 684-702`
    - `src/frontend/src/components/SettingsModal.tsx:17, 236`
- 处理：main
