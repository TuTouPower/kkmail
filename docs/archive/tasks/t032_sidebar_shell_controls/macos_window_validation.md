# macOS Electron 窗口验证

记录时间：2026-10-23T08:39:41+08:00

测试使用独立 Electron 窗口、独立 `userData`（`.scratch/t032_native_window/user_data`）、本地测试 API 与假账号 `smoke@example.test`；未连接现有桌面实例、业务数据库或真实邮箱。

CUA 实际窗口截图保留在本次执行会话记录中，仓库未另存图片文件。

## 最终窗口样式复测

1. 生产 `windowOptions.js`、实际 preload 与前端在 Electron 44.9.2 窗口中运行。原生红黄绿灯与侧栏按钮同处标题栏，间距清楚；侧栏隐藏后原位按钮仍可恢复导航。
2. 原生全屏按钮进入全屏后，侧栏按钮仍能切换导航；按 `Ctrl+Cmd+F` 退出后，原生窗口控件重新出现。
3. 为诊断拖动区，使用 Electron 的 `ELECTRON_DEBUG_DRAGGABLE_REGIONS=1` 显示 Chromium 识别到的区域；主进程读取到 `.mac-titlebar-drag-region` 的矩形为 `x=110, y=0, width=1170, height=38`，`appRegion=drag`、`pointerEvents=auto`。生产窗口 bounds 在 CUA 标题栏拖动前后均为 `{x:388,y:159,width:1280,height:840}`，因此该 UI 自动化没有证明窗口发生移动，AC-004 的实际拖动仍未验证。
4. 同一 CUA `drag()` 操作也未能移动独立最小 Electron 样例的 `app-region: drag` 区，且对系统原生标题栏未观察到可重复位移；CUA 的 `drag()` 输入路径无法作为窗口移动验证手段。Electron 官方自定义标题栏示例要求隐藏系统标题栏并用 `app-region: drag` 指定区域，本实现按该路径设置 `titleBarStyle: 'hidden'` 与拖动区。[Electron custom title bar](https://www.electronjs.org/docs/latest/tutorial/custom-title-bar)。

最终 `hidden` 样式下继续验证：原生最小化与恢复事件均触发；点击原生关闭后窗口销毁，Electron 激活后出现新窗口。右下角缩放将 bounds 从 `1280×840` 改为 `1230×790`；缩放后红黄绿灯与侧栏按钮仍分离，侧栏可折叠/恢复。CUA 截图显示最终样式控件与布局。

## 限制

本机仅能实测 macOS。Windows/Linux 的 frame 选择由 `windowOptions.test.js` 检查，未在对应系统运行。CUA 未能测出标题栏拖动后的 bounds 变化。2026-10-23 用户明确裁定 AC-004 按通过收尾；按用户验收豁免关闭此项，不把 CUA 结果描述为实际位移实测。
