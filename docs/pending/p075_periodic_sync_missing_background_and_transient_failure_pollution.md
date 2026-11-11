---
pid: "p075"
slug: "periodic_sync_missing_background_and_transient_failure_pollution"
status: "closed"
resolution: "transferred"
reason: "已核实根因与范围并转交该 task"
fix_ref: "t076"
---
# p075 周期性同步缺 background 标记致瞬时网络抖动将账号置为 failed 并展示误导性检查设置文案

- 现象：
    1. 用户在侧栏账号列表（如 Gmail 账号 `fengandelliot@gmail.com`）偶尔会看到账号右侧出现红色感叹号角标 `!`，展开后红字提示「同步失败，请检查账户设置」。
    2. 随后一段时间（或网络恢复/手动重试后），该错误提示又会自动消失并自愈为正常状态。
    3. 实际排查后端运行日志与数据库，该时段仅发生瞬时网络不可达（如 `OSError code=101`，本地代理或网络抖动），账号配置与密码完全正常，却被展示误导性的“检查账户设置”。
- 影响：
    1. 正常账号受瞬时网络抖动影响频繁被虚假打上 `failed` 标签，引发用户焦虑，误以为密码被封锁或服务器配置错误。
    2. 自动周期同步（后台轮询）本应作为静默维护机制，因未隔离故障，其瞬时断网失败直接穿透污染账号全局状态并在前端显著红字告警。
    3. 即使系统正在自动重试（15 秒后退避重试），在重试成功前，界面一直处于警报状态，缺乏“正在重试/网络异常”的精确反馈。
- 根因：
    1. 后端调度缺少上下文标识（产品缺陷）：
        - `src/mail_core/worker/main.py:279`：`_schedule_periodic_sync_once` 入队的 `SYNC_FOLDER_DELTA` 任务仅包含 `payload={"folder_id": str(folder_id)}`，缺少 `request_id` 或 `background: True` 作用域上下文。
        - `src/mail_core/sync/context.py:30-41`：`resolve_sync_context` 在无 `request_id` 时兜底返回 `is_background = False`。
        - `src/mail_core/worker/handlers.py:216-224`：`_evaluate_result` 在收到 `provider_error` 且 `is_background` 为 `False` 时，调用 `_apply_account_sync_failure`，无差别将账号的 `sync_status` 置为 `failed`。
    2. 失败提升粒度过粗且未与重试联动（产品缺陷）：
        - `handlers.py:216-224` 在任务首次遭遇 `provider_error` 时立即粗粒度将账号全局状态打为 `failed`，即使 `followup_scheduled: True`（系统已排队 15 秒后重试）。
        - 瞬时网络异常（如代理抖动、`OSError code=101`、连接超时）未与真正的持久配置错误/认证错误（`auth_failed`）解耦。
    3. 前端 UI 错误提示硬编码且不准确（UI 缺陷）：
        - `src/frontend/src/components/Sidebar.tsx:258, 335`：对 `syncStatus === 'failed'` 与 `auth_failed` 统一渲染静态硬编码文案「同步失败，请检查账户设置」，掩盖了“仅为网络临时中断/正在自动重试”的真实情况，误导用户检查密码/端口。
    4. 已确认同类位点清单：
        - `src/mail_core/worker/main.py:279`：周期性 delta 增量同步缺少 background 标记。
        - `src/mail_core/worker/handlers.py:216-224`：单次 provider_error 立即将账号提升为全局 `failed`，未结合重试状态与错误类型降级。
        - `src/mail_core/sync/engine.py:271-285`：`sync_account_folders` 遇到偶发 provider 异常同样直接置账号为 `failed`。
        - `src/frontend/src/components/Sidebar.tsx:258, 335, 1156`：前端未消费具体错误原因（`last_sync_error` 或网络/重试状态），统一提示“请检查账户设置”。
- 测试缺口：
    1. 后端集成测试：现有 `test_worker_periodic_sync` 或 delta 测试只测试本地可用环境（Dovecot），未断言周期性调度任务携带 `background: True`；缺少“周期性任务遭遇单次 `provider_error` 时账号 `sync_status` 不被污染为 `failed`”的测试。
    2. 前端组件测试：`Sidebar.test.tsx` 缺少在网络抖动重试中展示准确状态（非“检查设置”）的组件断言。
- 线索：
    - `.scratch/repro_transient_sync_failure.py`
    - `src/mail_core/worker/main.py:279`
    - `src/mail_core/sync/context.py:30-41`
    - `src/mail_core/worker/handlers.py:216-224`
    - `src/frontend/src/components/Sidebar.tsx:258, 335, 1156`
- 处理：t076；resolution=transferred；reason=已核实根因与范围并转交该 task
