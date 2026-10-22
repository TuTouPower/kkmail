# Task spec

## 背景

UI 引用浮标与 ErrorBoundary 复制诊断均直接调用 navigator.clipboard.writeText；桌面 hardening 无条件拒绝权限，真实点击触发 clipboard-sanitized-write 被拒。现有前端测试 mock 成功，桌面单测只覆盖 media 拒绝，未贯通真实复制。

## 契约区

### 范围

- 恢复 Electron 中 UI 引用及诊断日志两个显式复制入口，并保持浏览器端复制与失败反馈。
- 为文本写入建立最小授权边界，验证应用顶层页面与不可信 frame/来源隔离。

### 非范围

- 不增加读取剪贴板、后台监听、任意系统访问或通用 IPC 调用能力。
- 不通过全局放开权限、关闭 sandbox/contextIsolation、启用 nodeIntegration 或放宽邮件 CSP 修复复制。
- 不新增与复制无关诊断采集或 UI 引用功能。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：桌面应用内用户点击 UI 编号浮标后，系统剪贴板内容精确等于既有结构化引用格式，界面反馈成功，点击不触发下层控件。
- [ ] AC-002：桌面错误边界中点击“复制诊断日志”后，系统剪贴板内容等于既有诊断导出文本，界面反馈成功；保留现有脱敏行为。
- [ ] AC-003：文本复制授权仅适用于受信应用顶层页面；邮件 iframe、不可信 frame及外部来源不能借此写入剪贴板。剪贴板读取和原本拒绝的媒体等无关权限仍被拒绝。
- [ ] AC-004：Web 环境仍可使用标准剪贴板 API；API 缺失、拒绝或桌面写入失败时两个入口均明确提示失败，不误报成功，不使错误边界再次崩溃。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试；视觉截图仅作补充复核。

## 上下文区

- 来源：p019（2026-10-23 核实；无等价 effective task）。两个调用点为 UiReferenceOverlay.tsx/handleCopy 和 ErrorBoundary.tsx/copyReport；preload 仅暴露平台及版本，无复制通道。.scratch/pending_candidate_audit.js 在本地 Electron 44.9.2、聚焦窗口及真实鼠标输入下捕获 request:clipboard-sanitized-write 与 NotAllowedError: Write permission denied，使用生产 denyPermissionRequest/denyPermissionCheck。前端单测 mock clipboard、hardening.test.js 仅断言 media 拒绝，无法发现此跨层故障。

### 有意不测

- 真实业务诊断或邮件数据：复制集成测试使用脱敏合成字符串，避免接触用户内容。
- 全平台人工打包发布：以已安装真实 Electron 验证为创建及开发依据，本 task 不发布安装包。

### 测试策略

- 前端测试覆盖两个入口成功、缺失 API 与拒绝反馈，并验证 UI 引用点击不会触发底层动作、诊断仍经现有脱敏导出。
- 真实 Electron 集成测试加载生产复制路径与 hardening，聚焦后执行用户点击，读取系统剪贴板核对内容；不得仅 mock navigator.clipboard 或直接调用权限 helper。测试保护并恢复原剪贴板，运行数据限制在测试目录。
- 权限/桥接测试覆盖可信顶层来源、不可信来源、iframe、读取及媒体权限；若新增桌面桥接，还须覆盖错误类型载荷；根据最终选择仅开放所需文本写入。
- 运行受影响前端与桌面测试，并验证安全加固、preload 打包资源和实际 Electron 行为。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

本地真实 Electron 已验证触发 clipboard-sanitized-write 请求并被拒；具体修复路径由实施选取最小方案，测试须覆盖其真实授权边界。无新增外部协议未知项。

### 风险与回退

- 风险：来源或 frame 校验过宽可能让邮件内容获得系统写入能力；仅测试 mock 会继续假绿。
- 回退：回退本 task 执行 commit，恢复原权限拒绝策略；不修改用户数据。

### 依赖与约束

- 无硬依赖；t011 已完成。涉及权限与桌面隔离，review_level=full。
- 保持应用 loopback origin、导航加固、CSP、sandbox、contextIsolation 和 nodeIntegration 现有安全边界；不硬编码开发端口。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：桌面文本复制授权与前端两个入口的数据流。
- `docs/blueprint/conventions.md`：可信顶层页面写剪贴板、邮件 frame 隔离及失败反馈规则。
