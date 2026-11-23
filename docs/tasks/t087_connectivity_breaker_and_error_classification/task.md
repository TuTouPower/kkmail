# Task spec

## 背景

p088（2026-11-23 用户实报 + 截图）证明侧栏红字「网络连接不可用，系统正在重试」不是偶然网络抖动，而是两条确定性缺陷的合成：`accounts/health.py:130-142` 的失败计数单调累计、首次失败时间永不更新，5 次失败即使分散在 5 天且中间无成功也会升级 `unreachable`，违背 `docs/blueprint/conventions.md:160` 的「连续 5 次且跨 5 分钟」契约；`sync/context.py:121,18-31` 对 `OSError` 一刀切并对任意异常文本做宽泛 marker 匹配，磁盘满、句柄耗尽、配置字符串含 `connection`、服务端 `temporarily unavailable` 均被判为传输故障并污染 `connectivity_state`。t076 只隔离了 background 传输失败与误导文案，未触及这两条根因；`Sidebar.tsx:271-277` 的有文件夹盲区（p034 遗留）与 5 分钟 staleTime 又制造「偶尔出现、过一阵自愈」的假象。按开发铁律须从状态机语义与错误分类根因重构，禁止只调阈值或改文案。

## 契约区

### 范围

- 把 `connectivity_state` 熔断从「累计 N 次 + 固定首失败时间」改为真正的「滑动窗口内连续失败」语义，与 `docs/blueprint/conventions.md:160` 对齐：超窗或非连续失败重置计数；任何成功仍确定性复位 `connected` 并清除诊断字段。
- 传输故障分类改为异常类型 + `errno` 白名单，移除对任意异常 `str()` 的宽泛 marker 匹配；明确非网络 `OSError`（ENOSPC/EMFILE/EACCES）与配置/DB 文案不计入连接健康。
- 为 `unreachable` 提供有界自动复核，或让 UI 明确区分「同步已暂停 / IDLE 持有」与「网络不可达」，使「系统正在重试」文案成立；消除 `Sidebar.tsx:271-277` 仅在 `folders.length === 0` 显示健康提示的盲区；让状态变更及时反映到前端，不再因 5 分钟 staleTime 继续显示红字。
- 补后端状态机正反例与误分类样本、前端有/无文件夹两态与缓存陈旧性、E2E 文案与结构化状态一致性测试；同步 `docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 spec `mail_sync_and_storage`；p088 转办闭环指向本 task。

### 非范围

- 不重做 t076 已确立的 `credential_state` / `connectivity_state` / `sync_activity` 三维正交模型，不改 `mark_credential_invalid` 与认证错误判定。
- 不改 Worker 重试退避参数、周期轮询间隔与 IDLE 持有策略本身（除非状态机语义所必需）。
- 不改后端发信、联系人与系统通知；不 push、不重新部署生产。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：5 次传输失败必须落在同一滑动窗口内才使 `connectivity_state` 升级为 `unreachable`；同样的 5 次失败分散在超过窗口的时长且中间无成功时保持 `degraded`。后端测试按真实 `backoff_seconds` 序列推进时间，覆盖正反两例。
- [x] AC-002：非网络 `OSError`（ENOSPC/EMFILE/EACCES）、含 `connection string` 的配置错误、`temporarily unavailable` 服务端文案不再判为传输故障，`connectivity_state` 不被写为 `degraded` / `unreachable`；真实 `ConnectionError` / `TimeoutError` / `SSLEOFError` 仍判传输故障。反向与正向样本均有断言。
- [x] AC-003：任一次成功同步仍复位 `connected` 并清空失败计数、首次失败时间与诊断；`sync_enabled=false` 或 IDLE 持有账号不会因无成功事件而永久滞留 `unreachable`（有界自动复核或 UI 明确区分）。
- [x] AC-004：侧栏在账号有文件夹时也按 `credential_state` / `connectivity_state` 显示凭据失效、网络不可达或重试提示；`Sidebar.tsx` 不再把健康提示限制在 `folders.length === 0`。
- [x] AC-005：后端恢复 `connected` 后，前端不再因 5 分钟 staleTime 与 `refetchOnWindowFocus=false` 继续显示红字；E2E 断言文案与结构化状态一致。
- [x] AC-006：`docs/blueprint/testing.md` 的 `test_cmd` 与 `blackbox_verify` 全量通过，无弱化断言或临时补丁残留；`docs/blueprint/conventions.md:160` 的契约与实现一致。
- [x] AC-007：spec `mail_sync_and_storage` 与 `docs/blueprint/testing.md` 同步更新；p088 转办闭环指向 t087。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。AC-001/002/003 由后端状态机与错误分类单元测试验证；AC-004 由组件层测试验证；AC-005 由 playwright E2E 验证；AC-006/007 由门禁命令、文件检索与 pending 状态验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 关联说明：该 spec 已含「分批拉取与瞬态网络重试」条款（`:23-25`），本 task 在其中补连接健康状态机与错误分类契约并登记 t087
- 来源：p088（2026-11-23 用户实报与截图；现象、两条根因、同类位点与复现输出见 `docs/pending/p088_unreachable_accumulated_failure_false_positive.md`）

### 有意不测

- 真实公网 Gmail 账号跨数日的失败序列：不可控且耗时；以后端状态机按时间推进的正反例替代，复现见 p088。
- 真实 Electron 桌面端截图：以组件层 DOM 断言与 playwright E2E 替代，验证逻辑而非像素。
- 凭据失效判定与认证链路：t076 已覆盖，本 task 只确保不被误判为传输故障。

### 测试策略

- 后端：状态机按真实 backoff 序列推进时间，覆盖窗口内连续失败升级、超窗非连续失败不升级；错误分类覆盖非网络 OSError、配置文案、服务端文案的反向样本与真实网络异常的正向样本。
- 组件层：Sidebar 有/无文件夹两态下三种健康提示的渲染断言。
- E2E：后端状态变更到前端文案的一致性，覆盖恢复后无 SSE 事件场景。
- 门禁：`test_cmd` 与 `blackbox_verify` 全量执行。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无（两条根因已由 p088 与 `.scratch/repro_unreachable_intermittent.py` 复现确认）

### 风险与回退

- 风险：收紧错误分类可能漏报真实网络故障（仅停留在 `degraded` 不升级）；滑动窗口计数依赖 `accounts.config` 持久化字段，与历史累计数据混用需明确迁移语义；UI 盲区修复后提示密度上升。
- 回退：按文件粒度回退错误分类或状态机改动，保留测试；历史 `config` 中的累计字段在新语义首次失败时重置并写入理由，不做数据迁移；提示密度通过状态优先级与折叠控制。

### 依赖与约束

- 无前置依赖；必须保持 t076 的三维正交状态模型；不改现役部署与 .env；review_level=full。
- 约束：连接健康只由传输可达性决定，不得由凭据态、限流或辅助任务失败推导；文案必须与结构化状态一致。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：连接熔断连续窗口契约与传输错误分类白名单，与实现对齐。
- `docs/blueprint/testing.md`：状态机正反例、误分类样本与 UI 两态测试纳入门禁。
- `docs/specs/mail_sync_and_storage.md`：tasks 增加 t087，补连接健康状态机与错误分类条款。
