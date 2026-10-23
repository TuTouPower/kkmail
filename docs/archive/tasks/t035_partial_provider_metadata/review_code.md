# Task review t035（reviewer_focus: 代码）

- task：`t035_partial_provider_metadata`
- spec：`docs/tasks/t035_partial_provider_metadata/spec.md`
- diff_anchor：`852c01372e17a4d858050eb2e9fed148870e5495`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff 852c01372e17a4d858050eb2e9fed148870e5495`
- round：1
- reviewed_at：2026-10-23T08:43:33+08:00

reviewed_scope: 235037ac26070ab1

## Findings

### t035_code_f001 - Graph 元数据解析函数圈复杂度超阈值

- 严重度：minor
- 锚点：代码质量 / 圈复杂度标准；未违反行为 AC
- 位置：`src/mail_core/providers/parsing/graph_delta.py:21`（`_meta_from_graph`）
- 问题：未发现复杂度分析工具，按 prompt 规则手算近似 CC 约 17。recipient 两组 comprehension、fallback 表达式与本 task 新增的 `flagStatus`、`isRead`、`hasAttachments` 三个 presence 分支合计超过 CC≥15 阈值；函数复杂度在本 task 中继续增加。未观察到分支行为错误。
- 建议：后续继续扩展 Graph 元数据时，将可选状态字段归一化提取为小型解析 helper，避免继续堆叠解析分支。

## 结论

### AC 复验方式

- AC-001：`re_verified`。`parse_graph_delta` 仅将非 `None` 状态加入 `flags`；`_apply_flag_patches` 只应用传入字段，metadata upsert 也跳过未知状态，见 `src/mail_core/providers/parsing/graph_delta.py:42-45,71-84`、`src/mail_core/sync/delta.py:54-79`、`src/mail_core/sync/metadata.py:116-128`。
- AC-002：`re_verified`。Gmail 与 IMAP 附件状态缺失时传 `None`，明确 bool 仍保留；metadata upsert 对 `None` 跳过赋值，见 `src/mail_core/providers/gmail.py:132-134`、`src/mail_core/providers/imap.py:274-276`、`src/mail_core/providers/parsing/gmail_history.py:48-50`、`src/mail_core/sync/metadata.py:116-119`。
- AC-003：`trust_prior`。本代码轴未审查测试断言；`handoff.json` 列出 parser、delta 与 metadata 测试文件，完整自动化覆盖由独立 test reviewer 复核。本报告不以实施侧测试数量声明作为通过证据。
- coverage = 2/3
- 建议合并前人工抽查 trust_prior 项。

### 7 视角扫描

- 规格与正确性：AC-001/002 实现路径符合契约；未见状态覆盖、范围偏航或本地意图优先级变化。
- 安全：本 diff 未新增外部输入拼接执行、凭据处理、授权或渲染路径；未发现问题。
- 契约与 Breaking：变更限于内部 `RemoteMessageMeta` 类型与同步路径；未变更公开 API、schema 或配置键。
- 性能与资源：仅增加逐条 O(1) 字段检查与构造状态 dict；未新增循环查库、串行外部调用或资源生命周期问题。
- 架构与可维护性：无跨层依赖或重复逻辑缺陷；圈复杂度命中项见 f001。
- 健壮性与可观测：未见吞错、空 catch、日志泄密或失败状态不一致。
- 文档与规格：累计邮件同步 spec 和 index 已同步新增行为；测试断言留给 test reviewer。

### 未进表的提示

- `src/mail_core/providers/gmail.py` 当前 407 行；本 task 净增 2 行并触及实现源码 400 行提示阈值。按 prompt 规则仅在结论列出，不进 finding 表。

- `src/mail_core/providers/imap.py` 当前 800 行，但本 task 未净增该文件行数，不满足文件过大 finding 条件。

- `git diff --check` 无输出。

- 本轮新发现：1 条，均为 minor。

- 总体判断：未发现 critical / important finding；AC-001/002 代码路径通过，本轮 verdict 为 PASS。

- 系统性 follow-up：无。

verdict: PASS

## Round 2 (2026-10-23T08:50:46+08:00)

reviewed_scope: d007d7f37a900891

### Findings

本轮新发现：0。

### 结论

#### 前轮 finding 复核

- `t035_code_f001`：仍存在。Round 2 的完整 diff 中 `_meta_from_graph` 实现与 Round 1 相同；按 prompt 的手算规则，当前近似 CC 约 20，且本 task 增加了三个状态存在性分支，满足 CC≥15 且本 task 增加分支的 minor 条件。`task.md` 将其标记为“撤回”，但代码未改；“复杂度属启发式、无行为风险”不改变该量化条件，故本轮不认定为已修或同意撤回。该 finding 仍为 minor，不阻断 PASS。

#### AC 复验方式

- AC-001：`re_verified`。当前 parser 仍只把非 `None` 的 read/star 加入 flags，生产更新路径只应用存在键，未知 metadata 状态跳过赋值，见 `src/mail_core/providers/parsing/graph_delta.py:42-45,71-84`、`src/mail_core/sync/delta.py:54-79`、`src/mail_core/sync/metadata.py:116-128`。
- AC-002：`re_verified`。当前 Gmail/IMAP parser 对未知附件状态仍返回 `None`，显式 bool 保持原值并由 metadata 更新路径应用，见 `src/mail_core/providers/gmail.py:132-134`、`src/mail_core/providers/imap.py:274-276`、`src/mail_core/providers/parsing/gmail_history.py:48-50`、`src/mail_core/sync/metadata.py:116-119`。
- AC-003：`trust_prior`。代码轴不审查测试断言。Round 1 的 `review_test.md` 曾核对自动化覆盖，但当前 scope 中测试文件已有变化，覆盖复核应由 test reviewer 在本轮独立完成。
- coverage = 2/3
- 建议合并前人工抽查 trust_prior 项。

#### 7 视角扫描

- 规格与正确性：本轮无实现代码变化；AC-001/002 路径仍符合契约，未见本轮新增状态覆盖问题。
- 安全：当前代码 diff 未新增注入、授权、凭据或渲染路径问题。
- 契约与 Breaking：未新增公开 API、schema 或配置变更。
- 性能与资源：未新增循环查库、重复重计算、串行外部调用或资源泄漏。
- 架构与可维护性：f001 仍存在；无新边界或重复逻辑问题。
- 健壮性与可观测：未见吞错、日志泄密或失败状态不一致。
- 文档与规格：当前累计 spec 与实现一致；测试文件改动由 test reviewer 负责复核。

#### 未进表的提示

- `src/mail_core/providers/gmail.py` 407 行，task 净增 2 行；`src/mail_core/providers/imap.py` 800 行但净增 0 行，文件过大处理仍按 Round 1 结论。

- `git diff --check` 无输出。

- 本轮新发现：0 条；前轮 f001 仍为 minor。

- 总体判断：无 critical / important finding；本轮 verdict 为 PASS。

- 系统性 follow-up：无。

verdict: PASS
